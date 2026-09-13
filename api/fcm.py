# api/fcm.py
# Firebase Cloud Messaging API endpoints

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import firebase_admin
from firebase_admin import credentials, messaging
from datetime import datetime, time
from apscheduler.schedulers.background import BackgroundScheduler
from services.supabase_service import get_supabase_service
import os
from utils.errors import internal_error

router = APIRouter(prefix="/api/fcm", tags=["fcm"])

# Initialize Firebase Admin (do this once on startup)
def initialize_firebase():
    """Initialize Firebase Admin SDK"""
    try:
        # Check if already initialized
        firebase_admin.get_app()
        print("✅ Firebase already initialized")
    except ValueError:
        # Initialize with service account
        cred_path = os.getenv('FIREBASE_CREDENTIALS_PATH', 'firebase-credentials.json')
        
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase Admin initialized with credentials file")
        else:
            print("⚠️ Firebase credentials file not found, trying environment variables")
            # Alternative: Use environment variables
            cred_dict = {
                "type": "service_account",
                "project_id": os.getenv('FIREBASE_PROJECT_ID'),
                "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID'),
                "private_key": os.getenv('FIREBASE_PRIVATE_KEY', '').replace('\\n', '\n'),
                "client_email": os.getenv('FIREBASE_CLIENT_EMAIL'),
                "client_id": os.getenv('FIREBASE_CLIENT_ID'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            }
            
            if cred_dict['project_id']:
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("✅ Firebase Admin initialized with environment variables")
            else:
                print("❌ Firebase credentials not found!")

# Pydantic models
class FCMTokenRegister(BaseModel):
    user_id: str
    fcm_token: str
    platform: str = "android"

class FCMSubscribe(BaseModel):
    user_id: str

class FCMTestNotification(BaseModel):
    user_id: str

# Database functions
async def save_fcm_token(user_id: str, fcm_token: str, platform: str):
    """Save FCM token to database"""
    supabase = get_supabase_service()
    
    try:
        # Upsert token (insert or update if exists)
        result = supabase.client.table('fcm_tokens').upsert({
            'user_id': user_id,
            'fcm_token': fcm_token,
            'platform': platform,
            'updated_at': datetime.utcnow().isoformat()
        }, on_conflict='user_id').execute()
        
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"❌ Error saving FCM token: {e}")
        raise

async def get_user_fcm_token(user_id: str) -> Optional[str]:
    """Get FCM token for a user"""
    supabase = get_supabase_service()
    
    try:
        result = supabase.client.table('fcm_tokens')\
            .select('fcm_token')\
            .eq('user_id', user_id)\
            .single()\
            .execute()
        
        return result.data['fcm_token'] if result.data else None
    except Exception as e:
        print(f"❌ Error getting FCM token: {e}")
        return None

async def get_all_subscribed_users() -> List[dict]:
    """Get all users with FCM tokens"""
    supabase = get_supabase_service()
    
    try:
        result = supabase.client.table('fcm_tokens')\
            .select('user_id, fcm_token, platform')\
            .execute()
        
        return result.data if result.data else []
    except Exception as e:
        print(f"❌ Error getting subscribed users: {e}")
        return []

# FCM sending functions
async def send_notification_to_user(
    user_id: str,
    title: str,
    body: str,
    data: Optional[dict] = None
) -> bool:
    """Send FCM notification to a specific user"""
    try:
        # Get user's FCM token
        fcm_token = await get_user_fcm_token(user_id)
        
        if not fcm_token:
            print(f"⚠️ No FCM token found for user: {user_id}")
            return False
        
        # Create message
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    icon='@mipmap/ic_launcher',
                    color='#2196F3',
                    sound='default',
                    channel_id='fcm_default_channel',
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        alert=messaging.ApsAlert(
                            title=title,
                            body=body,
                        ),
                        sound='default',
                    ),
                ),
            ),
        )
        
        # Send message
        response = messaging.send(message)
        print(f"✅ Notification sent to user {user_id}: {response}")
        
        # Log to database
        await log_notification_sent(user_id, title, body, 'fcm')
        
        return True
        
    except Exception as e:
        print(f"❌ Error sending notification to user {user_id}: {e}")
        return False

