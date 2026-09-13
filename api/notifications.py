# api/notifications.py - UPDATED VERSION

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from services.supabase_service import get_supabase_service
import uuid
from utils.errors import internal_error

router = APIRouter(prefix="/notifications", tags=["notifications"])

class LogNotificationRequest(BaseModel):
    user_id: str
    title: str
    message: str
    type: str

@router.post("/log")
async def log_notification(notification: LogNotificationRequest):
    """Log a notification when it's scheduled"""
    try:
        supabase = get_supabase_service()
        
        notification_id = str(uuid.uuid4())
        data = {
            'id': notification_id,
            'user_id': notification.user_id,
            'title': notification.title,
            'message': notification.message,
            'type': notification.type,
            'is_read': False,
            'created_at': datetime.utcnow().isoformat()
        }
        
        print(f"📝 Logging notification to DB: {notification.type} for user {notification.user_id}")
        
        response = supabase.client.table('notifications').insert(data).execute()
        
        print(f"✅ Notification logged with ID: {notification_id}")
        
        return {
            "success": True,
            "notification": response.data[0] if response.data else None
        }
        
    except Exception as e:
        print(f"❌ Error logging notification: {e}")
        import traceback
        traceback.print_exc()
        raise internal_error(e)

@router.get("/unread/{user_id}")
async def get_unread_count(user_id: str):
    """Get count of unread notifications"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('notifications')\
            .select('id', count='exact')\
            .eq('user_id', user_id)\
            .eq('is_read', False)\
            .execute()
        
        count = len(response.data) if response.data else 0
        
        print(f"📊 Unread count for {user_id}: {count}")
        
        return {
            "success": True,
            "unread_count": count
        }
        
    except Exception as e:
        print(f"❌ Error getting unread count: {e}")
        raise internal_error(e)

@router.get("/{user_id}")
async def get_notifications(user_id: str, limit: int = 50):
    """Get all notifications for a user"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('notifications')\
            .select('*')\
            .eq('user_id', user_id)\
            .order('created_at', desc=True)\
            .limit(limit)\
            .execute()
        
        notifications_count = len(response.data) if response.data else 0
        print(f"📱 Retrieved {notifications_count} notifications for {user_id}")
        
        return {
            "success": True,
            "notifications": response.data if response.data else []
        }
        
    except Exception as e:
        print(f"❌ Error getting notifications: {e}")
        import traceback
        traceback.print_exc()
        raise internal_error(e)

@router.put("/mark-read/{notification_id}")
async def mark_notification_read(notification_id: str):
    """Mark a single notification as read"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('notifications')\
            .update({'is_read': True})\
            .eq('id', notification_id)\
            .execute()
        
        return {"success": True}
        
    except Exception as e:
        print(f"❌ Error marking notification as read: {e}")
        raise internal_error(e)

@router.put("/mark-all-read/{user_id}")
async def mark_all_notifications_read(user_id: str):
    """Mark all notifications as read for a user"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('notifications')\
            .update({'is_read': True})\
            .eq('user_id', user_id)\
            .eq('is_read', False)\
            .execute()
        
        return {"success": True}
        
    except Exception as e:
        print(f"❌ Error marking all as read: {e}")
        raise internal_error(e)

@router.delete("/{notification_id}")
async def delete_notification(notification_id: str):
    """Delete a notification"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('notifications')\
            .delete()\
            .eq('id', notification_id)\
            .execute()
        
        print(f"🗑️ Notification {notification_id} deleted")
        
        return {
            "success": True,
            "message": "Notification deleted successfully"
        }
        
    except Exception as e:
        print(f"❌ Error deleting notification: {e}")
        raise internal_error(e)

@router.delete("/{user_id}/clear-all")
async def clear_all_notifications(user_id: str):
    """Delete all notifications for a user"""
    try:
        supabase = get_supabase_service()
        
        response = supabase.client.table('notifications')\
            .delete()\
            .eq('user_id', user_id)\
            .execute()
        
        deleted_count = len(response.data) if response.data else 0
        print(f"🗑️ Cleared {deleted_count} notifications for {user_id}")
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Deleted {deleted_count} notifications"
        }
        
    except Exception as e:
        print(f"❌ Error clearing notifications: {e}")
        raise internal_error(e)