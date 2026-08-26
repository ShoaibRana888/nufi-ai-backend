# services/guardrails.py
"""
Body-state guardrails for the AI health coach.

Three cooperating layers keep suggestions safe and non-redundant:

  Layer 1 — compute_body_state(): distils the raw user profile + today's
            logged activities into a compact, decision-ready `body_state`
            dict (cycle phase, sleep, calorie balance, what's already done).
            Persisted onto the daily chat_context so it is cheap to read.

  Layer 2 — render_guardrail_prompt(): turns that dict into an explicit
            directive block for the system prompt. Does ~90% of the work by
            telling the model the facts + the hard rules up front.

  Layer 3 — post_check_response(): a deterministic (no-LLM) safety net that
            scans the generated reply for the few contradictions that must
            not slip through (pushing intensity while menstruating / sleep
            deprived, pushing more food while already over target) and
            appends a gentle corrective caveat.

The period/cycle guards only apply to users who menstruate; every guard
degrades gracefully when the underlying data is missing.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional


# --- high-intensity vocabulary the post-check watches for --------------------
_HIGH_INTENSITY_TERMS = [
    "hiit", "high-intensity", "high intensity", "sprint", "sprints",
    "heavy lift", "heavy lifting", "lift heavy", "max out", "maxing out",
    "1rm", "one rep max", "pr attempt", "go hard", "push hard",
    "intense workout", "intense session", "bootcamp", "boot camp",
    "crossfit", "tabata", "all-out", "all out", "burpees",
]

# phrases that indicate the reply is nudging the user to eat MORE
_EAT_MORE_TERMS = [
    "eat more", "another snack", "add a snack", "add a meal",
    "more calories", "extra calories", "grab a bite", "have a snack",
    "increase your intake", "bump up your calories",
]


def _is_female(user: Dict[str, Any]) -> bool:
    """Whether cycle-based guards are relevant for this user."""
    gender = (user.get("gender") or "").strip().lower()
    if gender in ("female", "woman", "f"):
        return True
    # has_periods / cycle fields are strong signals even if gender is blank
    if user.get("has_periods") is True:
        return True
    if user.get("cycle_length") or user.get("last_period_date"):
        return True
    return False


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        # tolerate timestamptz / ISO strings and plain YYYY-MM-DD
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None


# --- Layer 1: compute the body_state ----------------------------------------
def compute_period_status(
    user: Dict[str, Any],
    period_row: Optional[Dict[str, Any]],
    target_date: date,
) -> Dict[str, Any]:
    """
    Derive cycle phase for `target_date`.

    Uses an active period entry (authoritative for "is she bleeding today")
    when present, and falls back to last_period_date + cycle_length to
    estimate the phase across the rest of the cycle.
    """
    status: Dict[str, Any] = {
        "applies": _is_female(user),
        "is_menstruating": False,
        "phase": None,          # menstrual | follicular | ovulation | luteal
        "cycle_day": None,
        "flow_intensity": None,
        "symptoms": [],
        "mood": None,
    }
    if not status["applies"]:
        return status

    cycle_length = user.get("cycle_length") or 28
    period_length = user.get("period_length") or 5
    try:
        cycle_length = int(cycle_length)
        period_length = int(period_length)
    except (TypeError, ValueError):
        cycle_length, period_length = 28, 5
    if cycle_length < 15 or cycle_length > 60:
        cycle_length = 28

    # Anchor: the start of the most recent cycle we can see.
    period_start = _parse_date(period_row.get("start_date")) if period_row else None
    anchor = period_start or _parse_date(user.get("last_period_date"))

    if period_row:
        end = _parse_date(period_row.get("end_date"))
        # Active bleeding if the logged period covers today, or has no end yet
        # and we're still within the expected period length.
        if period_start and period_start <= target_date:
            if end is not None:
                status["is_menstruating"] = target_date <= end
            else:
                status["is_menstruating"] = (target_date - period_start).days < max(period_length, 2) + 1
        status["flow_intensity"] = period_row.get("flow_intensity")
        status["symptoms"] = period_row.get("symptoms") or []
        status["mood"] = period_row.get("mood")

    if anchor and anchor <= target_date:
        cycle_day = ((target_date - anchor).days % cycle_length) + 1
        status["cycle_day"] = cycle_day
        ovulation_day = cycle_length - 14  # luteal phase is ~14 days
        if status["is_menstruating"] or cycle_day <= period_length:
            status["phase"] = "menstrual"
            if cycle_day <= period_length and anchor == period_start:
                status["is_menstruating"] = True
        elif cycle_day < ovulation_day - 1:
            status["phase"] = "follicular"
        elif cycle_day <= ovulation_day + 1:
            status["phase"] = "ovulation"
        else:
            status["phase"] = "luteal"
    elif status["is_menstruating"]:
        status["phase"] = "menstrual"

    return status


def compute_sleep_status(sleep: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Flag poor / short sleep so intensity can be dialed back."""
    status = {
        "logged": False,
        "hours": None,
        "quality_label": None,
        "is_poor": False,
    }
    if not sleep:
        return status
    hours = sleep.get("total_hours")
    score = sleep.get("quality_score")
    status["logged"] = hours is not None or score is not None
    status["hours"] = hours
    if score is not None:
        # matches the app's _getQualityLabel thresholds
        if score >= 0.9:
            status["quality_label"] = "Excellent"
        elif score >= 0.7:
            status["quality_label"] = "Good"
        elif score >= 0.5:
            status["quality_label"] = "Fair"
        elif score >= 0.3:
            status["quality_label"] = "Poor"
        else:
            status["quality_label"] = "Very Poor"
    # Poor = short OR low quality
    if (hours is not None and hours < 6) or (score is not None and score < 0.5):
        status["is_poor"] = True
    return status


