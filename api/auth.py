# api/auth.py
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta
import uuid

from services.supabase_service import get_supabase_service
from api.users import hash_password, verify_password
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today, get_user_now
    
def normalize_timeline(timeline_value: str) -> str:
    """Normalize timeline values to week format"""
    
    # Map old values to new format
    timeline_map = {
        # Old month-based values
        '1_month': '4_weeks',
        '2_months': '8_weeks',
        '3_months': '12_weeks',
        '4_months': '16_weeks',
        '6_months': '24_weeks',
        
        # Text-based values
        'Ambitious': '6_weeks',
        'Moderate': '12_weeks',
        'Gradual': '20_weeks',
    }
    
    # Return mapped value or original if already in correct format
    return timeline_map.get(timeline_value, timeline_value)

def validate_and_sync_goals(weight_goal: str) -> str:
    """Map weight goal to primary goal"""
    
    goal_mapping = {
        'lose_weight': 'Lose Weight',
        'gain_weight': 'Gain Weight', 
        'maintain_weight': 'Maintain Weight',
    }
    
    return goal_mapping[weight_goal]


router = APIRouter()

# Flutter-compatible models
class HealthUserCreate(BaseModel):
    name: str
    email: str
    password: str
    gender: Optional[str] = None
    age: Optional[int] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    activityLevel: Optional[str] = None
    bmi: Optional[float] = None
    bmr: Optional[float] = None
    tdee: Optional[float] = None
    
    # Flutter expects these exact field names
    hasPeriods: Optional[bool] = None
    lastPeriodDate: Optional[str] = None
    cycleLength: Optional[int] = None
    cycleLengthRegular: Optional[bool] = None
    pregnancyStatus: Optional[str] = None
    periodTrackingPreference: Optional[str] = None
    
    primaryGoal: Optional[str] = None
    weightGoal: Optional[str] = None
    targetWeight: Optional[float] = None
    goalTimeline: Optional[str] = None
    
    sleepHours: Optional[float] = 7.0
    bedtime: Optional[str] = None
    wakeupTime: Optional[str] = None
    sleepIssues: Optional[list] = []
    
    dietaryPreferences: Optional[list] = []
    waterIntake: Optional[float] = 2.0
    waterIntakeGlasses: Optional[int] = 8
    dailyStepGoal: Optional[int] = 10000
    dailyMealsCount: Optional[int] = 3
    medicalConditions: Optional[list] = []
    otherMedicalCondition: Optional[str] = None
    
    preferredWorkouts: Optional[list] = []
    workoutFrequency: Optional[int] = 3
    workoutDuration: Optional[int] = 30
    workoutLocation: Optional[str] = None
    availableEquipment: Optional[list] = []
    fitnessLevel: Optional[str] = "Beginner"
    hasTrainer: Optional[bool] = False

class HealthUserResponse(BaseModel):
    success: bool
    userId: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    userProfile: Optional[Dict[str, Any]] = None

class HealthLoginRequest(BaseModel):
    email: str
    password: str

class UnifiedOnboardingRequest(BaseModel):
    basicInfo: Dict[str, Any]
    periodCycle: Optional[Dict[str, Any]] = {}
    primaryGoal: Optional[str] = None
    weightGoal: Optional[Dict[str, Any]] = {}
    sleepInfo: Optional[Dict[str, Any]] = {}
    dietaryPreferences: Optional[Dict[str, Any]] = {}
    workoutPreferences: Optional[Dict[str, Any]] = {}
    exerciseSetup: Optional[Dict[str, Any]] = {}

@router.get("/check")
async def health_check():
    """Health check for mobile app"""
    return {"status": "ok", "message": "Health API is running"}

