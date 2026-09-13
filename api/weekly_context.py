# api/weekly_context.py

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, date
from typing import Any, Dict, Optional
from services.weekly_context_manager import get_weekly_context_manager
from utils.timezone_utils import get_timezone_offset, get_user_today

router = APIRouter(prefix="/weekly", tags=["weekly_context"])


def _parse_day(value: Optional[str], fallback: date) -> date:
    if not value:
        return fallback
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")


@router.get("/context/{user_id}")
async def get_weekly_context(
    user_id: str, 
    date: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset),
):
    """The week containing `date` (default: the user's today).

    Both the target and "today" are the user's, not the server's. The
    dashboard's weekly card sends no date, so on the server clock a UTC-8
    user's Sunday evening read the *next*, empty week; and the manager
    judges whether a week is still current against `today`, and freezes a
    week it thinks is over -- so that Sunday's remaining activities were
    dropped from the week for good (ADR-0006, corrected in review).
    """
    try:
        manager = get_weekly_context_manager()
        today = get_user_today(tz_offset)
        target_date = _parse_day(date, today)
        return await manager.get_or_create_weekly_context(
            user_id, target_date, today=today
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting weekly context: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recent/{user_id}")
async def get_recent_weeks(
    user_id: str,
    weeks: int = 4,
    tz_offset: int = Depends(get_timezone_offset),
):
    """Recent weeks, counting back from the user's today."""
    try:
        manager = get_weekly_context_manager()
        contexts = await manager.get_recent_weeks_context(
            user_id, weeks, end_date=get_user_today(tz_offset)
        )
        
        return {
            'success': True,
            'weeks': contexts,
            'count': len(contexts)
        }
        
    except Exception as e:
        print(f"Error getting recent weeks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rebuild/{user_id}")
async def rebuild_weekly_context(
    user_id: str,
    body: Optional[Dict[str, Any]] = None,
    date: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset),
):
    """Force rebuild the week containing `date` (default: the user's today).

    The client sends `date` in the JSON body; this handler used to declare it
    as a query parameter only, so the body was ignored and every rebuild --
    including the debug page's "four weeks back" loop -- rebuilt the server's
    current week. Both spellings are accepted now; the body wins.
    """
    try:
        manager = get_weekly_context_manager()
        raw = (body or {}).get('date') or date
        target_date = _parse_day(raw, get_user_today(tz_offset))
        return await manager.update_weekly_context(user_id, target_date)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error rebuilding weekly context: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))