def compute_calorie_status(
    total_calories: float,
    tdee: Optional[float],
    meals_logged: int,
) -> Dict[str, Any]:
    """Compare intake against the daily target."""
    status = {
        "total_calories": round(total_calories or 0),
        "target": tdee,
        "remaining": None,
        "over_target": False,
        "well_under": False,
    }
    if not tdee or tdee <= 0:
        return status
    remaining = tdee - (total_calories or 0)
    status["remaining"] = round(remaining)
    if (total_calories or 0) >= tdee * 1.05:
        status["over_target"] = True
    # only call it "well under" once at least one meal exists (avoids flagging
    # an empty morning as under-eating)
    if meals_logged > 0 and (total_calories or 0) < tdee * 0.5:
        status["well_under"] = True
    return status


def compute_body_state(
    user: Dict[str, Any],
    activities: Dict[str, Any],
    totals: Dict[str, Any],
    target_date: date,
) -> Dict[str, Any]:
    """
    Layer 1 entry point. Build the compact body_state block from the same
    raw activities dict that rebuild_context already assembles.
    """
    meals = activities.get("meals", []) or []
    exercises = activities.get("exercise", []) or []
    water = activities.get("water", {}) or {}
    steps = activities.get("steps", {}) or {}
    supplements = activities.get("supplements", {}) or {}
    sleep = activities.get("sleep", {}) or {}
    period_row = activities.get("period", {}) or {}

    exercise_names = [e.get("exercise_name") for e in exercises if e.get("exercise_name")]
    meal_names = [m.get("food_item") for m in meals if m.get("food_item")]

    supplements_taken: List[str] = []
    if isinstance(supplements, dict):
        supplements_taken = [k for k, v in supplements.items()
                             if isinstance(v, dict) and v.get("taken")]

    already_done = {
        "exercises": exercise_names,
        "meals": meal_names,
        "water_glasses": water.get("glasses_consumed", 0),
        "steps": steps.get("steps", 0),
        "supplements_taken": supplements_taken,
        "exercised_today": len(exercise_names) > 0,
    }

    return {
        "date": str(target_date),
        "period": compute_period_status(user, period_row, target_date),
        "sleep": compute_sleep_status(sleep),
        "calories": compute_calorie_status(
            totals.get("calories", 0),
            user.get("tdee"),
            len(meals),
        ),
        "already_done_today": already_done,
        "medical_conditions": user.get("medical_conditions", []) or [],
    }


