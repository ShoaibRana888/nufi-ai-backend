# api/supplements.py
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime
import uuid

from models.supplement_schemas import SupplementPreferenceCreate, SupplementLogCreate
from services.supabase_service import get_supabase_service
from services.chat_context_manager import get_context_manager
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today, get_user_now

router = APIRouter()


@router.post("/supplements/preferences", response_model=dict)
async def save_supplement_preferences(preferences_data: SupplementPreferenceCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Save or update supplement preferences for a user"""
    try:
        print(f"💊 Saving supplement preferences for user: {preferences_data.user_id}")
        print(f"💊 Number of supplements: {len(preferences_data.supplements)}")

        supabase_service = get_supabase_service()

        # Clear existing preferences for this user
        await supabase_service.clear_supplement_preferences(preferences_data.user_id)

        # Save new preferences
        saved_preferences = []
        for supplement in preferences_data.supplements:
            preference_data = {
                'id': str(uuid.uuid4()),
                'user_id': preferences_data.user_id,
                'supplement_name': supplement.get('name', ''),
                'dosage': supplement.get('dosage', ''),
                'frequency': supplement.get('frequency', 'Daily'),
                'preferred_time': supplement.get('preferred_time', '9:00 AM'),
                'notes': supplement.get('notes', ''),
                'is_active': True,
                'created_at': get_user_now(tz_offset).isoformat(),
                'updated_at': get_user_now(tz_offset).isoformat()
            }

            saved_preference = await supabase_service.create_supplement_preference(preference_data)
            saved_preferences.append(saved_preference)

        print(f"✅ Saved {len(saved_preferences)} supplement preferences")

        return {
            "success": True,
            "preferences": saved_preferences,
            "message": f"Saved {len(saved_preferences)} supplement preferences"
        }

    except Exception as e:
        print(f"❌ Error saving supplement preferences: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/supplements/preferences/{user_id}")
async def get_supplement_preferences(user_id: str):
    """Get supplement preferences for a user"""
    try:
        print(f"💊 Getting supplement preferences for user: {user_id}")

        supabase_service = get_supabase_service()
        preferences = await supabase_service.get_supplement_preferences(user_id)

        print(f"✅ Retrieved {len(preferences)} supplement preferences")

        return {
            "success": True,
            "preferences": preferences,
            "count": len(preferences)
        }

    except Exception as e:
        print(f"❌ Error getting supplement preferences: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/supplements/log", response_model=dict)
async def log_supplement_intake(log_data: SupplementLogCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Log daily supplement intake"""
    try:
        print(f"💊 Logging supplement: {log_data.supplement_name} = {log_data.taken}")

        supabase_service = get_supabase_service()

        # Parse date
        try:
            entry_date = get_user_date(log_data.date, tz_offset)
        except ValueError:
            entry_date = get_user_today(tz_offset)

        # Check if log exists for this supplement and date
        existing_log = await supabase_service.get_supplement_log_by_date(
            log_data.user_id,
            log_data.supplement_name,
            entry_date
        )

        log_entry_data = {
            'user_id': log_data.user_id,
            'supplement_name': log_data.supplement_name,
            'date': str(entry_date),
            'taken': log_data.taken,
            'dosage': log_data.dosage,
            'time_taken': log_data.time_taken,
            'notes': log_data.notes,
            'updated_at': get_user_now(tz_offset).isoformat()
        }

        if existing_log:
            updated_log = await supabase_service.update_supplement_log(
                existing_log['id'],
                log_entry_data
            )
            result = {"success": True, "id": existing_log['id'], "log": updated_log}
        else:
            log_entry_data['id'] = str(uuid.uuid4())
            log_entry_data['created_at'] = get_user_now(tz_offset).isoformat()
            created_log = await supabase_service.create_supplement_log(log_entry_data)
            result = {"success": True, "id": created_log['id'], "log": created_log}

        # Update chat context
        context_manager = get_context_manager()
        await context_manager.update_context_activity(
            log_data.user_id,
            'supplement',
            log_entry_data,
            entry_date
        )

        return result

    except Exception as e:
        print(f"❌ Error logging supplement intake: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/supplements/status/{user_id}")
async def get_todays_supplement_status(user_id: str, date: Optional[str] = None, tz_offset: int = Depends(get_timezone_offset)):
    """Get today's supplement status for a user"""
    try:
        if date:
            target_date = get_user_date(date, tz_offset)
        else:
            target_date = get_user_today(tz_offset)

        print(f"💊 Getting supplement status for user: {user_id}, date: {target_date}")

        supabase_service = get_supabase_service()
        status = await supabase_service.get_supplement_status_by_date(user_id, target_date)

        print(f"✅ Retrieved status for {len(status)} supplements")

        return {
            "success": True,
            "status": status,
            "date": str(target_date)
        }

    except Exception as e:
        print(f"❌ Error getting supplement status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/supplements/history/{user_id}")
async def get_supplement_history(user_id: str, supplement_name: Optional[str] = None, days: int = 30):
    """Get supplement intake history"""
    try:
        print(f"💊 Getting supplement history for user: {user_id}")
        if supplement_name:
            print(f"💊 Filtering by supplement: {supplement_name}")

        supabase_service = get_supabase_service()
        history = await supabase_service.get_supplement_history(
            user_id,
            supplement_name=supplement_name,
            days=days
        )

        print(f"✅ Retrieved {len(history)} supplement history records")

        return {
            "success": True,
            "history": history,
            "count": len(history)
        }

    except Exception as e:
        print(f"❌ Error getting supplement history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/supplements/{user_id}/history")
async def get_supplement_history_in_range(
    user_id: str,
    start: str,
    end: str
):
    """Get supplement history for a date range"""
    try:
        supabase_service = get_supabase_service()

        start_date = datetime.strptime(start, '%Y-%m-%d').date()
        end_date = datetime.strptime(end, '%Y-%m-%d').date()
        days = (end_date - start_date).days + 1

        history = await supabase_service.get_supplement_history(
            user_id,
            days=days
        )

        # Filter by date range
        filtered_history = [
            log for log in history
            if start_date <= datetime.strptime(log['date'], '%Y-%m-%d').date() <= end_date
        ]

        return {
            "success": True,
            "history": filtered_history,
            "count": len(filtered_history)
        }
    except Exception as e:
        print(f"❌ Error getting supplement history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/supplements/stats/{user_id}")
async def get_supplement_stats(user_id: str, days: int = 30):
    """Get supplement statistics for the last N days"""
    try:
        print(f"💊 Getting supplement stats for user: {user_id}, last {days} days")

        supabase_service = get_supabase_service()

        # Get all logs for the period
        history = await supabase_service.get_supplement_history(user_id, days=days)

        if not history:
            return {
                "success": True,
                "stats": {
                    "total_supplements": 0,
                    "adherence_rate": 0.0,
                    "days_tracked": 0,
                    "most_consistent": None,
                    "least_consistent": None
                }
            }

        # Calculate statistics
        supplement_stats = {}
        for log in history:
            name = log['supplement_name']
            if name not in supplement_stats:
                supplement_stats[name] = {'taken': 0, 'total': 0}

            supplement_stats[name]['total'] += 1
            if log['taken']:
                supplement_stats[name]['taken'] += 1

        # Calculate adherence rates
        adherence_rates = {}
        for name, stats in supplement_stats.items():
            adherence_rates[name] = (stats['taken'] / stats['total']) * 100 if stats['total'] > 0 else 0

        # Find most and least consistent
        most_consistent = max(adherence_rates.items(), key=lambda x: x[1]) if adherence_rates else None
        least_consistent = min(adherence_rates.items(), key=lambda x: x[1]) if adherence_rates else None

        # Overall adherence rate
        total_taken = sum(stats['taken'] for stats in supplement_stats.values())
        total_doses = sum(stats['total'] for stats in supplement_stats.values())
        overall_adherence = (total_taken / total_doses) * 100 if total_doses > 0 else 0

        stats_result = {
            "total_supplements": len(supplement_stats),
            "adherence_rate": round(overall_adherence, 1),
            "days_tracked": days,
            "most_consistent": most_consistent[0] if most_consistent else None,
            "least_consistent": least_consistent[0] if least_consistent else None,
            "supplement_breakdown": adherence_rates
        }

        return {"success": True, "stats": stats_result}

    except Exception as e:
        print(f"❌ Error getting supplement stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/supplements/preferences/{preference_id}")
async def delete_supplement_preference(preference_id: str):
    """Delete a supplement preference"""
    try:
        print(f"💊 Deleting supplement preference: {preference_id}")

        supabase_service = get_supabase_service()
        success = await supabase_service.delete_supplement_preference(preference_id)

        if success:
            return {"success": True, "message": "Supplement preference deleted successfully"}
        else:
            return {"success": False, "message": "Supplement preference not found"}

    except Exception as e:
        print(f"❌ Error deleting supplement preference: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/supplements/{user_id}/status")
async def get_supplement_status_by_date(
    user_id: str,
    date: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset)
):
    """Get supplement status for a specific date"""
    try:
        supabase_service = get_supabase_service()

        if date:
            try:
                entry_date = datetime.strptime(date, '%Y-%m-%d').date()
            except ValueError:
                entry_date = get_user_today(tz_offset)
        else:
            entry_date = get_user_today(tz_offset)

        status = await supabase_service.get_supplement_status_by_date(user_id, entry_date)

        return {
            "success": True,
            "status": status,
            "date": str(entry_date)
        }
    except Exception as e:
        print(f"❌ Error getting supplement status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
