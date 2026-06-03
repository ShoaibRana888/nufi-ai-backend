# api/flutter_compat.py
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta
import uuid
from api.meals import update_daily_nutrition
from services.chat_context_manager import get_context_manager

from services.supabase_service import get_supabase_service
from api.users import hash_password, verify_password
from services.openai_service import get_openai_service
from models.exercise_schemas import ExerciseLogCreate
from services.chat_service import get_chat_service
from services.goal_frameworks import WeightGoalFrameworks
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

def calculate_exercise_duration(exercise_type, sets, reps, exercise_name=None):
    """
    Calculate realistic duration for an exercise in minutes
    Returns total workout time including rest periods
    """
    if exercise_type == 'cardio':
        # Cardio duration should be provided by user
        return None  # Let user input actual duration
    
    elif exercise_type == 'strength':
        # Time per rep (in seconds)
        time_per_rep = 3  # Average 3 seconds per rep (1 up, 1 hold, 1 down)
        
        # Rest time between sets (in seconds)
        rest_between_sets = 60  # 1 minute rest for most exercises
        
        # Adjust rest time based on exercise intensity
        heavy_exercises = ['squat', 'deadlift', 'bench press', 'leg press']
        if exercise_name and any(heavy in exercise_name.lower() for heavy in heavy_exercises):
            rest_between_sets = 90  # 1.5 minutes for heavy compound movements
        
        # Calculate total time
        total_rep_time = sets * reps * time_per_rep
        total_rest_time = (sets - 1) * rest_between_sets if sets > 1 else 0
        setup_time = 30  # 30 seconds to set up/adjust weights
        
        total_seconds = total_rep_time + total_rest_time + setup_time
        duration_minutes = round(total_seconds / 60)  # Round to integer
        
        return max(duration_minutes, 1)  # Minimum 1 minute
    
    # Default for unknown types
    return 5


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

@router.get("/daily-summary/{user_id}")
async def get_daily_summary_flutter(user_id: str, date: str = None, tz_offset: int = Depends(get_timezone_offset)):
    """Get daily summary for Flutter app with all nutrition data"""
    try:
        target_date = get_user_date(date, tz_offset) if date else get_user_today(tz_offset)
        
        print(f"📊 Getting daily summary for user {user_id} on {target_date}")
        
        supabase_service = get_supabase_service()
        meals = await supabase_service.get_user_meals_by_date(user_id, str(target_date))
        
        # Calculate totals including fiber, sugar, sodium
        total_calories = 0
        total_protein = 0
        total_carbs = 0
        total_fat = 0
        total_fiber = 0
        total_sugar = 0
        total_sodium = 0
        
        # Calculate totals from all meals
        for meal in meals:
            total_calories += float(meal.get('calories', 0))
            total_protein += float(meal.get('protein_g', 0))
            total_carbs += float(meal.get('carbs_g', 0))
            total_fat += float(meal.get('fat_g', 0))
            total_fiber += float(meal.get('fiber_g', 0))
            total_sugar += float(meal.get('sugar_g', 0))
            total_sodium += float(meal.get('sodium_mg', 0))
        
        print(f"📊 Calculated totals - Fiber: {total_fiber}, Sugar: {total_sugar}, Sodium: {total_sodium}")
        
        response_data = {
            "success": True,
            "date": str(target_date),
            "totals": {
                "calories": float(total_calories),
                "protein_g": float(total_protein),
                "carbs_g": float(total_carbs),
                "fat_g": float(total_fat),
                "fiber_g": float(total_fiber),
                "sugar_g": float(total_sugar),
                "sodium_mg": float(total_sodium),
            },
            "meals": {
                "total_calories": float(total_calories),
                "calories_consumed": float(total_calories),
                "total_protein": float(total_protein),
                "protein_g": float(total_protein),
                "total_carbs": float(total_carbs),
                "carbs_g": float(total_carbs),
                "total_fat": float(total_fat),
                "fat_g": float(total_fat),
                "total_fiber": float(total_fiber),
                "fiber_g": float(total_fiber),
                "total_sugar": float(total_sugar),
                "sugar_g": float(total_sugar),
                "total_sodium": float(total_sodium),
                "sodium_mg": float(total_sodium),
                "meals_count": len(meals),
                "total_count": len(meals)
            }
        }
        
        print(f"📊 Returning response: {response_data}")
        return response_data
        
    except Exception as e:
        print(f"❌ Error getting daily summary: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/meals/history/{user_id}")
