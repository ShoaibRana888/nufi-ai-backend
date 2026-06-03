# api/weight.py
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
import uuid

from models.weight_schemas import WeightEntryCreate
from services.supabase_service import get_supabase_service
from services.chat_context_manager import get_context_manager
from utils.timezone_utils import get_timezone_offset, get_user_now

router = APIRouter()


@router.post("/weight", response_model=dict)
async def save_weight_entry(weight_data: WeightEntryCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Save or update weight entry"""
    try:
        print(f"⚖️ Saving weight entry: {weight_data.weight} kg for user {weight_data.user_id}")

        supabase_service = get_supabase_service()

        # Parse date
        try:
            if isinstance(weight_data.date, str):
                # Parse the ISO datetime string preserving time
                if 'T' in weight_data.date:
                    # It's a full datetime string
                    entry_datetime = datetime.fromisoformat(weight_data.date.replace('Z', '+00:00'))
                else:
                    # It's just a date, use current time
                    entry_datetime = get_user_now(tz_offset)
            else:
                entry_datetime = get_user_now(tz_offset)
        except ValueError:
            entry_datetime = get_user_now(tz_offset)

        weight_entry_data = {
            'user_id': weight_data.user_id,
            'date': entry_datetime.isoformat(),
            'weight': weight_data.weight,
            'notes': weight_data.notes,
            'body_fat_percentage': weight_data.body_fat_percentage,
            'muscle_mass_kg': weight_data.muscle_mass_kg,
            'updated_at': get_user_now(tz_offset).isoformat()
        }

        # Always create new entry for weight (allow multiple entries per day)
        weight_entry_data['id'] = str(uuid.uuid4())
        weight_entry_data['created_at'] = get_user_now(tz_offset).isoformat()

        created_entry = await supabase_service.create_weight_entry(weight_entry_data)

        # ✅ NEW: Initialize starting weight if this is user's first entry
        await supabase_service.initialize_starting_weight_for_user(weight_data.user_id)

        # Update chat context (use date only from datetime)
        context_manager = get_context_manager()
        entry_date_only = entry_datetime.date()
        await context_manager.update_context_activity(
            weight_data.user_id,
            'weight',
            weight_entry_data,
            entry_date_only
        )

        return {"success": True, "id": created_entry['id'], "entry": created_entry}

    except Exception as e:
        print(f"❌ Error saving weight entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/weight/{user_id}")
async def get_weight_history(user_id: str, limit: int = 50):
    """Get weight history for a user"""
    try:
        print(f"⚖️ Getting weight history for user: {user_id}, limit: {limit}")

        supabase_service = get_supabase_service()
        entries = await supabase_service.get_weight_history(user_id, limit)

        print(f"✅ Returning {len(entries)} weight entries")

        return {
            "success": True,
            "weights": entries,
            "summary": {
                "total_entries": len(entries)
            }
        }

    except Exception as e:
        print(f"❌ Error getting weight history: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/weight/{user_id}/latest")
async def get_latest_weight(user_id: str):
    """Get the latest weight entry for a user"""
    try:
        print(f"⚖️ Getting latest weight for user: {user_id}")

        supabase_service = get_supabase_service()
        entry = await supabase_service.get_latest_weight(user_id)

        return {"success": True, "weight": entry}

    except Exception as e:
        print(f"❌ Error getting latest weight: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/weight/{entry_id}")
async def delete_weight_entry(entry_id: str):
    """Delete a weight entry and update user's profile weight"""
    try:
        print(f"⚖️ Deleting weight entry: {entry_id}")

        supabase_service = get_supabase_service()
        context_manager = get_context_manager()

        # Get entry details before deletion
        entry = await supabase_service.get_weight_entry_by_id(entry_id)
        if not entry:
            return {"success": False, "message": "Weight entry not found"}

        user_id = entry['user_id']

        # Delete from database
        success = await supabase_service.delete_weight_entry(entry_id)

        if success:
            # Update context - remove weight for that date
            entry_date = datetime.fromisoformat(entry['date']).date()
            await context_manager.update_context_activity(
                user_id,
                'weight',
                {'weight': None},  # Set to None to indicate no weight for today
                entry_date
            )

            # ✅ NEW: Update user's profile weight after deletion
            latest_weight_entry = await supabase_service.get_latest_weight(user_id)

            if latest_weight_entry:
                # Update to the most recent remaining weight entry
                new_weight = latest_weight_entry['weight']
                await supabase_service.update_user_weight(user_id, new_weight)
                print(f"✅ Updated user profile weight to {new_weight} kg (latest entry)")
            else:
                # No entries remain - revert to starting weight
                user = await supabase_service.get_user_by_id(user_id)
                starting_weight = user.get('starting_weight') or user.get('weight', 0)
                await supabase_service.update_user_weight(user_id, starting_weight)
                print(f"✅ Reverted user profile weight to starting weight: {starting_weight} kg")

            return {"success": True, "message": "Weight entry deleted successfully"}
        else:
            return {"success": False, "message": "Failed to delete weight entry"}

    except Exception as e:
        print(f"❌ Error deleting weight entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/weight/{user_id}/stats")
async def get_weight_stats(user_id: str, days: int = 30):
    """Get weight statistics for the last N days"""
    try:
        print(f"⚖️ Getting weight stats for user: {user_id}, last {days} days")

        supabase_service = get_supabase_service()
        entries = await supabase_service.get_weight_history(user_id, days)

        if not entries:
            return {
                "success": True,
                "stats": {
                    "average_weight": 0,
                    "weight_trend": "stable",
                    "total_change": 0,
                    "weekly_change": 0,
                    "monthly_change": 0
                }
            }

        weights = [entry.get('weight', 0) for entry in entries]
        avg_weight = sum(weights) / len(weights)

        # Determine trend
        if len(weights) >= 2:
            total_change = weights[0] - weights[-1]
            if total_change > 0.5:
                trend = "gaining"
            elif total_change < -0.5:
                trend = "losing"
            else:
                trend = "stable"
        else:
            total_change = 0
            trend = "stable"

        stats = {
            "average_weight": round(avg_weight, 1),
            "weight_trend": trend,
            "total_change": round(total_change, 1),
            "entry_count": len(entries)
        }

        return {"success": True, "stats": stats}

    except Exception as e:
        print(f"❌ Error getting weight stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/user/{user_id}/weight")
async def update_user_weight_endpoint(user_id: str, weight_data: dict):
    """Update user's current weight in profile"""
    try:
        print(f"⚖️ Updating user weight for {user_id} to {weight_data.get('weight')} kg")

        supabase_service = get_supabase_service()
        new_weight = weight_data.get('weight')

        if not new_weight:
            raise HTTPException(status_code=400, detail="Weight is required")

        success = await supabase_service.update_user_weight(user_id, new_weight)

        if success:
            return {"success": True, "message": "User weight updated successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to update user weight")

    except Exception as e:
        print(f"❌ Error updating user weight: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/user/{user_id}/set-starting-weight")
async def set_starting_weight_endpoint(user_id: str, weight_data: dict):
    """Set user's starting weight"""
    try:
        print(f"⚖️ Setting starting weight for {user_id} to {weight_data.get('starting_weight')} kg")

        supabase_service = get_supabase_service()
        starting_weight = weight_data.get('starting_weight')

        if not starting_weight:
            raise HTTPException(status_code=400, detail="Starting weight is required")

        # Update starting weight in users table
        response = supabase_service.client.table('users')\
            .update({
                'starting_weight': starting_weight,
                'starting_weight_date': datetime.utcnow().isoformat()
            })\
            .eq('id', user_id)\
            .execute()

        if response.data:
            return {
                "success": True,
                "message": "Starting weight set successfully",
                "starting_weight": starting_weight
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to set starting weight")

    except Exception as e:
        print(f"❌ Error setting starting weight: {e}")
        raise HTTPException(status_code=500, detail=str(e))
