# api/chat.py
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from services.supabase_service import get_supabase_service
from services.chat_context_manager import get_context_manager
from services.chat_service import get_chat_service
from utils.timezone_utils import get_timezone_offset, get_user_now

router = APIRouter(prefix="/chat", tags=["chat"])

@router.get("/context/{user_id}")
async def get_user_chat_context(user_id: str, date: Optional[str] = None):
    """Get user context - now using cached system"""
    try:
        context_manager = get_context_manager()
        
        target_date = datetime.strptime(date, '%Y-%m-%d').date() if date else datetime.now().date()
        result = await context_manager.get_or_create_context(user_id, target_date)
        
        # Format to match old structure for compatibility
        return {
            'success': True,
            **result['context']  # Unwrap the context directly
        }
        
    except Exception as e:
        print(f"Error getting context: {e}")
        # Fallback - generate fresh if cache fails
        context_manager = get_context_manager()
        result = await context_manager.generate_fresh_context(user_id, datetime.now().date())
        return {
            'success': True,
            **result['context']
        }
    
@router.delete("/context/cleanup")
async def cleanup_old_contexts(days_to_keep: int = 7):
    """Clean up contexts older than specified days"""
    try:
        supabase_service = get_supabase_service()
        cutoff_date = (datetime.now().date() - timedelta(days=days_to_keep)).isoformat()
        
        response = supabase_service.client.table('chat_contexts')\
            .delete()\
            .lt('date', cutoff_date)\
            .execute()
        
        return {
            'success': True,
            'message': f'Cleaned up contexts older than {cutoff_date}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
    
@router.get("/context/cached/{user_id}")
async def get_cached_context(user_id: str, date: Optional[str] = None):
    """Get cached context for user - much faster than rebuilding"""
    try:
        context_manager = get_context_manager()
        
        target_date = datetime.strptime(date, '%Y-%m-%d').date() if date else datetime.now().date()
        result = await context_manager.get_or_create_context(user_id, target_date)
        
        return {
            'success': True,
            **result,
            'is_cached': True
        }
        
    except Exception as e:
        print(f"Error getting cached context: {e}")
        # Fallback to generating fresh
        return await get_user_chat_context(user_id)

@router.post("/context/update/{user_id}")
async def update_context_activity(
    user_id: str, 
    activity_type: str,
    data: dict
):
    """Update context when an activity is logged"""
    try:
        context_manager = get_context_manager()
        result = await context_manager.update_context_activity(
            user_id, 
            activity_type, 
            data
        )
        
        return {
            'success': True,
            'message': f'Context updated for {activity_type}',
            'version': result['version']
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
    
@router.post("/context/rebuild/{user_id}")
async def rebuild_context(user_id: str, date: Optional[str] = None):
    """Force rebuild context from source tables"""
    try:
        context_manager = get_context_manager()
        
        target_date = datetime.strptime(date, '%Y-%m-%d').date() if date else datetime.now().date()
        result = await context_manager.rebuild_context(user_id, target_date)
        
        return {
            'success': True,
            'message': 'Context rebuilt successfully',
            **result
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
    
@router.post("/context/fix-today/{user_id}")
async def fix_today_context(user_id: str):
    """Delete and rebuild today's context"""
    try:
        from datetime import datetime
        
        supabase_service = get_supabase_service()
        today = datetime.now().date()
        
        # Delete today's corrupted context
        supabase_service.client.table('chat_contexts')\
            .delete()\
            .eq('user_id', user_id)\
            .eq('date', str(today))\
            .execute()
        
        # Force fresh generation
        context_manager = get_context_manager()
        result = await context_manager.generate_fresh_context(user_id, today)
        
        return {
            'success': True,
            'message': 'Context fixed and rebuilt',
            'context': result['context']
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
    
@router.post("/chat/rebuild-context")
async def rebuild_chat_context(request: Dict[str, Any]):
    """Rebuild chat context from source tables"""
    try:
        user_id = request.get('user_id')
        date_str = request.get('date')
        
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()
        
        from services.chat_context_manager import get_context_manager
        context_manager = get_context_manager()
        
        result = await context_manager.rebuild_context(user_id, target_date)
        
        return {
            "success": True,
            "message": "Context rebuilt successfully",
            "context": result['context']
        }
    except Exception as e:
        print(f"Error rebuilding context: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/chat/context/check/{user_id}")
async def check_context_date(user_id: str):
    """Check if context needs daily reset"""
    try:
        from services.chat_context_manager import get_context_manager
        context_manager = get_context_manager()
        
        today = datetime.now().date()
        
        # Check for existing context
        response = context_manager.supabase_service.client.table('chat_contexts')\
            .select('date')\
            .eq('user_id', user_id)\
            .order('date', desc=True)\
            .limit(1)\
            .execute()
        
        if response.data:
            last_context_date = datetime.strptime(response.data[0]['date'], '%Y-%m-%d').date()
            needs_reset = last_context_date < today
            
            return {
                "needs_reset": needs_reset,
                "last_context_date": str(last_context_date),
                "current_date": str(today)
            }
        
        return {
            "needs_reset": True,
            "last_context_date": None,
            "current_date": str(today)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/context/daily-reset/{user_id}")
async def daily_context_reset(user_id: str):
    """Create fresh context for a new day"""
    try:
        from services.chat_context_manager import get_context_manager
        context_manager = get_context_manager()
        
        result = await context_manager.ensure_daily_context(user_id)
        
        return {
            "success": True,
            "is_new": result.get('is_new', False),
            "date": str(datetime.now().date()),
            "message": "Daily context ready"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=dict)
async def health_chat(request: dict, tz_offset: int = Depends(get_timezone_offset)):
    """Enhanced health chat with OpenAI integration"""
    import time
    start_time = time.time()

    try:
        print(f"💬 Chat request received at {time.time()}")
        chat_service = get_chat_service()
        user_id = request.get('user_id')
        message = request.get('message')

        if not user_id or not message:
            raise HTTPException(status_code=400, detail="user_id and message are required")

        print(f"💬 Chat request from user: {user_id}, message: {message[:50]}...")
        print(f"⏱️ Time before generate_chat_response: {time.time() - start_time:.2f}s")

        response = await chat_service.generate_chat_response(user_id, message)

        print(f"⏱️ Total time: {time.time() - start_time:.2f}s")

        return {
            "success": True,
            "response": response,
            "timestamp": get_user_now(tz_offset).isoformat()
        }
    except Exception as e:
        print(f"❌ Error in health chat after {time.time() - start_time:.2f}s: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "response": "I'm having trouble connecting. Please check your connection and try again.",
            "error": str(e)
        }

@router.get("/history/{user_id}")
async def get_chat_history(user_id: str):
    """Get user's chat history"""
    try:
        supabase_service = get_supabase_service()
        history = await supabase_service.get_chat_messages(user_id)

        return {
            "success": True,
            "messages": history,
            "count": len(history)
        }
    except Exception as e:
        print(f"❌ Error getting chat history: {e}")
        return {"success": False, "messages": [], "count": 0}

@router.delete("/history/{user_id}")
async def clear_chat_history(user_id: str):
    """Clear user's chat history"""
    try:
        supabase_service = get_supabase_service()
        success = await supabase_service.clear_user_conversation(user_id)

        return {
            "success": success,
            "message": "Chat history cleared" if success else "Failed to clear chat history"
        }
    except Exception as e:
        print(f"❌ Error clearing chat history: {e}")
        return {"success": False, "message": "Failed to clear chat history"}

@router.get("/messages/{user_id}")
async def get_chat_messages(user_id: str, limit: int = 50):
    """Get chat messages for a user"""
    try:
        supabase_service = get_supabase_service()
        messages = supabase_service.get_chat_messages(user_id, limit)

        return {
            "success": True,
            "messages": messages,
            "count": len(messages)
        }
    except Exception as e:
        print(f"Error getting chat messages: {e}")
        return {"success": False, "messages": [], "count": 0}

@router.delete("/messages/{user_id}")
async def clear_chat_messages(user_id: str):
    """Clear chat messages for a user"""
    try:
        supabase_service = get_supabase_service()
        success = await supabase_service.clear_chat_messages(user_id)

        return {
            "success": success,
            "message": "Messages cleared" if success else "Failed to clear messages"
        }
    except Exception as e:
        print(f"Error clearing chat messages: {e}")
        return {"success": False, "message": "Failed to clear messages"}

@router.get("/sessions/{user_id}")
async def get_user_chat_sessions(user_id: str):
    """Get all chat sessions for a user"""
    try:
        supabase_service = get_supabase_service()

        response = supabase_service.client.table("chat_sessions")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .execute()

        return {
            "success": True,
            "sessions": response.data or [],
            "count": len(response.data or [])
        }
    except Exception as e:
        print(f"Error getting chat sessions: {e}")
        return {"success": False, "sessions": [], "count": 0}

@router.get("/messages/{user_id}/{session_id}")
async def get_session_messages(user_id: str, session_id: str):
    """Get messages for a specific session"""
    try:
        supabase_service = get_supabase_service()
        messages = await supabase_service.get_chat_messages(user_id, session_id=session_id)

        return {
            "success": True,
            "messages": messages,
            "count": len(messages)
        }
    except Exception as e:
        print(f"Error getting session messages: {e}")
        return {"success": False, "messages": [], "count": 0}