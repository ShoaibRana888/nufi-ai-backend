# api/sleep.py
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
import uuid

from models.sleep_schemas import SleepEntryCreate, SleepEntryUpdate
from services.supabase_service import get_supabase_service
from services.chat_context_manager import get_context_manager
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today, get_user_now

router = APIRouter()


@router.post("/sleep/entries", response_model=dict)
async def create_sleep_entry(sleep_data: SleepEntryCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Create or update sleep entry"""
    try:
        print(f"😴 Creating sleep entry: {sleep_data.total_hours}h for user {sleep_data.user_id}")

        supabase_service = get_supabase_service()

        # Parse date
        try:
            entry_date = get_user_date(sleep_data.date, tz_offset)
        except ValueError:
            entry_date = get_user_today(tz_offset)

        # Parse bedtime and wake_time if provided
        bedtime = None
        wake_time = None

        if sleep_data.bedtime:
            try:
                bedtime = get_user_date(sleep_data.bedtime, tz_offset)
            except ValueError:
                pass

        if sleep_data.wake_time:
            try:
                wake_time = get_user_date(sleep_data.wake_time, tz_offset)
            except ValueError:
                pass

        # Check if entry exists for this date
        existing_entry = await supabase_service.get_sleep_entry_by_date(
            sleep_data.user_id,
            entry_date
        )

        sleep_entry_data = {
            'user_id': sleep_data.user_id,
            'date': str(entry_date),
            'bedtime': bedtime.isoformat() if bedtime else None,
            'wake_time': wake_time.isoformat() if wake_time else None,
            'total_hours': sleep_data.total_hours,
            'quality_score': sleep_data.quality_score,
            'deep_sleep_hours': sleep_data.deep_sleep_hours,
            'sleep_issues': sleep_data.sleep_issues or [],
            'notes': sleep_data.notes,
            'updated_at': get_user_now(tz_offset).isoformat()
        }

        if existing_entry:
            updated_entry = await supabase_service.update_sleep_entry(
                existing_entry['id'],
                sleep_entry_data
            )
            result = {"success": True, "id": existing_entry['id'], "entry": updated_entry}
        else:
            sleep_entry_data['id'] = str(uuid.uuid4())
            sleep_entry_data['created_at'] = get_user_now(tz_offset).isoformat()
            created_entry = await supabase_service.create_sleep_entry(sleep_entry_data)
            result = {"success": True, "id": created_entry['id'], "entry": created_entry}

        # Update chat context
        context_manager = get_context_manager()
        await context_manager.update_context_activity(
            sleep_data.user_id,
            'sleep',
            sleep_entry_data,
            entry_date
        )

        return result

    except Exception as e:
        print(f"❌ Error creating sleep entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sleep/entries/{user_id}")
async def get_sleep_history(user_id: str, limit: int = 30):
    """Get sleep history for a user"""
    try:
        print(f"😴 Getting sleep history for user: {user_id}, limit: {limit}")

        supabase_service = get_supabase_service()
        entries = await supabase_service.get_sleep_history(user_id, limit)

        # Format entries for Flutter
        formatted_entries = []
        for entry in entries:
            formatted_entry = {
                'id': entry['id'],
                'user_id': entry['user_id'],
                'date': entry['date'],
                'bedtime': entry.get('bedtime'),
                'wake_time': entry.get('wake_time'),
                'total_hours': float(entry.get('total_hours', 0.0)),
                'quality_score': float(entry.get('quality_score', 0.0)),
                'deep_sleep_hours': float(entry.get('deep_sleep_hours', 0.0)),
                'sleep_issues': entry.get('sleep_issues', []),
                'notes': entry.get('notes'),
                'created_at': entry.get('created_at'),
                'updated_at': entry.get('updated_at')
            }
            formatted_entries.append(formatted_entry)

        print(f"✅ Returning {len(formatted_entries)} sleep entries")
        return formatted_entries

    except Exception as e:
        print(f"❌ Error getting sleep history: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sleep/entries/{user_id}/{date}")
async def get_sleep_entry_by_date(user_id: str, date: str, tz_offset: int = Depends(get_timezone_offset)):
    """Get sleep entry for a specific date"""
    try:
        print(f"Getting sleep entry for user: {user_id}, date: {date}")

        supabase_service = get_supabase_service()

        # Parse date
        try:
            entry_date = entry_date = get_user_date(date, tz_offset)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        entry = await supabase_service.get_sleep_entry_by_date(user_id, entry_date)

        if entry:
            # Format the response consistently
            formatted_entry = {
                'id': entry['id'],
                'user_id': entry['user_id'],
                'date': entry['date'],
                'bedtime': entry.get('bedtime'),
                'wake_time': entry.get('wake_time'),
                'total_hours': float(entry.get('total_hours', 0.0)),
                'quality_score': float(entry.get('quality_score', 0.0)),
                'deep_sleep_hours': float(entry.get('deep_sleep_hours', 0.0)),
                'sleep_issues': entry.get('sleep_issues', []),
                'notes': entry.get('notes'),
                'created_at': entry.get('created_at'),
                'updated_at': entry.get('updated_at')
            }

            print(f"Found sleep entry: {formatted_entry}")
            # Return consistent structure like other endpoints
            return {
                "success": True,
                "entry": formatted_entry
            }
        else:
            print(f"No sleep entry found for {user_id} on {date}")
            # Return null entry instead of 404 error - consistent with water endpoint
            return {
                "success": True,
                "entry": None
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting sleep entry by date: {e}")
        return {
            "success": False,
            "entry": None,
            "error": str(e)
        }

@router.put("/sleep/entries/{entry_id}")
async def update_sleep_entry(entry_id: str, sleep_data: SleepEntryUpdate, tz_offset: int = Depends(get_timezone_offset)):
    """Update an existing sleep entry"""
    try:
        print(f"😴 Updating sleep entry: {entry_id}")

        supabase_service = get_supabase_service()

        update_data = {}

        if sleep_data.bedtime is not None:
            try:
                bedtime = get_user_date(sleep_data.bedtime, tz_offset)
                update_data['bedtime'] = bedtime.isoformat()
            except ValueError:
                pass

        if sleep_data.wake_time is not None:
            try:
                wake_time = get_user_date(sleep_data.wake_time, tz_offset)
                update_data['wake_time'] = wake_time.isoformat()
            except ValueError:
                pass

        if sleep_data.total_hours is not None:
            update_data['total_hours'] = sleep_data.total_hours
        if sleep_data.quality_score is not None:
            update_data['quality_score'] = sleep_data.quality_score
        if sleep_data.deep_sleep_hours is not None:
            update_data['deep_sleep_hours'] = sleep_data.deep_sleep_hours
        if sleep_data.sleep_issues is not None:
            update_data['sleep_issues'] = sleep_data.sleep_issues
        if sleep_data.notes is not None:
            update_data['notes'] = sleep_data.notes

        update_data['updated_at'] = get_user_now(tz_offset).isoformat()

        updated_entry = await supabase_service.update_sleep_entry(entry_id, update_data)

        return {"success": True, "entry": updated_entry}

    except Exception as e:
        print(f"❌ Error updating sleep entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/sleep/entries/{entry_id}")
async def delete_sleep_entry(entry_id: str):
    """Delete a sleep entry"""
    try:
        print(f"😴 Deleting sleep entry: {entry_id}")

        supabase_service = get_supabase_service()
        context_manager = get_context_manager()

        # Get entry details before deletion
        entry = await supabase_service.get_sleep_entry_by_id(entry_id)
        if not entry:
            return {"success": False, "message": "Sleep entry not found"}

        # Delete from database
        success = await supabase_service.delete_sleep_entry(entry_id)

        if success:
            # Update context - remove sleep hours
            entry_date = datetime.fromisoformat(entry['date']).date()
            await context_manager.update_context_activity(
                entry['user_id'],
                'sleep',
                {'total_hours': None},
                entry_date
            )

            return {"success": True, "message": "Sleep entry deleted successfully"}
        else:
            return {"success": False, "message": "Failed to delete sleep entry"}

    except Exception as e:
        print(f"❌ Error deleting sleep entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sleep/stats/{user_id}")
async def get_sleep_stats(user_id: str, days: int = 30):
    """Get sleep statistics for the last N days"""
    try:
        print(f"😴 Getting sleep stats for user: {user_id}, last {days} days")

        supabase_service = get_supabase_service()
        entries = await supabase_service.get_sleep_history(user_id, days)

        if not entries:
            return {
                "success": True,
                "stats": {
                    "avg_sleep": 0.0,
                    "avg_quality": 0.0,
                    "avg_deep_sleep": 0.0,
                    "entries_count": 0,
                    "sleep_efficiency": 0.0
                }
            }

        # Calculate statistics
        total_sleep = sum(entry.get('total_hours', 0) for entry in entries)
        total_quality = sum(entry.get('quality_score', 0) for entry in entries)
        total_deep_sleep = sum(entry.get('deep_sleep_hours', 0) for entry in entries)

        avg_sleep = total_sleep / len(entries)
        avg_quality = total_quality / len(entries)
        avg_deep_sleep = total_deep_sleep / len(entries)

        # Calculate sleep efficiency (deep sleep / total sleep)
        sleep_efficiency = (avg_deep_sleep / avg_sleep * 100) if avg_sleep > 0 else 0

        stats = {
            "avg_sleep": round(avg_sleep, 1),
            "avg_quality": round(avg_quality, 2),
            "avg_deep_sleep": round(avg_deep_sleep, 1),
            "entries_count": len(entries),
            "sleep_efficiency": round(sleep_efficiency, 1)
        }

        return {"success": True, "stats": stats}

    except Exception as e:
        print(f"❌ Error getting sleep stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