async def log_notification_sent(user_id: str, title: str, body: str, notification_type: str):
    """Log notification to database"""
    supabase = get_supabase_service()
    
    try:
        # Map notification types to match database constraint
        type_mapping = {
            'breakfast': 'meal',
            'lunch': 'meal',
            'dinner': 'meal',
            'water': 'hydration',
            'supplement': 'supplement',
            'sleep': 'sleep',
            'exercise': 'exercise',
            'reminder': 'reminder',
            'fcm': 'fcm',
            'test': 'test'
        }
        
        db_type = type_mapping.get(notification_type, 'reminder')
        
        supabase.client.table('notifications').insert({
            'user_id': user_id,
            'title': title,
            'message': body,
            'type': db_type,
            'created_at': datetime.utcnow().isoformat()
        }).execute()
        
        print(f"✅ Logged notification: {db_type}")
    except Exception as e:
        print(f"⚠️ Error logging notification: {e}")

# API Endpoints
@router.post("/register")
async def register_fcm_token(data: FCMTokenRegister):
    """Register FCM token for a user"""
    try:
        print(f"📱 Registering FCM token for user: {data.user_id}")
        
        result = await save_fcm_token(data.user_id, data.fcm_token, data.platform)
        
        return {
            "success": True,
            "message": "FCM token registered successfully",
            "data": result
        }
    except Exception as e:
        raise internal_error(e)

@router.post("/test")
async def send_test_notification(data: FCMTestNotification):
    """Send a test notification to a user"""
    try:
        print(f"🧪 Sending test notification to user: {data.user_id}")
        
        success = await send_notification_to_user(
            user_id=data.user_id,
            title="🧪 Test Notification",
            body="If you see this, FCM is working perfectly!",
            data={"type": "test", "timestamp": datetime.utcnow().isoformat()}
        )
        
        if success:
            return {
                "success": True,
                "message": "Test notification sent successfully"
            }
        else:
            raise HTTPException(status_code=404, detail="No FCM token found for user")
            
    except Exception as e:
        raise internal_error(e)

@router.post("/subscribe")
async def subscribe_to_notifications(data: FCMSubscribe):
    """Subscribe user to daily notifications"""
    try:
        print(f"📬 Subscribing user to notifications: {data.user_id}")
        
        # Mark user as subscribed in database
        supabase = get_supabase_service()
        supabase.client.table('fcm_tokens')\
            .update({'subscribed': True})\
            .eq('user_id', data.user_id)\
            .execute()
        
        return {
            "success": True,
            "message": "Subscribed to notifications successfully"
        }
    except Exception as e:
        raise internal_error(e)

@router.post("/unsubscribe")
async def unsubscribe_from_notifications(data: FCMSubscribe):
    """Unsubscribe user from daily notifications"""
    try:
        print(f"🔕 Unsubscribing user from notifications: {data.user_id}")
        
        supabase = get_supabase_service()
        supabase.client.table('fcm_tokens')\
            .update({'subscribed': False})\
            .eq('user_id', data.user_id)\
            .execute()
        
        return {
            "success": True,
            "message": "Unsubscribed from notifications successfully"
        }
    except Exception as e:
        raise internal_error(e)

# Scheduled notification functions
async def send_breakfast_notifications():
    """Send breakfast reminders to all users (scheduled for 8:00 AM)"""
    print("🍳 Sending breakfast notifications...")
    
    users = await get_all_subscribed_users()
    success_count = 0
    
    for user in users:
        success = await send_notification_to_user(
            user_id=user['user_id'],
            title="🍳 Breakfast Reminder",
            body="Time to log your breakfast!",
            data={"type": "meal", "meal_type": "breakfast"}
        )
        if success:
            success_count += 1
    
    print(f"✅ Sent breakfast notifications to {success_count}/{len(users)} users")

async def send_lunch_notifications():
    """Send lunch reminders (1:00 PM)"""
    print("🍽️ Sending lunch notifications...")
    
    users = await get_all_subscribed_users()
    success_count = 0
    
    for user in users:
        success = await send_notification_to_user(
            user_id=user['user_id'],
            title="🍽️ Lunch Reminder",
            body="Time to log your lunch!",
            data={"type": "meal", "meal_type": "lunch"}
        )
        if success:
            success_count += 1
    
    print(f"✅ Sent lunch notifications to {success_count}/{len(users)} users")

async def send_dinner_notifications():
    """Send dinner reminders (7:00 PM)"""
    print("🌙 Sending dinner notifications...")
    
    users = await get_all_subscribed_users()
    success_count = 0
    
    for user in users:
        success = await send_notification_to_user(
            user_id=user['user_id'],
            title="🌙 Dinner Reminder",
            body="Time to log your dinner!",
            data={"type": "meal", "meal_type": "dinner"}
        )
        if success:
            success_count += 1
    
    print(f"✅ Sent dinner notifications to {success_count}/{len(users)} users")