@router.post("/users", response_model=HealthUserResponse)
async def create_health_user(user_profile: HealthUserCreate, tz_offset: int = Depends(get_timezone_offset)):
    """Create user profile for mobile app - Flutter compatible"""
    try:
        print(f"🔍 Flutter user registration: {user_profile.email}")
        
        supabase_service = get_supabase_service()
        
        # Check if user already exists
        existing_user = await supabase_service.get_user_by_email(user_profile.email)
        if existing_user:
            return HealthUserResponse(
                success=False,
                error="Email already exists"
            )
        
        # Convert Flutter model to our backend format
        user_dict = {
            'id': str(uuid.uuid4()),
            'name': user_profile.name,
            'email': user_profile.email,
            'password_hash': hash_password(user_profile.password),
            'gender': user_profile.gender,
            'age': user_profile.age,
            'height': user_profile.height,
            'weight': user_profile.weight,
            'starting_weight': user_profile.weight,
            'starting_weight_date': get_user_now(tz_offset).isoformat(),
            'activity_level': user_profile.activityLevel,
            'bmi': user_profile.bmi,
            'bmr': user_profile.bmr,
            'tdee': user_profile.tdee,
            
            # Period tracking
            'has_periods': user_profile.hasPeriods,
            'last_period_date': user_profile.lastPeriodDate,
            'cycle_length': user_profile.cycleLength,
            'cycle_length_regular': user_profile.cycleLengthRegular,
            'pregnancy_status': user_profile.pregnancyStatus,
            'period_tracking_preference': user_profile.periodTrackingPreference,
            
            # Goals
            'primary_goal': user_profile.primaryGoal,
            'weight_goal': user_profile.weightGoal,
            'target_weight': user_profile.targetWeight,
            'goal_timeline': user_profile.goalTimeline,
            'daily_step_goal': user_profile.dailyStepGoal ,
            
            # Sleep
            'sleep_hours': user_profile.sleepHours,
            'bedtime': user_profile.bedtime,
            'wakeup_time': user_profile.wakeupTime,
            'sleep_issues': user_profile.sleepIssues or [],
            
            # Nutrition
            'dietary_preferences': user_profile.dietaryPreferences or [],
            'water_intake': user_profile.waterIntake,
            'water_intake_glasses': user_profile.waterIntakeGlasses,
            'daily_meals_count': user_profile.dailyMealsCount,
            'medical_conditions': user_profile.medicalConditions or [],
            'other_medical_condition': user_profile.otherMedicalCondition,
            
            # Exercise
            'preferred_workouts': user_profile.preferredWorkouts or [],
            'workout_frequency': user_profile.workoutFrequency,
            'workout_duration': user_profile.workoutDuration,
            'workout_location': user_profile.workoutLocation,
            'available_equipment': user_profile.availableEquipment or [],
            'fitness_level': user_profile.fitnessLevel,
            'has_trainer': user_profile.hasTrainer,
            
            'preferences': {},
            'created_at': get_user_now(tz_offset).isoformat(),
            'updated_at': get_user_now(tz_offset).isoformat()
        }
        
        # Create user in Supabase
        created_user = await supabase_service.create_user(user_dict)
        
        return HealthUserResponse(
            success=True,
            userId=created_user['id'],
            message="User registered successfully"
        )
        
    except Exception as e:
        print(f"❌ Error creating Flutter user: {e}")
        return HealthUserResponse(
            success=False,
            error=str(e)
        )

@router.post("/onboarding/complete", response_model=HealthUserResponse)
async def complete_flutter_onboarding(
    onboarding_data: UnifiedOnboardingRequest,
    tz_offset: int = Depends(get_timezone_offset)
):
    """Complete onboarding process for Flutter app"""
    try:
        print("🔍 Flutter onboarding data received")
        
        # Get Supabase service
        supabase_service = get_supabase_service()

        basic_info = onboarding_data.basicInfo
        period_cycle = onboarding_data.periodCycle or {}
        weight_goal = onboarding_data.weightGoal or {}
        sleep_info = onboarding_data.sleepInfo or {}
        dietary_prefs = onboarding_data.dietaryPreferences or {}
        workout_prefs = onboarding_data.workoutPreferences or {}
        exercise_setup = onboarding_data.exerciseSetup or {}
        
        print(f"🔍 Flutter user registration: {basic_info.get('email')}")
        
        timeline = weight_goal.get('timeline', '12_weeks')
        normalized_timeline = normalize_timeline(timeline)

        weight_goal_value = weight_goal.get('weightGoal', 'maintain_weight')
        primary_goal_value = validate_and_sync_goals(weight_goal_value)

        target_weight = weight_goal.get('targetWeight', 0.0)
        if weight_goal.get('weightGoal') == 'maintain_weight' and target_weight == 0:
            target_weight = basic_info.get('weight', 0.0)

        current_weight = basic_info.get('weight')
        
        # Create user dictionary directly
        user_dict = {
            'id': str(uuid.uuid4()),
            'name': basic_info.get('name'),
            'email': basic_info.get('email'),
            'password_hash': hash_password(basic_info.get('password')),
            'gender': basic_info.get('gender'),
            'age': basic_info.get('age'),
            'height': basic_info.get('height'),
            'weight': basic_info.get('weight'),
            'starting_weight': current_weight,
            'starting_weight_date': get_user_now(tz_offset).isoformat(),
            'activity_level': basic_info.get('activityLevel'),
            'bmi': basic_info.get('bmi'),
            'bmr': basic_info.get('bmr'),
            'tdee': basic_info.get('tdee'),
            
            # Period tracking
            'has_periods': period_cycle.get('hasPeriods'),
            'last_period_date': period_cycle.get('lastPeriodDate'),
            'cycle_length': period_cycle.get('cycleLength'),
            'cycle_length_regular': period_cycle.get('cycleLengthRegular'),
            'pregnancy_status': period_cycle.get('pregnancyStatus'),
            'period_tracking_preference': period_cycle.get('trackingPreference'),
            
            # Goals
            'primary_goal': primary_goal_value,
            'weight_goal': weight_goal.get('weightGoal'),
            'target_weight': target_weight,
            'goal_timeline': normalized_timeline,
            'daily_step_goal': basic_info.get('dailyStepGoal', 10000),
            
            # Sleep
            'sleep_hours': sleep_info.get('sleepHours', 7.0),
            'bedtime': sleep_info.get('bedtime'),
            'wakeup_time': sleep_info.get('wakeupTime'),
            'sleep_issues': sleep_info.get('sleepIssues', []),
            
            # Nutrition
            'dietary_preferences': dietary_prefs.get('dietaryPreferences', []),
            'water_intake': dietary_prefs.get('waterIntake', 2.0),
            'water_intake_glasses': dietary_prefs.get('waterIntakeGlasses', 8),
            'daily_meals_count': dietary_prefs.get('dailyMealsCount', 3),
            'medical_conditions': dietary_prefs.get('medicalConditions', []),
            'other_medical_condition': dietary_prefs.get('otherCondition'),
            
            # Exercise
            'preferred_workouts': workout_prefs.get('workoutTypes', []),
            'workout_frequency': workout_prefs.get('frequency', 3),
            'workout_duration': workout_prefs.get('duration', 30),
            'workout_location': exercise_setup.get('workoutLocation'),
            'available_equipment': exercise_setup.get('equipment', []),
            'fitness_level': exercise_setup.get('fitnessLevel', 'Beginner'),
            'has_trainer': exercise_setup.get('hasTrainer', False),
            
            'preferences': {},
            'created_at': get_user_now(tz_offset).isoformat(),
            'updated_at': get_user_now(tz_offset).isoformat()
        }
        
        # Check if user already exists
        print(f"🔍 Getting user by email: {basic_info.get('email')}")
        existing_user = await supabase_service.get_user_by_email(basic_info.get('email'))
        
        if existing_user:
            print(f"❌ User already exists: {basic_info.get('email')}")
            return HealthUserResponse(
                success=False,
                error="Email already exists"
            )
        
        print(f"✅ User not found by email: {basic_info.get('email')}")


        print(f"✅ Creating user in Supabase...")
        
        # Create user in Supabase
        created_user = await supabase_service.create_user(user_dict)
        
        if created_user:
            print(f"✅ User created successfully with ID: {created_user['id']}")
            print(f"   Daily step goal: {created_user.get('daily_step_goal')}")
            print(f"   Daily meals count: {created_user.get('daily_meals_count')}")
            print(f"   Target weight: {created_user.get('target_weight')}")
            
            # Return the created user profile
            return HealthUserResponse(
                success=True,
                userId=created_user['id'],
                message="Onboarding completed successfully",
                userProfile=created_user
            )
        else:
            return HealthUserResponse(
                success=False,
                error="Failed to create user"
            )
        
    except Exception as e:
        print(f"❌ Error completing Flutter onboarding: {e}")
        import traceback
        traceback.print_exc()
        return HealthUserResponse(
            success=False,
            error=str(e)
        )