# --- Layer 2: render the directive block ------------------------------------
def render_guardrail_prompt(body_state: Optional[Dict[str, Any]]) -> str:
    """Turn body_state into an explicit system-prompt directive block."""
    if not body_state:
        return ""

    lines: List[str] = ["", "=== BEHAVIORAL GUARDRAILS (obey strictly) ==="]

    # -- already done today --
    done = body_state.get("already_done_today", {})
    facts: List[str] = []
    if done.get("exercises"):
        facts.append(f"Workouts done: {', '.join(done['exercises'])}")
    if done.get("meals"):
        facts.append(f"Meals eaten: {', '.join(done['meals'])}")
    if done.get("water_glasses"):
        facts.append(f"Water: {done['water_glasses']} glasses")
    if done.get("steps"):
        facts.append(f"Steps: {done['steps']}")
    if done.get("supplements_taken"):
        facts.append(f"Supplements taken: {', '.join(done['supplements_taken'])}")
    if facts:
        lines.append("ALREADY DONE TODAY — " + "; ".join(facts) + ".")
        lines.append("- Do NOT suggest anything she has already completed today. "
                     "Acknowledge it and build on it instead.")
    if done.get("exercised_today"):
        lines.append("- She has already exercised today. Prefer recovery, mobility, "
                     "or complementary movement over prescribing another full workout.")

    # -- cycle / period --
    period = body_state.get("period", {})
    if period.get("applies"):
        if period.get("is_menstruating"):
            detail = []
            if period.get("flow_intensity"):
                detail.append(f"{period['flow_intensity']} flow")
            if period.get("cycle_day"):
                detail.append(f"day {period['cycle_day']}")
            if period.get("symptoms"):
                detail.append("symptoms: " + ", ".join(period["symptoms"]))
            suffix = f" ({'; '.join(detail)})" if detail else ""
            lines.append(f"CYCLE STATE — She is on her period today{suffix}.")
            lines.append("- Recommend ONLY low-intensity movement: walking, gentle yoga, "
                         "stretching, light mobility, or rest.")
            lines.append("- Do NOT push high-intensity training (HIIT, sprints, heavy "
                         "lifting, PRs). If SHE explicitly asks for an intense session, "
                         "allow it but add a gentle, non-judgmental caveat about listening "
                         "to her body.")
            lines.append("- Be warm about cramps/fatigue; frame nutrition around iron, "
                         "hydration, and comfort.")
        elif period.get("phase") == "luteal":
            lines.append(f"CYCLE STATE — Luteal phase (cycle day {period.get('cycle_day')}). "
                         "Energy may be lower; favor moderate intensity and good recovery. "
                         "Avoid pushing for personal records.")
        elif period.get("phase"):
            lines.append(f"CYCLE STATE — {period['phase'].capitalize()} phase "
                         f"(cycle day {period.get('cycle_day')}).")

    # -- sleep --
    sleep = body_state.get("sleep", {})
    if sleep.get("is_poor"):
        detail = []
        if sleep.get("hours") is not None:
            detail.append(f"{sleep['hours']}h")
        if sleep.get("quality_label"):
            detail.append(sleep["quality_label"].lower())
        suffix = f" ({', '.join(detail)})" if detail else ""
        lines.append(f"SLEEP — Poor/short sleep logged{suffix}.")
        lines.append("- Dial back suggested training intensity and prioritize recovery, "
                     "hydration, and an earlier bedtime tonight.")

    # -- calories --
    cals = body_state.get("calories", {})
    if cals.get("over_target"):
        lines.append(f"CALORIES — Already at/over her daily target "
                     f"({cals.get('total_calories')} / {cals.get('target')} kcal).")
        lines.append("- Do NOT suggest eating more or adding snacks. If she's still "
                     "hungry, suggest water, protein/fiber-forward choices, or a walk.")
    elif cals.get("well_under"):
        lines.append(f"CALORIES — Well under target so far "
                     f"({cals.get('total_calories')} / {cals.get('target')} kcal, "
                     f"{cals.get('remaining')} kcal remaining).")
        lines.append("- Do NOT suggest workouts that deepen the deficit; encourage a "
                     "balanced, nourishing meal.")

    # -- medical conditions --
    conditions = body_state.get("medical_conditions", [])
    if conditions:
        lines.append(f"MEDICAL — Known conditions: {', '.join(conditions)}. "
                     "Keep advice general and remind her to coordinate with her provider.")

    # nothing besides the header => no guardrails worth adding
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)


# --- Layer 3: deterministic post-check --------------------------------------
def post_check_response(reply: str, body_state: Optional[Dict[str, Any]]) -> str:
    """
    Deterministic safety net. Appends a corrective caveat when the reply
    contradicts a safety-critical body-state signal. Never rewrites the
    model's words — only adds a clearly-marked note.
    """
    if not reply or not body_state:
        return reply

    reply_lower = reply.lower()
    notes: List[str] = []

    period = body_state.get("period", {})
    sleep = body_state.get("sleep", {})
    cals = body_state.get("calories", {})

    mentions_intensity = any(term in reply_lower for term in _HIGH_INTENSITY_TERMS)

    if mentions_intensity and period.get("is_menstruating"):
        notes.append(
            "💛 Since you're on your period today, keep it gentle — walking, yoga, "
            "or stretching are better than high-intensity work. Listen to your body."
        )
    elif mentions_intensity and sleep.get("is_poor"):
        notes.append(
            "😴 You're running low on sleep, so consider dialing the intensity back "
            "today and prioritizing recovery."
        )

    if cals.get("over_target") and any(term in reply_lower for term in _EAT_MORE_TERMS):
        notes.append(
            "🍽️ Heads up: you're already at your calorie target for today, so lean on "
            "water or a light walk rather than adding more food."
        )

    if not notes:
        return reply
    return reply + "\n\n" + "\n\n".join(notes)
