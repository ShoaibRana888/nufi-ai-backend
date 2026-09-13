# api/debug.py
from fastapi import APIRouter, Query
from datetime import datetime, timedelta, date
from typing import Optional
from services.supabase_service import get_supabase_service
from services.weekly_context_manager import get_weekly_context_manager
from utils.errors import public_message

router = APIRouter(prefix="/debug", tags=["debug"])

@router.get("/check-data/{user_id}")
async def check_data(user_id: str):
    """Check what data exists in database"""
    try:
        supabase = get_supabase_service()
        
        # Get sample of ALL data for this user
        meals = supabase.client.table('meal_entries')\
            .select('meal_date, food_item, calories')\
            .eq('user_id', user_id)\
            .limit(10)\
            .execute()
        
        exercises = supabase.client.table('exercise_logs')\
            .select('exercise_date, exercise_name, duration_minutes')\
            .eq('user_id', user_id)\
            .limit(10)\
            .execute()
        
        sleep = supabase.client.table('sleep_entries')\
            .select('date, total_hours')\
            .eq('user_id', user_id)\
            .limit(10)\
            .execute()
        
        return {
            'meals': meals.data,
            'exercises': exercises.data,
            'sleep': sleep.data
        }
    except Exception as e:
        return {'error': public_message(e)}