async def send_water_notifications():
    """Send water reminders (10:00 AM and 4:00 PM)"""
    print("💧 Sending water notifications...")
    
    users = await get_all_subscribed_users()
    success_count = 0
    
    for user in users:
        success = await send_notification_to_user(
            user_id=user['user_id'],
            title="💧 Hydration Check",
            body="Remember to log your water intake!",
            data={"type": "hydration"}
        )
        if success:
            success_count += 1
    
    print(f"✅ Sent water notifications to {success_count}/{len(users)} users")

async def send_supplement_notifications():
    """Send supplement reminders (8:30 AM)"""
    print("💊 Sending supplement notifications...")
    
    users = await get_all_subscribed_users()
    success_count = 0
    
    for user in users:
        success = await send_notification_to_user(
            user_id=user['user_id'],
            title="💊 Supplement Reminder",
            body="Time to take your supplements!",
            data={"type": "supplement"}
        )
        if success:
            success_count += 1
    
    print(f"✅ Sent supplement notifications to {success_count}/{len(users)} users")

async def send_sleep_notifications():
    """Send sleep log reminders (9:00 AM)"""
    print("😴 Sending sleep notifications...")
    
    users = await get_all_subscribed_users()
    success_count = 0
    
    for user in users:
        success = await send_notification_to_user(
            user_id=user['user_id'],
            title="😴 Sleep Log Reminder",
            body="How was your sleep last night?",
            data={"type": "sleep"}
        )
        if success:
            success_count += 1
    
    print(f"✅ Sent sleep notifications to {success_count}/{len(users)} users")

async def send_exercise_notifications():
    """Send exercise reminders (6:00 PM)"""
    print("💪 Sending exercise notifications...")
    
    users = await get_all_subscribed_users()
    success_count = 0
    
    for user in users:
        success = await send_notification_to_user(
            user_id=user['user_id'],
            title="💪 Exercise Reminder",
            body="Don't forget to log your workout!",
            data={"type": "exercise"}
        )
        if success:
            success_count += 1
    
    print(f"✅ Sent exercise notifications to {success_count}/{len(users)} users")

# Initialize scheduler
def setup_notification_scheduler():
    """Set up APScheduler to send notifications at specific times"""
    scheduler = BackgroundScheduler()
    
    # Schedule breakfast notification (8:00 AM)
    scheduler.add_job(
        send_breakfast_notifications,
        'cron',
        hour=8,
        minute=0,
        id='breakfast_notification'
    )
    
    # Schedule supplement notification (8:30 AM)
    scheduler.add_job(
        send_supplement_notifications,
        'cron',
        hour=8,
        minute=30,
        id='supplement_notification'
    )
    
    # Schedule sleep notification (9:00 AM)
    scheduler.add_job(
        send_sleep_notifications,
        'cron',
        hour=9,
        minute=0,
        id='sleep_notification'
    )
    
    # Schedule water notification 1 (10:00 AM)
    scheduler.add_job(
        send_water_notifications,
        'cron',
        hour=10,
        minute=0,
        id='water_notification_1'
    )
    
    # Schedule lunch notification (1:00 PM)
    scheduler.add_job(
        send_lunch_notifications,
        'cron',
        hour=13,
        minute=0,
        id='lunch_notification'
    )
    
    # Schedule water notification 2 (4:00 PM)
    scheduler.add_job(
        send_water_notifications,
        'cron',
        hour=16,
        minute=0,
        id='water_notification_2'
    )
    
    # Schedule exercise notification (6:00 PM)
    scheduler.add_job(
        send_exercise_notifications,
        'cron',
        hour=18,
        minute=0,
        id='exercise_notification'
    )
    
    # Schedule dinner notification (7:00 PM)
    scheduler.add_job(
        send_dinner_notifications,
        'cron',
        hour=19,
        minute=0,
        id='dinner_notification'
    )
    
    scheduler.start()
    print("✅ Notification scheduler started")
    print("📅 Scheduled notifications:")
    print("   - 8:00 AM: Breakfast")
    print("   - 8:30 AM: Supplement")
    print("   - 9:00 AM: Sleep Log")
    print("   - 10:00 AM: Water")
    print("   - 1:00 PM: Lunch")
    print("   - 4:00 PM: Water")
    print("   - 6:00 PM: Exercise")
    print("   - 7:00 PM: Dinner")