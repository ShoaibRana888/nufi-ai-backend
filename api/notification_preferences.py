# api/notification_preferences.py
# NEW FILE - Backend API for notification preferences

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.supabase_service import get_supabase_service
from datetime import datetime
from typing import Optional
from utils.errors import internal_error

router = APIRouter(prefix="/notification-preferences", tags=["notification-preferences"])

class NotificationPreferences(BaseModel):
    user_id: str
    enabled: bool = True
    meal_reminders: bool = True
    exercise_reminders: bool = True
    water_reminders: bool = True
    sleep_reminders: bool = True
    supplement_reminders: bool = True
    weight_reminders: bool = True
    breakfast_hour: int = 8
    breakfast_minute: int = 0
    lunch_hour: int = 13
    lunch_minute: int = 0
    dinner_hour: int = 19
    dinner_minute: int = 0
    exercise_hour: int = 18
    exercise_minute: int = 0
    water_reminder_frequency: int = 2

@router.post("/save")
async def save_notification_preferences(prefs: NotificationPreferences):
    """Save user's notification preferences to database"""
    try:
        supabase = get_supabase_service()
        
        # Check if preferences already exist
        existing = supabase.client.table('notification_preferences')\
            .select('*')\
            .eq('user_id', prefs.user_id)\
            .execute()
        
        data = {
            'user_id': prefs.user_id,
            'enabled': prefs.enabled,
            'meal_reminders': prefs.meal_reminders,
            'exercise_reminders': prefs.exercise_reminders,
            'water_reminders': prefs.water_reminders,
            'sleep_reminders': prefs.sleep_reminders,
            'supplement_reminders': prefs.supplement_reminders,
            'weight_reminders': prefs.weight_reminders,
            'breakfast_hour': prefs.breakfast_hour,
            'breakfast_minute': prefs.breakfast_minute,
            'lunch_hour': prefs.lunch_hour,
            'lunch_minute': prefs.lunch_minute,
            'dinner_hour': prefs.dinner_hour,
            'dinner_minute': prefs.dinner_minute,
            'exercise_hour': prefs.exercise_hour,
            'exercise_minute': prefs.exercise_minute,
            'water_reminder_frequency': prefs.water_reminder_frequency,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        if existing.data and len(existing.data) > 0:
            # Update existing
            response = supabase.client.table('notification_preferences')\
                .update(data)\
                .eq('user_id', prefs.user_id)\
                .execute()
        else:
            # Insert new
            data['created_at'] = datetime.utcnow().isoformat()
            response = supabase.client.table('notification_preferences')\
                .insert(data)\
                .execute()
        
        print(f"✅ Notification preferences saved for user {prefs.user_id}")
        
        return {
            "success": True,
            "message": "Notification preferences saved successfully",
            "data": response.data[0] if response.data else None
        }
        
    except Exception as e:
        print(f"❌ Error saving notification preferences: {e}")
        raise internal_error(e)

@router.get("/{user_id}")
async def get_notification_preferences(user_id: str):
    """Get user's notification preferences"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('notification_preferences')\
            .select('*')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return {
                "success": True,
                "preferences": response.data[0]
            }
        else:
            # Return default preferences
            return {
                "success": True,
                "preferences": {
                    "user_id": user_id,
                    "enabled": True,
                    "meal_reminders": True,
                    "exercise_reminders": True,
                    "water_reminders": True,
                    "sleep_reminders": True,
                    "supplement_reminders": True,
                    "weight_reminders": True,
                    "breakfast_hour": 8,
                    "breakfast_minute": 0,
                    "lunch_hour": 13,
                    "lunch_minute": 0,
                    "dinner_hour": 19,
                    "dinner_minute": 0,
                    "exercise_hour": 18,
                    "exercise_minute": 0,
                    "water_reminder_frequency": 2
                }
            }
        
    except Exception as e:
        print(f"❌ Error getting notification preferences: {e}")
        raise internal_error(e)

@router.delete("/{user_id}")
async def delete_notification_preferences(user_id: str):
    """Delete user's notification preferences (reset to defaults)"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('notification_preferences')\
            .delete()\
            .eq('user_id', user_id)\
            .execute()
        
        return {
            "success": True,
            "message": "Notification preferences reset to defaults"
        }
        
    except Exception as e:
        print(f"❌ Error deleting notification preferences: {e}")
        raise internal_error(e)