# api/water.py
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime
import uuid

from models.water_schemas import WaterEntryCreate
from services.supabase_service import get_supabase_service
from services.chat_context_manager import get_context_manager
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today, get_user_now

router = APIRouter()


@router.post("/water", response_model=dict)
async def save_water_entry(water_data: WaterEntryCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Save or update daily water intake"""
    try:
        print(f"💧 Saving water entry: {water_data.glasses_consumed} glasses for user {water_data.user_id}")

        supabase_service = get_supabase_service()

        # Parse date and convert to date only (not datetime)
        try:
            entry_date = get_user_date(water_data.date, tz_offset)
        except ValueError:
            entry_date = get_user_today(tz_offset)

        # Check if entry exists for this date
        existing_entry = await supabase_service.get_water_entry_by_date(
            water_data.user_id,
            entry_date
        )

        water_entry_data = {
            'user_id': water_data.user_id,
            'date': str(entry_date),  # Convert date to string for Supabase
            'glasses_consumed': water_data.glasses_consumed,
            'total_ml': water_data.total_ml,
            'target_ml': water_data.target_ml,
            'notes': water_data.notes,
            'updated_at': get_user_now(tz_offset).isoformat()
        }

        if existing_entry:
            # Update existing entry
            updated_entry = await supabase_service.update_water_entry(
                existing_entry['id'],
                water_entry_data
            )
            return {"success": True, "id": existing_entry['id'], "entry": updated_entry}
        else:
            water_entry_data['id'] = str(uuid.uuid4())
            water_entry_data['created_at'] = get_user_now(tz_offset).isoformat()
            created_entry = await supabase_service.create_water_entry(water_entry_data)
            result = {"success": True, "id": created_entry['id'], "entry": created_entry}

        # Update chat context
        context_manager = get_context_manager()
        await context_manager.update_context_activity(
            water_data.user_id,
            'water',
            water_entry_data,
            entry_date
        )

        return result

    except Exception as e:
        print(f"❌ Error saving water entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/water/{user_id}/today")
async def get_today_water(user_id: str, tz_offset: int = Depends(get_timezone_offset)):
    """Get today's water intake"""
    try:
        print(f"💧 Getting today's water for user: {user_id}")

        supabase_service = get_supabase_service()
        today = get_user_today(tz_offset)
        entry = await supabase_service.get_water_entry_by_date(user_id, today)

        return {"success": True, "entry": entry}

    except Exception as e:
        print(f"❌ Error getting today's water: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/water/{user_id}/history")
async def get_water_history(user_id: str, limit: int = 30):
    """Get water intake history"""
    try:
        supabase_service = get_supabase_service()
        entries = await supabase_service.get_water_history(user_id, limit=limit)

        return {
            "success": True,
            "entries": entries,
            "count": len(entries)
        }
    except Exception as e:
        print(f"❌ Error getting water history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/water/{user_id}")
async def get_water_by_date(
    user_id: str,
    date: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset)
):
    """Get water entry for a specific date"""
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

        # Get entry for date
        entry = await supabase_service.get_water_entry_by_date(user_id, entry_date)

        if entry:
            return {
                "success": True,
                "entry": entry
            }
        else:
            return {
                "success": False,
                "message": "No water entry found for this date"
            }
    except Exception as e:
        print(f"❌ Error getting water by date: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/water/{user_id}/{date}")
async def delete_water_entry(user_id: str, date: str, tz_offset: int = Depends(get_timezone_offset)):
    """Delete water entry for a specific date"""
    try:
        print(f"💧 Deleting water entry for user: {user_id}, date: {date}")

        supabase_service = get_supabase_service()
        context_manager = get_context_manager()

        # Parse date
        entry_date = get_user_date(date, tz_offset)

        # Get existing entry
        existing = await supabase_service.get_water_entry_by_date(user_id, entry_date)
        if not existing:
            return {"success": False, "message": "Water entry not found"}

        # Delete from database
        success = await supabase_service.delete_water_entry(existing['id'])

        if success:
            # Update context - reset water to 0
            await context_manager.update_context_activity(
                user_id,
                'water',
                {'glasses_consumed': 0},
                entry_date
            )

            return {"success": True, "message": "Water entry deleted successfully"}
        else:
            return {"success": False, "message": "Failed to delete water entry"}

    except Exception as e:
        print(f"❌ Error deleting water entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/water/{user_id}/stats")
async def get_water_stats(user_id: str, days: int = 7):
    """Get water intake statistics for the last N days"""
    try:
        print(f"💧 Getting water stats for user: {user_id}, last {days} days")

        supabase_service = get_supabase_service()
        entries = await supabase_service.get_water_history(user_id, days)

        if not entries:
            return {
                "success": True,
                "stats": {
                    "average_daily": 0,
                    "best_day": 0,
                    "goal_achievement_rate": 0,
                    "total_glasses": 0,
                    "streak_days": 0
                }
            }

        # Calculate statistics
        daily_totals = [entry.get('total_ml', 0) for entry in entries]
        goal_achievements = [entry.get('total_ml', 0) >= entry.get('target_ml', 2000) for entry in entries]

        stats = {
            "average_daily": round(sum(daily_totals) / len(daily_totals), 1),
            "best_day": max(daily_totals),
            "goal_achievement_rate": round((sum(goal_achievements) / len(goal_achievements)) * 100, 1),
            "total_glasses": sum(entry.get('glasses_consumed', 0) for entry in entries),
            "streak_days": _calculate_water_streak(goal_achievements)
        }

        return {"success": True, "stats": stats}

    except Exception as e:
        print(f"❌ Error getting water stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _calculate_water_streak(achievements: List[bool]) -> int:
    """Calculate current streak of goal achievements"""
    streak = 0
    for achieved in achievements:
        if achieved:
            streak += 1
        else:
            break
    return streak
