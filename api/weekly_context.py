# api/weekly_context.py

from fastapi import APIRouter, HTTPException
from datetime import datetime, date
from typing import Optional
from services.weekly_context_manager import get_weekly_context_manager
from utils.errors import internal_error

router = APIRouter(prefix="/weekly", tags=["weekly_context"])

@router.get("/context/{user_id}")
async def get_weekly_context(
    user_id: str, 
    date: Optional[str] = None
):
    """Get weekly context for a specific date"""
    try:
        manager = get_weekly_context_manager()
        
        target_date = datetime.strptime(date, '%Y-%m-%d').date() if date else datetime.now().date()
        result = await manager.get_or_create_weekly_context(user_id, target_date)
        
        return result
        
    except Exception as e:
        print(f"Error getting weekly context: {e}")
        raise internal_error(e)

@router.get("/recent/{user_id}")
async def get_recent_weeks(
    user_id: str,
    weeks: int = 4
):
    """Get recent weeks' contexts"""
    try:
        manager = get_weekly_context_manager()
        contexts = await manager.get_recent_weeks_context(user_id, weeks)
        
        return {
            'success': True,
            'weeks': contexts,
            'count': len(contexts)
        }
        
    except Exception as e:
        print(f"Error getting recent weeks: {e}")
        raise internal_error(e)

@router.post("/rebuild/{user_id}")
async def rebuild_weekly_context(
    user_id: str,
    date: Optional[str] = None
):
    """Force rebuild weekly context"""
    try:
        manager = get_weekly_context_manager()
        
        target_date = datetime.strptime(date, '%Y-%m-%d').date() if date else datetime.now().date()
        result = await manager.update_weekly_context(user_id, target_date)
        
        return result
        
    except Exception as e:
        print(f"Error rebuilding weekly context: {e}")
        raise internal_error(e)

@router.get("/summary/{user_id}")
async def get_weekly_summaries(
    user_id: str,
    weeks: int = 12
):
    """Get weekly summaries for trend analysis"""
    try:
        from services.supabase_service import get_supabase_service
        supabase = get_supabase_service()
        
        # Get last N weeks of summaries
        response = supabase.client.table('weekly_contexts')\
            .select('week_start_date, week_end_date, week_number, year, summary_data')\
            .eq('user_id', user_id)\
            .order('week_start_date', desc=True)\
            .limit(weeks)\
            .execute()
        
        summaries = []
        for record in response.data:
            summary = record['summary_data']
            summary['week_start'] = record['week_start_date']
            summary['week_end'] = record['week_end_date']
            summaries.append(summary)
        
        return {
            'success': True,
            'summaries': summaries,
            'count': len(summaries)
        }
        
    except Exception as e:
        print(f"Error getting weekly summaries: {e}")
        raise internal_error(e)