async def get_meal_history_flutter(user_id: str, limit: int = 50, date: str = None, tz_offset: int = Depends(get_timezone_offset)):
    """Get meal history for Flutter app"""
    try:
        print(f"🍽️ Getting meal history for user: {user_id}, limit: {limit}, date: {date}")
        
        supabase_service = get_supabase_service()
        
        if date:
            date_only = str(get_user_date(date, tz_offset))
            meals = await supabase_service.get_user_meals_by_date(user_id, date_only)
        else:
            meals = await supabase_service.get_user_meals(user_id, limit=limit)
        
        # Helper function to capitalize meal types
        def capitalize_meal_type(meal_type):
            if not meal_type:
                return "Snack"
            meal_type = str(meal_type).lower()
            if meal_type == "lunch":
                return "Lunch"
            elif meal_type == "breakfast":
                return "Breakfast"
            elif meal_type == "dinner":
                return "Dinner"
            else:
                return "Snack"
        
        # Format meals for Flutter with proper field names
        formatted_meals = []
        for meal in meals:
            formatted_meal = {
                "id": str(meal.get('id', '')),
                "food_item": str(meal.get('food_item', '')),  # This is what Flutter expects!
                "name": str(meal.get('food_item', '')),
                "quantity": str(meal.get('quantity', '')),
                "meal_type": capitalize_meal_type(meal.get('meal_type')),
                "calories": float(meal.get('calories', 0)),
                "protein": float(meal.get('protein_g', 0)),
                "carbs": float(meal.get('carbs_g', 0)),
                "fat": float(meal.get('fat_g', 0)),
                "protein_g": float(meal.get('protein_g', 0)),
                "carbs_g": float(meal.get('carbs_g', 0)),
                "fat_g": float(meal.get('fat_g', 0)),
                "fiber": float(meal.get('fiber_g', 0)),
                "sugar": float(meal.get('sugar_g', 0)),
                "sodium": float(meal.get('sodium_mg', 0)),
                "logged_at": str(meal.get('logged_at', meal.get('meal_date', ''))),
                "meal_date": str(meal.get('meal_date', '')),
                "nutrition_notes": str(meal.get('nutrition_data', {}).get('nutrition_notes', '')),
                "healthiness_score": int(meal.get('nutrition_data', {}).get('healthiness_score', 7)),
                "suggestions": str(meal.get('nutrition_data', {}).get('suggestions', ''))
            }
            formatted_meals.append(formatted_meal)
        
        return {
            "success": True,
            "meals": formatted_meals,
            "total_count": len(formatted_meals)
        }
        
    except Exception as e:
        print(f"❌ Error getting Flutter meal history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.put("/meals/{meal_id}")
async def update_meal_flutter(meal_id: str, meal_data: dict):
    """Update meal entry for Flutter app"""
    try:
        print(f"📝 Updating meal {meal_id}")
        
        supabase_service = get_supabase_service()
        
        # Prepare update data
        update_data = {
            'food_item': meal_data.get('food_item'),
            'quantity': meal_data.get('quantity'),
            'calories': meal_data.get('calories'),
            'protein_g': meal_data.get('protein_g'),
            'carbs_g': meal_data.get('carbs_g'),
            'fat_g': meal_data.get('fat_g'),
        }
        
        # Update in database
        updated = await supabase_service.update_meal(meal_id, update_data)
        
        return {
            "success": True,
            "message": "Meal updated successfully",
            "meal": updated
        }
        
    except Exception as e:
        print(f"❌ Error updating meal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/meals/{meal_id}")
async def delete_meal(meal_id: str, user_id: str):
    """Delete meal and update context"""
    try:
        supabase_service = get_supabase_service()
        
        # Get meal details before deletion
        meal = await supabase_service.get_meal_by_id(meal_id)
        if not meal:
            raise HTTPException(status_code=404, detail="Meal not found")
        
        # Delete from database
        await supabase_service.delete_meal(meal_id)
        
        # Update context
        context_manager = get_context_manager()
        meal_date = datetime.fromisoformat(meal['created_at']).date()
        await context_manager.remove_from_context(
            user_id,
            'meal',
            meal_id,
            meal_date
        )
        
        return {"success": True, "message": "Meal deleted"}
        
    except Exception as e:
        print(f"❌ Error deleting meal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/exercise/log", response_model=dict)
async def log_exercise(exercise_data: dict, tz_offset: int = Depends(get_timezone_offset)):
    """Log exercise activity"""
    try:
        print(f"💪 Logging exercise: {exercise_data.get('exercise_name')} for user {exercise_data.get('user_id')}")
        
        supabase_service = get_supabase_service()
        
        # Parse exercise date
        exercise_date_str = exercise_data.get('exercise_date')
        if exercise_date_str:
            try:
                exercise_date = get_user_date(exercise_date_str, tz_offset)
            except ValueError:
                exercise_date = get_user_now(tz_offset)
        else:
            exercise_date = get_user_now(tz_offset)
        
        # ✅ ENSURE duration_minutes is ALWAYS populated
        exercise_type = exercise_data.get('exercise_type', 'strength')
        
        if not exercise_data.get('duration_minutes'):
            # Calculate duration if not provided
            if exercise_type == 'strength' and exercise_data.get('sets'):
                calculated_duration = calculate_exercise_duration(
                    exercise_type=exercise_type,
                    sets=exercise_data.get('sets', 3),
                    reps=exercise_data.get('reps', 12),
                    exercise_name=exercise_data.get('exercise_name')
                )
                exercise_data['duration_minutes'] = calculated_duration
                print(f"💪 Calculated duration for strength exercise: {calculated_duration} minutes")
            elif exercise_type == 'cardio':
                # Cardio should have duration, but set default if missing
                exercise_data['duration_minutes'] = 10  # Default 10 min for cardio
                print(f"⚠️ Warning: Cardio exercise without duration, using default: 10 minutes")
            else:
                # Unknown type - set default
                exercise_data['duration_minutes'] = 5
                print(f"⚠️ Warning: Exercise without duration or sets, using default: 5 minutes")
        else:
            print(f"💪 Using provided duration: {exercise_data.get('duration_minutes')} minutes")
        
        # Clean the data - remove null values and ensure proper types
        exercise_log_data = {
            'id': str(uuid.uuid4()),
            'user_id': exercise_data.get('user_id'),
            'exercise_name': exercise_data.get('exercise_name'),
            'exercise_type': exercise_type,
            'muscle_group': exercise_data.get('muscle_group', 'general'),
            'duration_minutes': int(exercise_data.get('duration_minutes')),  # ✅ Always include
            'intensity': exercise_data.get('intensity'),
            'notes': exercise_data.get('notes'),
            'exercise_date': exercise_date.isoformat(),
            'created_at': get_user_now(tz_offset).isoformat(),
            'updated_at': get_user_now(tz_offset).isoformat()
        }
        
        # Add type-specific fields only if they have values
        if exercise_type == 'cardio':
            # For cardio exercises
            if exercise_data.get('distance_km') is not None and exercise_data.get('distance_km') > 0:
                exercise_log_data['distance_km'] = float(exercise_data.get('distance_km'))
            if exercise_data.get('calories_burned') is not None:
                exercise_log_data['calories_burned'] = float(exercise_data.get('calories_burned'))
        else:
            # For strength exercises
            if exercise_data.get('sets') is not None:
                exercise_log_data['sets'] = int(exercise_data.get('sets'))
            if exercise_data.get('reps') is not None:
                exercise_log_data['reps'] = int(exercise_data.get('reps'))
            if exercise_data.get('weight_kg') is not None and exercise_data.get('weight_kg') > 0:
                exercise_log_data['weight_kg'] = float(exercise_data.get('weight_kg'))
            if exercise_data.get('calories_burned') is not None:
                exercise_log_data['calories_burned'] = float(exercise_data.get('calories_burned'))
        
        print(f"💪 Processed exercise data: {exercise_log_data}")
        
        created_log = await supabase_service.create_exercise_log(exercise_log_data)

        context_manager = get_context_manager()
        exercise_date_obj = datetime.fromisoformat(exercise_date.isoformat()).date()
        await context_manager.update_context_activity(
            exercise_data.get('user_id'),
            'exercise',
            created_log,
            exercise_date_obj
        )
        
        return {"success": True, "id": created_log['id'], "exercise": created_log}
        
    except Exception as e:
        print(f"❌ Error logging exercise: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exercise/logs/{user_id}")
async def get_exercise_logs(
    user_id: str, 
    exercise_type: Optional[str] = None, 
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None, 
    limit: int = 50
):
    """Get exercise logs for a user"""
    try:
        print(f"💪 Getting exercise logs for user: {user_id}")
        
        supabase_service = get_supabase_service()
        logs = await supabase_service.get_exercise_logs(
            user_id, 
            exercise_type=exercise_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        print(f"💪 Returning {len(logs)} exercise logs")
        
        return {"success": True, "exercises": logs}
        
    except Exception as e:
        print(f"❌ Error getting exercise logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exercise/stats/{user_id}")
async def get_exercise_stats(user_id: str, days: int = 30, tz_offset: int = Depends(get_timezone_offset)):
    """Get exercise statistics"""
    try:
        print(f"💪 Getting exercise stats for user: {user_id}, last {days} days")
        
        supabase_service = get_supabase_service()
        
        # Get recent exercise logs - use a broader date range
        end_date = get_user_today(tz_offset)
        start_date = end_date - timedelta(days=days)
        
        print(f"💪 Date range: {start_date} to {end_date}")
        
        # Get all logs for the user in the date range
        logs = await supabase_service.get_exercise_logs(
            user_id,
            start_date=str(start_date),
            end_date=str(end_date),
            limit=1000  # Increase limit to get all exercises
        )
        
        print(f"💪 Found {len(logs)} exercise logs for stats calculation")
        
        # Always return a proper stats object, even if empty
        stats = {
            "total_workouts": 0,
            "total_minutes": 0,
            "total_calories": 0.0,
            "avg_duration": 0.0,
            "most_common_type": None,
            "type_breakdown": {}
        }
        
        if logs and len(logs) > 0:
            print(f"💪 Processing {len(logs)} logs for stats...")
            
            # Calculate statistics
            total_workouts = len(logs)
            total_minutes = 0
            total_calories = 0.0
            type_counts = {}
            
            for log in logs:
                # Debug each log
                duration = log.get('duration_minutes', 0)
                calories = log.get('calories_burned', 0) or 0
                exercise_type = log.get('exercise_type', 'other')
                
                print(f"💪 Log: {log.get('exercise_name')} - {duration} min, {calories} cal, type: {exercise_type}")
                
                total_minutes += duration
                total_calories += calories
                
                # Count exercise types
                type_counts[exercise_type] = type_counts.get(exercise_type, 0) + 1
            
            avg_duration = total_minutes / total_workouts if total_workouts > 0 else 0
            most_common_type = max(type_counts.items(), key=lambda x: x[1])[0] if type_counts else None
            
            stats.update({
                "total_workouts": total_workouts,
                "total_minutes": total_minutes,
                "total_calories": round(total_calories, 1),
                "avg_duration": round(avg_duration, 1),
                "most_common_type": most_common_type,
                "type_breakdown": type_counts
            })
            
            print(f"💪 Calculated stats: {stats}")
        else:
            print("💪 No exercise logs found for stats calculation")
        
        return {"success": True, "stats": stats}
        
    except Exception as e:
        print(f"❌ Error getting exercise stats: {e}")
        import traceback
        traceback.print_exc()
        # Return empty stats on error, don't raise exception
        return {
            "success": False, 
            "stats": {
                "total_workouts": 0,
                "total_minutes": 0,
                "total_calories": 0.0,
                "avg_duration": 0.0,
                "most_common_type": None,
                "type_breakdown": {}
            },
            "error": str(e)
        }

@router.delete("/exercise/log/{exercise_id}")
async def delete_exercise_log(exercise_id: str):
    """Delete an exercise log entry"""
    try:
        print(f"💪 Deleting exercise log: {exercise_id}")
        
        supabase_service = get_supabase_service()
        context_manager = get_context_manager()
        
        # Get exercise details before deletion
        exercise = await supabase_service.get_exercise_by_id(exercise_id)
        if not exercise:
            raise HTTPException(status_code=404, detail="Exercise not found")
        
        # Delete from database
        success = await supabase_service.delete_exercise_log(exercise_id)
        
        if success:
            # Update context - remove this specific exercise
            exercise_date = datetime.fromisoformat(exercise['exercise_date']).date()
            await context_manager.remove_from_context(
                exercise['user_id'],  # Get user_id from the exercise record
                'exercise',
                exercise_id,
                exercise_date
            )
            
            return {"success": True, "message": "Exercise deleted successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete exercise")
            
    except Exception as e:
        print(f"❌ Error deleting exercise: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exercise/weekly-summary/{user_id}")
async def get_weekly_exercise_summary(user_id: str, tz_offset: int = Depends(get_timezone_offset)):
    """Get weekly exercise summary for analytics"""
    try:
        print(f"💪 Getting weekly summary for user: {user_id}")
        
        supabase_service = get_supabase_service()
        
        # Get exercises from the last 4 weeks for better analysis
        end_date = get_user_today(tz_offset)
        start_date = end_date - timedelta(days=28)
        
        exercises = await supabase_service.get_exercise_logs(
            user_id,
            start_date=str(start_date),
            end_date=str(end_date),
            limit=500
        )
        
        # Calculate weekly summary
        summary = {
            "total_workouts": len(exercises),
            "total_calories": sum(ex.get('calories_burned', 0) for ex in exercises),
            "muscle_groups": {},
            "weekly_breakdown": {},
            "most_frequent_exercise": None,
            "total_volume": 0  # For strength exercises
        }
        
        # Calculate muscle group distribution
        for ex in exercises:
            muscle_group = ex.get('muscle_group', 'other')
            summary["muscle_groups"][muscle_group] = summary["muscle_groups"].get(muscle_group, 0) + 1
        
        # Calculate weekly breakdown
        for ex in exercises:
            date = get_user_now(tz_offset).isoformat(ex['exercise_date'].replace('Z', '+00:00'))
            week_start = date - timedelta(days=date.weekday())
            week_key = week_start.strftime('%Y-%m-%d')
            summary["weekly_breakdown"][week_key] = summary["weekly_breakdown"].get(week_key, 0) + 1
        
        # Find most frequent exercise
        exercise_counts = {}
        for ex in exercises:
            name = ex.get('exercise_name', 'Unknown')
            exercise_counts[name] = exercise_counts.get(name, 0) + 1
        
        if exercise_counts:
            summary["most_frequent_exercise"] = max(exercise_counts.items(), key=lambda x: x[1])[0]
        
        # Calculate total volume for strength exercises
        for ex in exercises:
            if ex.get('exercise_type') == 'strength':
                sets = ex.get('sets', 0) or 0
                reps = ex.get('reps', 0) or 0
                weight = ex.get('weight_kg', 0) or 0
                summary["total_volume"] += sets * reps * weight
        
        return {"success": True, "summary": summary}
        
    except Exception as e:
        print(f"❌ Error getting weekly summary: {e}")
        return {"success": False, "summary": {}}

@router.get("/exercise/history/{user_id}")
async def get_exercise_history(
    user_id: str,
    limit: int = 100,
    date: str = None
):
    """Get exercise history with optional date filtering"""
    try:
        print(f"💪 Getting exercise history for user: {user_id}")
        
        supabase_service = get_supabase_service()
        
        if date:
            # Get exercises for specific date
            exercises = await supabase_service.get_exercise_logs(
                user_id,
                start_date=date,
                end_date=date,
                limit=limit
            )
        else:
            # Get all recent exercises
            exercises = await supabase_service.get_exercise_logs(
                user_id,
                limit=limit
            )
        
        return {"success": True, "exercises": exercises}
        
    except Exception as e:
        print(f"❌ Error getting exercise history: {e}")
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
    
@router.post("/chat", response_model=dict)
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
    
@router.get("/user/{user_id}/framework")
async def get_user_framework(user_id: str):
    try:
        print(f"🎯 Getting framework for user: {user_id}")
        
        supabase_service = get_supabase_service()
        user = await supabase_service.get_user_by_id(user_id)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Debug the user data
        print(f"🎯 User data: {user}")
        print(f"🎯 User weight_goal: '{user.get('weight_goal')}'")
        print(f"🎯 User primary_goal: '{user.get('primary_goal')}'")
        
        # Fix the weight goal mapping
        weight_goal = user.get('weight_goal', '').lower().strip()
        primary_goal = user.get('primary_goal', '').lower().strip()
        
        # Map based on both weight_goal and primary_goal
        if 'lose' in weight_goal or 'lose' in primary_goal:
            mapped_goal = 'lose_weight'
        elif 'gain' in weight_goal or 'gain' in primary_goal:
            mapped_goal = 'gain_weight'
        else:
            mapped_goal = 'maintain_weight'
            
        print(f"🎯 Mapped goal: {mapped_goal}")
        
        # Update the user data for framework generation
        user_for_framework = {**user, 'weight_goal': mapped_goal}
        
        # Get framework based on mapped goal
        framework = WeightGoalFrameworks.get_framework_for_user(user_for_framework)
        
        print(f"🎯 Generated framework type: {framework.get('framework_type')}")
        
        return {
            "success": True,
            "framework": framework,
            "debug_info": {
                "original_weight_goal": user.get('weight_goal'),
                "original_primary_goal": user.get('primary_goal'),
                "mapped_goal": mapped_goal,
                "framework_type": framework.get('framework_type')
            }
        }
        
    except Exception as e:
        print(f"❌ Error getting user framework: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/frameworks/compare")
async def compare_frameworks():
    """Get all framework types for comparison"""
    try:
        # Sample user profile for demonstration
        sample_profile = {
            'weight': 70,
            'target_weight': 65,
            'height': 170,
            'age': 30,
            'gender': 'Female',
            'activity_level': 'Moderately active',
            'tdee': 2000,
            'fitness_level': 'Intermediate'
        }
        
        frameworks = {
            'weight_loss': WeightGoalFrameworks.get_weight_loss_framework(
                {**sample_profile, 'weight_goal': 'lose_weight', 'target_weight': 60}
            ),
            'weight_gain': WeightGoalFrameworks.get_weight_gain_framework(
                {**sample_profile, 'weight_goal': 'gain_weight', 'target_weight': 75}
            ),
            'maintenance': WeightGoalFrameworks.get_maintenance_framework(
                {**sample_profile, 'weight_goal': 'maintain_weight'}
            )
        }
        
        return {
            "success": True,
            "frameworks": frameworks
        }
        
    except Exception as e:
        print(f"❌ Error comparing frameworks: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/chat/history/{user_id}")
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

@router.delete("/chat/history/{user_id}")
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
    
@router.get("/chat/messages/{user_id}")
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

@router.delete("/chat/messages/{user_id}")
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
    
@router.get("/chat/sessions/{user_id}")
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

@router.get("/chat/messages/{user_id}/{session_id}")
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
    
