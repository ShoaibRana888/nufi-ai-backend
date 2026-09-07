# api/activity_check.py
from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime, date, timedelta
from services.supabase_service import get_supabase_service
from utils.timezone_utils import get_timezone_offset, get_user_today
from typing import Optional

router = APIRouter()

@router.get("/check-activity/{user_id}/{activity_type}")
async def check_activity_logged(
    user_id: str, 
    activity_type: str,
    date_str: Optional[str] = Query(None, alias="date"),
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Check if a specific activity has been logged for a given date (default: today)
    
    activity_type can be: meal, exercise, water, sleep, supplement, weight, steps
    """
    try:
        print(f"🔍 Checking if {activity_type} logged for user {user_id}")
        
        supabase_service = get_supabase_service()
        
        # Get the check date
        if date_str:
            check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            check_date = get_user_today(tz_offset)
        
        is_logged = False
        details = {}
        
        # Check based on activity type
        if activity_type == 'meal':
            # Check if any meal logged today
            response = supabase_service.client.table('meal_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', str(check_date))\
                .lt('date', str(check_date + datetime.timedelta(days=1)))\
                .execute()
            
            meals = response.data if response.data else []
            is_logged = len(meals) > 0
            details = {
                'meals_count': len(meals),
                'meal_types': [m.get('meal_type') for m in meals]
            }
            
        elif activity_type == 'exercise':
            # Check if exercise logged today
            response = supabase_service.client.table('exercise_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', str(check_date))\
                .lt('date', str(check_date + datetime.timedelta(days=1)))\
                .execute()
            
            exercises = response.data if response.data else []
            is_logged = len(exercises) > 0
            details = {
                'workouts_count': len(exercises),
                'exercises': [e.get('exercise_name') for e in exercises]
            }
            
        elif activity_type == 'water':
            # Check if water logged today
            response = supabase_service.client.table('daily_water')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(check_date))\
                .execute()
            
            water_entries = response.data if response.data else []
            is_logged = len(water_entries) > 0 and any(
                entry.get('glasses_consumed', 0) > 0 for entry in water_entries
            )
            details = {
                'total_glasses': sum(e.get('glasses_consumed', 0) for e in water_entries)
            }
            
        elif activity_type == 'sleep':
            # Check if sleep logged for last night
            response = supabase_service.client.table('sleep_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(check_date))\
                .execute()
            
            sleep_entries = response.data if response.data else []
            is_logged = len(sleep_entries) > 0
            details = {
                'sleep_hours': sleep_entries[0].get('total_hours') if sleep_entries else 0
            }
            
        elif activity_type == 'supplement':
            # Check if supplements logged today
            response = supabase_service.client.table('supplement_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', str(check_date))\
                .lt('date', str(check_date + datetime.timedelta(days=1)))\
                .execute()
            
            supplement_entries = response.data if response.data else []
            is_logged = len(supplement_entries) > 0
            details = {
                'supplements_count': len(supplement_entries)
            }
            
        elif activity_type == 'weight':
            # Check if weight logged this week
            # Weight is logged weekly, so check last 7 days
            week_ago = check_date - datetime.timedelta(days=7)
            response = supabase_service.client.table('weight_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', str(week_ago))\
                .lte('date', str(check_date))\
                .execute()
            
            weight_entries = response.data if response.data else []
            is_logged = len(weight_entries) > 0
            details = {
                'latest_weight': weight_entries[0].get('weight') if weight_entries else None
            }
            
        elif activity_type == 'steps':
            # Check if steps logged today
            response = supabase_service.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(check_date))\
                .execute()
            
            step_entries = response.data if response.data else []
            is_logged = len(step_entries) > 0 and any(
                entry.get('steps', 0) > 0 for entry in step_entries
            )
            details = {
                'steps': step_entries[0].get('steps', 0) if step_entries else 0
            }
        
        else:
            raise HTTPException(status_code=400, detail=f"Invalid activity type: {activity_type}")
        
        return {
            "success": True,
            "logged": is_logged,
            "activity_type": activity_type,
            "date": str(check_date),
            "details": details
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error checking activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check-multiple-activities/{user_id}")
async def check_multiple_activities(
    user_id: str,
    activity_types: str = Query(..., description="Comma-separated activity types"),
    date_str: Optional[str] = Query(None, alias="date"),
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Check multiple activities at once
    Example: /check-multiple-activities/user123?activity_types=meal,exercise,water
    """
    try:
        activity_list = activity_types.split(',')
        results = {}
        
        for activity_type in activity_list:
            activity_type = activity_type.strip()
            result = await check_activity_logged(
                user_id=user_id,
                activity_type=activity_type,
                date_str=date_str,
                tz_offset=tz_offset
            )
            results[activity_type] = result['logged']
        
        return {
            "success": True,
            "user_id": user_id,
            "activities": results
        }
        
    except Exception as e:
        print(f"❌ Error checking multiple activities: {e}")
        raise HTTPException(status_code=500, detail=str(e))