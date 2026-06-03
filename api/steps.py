# api/steps.py
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime
import uuid

from models.step_schemas import StepEntryCreate
from services.supabase_service import get_supabase_service
from services.chat_context_manager import get_context_manager
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today, get_user_now

router = APIRouter()


@router.post("/steps", response_model=dict)
async def save_step_entry(step_data: StepEntryCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Save or update daily step entry"""
    try:
        print(f"🚶 Saving step entry: {step_data.steps} steps for user {step_data.userId}")

        supabase_service = get_supabase_service()

        # Parse date
        try:
            entry_date = get_user_date(step_data.date, tz_offset)
        except ValueError:
            entry_date = get_user_today(tz_offset)

        # Check if entry exists for this date
        existing_entry = await supabase_service.get_step_entry_by_date(
            step_data.userId,
            entry_date
        )

        step_entry_data = {
            'user_id': step_data.userId,
            'date': str(entry_date),
            'steps': step_data.steps,
            'goal': step_data.goal,
            'calories_burned': step_data.caloriesBurned,
            'distance_km': step_data.distanceKm,
            'active_minutes': step_data.activeMinutes,
            'source_type': step_data.sourceType,
            'last_synced': step_data.lastSynced,
            'updated_at': get_user_now(tz_offset).isoformat()
        }

        if existing_entry:
            updated_entry = await supabase_service.update_step_entry(
                existing_entry['id'],
                step_entry_data
            )
            result = {"success": True, "id": existing_entry['id'], "entry": updated_entry}
        else:
            step_entry_data['id'] = str(uuid.uuid4())
            step_entry_data['created_at'] = get_user_now(tz_offset).isoformat()
            created_entry = await supabase_service.create_step_entry(step_entry_data)
            result = {"success": True, "id": created_entry['id'], "entry": created_entry}

        # Update chat context
        context_manager = get_context_manager()
        await context_manager.update_context_activity(
            step_data.userId,
            'steps',
            step_entry_data,
            entry_date
        )

        return result

    except Exception as e:
        print(f"❌ Error saving step entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/steps/{user_id}")
async def get_steps_by_date(
    user_id: str,
    date: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset)
):
    """Get step entry for a specific date"""
    try:
        supabase_service = get_supabase_service()

        # Parse date
        if date:
            try:
                entry_date = datetime.strptime(date, '%Y-%m-%d').date()
            except ValueError:
                entry_date = get_user_today(tz_offset)
        else:
            entry_date = get_user_today(tz_offset)

        entry = await supabase_service.get_step_entry_by_date(user_id, entry_date)

        if entry:
            return {
                "success": True,
                "entry": entry
            }
        else:
            return {
                "success": False,
                "message": "No step entry found for this date"
            }
    except Exception as e:
        print(f"❌ Error getting steps by date: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/steps/{user_id}/today")
async def get_today_steps(user_id: str, tz_offset: int = Depends(get_timezone_offset)):
    """Get today's step entry with user's default goal"""
    try:
        print(f"🚶 Getting today's steps for user: {user_id}")

        supabase_service = get_supabase_service()
        today = get_user_today(tz_offset)

        # Get user's step goal preference
        user = await supabase_service.get_user(user_id)
        user_step_goal = user.get('daily_step_goal', 10000) if user else 10000

        # Get today's entry
        entry = await supabase_service.get_step_entry_by_date(user_id, today)

        if not entry:
            # Create virtual entry with user's goal
            entry = {
                'id': None,
                'user_id': user_id,
                'date': str(today),
                'steps': 0,
                'goal': user_step_goal,  # Use user's preference
                'calories_burned': 0.0,
                'distance_km': 0.0,
                'active_minutes': 0,
                'source_type': 'none',
                'last_synced': None,
                'created_at': None,
                'updated_at': None
            }

        return {"success": True, "entry": entry}

    except Exception as e:
        print(f"❌ Error getting today's steps: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/steps/{user_id}/range")
async def get_steps_in_range(
    user_id: str,
    start: str,
    end: str
):
    """Get step entries for a date range"""
    try:
        supabase_service = get_supabase_service()

        start_date = datetime.strptime(start, '%Y-%m-%d').date()
        end_date = datetime.strptime(end, '%Y-%m-%d').date()

        entries = await supabase_service.get_steps_in_range(user_id, start_date, end_date)

        return {
            "success": True,
            "entries": entries,
            "count": len(entries)
        }
    except Exception as e:
        print(f"❌ Error getting steps in range: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/steps/{user_id}/{date}")
async def delete_step_entry(user_id: str, date: str, tz_offset: int = Depends(get_timezone_offset)):
    """Delete a step entry for a specific date"""
    try:
        print(f"🚶 Deleting step entry for user: {user_id}, date: {date}")

        supabase_service = get_supabase_service()
        context_manager = get_context_manager()

        # Parse date
        entry_date = get_user_date(date, tz_offset)

        # Delete from database
        success = await supabase_service.delete_step_entry_by_date(user_id, entry_date)

        if success:
            # Update context - reset steps to 0
            await context_manager.update_context_activity(
                user_id,
                'steps',
                {'steps': 0},
                entry_date
            )

            return {"success": True, "message": "Step entry deleted successfully"}
        else:
            return {"success": False, "message": "Step entry not found"}

    except Exception as e:
        print(f"❌ Error deleting step entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/steps/{user_id}/stats")
async def get_step_stats(user_id: str, days: int = 7):
    """Get step statistics using user's default goal"""
    try:
        print(f"🚶 Getting step stats for user: {user_id}, last {days} days")

        supabase_service = get_supabase_service()
        entries = await supabase_service.get_step_history(user_id, days)

        # Get user's default goal
        user = await supabase_service.get_user(user_id)
        user_step_goal = user.get('daily_step_goal', 10000) if user else 10000

        if not entries:
            return {
                "success": True,
                "stats": {
                    "average_daily_steps": 0,
                    "best_day_steps": 0,
                    "goal_achievement_rate": 0,
                    "total_steps": 0,
                    "streak_days": 0,
                    "total_distance": 0.0,
                    "total_calories": 0.0
                }
            }

        # Calculate statistics using user's goal as fallback
        daily_steps = [entry.get('steps', 0) for entry in entries]
        goal_achievements = [
            entry.get('steps', 0) >= entry.get('goal', user_step_goal)
            for entry in entries
        ]

        stats = {
            "average_daily_steps": round(sum(daily_steps) / len(daily_steps)),
            "best_day_steps": max(daily_steps),
            "goal_achievement_rate": round((sum(goal_achievements) / len(goal_achievements)) * 100, 1),
            "total_steps": sum(daily_steps),
            "streak_days": _calculate_step_streak(goal_achievements),
            "total_distance": round(sum(entry.get('distance_km', 0) for entry in entries), 2),
            "total_calories": round(sum(entry.get('calories_burned', 0) for entry in entries), 1)
        }

        return {"success": True, "stats": stats}

    except Exception as e:
        print(f"❌ Error getting step stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _calculate_step_streak(achievements: List[bool]) -> int:
    """Calculate current streak of step goal achievements"""
    streak = 0
    for achieved in achievements:
        if achieved:
            streak += 1
        else:
            break
    return streak
