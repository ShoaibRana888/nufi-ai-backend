# api/periods.py
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
import uuid

from models.period_schemas import PeriodEntryCreate
from services.supabase_service import get_supabase_service
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today, get_user_now

router = APIRouter()


@router.post("/period", response_model=dict)
async def save_period_entry(period_data: PeriodEntryCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Save or update period entry"""
    try:
        print(f"🌸 Saving period entry for user {period_data.user_id}")

        supabase_service = get_supabase_service()

        # Parse dates
        try:
            start_date = get_user_date(period_data.start_date, tz_offset)
        except ValueError:
            start_date = get_user_today(tz_offset)

        end_date = None
        if period_data.end_date:
            try:
                end_date = get_user_date(period_data.end_date ,tz_offset)
            except ValueError:
                pass

        period_entry_data = {
            'user_id': period_data.user_id,
            'start_date': str(start_date),
            'end_date': str(end_date) if end_date else None,
            'flow_intensity': period_data.flow_intensity,
            'symptoms': period_data.symptoms or [],
            'mood': period_data.mood,
            'notes': period_data.notes,
            'updated_at': get_user_now(tz_offset).isoformat()
        }

        # Check if there's an ongoing period entry
        existing_entry = await supabase_service.get_current_period(period_data.user_id)

        if existing_entry and not existing_entry.get('end_date'):
            # Update existing ongoing period
            updated_entry = await supabase_service.update_period_entry(
                existing_entry['id'],
                period_entry_data
            )
            return {"success": True, "id": existing_entry['id'], "period": updated_entry}
        else:
            # Create new period entry
            period_entry_data['id'] = str(uuid.uuid4())
            period_entry_data['created_at'] = get_user_now(tz_offset).isoformat()
            created_entry = await supabase_service.create_period_entry(period_entry_data)
            return {"success": True, "id": created_entry['id'], "period": created_entry}

    except Exception as e:
        print(f"❌ Error saving period entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/period/{user_id}")
async def get_period_history(user_id: str, limit: int = 12):
    """Get period history for user"""
    try:
        print(f"🌸 Getting period history for user: {user_id}")

        supabase_service = get_supabase_service()
        entries = await supabase_service.get_period_history(user_id, limit)

        return {"success": True, "periods": entries}

    except Exception as e:
        print(f"❌ Error getting period history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/period/{user_id}/current")
async def get_current_period(user_id: str):
    """Get current ongoing period"""
    try:
        print(f"🌸 Getting current period for user: {user_id}")

        supabase_service = get_supabase_service()
        current_period = await supabase_service.get_current_period(user_id)

        return {"success": True, "period": current_period}

    except Exception as e:
        print(f"❌ Error getting current period: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/period/{period_id}")
async def delete_period_entry(period_id: str):
    """Delete a period entry"""
    try:
        print(f"🌸 Deleting period entry: {period_id}")

        supabase_service = get_supabase_service()
        # Period entries might not need context updates as they're not daily metrics

        success = await supabase_service.delete_period_entry(period_id)

        if success:
            return {"success": True, "message": "Period entry deleted successfully"}
        else:
            return {"success": False, "message": "Period entry not found"}

    except Exception as e:
        print(f"❌ Error deleting period entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/period/{period_id}/end")
async def end_period(period_id: str, end_date: str, tz_offset: int = Depends(get_timezone_offset)):
    """End an ongoing period"""
    try:
        print(f"🌸 Ending period {period_id} on {end_date}")

        supabase_service = get_supabase_service()

        # Parse end date
        try:
            parsed_end_date = get_user_date(end_date, tz_offset)
        except ValueError:
            parsed_end_date = get_user_today(tz_offset)

        # Update the period entry
        updated_entry = await supabase_service.update_period_entry(
            period_id,
            {
                'end_date': str(parsed_end_date),
                'updated_at': get_user_now(tz_offset).isoformat()
            }
        )

        return {"success": True, "period": updated_entry}

    except Exception as e:
        print(f"❌ Error ending period: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/period/custom")
async def create_custom_period(period_data: PeriodEntryCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Create a period entry for past dates (missed logging)"""
    try:
        print(f"🌸 Creating custom period entry for user {period_data.user_id}")

        supabase_service = get_supabase_service()

        # Parse dates - allow past dates
        start_date = get_user_date(period_data.start_date, tz_offset)
        end_date = None
        if period_data.end_date:
            end_date = get_user_date(period_data.end_date, tz_offset)

        period_entry_data = {
            'id': str(uuid.uuid4()),
            'user_id': period_data.user_id,
            'start_date': str(start_date),
            'end_date': str(end_date) if end_date else None,
            'flow_intensity': period_data.flow_intensity,
            'symptoms': period_data.symptoms or [],
            'mood': period_data.mood,
            'notes': period_data.notes,
            'created_at': get_user_now(tz_offset).isoformat(),
            'updated_at': get_user_now(tz_offset).isoformat()
        }

        created_entry = await supabase_service.create_period_entry(period_entry_data)

        # Update user's last period date if this is more recent
        user = await supabase_service.get_user_by_id(period_data.user_id)
        if user:
            last_period = user.get('last_period_date')
            if not last_period or start_date > datetime.fromisoformat(last_period.replace('Z', '+00:00')).date():
                await supabase_service.update_user(
                    period_data.user_id,
                    {'last_period_date': str(start_date)}
                )

        return {"success": True, "id": created_entry['id'], "period": created_entry}

    except Exception as e:
        print(f"❌ Error creating custom period entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))