@router.get("/users/{user_id}", response_model=HealthUserResponse)
async def get_health_user_profile(user_id: str):
    """Get user profile for mobile app"""
    try:
        print(f"🔍 Getting user profile for: {user_id}")
        
        supabase_service = get_supabase_service()
        user = await supabase_service.get_user_by_id(user_id)
        
        if not user:
            return HealthUserResponse(
                success=False,
                error="User not found"
            )
        
        # ✅ Auto-initialize starting weight if missing
        if not user.get('starting_weight'):
            print(f"🔄 Auto-initializing starting weight for user {user_id}")
            await supabase_service.initialize_starting_weight_for_user(user_id)
            # Fetch user again to get updated data
            user = await supabase_service.get_user_by_id(user_id)
        
        return HealthUserResponse(
            success=True,
            userId=user['id'],
            userProfile=user,
            message="User profile retrieved successfully"
        )
        
    except Exception as e:
        print(f"❌ Error getting Flutter user profile: {e}")
        return HealthUserResponse(
            success=False,
            error=str(e)
        )
    
@router.post("/auth/login")
async def auth_login(login_data: dict):
    """Login endpoint that matches Flutter's expected path"""
    try:
        email = login_data.get('email')
        password = login_data.get('password')
        
        print(f"🔐 Flutter auth login attempt for: {email}")
        
        if not email or not password:
            raise HTTPException(status_code=400, detail="Email and password required")
        
        supabase_service = get_supabase_service()
        
        # Get user by email
        user = await supabase_service.get_user_by_email(email)
        if not user:
            print(f"❌ User not found: {email}")
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Verify password
        if not verify_password(password, user['password_hash']):
            print(f"❌ Invalid password for: {email}")
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        print(f"✅ Login successful for: {email}")
        
        return {
            "success": True,
            "user": {
                "id": user['id'],
                "name": user['name'],
                "email": user['email'],
                "age": user.get('age'),
                "gender": user.get('gender'),
                "height": user.get('height'),
                "weight": user.get('weight'),
                "activity_level": user.get('activity_level'),
                "bmi": user.get('bmi'),
                "bmr": user.get('bmr'),
                "tdee": user.get('tdee')
            },
            "message": "Login successful"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Login error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{user_id}")
async def update_user_profile(user_id: str, user_data: dict):
    """Update user profile"""
    try:
        print(f"👤 Updating user profile: {user_id}")
        
        supabase_service = get_supabase_service()
        updated_user = await supabase_service.update_user(user_id, user_data)
        
        return {"success": True, "user": updated_user}
        
    except Exception as e:
        print(f"❌ Error updating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