@router.get("/list-cached-weeks/{user_id}")
async def list_cached_weeks(user_id: str):
    """See all cached weekly contexts for a user"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('weekly_contexts')\
            .select('week_start_date, week_end_date, week_number, year, created_at')\
            .eq('user_id', user_id)\
            .order('week_start_date', desc=True)\
            .execute()
        
        weeks = response.data or []
        
        return {
            'success': True,
            'total_cached_weeks': len(weeks),
            'weeks': weeks,
            'note': 'These weeks have cached data that may be outdated'
        }
    except Exception as e:
        return {'error': public_message(e)}

@router.get("/clear-cache/{user_id}")
async def clear_weekly_cache(user_id: str):
    """Delete ALL cached weekly contexts for a user - works for any date range"""
    try:
        supabase = get_supabase_service()
        
        print(f"🗑️ Clearing ALL weekly context cache for user: {user_id}")
        
        # Delete all weekly contexts (no date filter = delete everything)
        response = supabase.client.table('weekly_contexts')\
            .delete()\
            .eq('user_id', user_id)\
            .execute()
        
        deleted_count = len(response.data) if response.data else 0
        print(f"✅ Deleted {deleted_count} cached weekly contexts")
        
        return {
            'success': True,
            'message': f'Cleared ALL weekly context cache for user {user_id}',
            'deleted_count': deleted_count,
            'note': 'All weeks will regenerate when accessed in the app'
        }
    except Exception as e:
        print(f"❌ Error clearing cache: {e}")
        return {'error': public_message(e)}

@router.get("/rebuild-week/{user_id}")
async def rebuild_specific_week(
    user_id: str, 
    week_date: str = Query(..., description="Date in the week to rebuild (YYYY-MM-DD)")
):
    """Force rebuild a specific week with detailed logging - works for ANY date"""
    try:
        supabase = get_supabase_service()
        manager = get_weekly_context_manager()
        
        # Parse date
        target_date = datetime.strptime(week_date, '%Y-%m-%d').date()
        
        # Get week boundaries
        week_start, week_end = manager.get_week_boundaries(target_date)
        
        print(f"\n🔄 ===== FORCE REBUILDING WEEK =====")
        print(f"Target date: {week_date}")
        print(f"Week: {week_start} to {week_end}")
        
        # Delete existing cache for this specific week
        delete_response = supabase.client.table('weekly_contexts')\
            .delete()\
            .eq('user_id', user_id)\
            .eq('week_start_date', str(week_start))\
            .execute()
        
        print(f"✅ Deleted old cache for this week")
        
        # Force rebuild (this will trigger all the print statements)
        result = await manager.get_or_create_weekly_context(user_id, target_date)
        
        print(f"✅ ===== REBUILD COMPLETE =====\n")
        
        return {
            'success': True,
            'week_start': str(week_start),
            'week_end': str(week_end),
            'week_number': result.get('weekly_context', {}).get('week_info', {}).get('week_number'),
            'total_meals': result.get('weekly_context', {}).get('nutrition_summary', {}).get('total_meals_logged', 0),
            'total_workouts': result.get('weekly_context', {}).get('exercise_summary', {}).get('total_workouts', 0),
            'avg_sleep': result.get('weekly_context', {}).get('sleep_summary', {}).get('avg_nightly_hours', 0),
            'note': 'Check Render logs for detailed aggregation info'
        }
    except Exception as e:
        print(f"❌ Error rebuilding week: {e}")
        import traceback
        traceback.print_exc()
        return {'error': public_message(e)}

@router.get("/rebuild-date-range/{user_id}")
async def rebuild_date_range(
    user_id: str,
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)")
):
    """Rebuild all weeks within a date range - perfect for old data"""
    try:
        supabase = get_supabase_service()
        manager = get_weekly_context_manager()
        
        # Parse dates
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        print(f"\n🔄 ===== REBUILDING DATE RANGE =====")
        print(f"From: {start_date} to {end_date}")
        
        # Find all unique weeks in this range
        current_date = start
        weeks_to_rebuild = []
        seen_weeks = set()
        
        while current_date <= end:
            week_start, week_end = manager.get_week_boundaries(current_date)
            week_key = str(week_start)
            
            if week_key not in seen_weeks:
                weeks_to_rebuild.append((week_start, week_end, current_date))
                seen_weeks.add(week_key)
            
            current_date += timedelta(days=7)  # Jump to next week
        
        print(f"📊 Found {len(weeks_to_rebuild)} unique weeks to rebuild")
        
        # Clear cache for all these weeks first
        for week_start, week_end, _ in weeks_to_rebuild:
            supabase.client.table('weekly_contexts')\
                .delete()\
                .eq('user_id', user_id)\
                .eq('week_start_date', str(week_start))\
                .execute()
        
        print(f"✅ Cleared cache for all {len(weeks_to_rebuild)} weeks")
        
        # Rebuild each week
        rebuilt_weeks = []
        for i, (week_start, week_end, target_date) in enumerate(weeks_to_rebuild):
            print(f"\n📅 Rebuilding Week {i+1}/{len(weeks_to_rebuild)}: {week_start} to {week_end}")
            
            result = await manager.get_or_create_weekly_context(user_id, target_date)
            
            rebuilt_weeks.append({
                'week_number': i + 1,
                'week_start': str(week_start),
                'week_end': str(week_end),
                'success': result.get('success', False),
                'total_meals': result.get('weekly_context', {}).get('nutrition_summary', {}).get('total_meals_logged', 0),
                'total_workouts': result.get('weekly_context', {}).get('exercise_summary', {}).get('total_workouts', 0)
            })
            
            print(f"✅ Week {i+1} rebuilt")
        
        print(f"\n✅ ===== ALL WEEKS REBUILT =====\n")
        
        return {
            'success': True,
            'message': f'Rebuilt {len(rebuilt_weeks)} weeks from {start_date} to {end_date}',
            'weeks_rebuilt': len(rebuilt_weeks),
            'rebuilt_weeks': rebuilt_weeks
        }
    except Exception as e:
        print(f"❌ Error rebuilding date range: {e}")
        import traceback
        traceback.print_exc()
        return {'error': public_message(e)}

@router.get("/rebuild-all-weeks/{user_id}")
async def rebuild_all_weeks(user_id: str, weeks: int = Query(4, description="Number of recent weeks to rebuild")):
    """Clear cache and rebuild last N weeks"""
    try:
        manager = get_weekly_context_manager()
        
        print(f"\n🔄 ===== REBUILDING LAST {weeks} WEEKS =====")
        
        # Step 1: Clear ALL cache
        print(f"Step 1: Clearing ALL cache...")
        clear_result = await clear_weekly_cache(user_id)
        print(f"✅ Cleared {clear_result['deleted_count']} cached weeks")
        
        # Step 2: Rebuild last N weeks
        print(f"\nStep 2: Rebuilding last {weeks} weeks...")
        rebuilt_weeks = []
        
        for week_offset in range(weeks):
            target_date = datetime.now().date() - timedelta(weeks=week_offset)
            week_start, week_end = manager.get_week_boundaries(target_date)
            
            print(f"\n📅 Rebuilding Week {week_offset + 1}: {week_start} to {week_end}")
            
            result = await manager.get_or_create_weekly_context(user_id, target_date)
            
            rebuilt_weeks.append({
                'week_start': str(week_start),
                'week_end': str(week_end),
                'success': result.get('success', False),
                'total_meals': result.get('weekly_context', {}).get('nutrition_summary', {}).get('total_meals_logged', 0),
                'total_workouts': result.get('weekly_context', {}).get('exercise_summary', {}).get('total_workouts', 0)
            })
            
            print(f"✅ Week {week_offset + 1} rebuilt")
        
        print(f"\n✅ ===== ALL WEEKS REBUILT =====\n")
        
        return {
            'success': True,
            'message': f'Cleared cache and rebuilt last {weeks} weeks',
            'rebuilt_weeks': rebuilt_weeks
        }
    except Exception as e:
        print(f"❌ Error rebuilding all weeks: {e}")
        import traceback
        traceback.print_exc()
        return {'error': public_message(e)}