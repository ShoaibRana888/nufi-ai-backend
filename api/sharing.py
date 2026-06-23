# api/sharing.py
"""User-controlled "share with AI chat" toggles.

Lets the user flip an individual logged activity's `shared_with_chat` flag on
or off at any time, and manage per-activity-type defaults for new entries.
The flag is enforced server-side in every chat/context read (see
services/chat_context_manager.py and services/chat_service.py), so hiding an
activity removes it from what the AI coach can see without deleting the data.
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime, date
from typing import Optional

from services.supabase_service import get_supabase_service
from services.chat_context_manager import get_context_manager

router = APIRouter(prefix="/sharing", tags=["sharing"])

# Per-entry tables keyed by row id, with the column that holds the entry's date.
# Period entries span a range; we key the rebuild off start_date (end_date is
# nullable while a period is ongoing).
_ROW_TABLES = {
    "meal": ("meal_entries", "meal_date"),
    "exercise": ("exercise_logs", "exercise_date"),
    "weight": ("weight_entries", "date"),
    "sleep": ("sleep_entries", "date"),
    "period": ("period_entries", "start_date"),
}

# Per-day aggregate tables keyed by (user_id, date).
_DATE_TABLES = {
    "water": "daily_water",
    "steps": "daily_steps",
}


def _parse_date(value) -> Optional[date]:
    """Best-effort parse of a date or datetime string to a date."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


@router.patch("/{user_id}")
async def set_activity_sharing(user_id: str, body: dict):
    """Toggle whether one logged activity is shared with the AI chat.

    Body:
      activity_type: meal | exercise | weight | sleep | water | steps | supplement
      shared: bool
      item_id: required for meal/exercise/weight/sleep
      date: required for water/steps/supplement (YYYY-MM-DD)
      supplement_name: required for supplement
    """
    activity_type = body.get("activity_type")
    shared = body.get("shared")
    item_id = body.get("item_id")
    date_str = body.get("date")
    supplement_name = body.get("supplement_name")

    if activity_type is None or shared is None:
        raise HTTPException(status_code=400, detail="activity_type and shared are required")

    supabase = get_supabase_service()
    client = supabase.client
    affected_date: Optional[date] = None

    try:
        if activity_type in _ROW_TABLES:
            if not item_id:
                raise HTTPException(status_code=400, detail=f"item_id is required for {activity_type}")
            table, date_col = _ROW_TABLES[activity_type]
            resp = client.table(table)\
                .update({"shared_with_chat": shared})\
                .eq("id", item_id)\
                .eq("user_id", user_id)\
                .execute()
            if not resp.data:
                raise HTTPException(status_code=404, detail="Activity not found")
            affected_date = _parse_date(resp.data[0].get(date_col))

        elif activity_type in _DATE_TABLES:
            if not date_str:
                raise HTTPException(status_code=400, detail=f"date is required for {activity_type}")
            table = _DATE_TABLES[activity_type]
            resp = client.table(table)\
                .update({"shared_with_chat": shared})\
                .eq("user_id", user_id)\
                .eq("date", date_str)\
                .execute()
            if not resp.data:
                raise HTTPException(status_code=404, detail="Activity not found")
            affected_date = _parse_date(date_str)

        elif activity_type == "supplement":
            if not date_str:
                raise HTTPException(status_code=400, detail="date is required for supplement")
            query = client.table("supplement_logs")\
                .update({"shared_with_chat": shared})\
                .eq("user_id", user_id)\
                .eq("date", date_str)
            # Optionally scope to a single supplement on that date.
            if supplement_name:
                query = query.eq("supplement_name", supplement_name)
            resp = query.execute()
            if not resp.data:
                raise HTTPException(status_code=404, detail="Activity not found")
            affected_date = _parse_date(date_str)

        else:
            raise HTTPException(status_code=400, detail=f"Unknown activity_type: {activity_type}")

        # Rebuild the cached chat context for the affected day so the change is
        # reflected immediately the next time the user opens the chat.
        if affected_date is not None:
            try:
                await get_context_manager().rebuild_context(user_id, affected_date)
            except Exception as e:
                print(f"⚠️ Sharing toggle: context rebuild failed (non-critical): {e}")

        return {"success": True, "shared": shared, "date": str(affected_date) if affected_date else None}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error setting activity sharing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}/defaults")
async def get_sharing_defaults(user_id: str):
    """Get the user's per-activity-type sharing defaults for new entries."""
    try:
        user = await get_supabase_service().get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True, "defaults": user.get("chat_sharing_defaults") or {}}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error getting sharing defaults: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{user_id}/defaults")
async def set_sharing_defaults(user_id: str, body: dict):
    """Merge per-activity-type sharing defaults.

    Body: { defaults: { "weight": false, "period": false, ... } }
    Any activity type omitted keeps its current value; a type set to true is
    removed (true is the implicit default), keeping the stored map small.
    """
    incoming = body.get("defaults")
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="defaults object is required")

    supabase = get_supabase_service()
    try:
        user = await supabase.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        defaults = dict(user.get("chat_sharing_defaults") or {})
        for activity_type, shared in incoming.items():
            if shared:
                defaults.pop(activity_type, None)  # true is the implicit default
            else:
                defaults[activity_type] = False

        supabase.client.table("users")\
            .update({"chat_sharing_defaults": defaults})\
            .eq("id", user_id)\
            .execute()

        return {"success": True, "defaults": defaults}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error setting sharing defaults: {e}")
        raise HTTPException(status_code=500, detail=str(e))
