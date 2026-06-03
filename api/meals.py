# api/meals.py
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime, timedelta
import uuid

from models.meal_schemas import (
    MealAnalysisRequest, 
    MealEntryResponse, 
    MealHistoryResponse
)
from services.supabase_service import get_supabase_service
from services.meal_analysis_service import get_meal_analysis_service
from services.chat_context_manager import get_context_manager
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today, get_user_now

router = APIRouter()

@router.post("/analyze", response_model=MealEntryResponse)
async def analyze_meal(request: MealAnalysisRequest, tz_offset: int = Depends(get_timezone_offset)):
    """Analyze meal using smart parser with CACHING"""
    try:
        print(f"🍽️ Analyzing meal for user {request.user_id}: {request.food_item}")
        print(f"📅 Received meal_date (UTC): {request.meal_date}")
        
        # Parse the UTC datetime - NO CONVERSION, just parse it
        if request.meal_date:
            try:
                # Parse as UTC, keep as UTC
                meal_datetime_utc = datetime.fromisoformat(request.meal_date.replace('Z', '+00:00'))
                # Extract date for daily nutrition (convert to user's date for grouping)
                user_date = (meal_datetime_utc + timedelta(minutes=tz_offset)).date()
                
                print(f"✅ Storing UTC time: {meal_datetime_utc}")
                print(f"📅 User's date for grouping: {user_date}")
            except Exception as e:
                print(f"⚠️ Error parsing meal_date: {e}, using current UTC time")
                meal_datetime_utc = datetime.utcnow()
                user_date = (meal_datetime_utc + timedelta(minutes=tz_offset)).date()
        else:
            # No meal_date provided, use current UTC time
            meal_datetime_utc = datetime.utcnow()
            user_date = (meal_datetime_utc + timedelta(minutes=tz_offset)).date()
            print(f"📅 No meal_date provided, using current UTC: {meal_datetime_utc}")

        # Get services
        supabase_service = get_supabase_service()
        analysis_service = get_meal_analysis_service()
        context_manager = get_context_manager()
        
        # Get user context
        user = await supabase_service.get_user_by_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_context = {
            'weight': user.get('weight', 70),
            'primary_goal': user.get('primary_goal', 'maintain weight'),
            'activity_level': user.get('activity_level', 'moderate'),
            'tdee': user.get('tdee', 2000)
        }
        
        nutrition_data = await analysis_service.analyze_meal_with_cache(
            food_item=request.food_item,
            quantity=request.quantity,
            user_context=user_context,
            user_id=request.user_id, 
            preparation=request.preparation
        )
        
        # Store components if it's a multi-food meal
        if nutrition_data.get('components'):
            print(f"✅ Analyzed {len(nutrition_data['components'])} food items")

        if not nutrition_data.get('data_source'):
            print(f"⚠️ WARNING: No data_source set for meal analysis!")
            nutrition_data['data_source'] = 'unknown'
        
        # Prepare meal entry data - store UTC time as-is
        meal_entry = {
            'id': str(uuid.uuid4()),
            'user_id': request.user_id,
            'food_item': request.food_item,
            'quantity': request.quantity,
            'preparation': request.preparation,
            'meal_type': request.meal_type,
            'calories': nutrition_data['calories'],
            'protein_g': nutrition_data['protein_g'],
            'carbs_g': nutrition_data['carbs_g'],
            'fat_g': nutrition_data['fat_g'],
            'fiber_g': nutrition_data['fiber_g'],
            'sugar_g': nutrition_data['sugar_g'],
            'sodium_mg': nutrition_data['sodium_mg'],
            'nutrition_data': nutrition_data,
            'data_source': nutrition_data.get('data_source'),
            'search_hash': nutrition_data.get('search_hash'),
            'is_cached_source': nutrition_data.get('data_source') == 'cached',
            'confidence_score': nutrition_data.get('confidence_score', 0.8),
            'meal_date': user_date.isoformat(),
            'logged_at': meal_datetime_utc.isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        print(f"💾 Saving meal with logged_at (UTC): {meal_entry['logged_at']}")
        print(f"💾 Meal date for grouping: {meal_entry['meal_date']}")
        
        # Save to database
        saved_meal = await supabase_service.create_meal_entry(meal_entry)
        
        print(f"✅ Meal saved in UTC!")
        
        # Update chat context with the new meal
        await context_manager.update_context_activity(
            request.user_id,
            'meal',
            saved_meal,
            user_date
        )
        
        # Update daily nutrition
        await update_daily_nutrition(
            supabase_service, 
            request.user_id, 
            user_date.isoformat(),
            nutrition_data,
            tz_offset
        )
        
        # Return response
        return MealEntryResponse(
            id=saved_meal['id'],
            user_id=saved_meal['user_id'],
            food_item=saved_meal['food_item'],
            quantity=saved_meal['quantity'],
            meal_type=saved_meal['meal_type'],
            calories=saved_meal['calories'],
            protein_g=saved_meal['protein_g'],
            carbs_g=saved_meal['carbs_g'],
            fat_g=saved_meal['fat_g'],
            fiber_g=saved_meal['fiber_g'],
            sugar_g=saved_meal['sugar_g'],
            sodium_mg=saved_meal['sodium_mg'],
            nutrition_notes=nutrition_data.get('nutrition_notes'),
            healthiness_score=nutrition_data.get('healthiness_score'),
            suggestions=nutrition_data.get('suggestions'),
            meal_date=saved_meal['meal_date'],
            logged_at=saved_meal['logged_at'],
            data_source=saved_meal.get('data_source', 'ai')
        )
        
    except Exception as e:
        print(f"❌ Error analyzing meal: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/log", response_model=dict)
async def log_meal(meal_entry: dict):
    """Log a meal entry directly (for manual entries)"""
    try:
        supabase_service = get_supabase_service()
        context_manager = get_context_manager()
        
        # Add IDs and timestamps
        meal_entry['id'] = str(uuid.uuid4())
        meal_entry['logged_at'] = datetime.now().isoformat()
        meal_entry['updated_at'] = datetime.now().isoformat()
        
        # Save to database
        created_entry = await supabase_service.create_meal_entry(meal_entry)
        
        # Update chat context
        meal_date = datetime.fromisoformat(meal_entry.get('meal_date', datetime.now().isoformat())).date()
        await context_manager.update_context_activity(
            meal_entry['user_id'],
            'meal',
            created_entry,
            meal_date
        )
        
        # Update daily nutrition
        await update_daily_nutrition(
            supabase_service,
            meal_entry['user_id'],
            meal_date.isoformat(),
            created_entry
        )
        
        return {"success": True, "meal": created_entry}
        
    except Exception as e:
        print(f"❌ Error logging meal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{user_id}/history", response_model=MealHistoryResponse)
async def get_meal_history(user_id: str, limit: int = 20, date_from: Optional[str] = None):
    """Get user's meal history"""
    try:
        supabase_service = get_supabase_service()
        
        # Get meals from database
        meals = await supabase_service.get_user_meals(user_id, limit=limit, date_from=date_from)
        
        meal_responses = [
            MealEntryResponse(
                id=meal['id'],
                user_id=meal['user_id'],
                food_item=meal['food_item'],
                quantity=meal['quantity'],
                meal_type=meal['meal_type'],
                calories=meal['calories'],
                protein_g=meal['protein_g'],
                carbs_g=meal['carbs_g'],
                fat_g=meal['fat_g'],
                fiber_g=meal['fiber_g'],
                sugar_g=meal['sugar_g'],
                sodium_mg=meal['sodium_mg'],
                nutrition_notes=meal.get('nutrition_data', {}).get('nutrition_notes'),
                healthiness_score=meal.get('nutrition_data', {}).get('healthiness_score'),
                suggestions=meal.get('nutrition_data', {}).get('suggestions'),
                meal_date=meal['meal_date'],
                logged_at=meal['logged_at']
            )
            for meal in meals
        ]
        
        return MealHistoryResponse(
            meals=meal_responses,
            total_count=len(meal_responses),
            date_range=date_from
        )
        
    except Exception as e:
        print(f"❌ Error getting meal history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.delete("/{meal_id}")
async def delete_meal(meal_id: str):
    """Delete a meal entry and update context"""
    try:
        print(f"🍽️ Deleting meal: {meal_id}")
        
        supabase_service = get_supabase_service()
        context_manager = get_context_manager()
        
        # Get meal details before deletion
        meal = await supabase_service.get_meal_by_id(meal_id)
        if not meal:
            raise HTTPException(status_code=404, detail="Meal not found")
        
        # Delete from database
        success = await supabase_service.delete_meal(meal_id)
        
        if success:
            # Update context - remove this specific meal
            meal_date = datetime.fromisoformat(meal['meal_date']).date()
            await context_manager.remove_from_context(
                meal['user_id'],
                'meal',
                meal_id,
                meal_date
            )
            
            # Also update daily nutrition totals
            await recalculate_daily_nutrition(
                supabase_service,
                meal['user_id'],
                meal_date.isoformat()
            )
            
            return {"success": True, "message": "Meal deleted successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete meal")
            
    except Exception as e:
        print(f"❌ Error deleting meal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper function to recalculate daily nutrition after deletion
async def recalculate_daily_nutrition(supabase_service, user_id: str, date: str):
    """Recalculate daily nutrition totals after a meal deletion"""
    try:
        # Get all meals for the day
        meals = await supabase_service.get_user_meals_by_date(user_id, date)
        
        # Get existing daily nutrition entry
        existing = await supabase_service.get_daily_nutrition(user_id, date)
        
        if not existing:
            print(f"⚠️ No daily nutrition entry found for {date}, skipping recalculation")
            return
        
        # Calculate new totals
        totals = {
            'calories_consumed': int(sum(m.get('calories', 0) for m in meals)),
            'protein_g': round(sum(m.get('protein_g', 0) for m in meals), 1),
            'carbs_g': round(sum(m.get('carbs_g', 0) for m in meals), 1),
            'fat_g': round(sum(m.get('fat_g', 0) for m in meals), 1),
            'fiber_g': round(sum(m.get('fiber_g', 0) for m in meals), 1),
            'sugar_g': round(sum(m.get('sugar_g', 0) for m in meals), 1),
            'sodium_mg': int(sum(m.get('sodium_mg', 0) for m in meals)),
            'meals_logged': len(meals),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # Update daily nutrition table - use entry_id, not user_id and date
        await supabase_service.update_daily_nutrition(existing['id'], totals)
        print(f"✅ Recalculated daily nutrition for {date}")
        
    except Exception as e:
        print(f"Error recalculating daily nutrition: {e}")

@router.get("/")
async def meals_health_check():
    """Health check for meals API"""
    return {
        "status": "Meals API is healthy",
        "features": ["ai_meal_analysis", "meal_history", "nutrition_tracking"],
        "timestamp": datetime.now()
    }

async def update_daily_nutrition(supabase_service, user_id: str, meal_date: str, nutrition_data: dict, timezone_offset: int = 0):
    """Update daily nutrition summary in daily_nutrition table"""
    try:
        from utils.timezone_utils import get_user_date, get_user_now
        
        # Extract date in user's timezone
        if 'T' in meal_date:
            # It's a datetime string - convert to user's local date
            date_only = str(get_user_date(meal_date, timezone_offset))
        else:
            # Already a date string
            date_only = meal_date
        
        # Get existing daily nutrition
        existing = await supabase_service.get_daily_nutrition(user_id, date_only)
        
        if existing:
            # Update existing entry
            updated_data = {
                'calories_consumed': int(float(existing.get('calories_consumed', 0)) + float(nutrition_data.get('calories', 0))),
                'protein_g': round(float(existing.get('protein_g', 0)) + float(nutrition_data.get('protein_g', 0)), 1),
                'carbs_g': round(float(existing.get('carbs_g', 0)) + float(nutrition_data.get('carbs_g', 0)), 1),
                'fat_g': round(float(existing.get('fat_g', 0)) + float(nutrition_data.get('fat_g', 0)), 1),
                'fiber_g': round(float(existing.get('fiber_g', 0)) + float(nutrition_data.get('fiber_g', 0)), 1),
                'sugar_g': round(float(existing.get('sugar_g', 0)) + float(nutrition_data.get('sugar_g', 0)), 1),
                'sodium_mg': int(float(existing.get('sodium_mg', 0)) + float(nutrition_data.get('sodium_mg', 0))),
                'meals_logged': int(existing.get('meals_logged', 0)) + 1,
                'updated_at': get_user_now(timezone_offset).isoformat()
            }
            await supabase_service.update_daily_nutrition(existing['id'], updated_data)
            print(f"✅ Updated daily nutrition for {user_id} on {date_only}")
        else:
            # Create new entry
            new_data = {
                'user_id': user_id,
                'date': date_only,
                'calories_consumed': int(float(nutrition_data.get('calories', 0))),
                'protein_g': round(float(nutrition_data.get('protein_g', 0)), 1),
                'carbs_g': round(float(nutrition_data.get('carbs_g', 0)), 1),
                'fat_g': round(float(nutrition_data.get('fat_g', 0)), 1),
                'fiber_g': round(float(nutrition_data.get('fiber_g', 0)), 1),
                'sugar_g': round(float(nutrition_data.get('sugar_g', 0)), 1),
                'sodium_mg': int(float(nutrition_data.get('sodium_mg', 0))),
                'meals_logged': 1,
                'calorie_goal': 2000,  # Default or calculate based on user profile
                'created_at': get_user_now(timezone_offset).isoformat(),
                'updated_at': get_user_now(timezone_offset).isoformat()
            }
            await supabase_service.create_daily_nutrition(new_data)
            print(f"✅ Created daily nutrition for {user_id} on {date_only}")
            
    except Exception as e:
        print(f"❌ Error updating daily nutrition: {e}")
        import traceback
        traceback.print_exc()

@router.post("/presets/create")
async def create_meal_preset(preset_data: dict):
    """Create a meal preset from logged meals"""
    try:
        supabase_service = get_supabase_service()
        
        preset = {
            'id': str(uuid.uuid4()),
            'user_id': preset_data['user_id'],
            'preset_name': preset_data['preset_name'],
            'description': preset_data.get('description'),
            'food_items': preset_data['food_items'],  # Array of items
            'meal_type': preset_data.get('meal_type'),
            'total_calories': preset_data['total_calories'],
            'total_protein_g': preset_data['total_protein_g'],
            'total_carbs_g': preset_data['total_carbs_g'],
            'total_fat_g': preset_data['total_fat_g'],
            'total_fiber_g': preset_data.get('total_fiber_g', 0),
            'total_sugar_g': preset_data.get('total_sugar_g', 0),
            'total_sodium_mg': preset_data.get('total_sodium_mg', 0),
            'is_favorite': preset_data.get('is_favorite', False),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        created = await supabase_service.create_meal_preset(preset)
        return {"success": True, "preset": created}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/presets/{user_id}")
async def get_meal_presets(user_id: str):
    """Get all meal presets for a user"""
    try:
        supabase_service = get_supabase_service()
        presets = await supabase_service.get_user_meal_presets(user_id)
        return {"success": True, "presets": presets}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/presets/{preset_id}/use")
async def use_meal_preset(preset_id: str, data: dict, tz_offset: int = Depends(get_timezone_offset)):
    """Log meals from a preset"""
    try:
        print(f"🍽️ Using preset: {preset_id}")
        print(f"📅 Received data: {data}")
        print(f"🌍 Timezone offset: {tz_offset} minutes")
        
        supabase_service = get_supabase_service()
        
        # Get the preset
        response = supabase_service.client.table('meal_presets')\
            .select('*')\
            .eq('id', preset_id)\
            .execute()
        
        if not response.data:
            print(f"❌ Preset not found: {preset_id}")
            raise HTTPException(status_code=404, detail="Preset not found")
        
        preset = response.data[0]
        print(f"✅ Found preset: {preset.get('preset_name')}")
        
        # Parse the UTC datetime - keep as UTC
        meal_datetime_utc = datetime.utcnow()  
        
        if data.get('meal_date'):
            try:
                # Parse as UTC, keep as UTC
                meal_date_str = data['meal_date'].replace('Z', '+00:00')
                meal_datetime_utc = datetime.fromisoformat(meal_date_str)
                # Remove timezone info to make it naive
                if meal_datetime_utc.tzinfo is not None:
                    meal_datetime_utc = meal_datetime_utc.replace(tzinfo=None)
                print(f"✅ Parsed meal_date: {meal_datetime_utc}")
            except Exception as e:
                print(f"⚠️ Error parsing meal_date: {e}, using current UTC time")
        
        # Calculate user's date for grouping
        user_date = (meal_datetime_utc + timedelta(minutes=tz_offset)).date()
        print(f"📅 User's date for grouping: {user_date}")
        
        # Create meal entry from preset
        meal_entry = {
            'id': str(uuid.uuid4()),
            'user_id': preset['user_id'],
            'food_item': preset.get('food_items', preset.get('preset_name', 'Preset Meal')),
            'quantity': '1 serving',
            'meal_type': data.get('meal_type', preset.get('meal_type', 'snack')),
            'calories': float(preset.get('total_calories', 0)),
            'protein_g': float(preset.get('total_protein_g', 0)),
            'carbs_g': float(preset.get('total_carbs_g', 0)),
            'fat_g': float(preset.get('total_fat_g', 0)),
            'fiber_g': float(preset.get('total_fiber_g', 0)),
            'sugar_g': float(preset.get('total_sugar_g', 0)),
            'sodium_mg': float(preset.get('total_sodium_mg', 0)),
            'nutrition_data': {
                'from_preset': True,
                'preset_id': preset_id,
                'food_items': preset.get('food_items', preset.get('preset_name', ''))
            },
            'data_source': 'preset',
            'meal_date': user_date.isoformat(),
            'logged_at': meal_datetime_utc.isoformat(), 
            'updated_at': datetime.utcnow().isoformat() 
        }
        
        print(f"💾 Saving meal entry: {meal_entry['food_item']}")
        print(f"💾 logged_at (UTC): {meal_entry['logged_at']}")
        
        # Save meal
        saved = await supabase_service.create_meal_entry(meal_entry)
        print(f"✅ Meal saved with ID: {saved.get('id')}")
        
        # Update preset usage (non-critical)
        try:
            await supabase_service.update_preset_usage(preset_id)
            print(f"✅ Updated preset usage count")
        except Exception as e:
            print(f"⚠️ Failed to update preset usage: {e}")

        # Update context (non-critical)
        try:
            context_manager = get_context_manager()
            await context_manager.update_context_activity(
                user_id=preset['user_id'],
                activity_type='meal',
                data=saved,
                target_date=user_date
            )
            print(f"✅ Updated context")
        except Exception as e:
            print(f"⚠️ Failed to update context: {e}")

        return {"success": True, "meal": saved}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error using preset: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to use preset: {str(e)}")

@router.get("/suggestions/{user_id}")
async def get_meal_suggestions(user_id: str):
    """Get meal suggestions from history and presets"""
    try:
        supabase_service = get_supabase_service()
        
        # Get recent unique meals (15 instead of default 10)
        recent_meals = await supabase_service.get_recent_unique_meals(user_id, limit=15)
        
        # Get top presets
        presets = await supabase_service.get_user_meal_presets(user_id)
        top_presets = presets[:5] if presets else []
        
        return {
            "success": True,
            "recent_meals": recent_meals,
            "presets": top_presets
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.delete("/presets/{preset_id}")
async def delete_meal_preset(preset_id: str):
    """Delete a meal preset"""
    try:
        supabase_service = get_supabase_service()
        
        # Get the preset first to verify it exists
        response = supabase_service.client.table('meal_presets')\
            .select('*')\
            .eq('id', preset_id)\
            .execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Preset not found")
        
        # Delete the preset
        delete_response = supabase_service.client.table('meal_presets')\
            .delete()\
            .eq('id', preset_id)\
            .execute()
        
        return {"success": True, "message": "Preset deleted successfully"}
        
    except Exception as e:
        print(f"❌ Error deleting preset: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def calculate_calorie_goal(user_profile: dict) -> int:
    """Calculate daily calorie goal based on user's TDEE and weight goal"""
    
    tdee = user_profile.get('tdee', 2000)
    weight_goal = user_profile.get('weight_goal', 'maintain_weight').lower()
    
    # Normalize the goal (handle different formats)
    if 'lose' in weight_goal:
        weight_goal = 'lose_weight'
    elif 'gain' in weight_goal:
        weight_goal = 'gain_weight'
    else:
        weight_goal = 'maintain_weight'
    
    # Calculate based on goal
    if weight_goal == 'lose_weight':
        # Moderate deficit: 15-20% below TDEE
        calorie_goal = int(tdee * 0.82)  # 18% deficit
        
    elif weight_goal == 'gain_weight':
        # Moderate surplus: 10-15% above TDEE  
        calorie_goal = int(tdee * 1.12)  # 12% surplus
        
    else:  # maintain_weight
        # Maintenance: equal to TDEE
        calorie_goal = int(tdee)
    
    # Safety bounds (never go too extreme)
    min_calories = 1200 if user_profile.get('gender', '').lower() == 'female' else 1500
    max_calories = min(4000, int(tdee * 1.5))
    
    return max(min_calories, min(calorie_goal, max_calories))

@router.get("/energy-balance/{user_id}")
async def get_energy_balance(
    user_id: str, 
    date: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Get energy balance for a user on a specific date.
    Returns calories consumed, burned, net calories, and remaining.
    """
    try:
        from utils.timezone_utils import get_user_today
        
        supabase_service = get_supabase_service()
        
        # Get target date
        if date:
            target_date = datetime.strptime(date, '%Y-%m-%d').date()
        else:
            target_date = get_user_today(tz_offset)
        
        # Get user profile for TDEE
        user = await supabase_service.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        tdee = user.get('tdee', 2000)
        primary_goal = user.get('primary_goal', 'maintain_weight')
        
        # Calculate calorie goal based on user's goal
        calorie_goal = tdee
        if primary_goal in ['lose_weight', 'weight_loss']:
            calorie_goal = tdee - 500
        elif primary_goal in ['gain_weight', 'weight_gain', 'bulk']:
            calorie_goal = tdee + 400
        elif primary_goal in ['gain_muscle', 'muscle_gain', 'recomposition']:
            calorie_goal = tdee + 200
        
        # Get calories consumed
        daily_nutrition = await supabase_service.get_daily_nutrition(user_id, str(target_date))
        calories_consumed = daily_nutrition.get('calories_consumed', 0) if daily_nutrition else 0
        
        # Get calories burned from exercise
        exercise_logs = await supabase_service.get_exercise_logs(
            user_id,
            start_date=str(target_date),
            end_date=str(target_date)
        )
        calories_burned = sum(ex.get('calories_burned', 0) for ex in exercise_logs)
        
        # Calculate net and remaining
        net_calories = calories_consumed - calories_burned
        
        # Adjusted remaining: Goal - Consumed + Burned
        # This means if you exercise, you "earn back" calories
        remaining_calories = calorie_goal - calories_consumed + calories_burned
        
        # Get macros consumed
        protein_consumed = daily_nutrition.get('protein_g', 0) if daily_nutrition else 0
        carbs_consumed = daily_nutrition.get('carbs_g', 0) if daily_nutrition else 0
        fat_consumed = daily_nutrition.get('fat_g', 0) if daily_nutrition else 0
        
        return {
            "success": True,
            "date": str(target_date),
            "energy_balance": {
                "calories_consumed": round(calories_consumed),
                "calories_burned": round(calories_burned),
                "net_calories": round(net_calories),
                "calorie_goal": round(calorie_goal),
                "remaining_calories": round(remaining_calories),
                "tdee": round(tdee),
                "goal_type": primary_goal
            },
            "macros_consumed": {
                "protein_g": round(protein_consumed, 1),
                "carbs_g": round(carbs_consumed, 1),
                "fat_g": round(fat_consumed, 1)
            },
            "exercise_summary": {
                "total_exercises": len(exercise_logs),
                "total_calories_burned": round(calories_burned),
                "exercises": [
                    {
                        "name": ex.get('exercise_name'),
                        "calories": ex.get('calories_burned', 0),
                        "duration": ex.get('duration_minutes', 0)
                    } for ex in exercise_logs
                ]
            }
        }
        
    except Exception as e:
        print(f"❌ Error getting energy balance: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/remaining-macros/{user_id}")
async def get_remaining_macros(
    user_id: str,
    date: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Get remaining macros for the day, adjusted for exercise.
    """
    try:
        from utils.timezone_utils import get_user_today
        
        supabase_service = get_supabase_service()
        
        target_date = datetime.strptime(date, '%Y-%m-%d').date() if date else get_user_today(tz_offset)
        
        # Get user profile
        user = await supabase_service.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Calculate macro goals based on user profile
        tdee = user.get('tdee', 2000)
        primary_goal = user.get('primary_goal', 'maintain_weight')
        weight = user.get('weight', 70)
        activity_level = user.get('activity_level', 'moderately_active')
        
        # Adjust calorie goal
        calorie_adjustment = 0
        if primary_goal in ['lose_weight', 'weight_loss']:
            calorie_adjustment = -500
            macro_percentages = {'protein': 0.35, 'carbs': 0.40, 'fat': 0.25}
        elif primary_goal in ['gain_muscle', 'muscle_gain', 'recomposition']:
            calorie_adjustment = 200 if 'gain' in primary_goal else -200
            macro_percentages = {'protein': 0.40, 'carbs': 0.35, 'fat': 0.25}
        elif primary_goal in ['gain_weight', 'weight_gain', 'bulk']:
            calorie_adjustment = 400
            macro_percentages = {'protein': 0.25, 'carbs': 0.45, 'fat': 0.30}
        else:
            macro_percentages = {'protein': 0.30, 'carbs': 0.40, 'fat': 0.30}
        
        # Adjust for activity level
        if activity_level in ['very_active', 'extremely_active']:
            macro_percentages['carbs'] += 0.05
            macro_percentages['fat'] -= 0.05
        
        calorie_goal = tdee + calorie_adjustment
        
        # Calculate macro goals in grams
        macro_goals = {
            'protein_g': (calorie_goal * macro_percentages['protein']) / 4,
            'carbs_g': (calorie_goal * macro_percentages['carbs']) / 4,
            'fat_g': (calorie_goal * macro_percentages['fat']) / 9
        }
        
        # Ensure minimum protein (1g per kg body weight for most, higher for muscle goals)
        min_protein = weight * (2.0 if 'muscle' in primary_goal.lower() else 1.0)
        macro_goals['protein_g'] = max(macro_goals['protein_g'], min_protein)
        
        # Get calories burned from exercise
        exercise_logs = await supabase_service.get_exercise_logs(
            user_id,
            start_date=str(target_date),
            end_date=str(target_date)
        )
        calories_burned = sum(ex.get('calories_burned', 0) for ex in exercise_logs)
        
        # Adjust goals based on exercise (add back proportionally)
        exercise_adjustment_ratio = 1 + (calories_burned / calorie_goal) if calorie_goal > 0 else 1
        
        adjusted_macro_goals = {
            'protein_g': round(macro_goals['protein_g'] * exercise_adjustment_ratio, 1),
            'carbs_g': round(macro_goals['carbs_g'] * exercise_adjustment_ratio, 1),
            'fat_g': round(macro_goals['fat_g'] * exercise_adjustment_ratio, 1),
            'calories': round(calorie_goal + calories_burned)
        }
        
        # Get consumed macros
        daily_nutrition = await supabase_service.get_daily_nutrition(user_id, str(target_date))
        
        consumed = {
            'protein_g': daily_nutrition.get('protein_g', 0) if daily_nutrition else 0,
            'carbs_g': daily_nutrition.get('carbs_g', 0) if daily_nutrition else 0,
            'fat_g': daily_nutrition.get('fat_g', 0) if daily_nutrition else 0,
            'calories': daily_nutrition.get('calories_consumed', 0) if daily_nutrition else 0
        }
        
        # Calculate remaining
        remaining = {
            'protein_g': round(adjusted_macro_goals['protein_g'] - consumed['protein_g'], 1),
            'carbs_g': round(adjusted_macro_goals['carbs_g'] - consumed['carbs_g'], 1),
            'fat_g': round(adjusted_macro_goals['fat_g'] - consumed['fat_g'], 1),
            'calories': round(adjusted_macro_goals['calories'] - consumed['calories'])
        }
        
        return {
            "success": True,
            "date": str(target_date),
            "goals": adjusted_macro_goals,
            "consumed": consumed,
            "remaining": remaining,
            "exercise_calories_burned": round(calories_burned),
            "base_calorie_goal": round(calorie_goal),
            "adjusted_calorie_goal": round(calorie_goal + calories_burned)
        }
        
    except Exception as e:
        print(f"❌ Error getting remaining macros: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/trends/{user_id}")
async def get_nutrition_trends(
    user_id: str,
    days: int = 30,
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Get nutrition trends for the specified number of days.
    Returns daily data for charting.
    """
    try:
        supabase_service = get_supabase_service()
        
        # Get user for goals
        user = await supabase_service.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        tdee = user.get('tdee', 2000)
        
        # Calculate date range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Get all daily nutrition entries in range
        response = supabase_service.client.table('daily_nutrition')\
            .select('*')\
            .eq('user_id', user_id)\
            .gte('date', str(start_date))\
            .lte('date', str(end_date))\
            .order('date', desc=False)\
            .execute()
        
        daily_data = response.data or []
        
        # Get exercise data for the same period
        exercise_response = supabase_service.client.table('exercise_logs')\
            .select('exercise_date, calories_burned')\
            .eq('user_id', user_id)\
            .gte('exercise_date', str(start_date))\
            .lte('exercise_date', str(end_date))\
            .execute()
        
        # Aggregate exercise by date
        exercise_by_date = {}
        for ex in (exercise_response.data or []):
            date_key = ex['exercise_date'][:10]  # Get just the date part
            exercise_by_date[date_key] = exercise_by_date.get(date_key, 0) + ex.get('calories_burned', 0)
        
        # Build trend data
        trend_data = []
        nutrition_by_date = {d['date']: d for d in daily_data}
        
        current_date = start_date
        while current_date <= end_date:
            date_str = str(current_date)
            nutrition = nutrition_by_date.get(date_str, {})
            
            trend_data.append({
                'date': date_str,
                'calories_consumed': nutrition.get('calories_consumed', 0),
                'calories_burned': exercise_by_date.get(date_str, 0),
                'net_calories': nutrition.get('calories_consumed', 0) - exercise_by_date.get(date_str, 0),
                'protein_g': nutrition.get('protein_g', 0),
                'carbs_g': nutrition.get('carbs_g', 0),
                'fat_g': nutrition.get('fat_g', 0),
                'fiber_g': nutrition.get('fiber_g', 0),
                'meals_logged': nutrition.get('meals_logged', 0)
            })
            
            current_date += timedelta(days=1)
        
        # Calculate averages
        days_with_data = [d for d in trend_data if d['meals_logged'] > 0]
        num_days = len(days_with_data) or 1
        
        averages = {
            'avg_calories': sum(d['calories_consumed'] for d in days_with_data) / num_days,
            'avg_protein': sum(d['protein_g'] for d in days_with_data) / num_days,
            'avg_carbs': sum(d['carbs_g'] for d in days_with_data) / num_days,
            'avg_fat': sum(d['fat_g'] for d in days_with_data) / num_days,
            'avg_fiber': sum(d['fiber_g'] for d in days_with_data) / num_days,
            'avg_net_calories': sum(d['net_calories'] for d in days_with_data) / num_days,
            'days_logged': num_days,
            'logging_streak': _calculate_streak(trend_data),
            'calorie_goal': tdee
        }
        
        # Calculate weekly summaries
        weekly_summaries = _calculate_weekly_summaries(trend_data)
        
        return {
            "success": True,
            "user_id": user_id,
            "period_days": days,
            "trend_data": trend_data,
            "averages": averages,
            "weekly_summaries": weekly_summaries
        }
        
    except Exception as e:
        print(f"❌ Error getting nutrition trends: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _calculate_streak(trend_data: list) -> int:
    """Calculate current logging streak"""
    streak = 0
    # Iterate from most recent
    for day in reversed(trend_data):
        if day['meals_logged'] > 0:
            streak += 1
        else:
            break
    return streak


def _calculate_weekly_summaries(trend_data: list) -> list:
    """Group trend data into weekly summaries"""
    from collections import defaultdict
    
    weeks = defaultdict(list)
    for day in trend_data:
        date = datetime.strptime(day['date'], '%Y-%m-%d')
        week_start = date - timedelta(days=date.weekday())
        week_key = week_start.strftime('%Y-%m-%d')
        weeks[week_key].append(day)
    
    summaries = []
    for week_start, days in sorted(weeks.items()):
        days_with_data = [d for d in days if d['meals_logged'] > 0]
        num_days = len(days_with_data) or 1
        
        summaries.append({
            'week_start': week_start,
            'days_logged': len(days_with_data),
            'avg_calories': round(sum(d['calories_consumed'] for d in days_with_data) / num_days),
            'avg_protein': round(sum(d['protein_g'] for d in days_with_data) / num_days, 1),
            'total_calories_burned': sum(d['calories_burned'] for d in days),
        })
    
    return summaries


@router.get("/macro-breakdown/{user_id}")
async def get_macro_breakdown(
    user_id: str,
    days: int = 7,
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Get detailed macro breakdown for pie charts and analysis.
    """
    try:
        supabase_service = get_supabase_service()
        
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Get meals in range
        response = supabase_service.client.table('meal_entries')\
            .select('*')\
            .eq('user_id', user_id)\
            .gte('meal_date', str(start_date))\
            .lte('meal_date', str(end_date))\
            .execute()
        
        meals = response.data or []
        
        # Aggregate by meal type
        meal_type_breakdown = {}
        for meal in meals:
            meal_type = meal.get('meal_type', 'snack')
            if meal_type not in meal_type_breakdown:
                meal_type_breakdown[meal_type] = {
                    'calories': 0,
                    'protein_g': 0,
                    'carbs_g': 0,
                    'fat_g': 0,
                    'count': 0
                }
            
            meal_type_breakdown[meal_type]['calories'] += meal.get('calories', 0)
            meal_type_breakdown[meal_type]['protein_g'] += meal.get('protein_g', 0)
            meal_type_breakdown[meal_type]['carbs_g'] += meal.get('carbs_g', 0)
            meal_type_breakdown[meal_type]['fat_g'] += meal.get('fat_g', 0)
            meal_type_breakdown[meal_type]['count'] += 1
        
        # Calculate total macros
        total_protein = sum(m.get('protein_g', 0) for m in meals)
        total_carbs = sum(m.get('carbs_g', 0) for m in meals)
        total_fat = sum(m.get('fat_g', 0) for m in meals)
        total_calories = sum(m.get('calories', 0) for m in meals)
        
        # Calculate percentages
        total_macro_calories = (total_protein * 4) + (total_carbs * 4) + (total_fat * 9)
        
        macro_percentages = {
            'protein': round((total_protein * 4 / total_macro_calories * 100) if total_macro_calories > 0 else 0, 1),
            'carbs': round((total_carbs * 4 / total_macro_calories * 100) if total_macro_calories > 0 else 0, 1),
            'fat': round((total_fat * 9 / total_macro_calories * 100) if total_macro_calories > 0 else 0, 1)
        }
        
        return {
            "success": True,
            "period_days": days,
            "totals": {
                "calories": round(total_calories),
                "protein_g": round(total_protein, 1),
                "carbs_g": round(total_carbs, 1),
                "fat_g": round(total_fat, 1),
                "meals_count": len(meals)
            },
            "macro_percentages": macro_percentages,
            "meal_type_breakdown": meal_type_breakdown,
            "daily_average": {
                "calories": round(total_calories / days),
                "protein_g": round(total_protein / days, 1),
                "carbs_g": round(total_carbs / days, 1),
                "fat_g": round(total_fat / days, 1)
            }
        }
        
    except Exception as e:
        print(f"❌ Error getting macro breakdown: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/micronutrients/{user_id}")
async def get_micronutrient_summary(
    user_id: str,
    date: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Get micronutrient summary with % of daily values.
    """
    try:
        from utils.timezone_utils import get_user_today
        
        supabase_service = get_supabase_service()
        
        target_date = datetime.strptime(date, '%Y-%m-%d').date() if date else get_user_today(tz_offset)
        
        # Get meals for the day
        response = supabase_service.client.table('meal_entries')\
            .select('*')\
            .eq('user_id', user_id)\
            .gte('meal_date', f"{target_date}T00:00:00")\
            .lte('meal_date', f"{target_date}T23:59:59")\
            .execute()
        
        meals = response.data or []
        
        # Aggregate micronutrients
        totals = {
            'vitamin_a_mcg': 0,
            'vitamin_c_mg': 0,
            'vitamin_d_mcg': 0,
            'vitamin_e_mg': 0,
            'vitamin_k_mcg': 0,
            'vitamin_b12_mcg': 0,
            'calcium_mg': 0,
            'iron_mg': 0,
            'potassium_mg': 0,
            'magnesium_mg': 0,
            'zinc_mg': 0,
            'cholesterol_mg': 0,
            'saturated_fat_g': 0,
            'fiber_g': 0
        }
        
        for meal in meals:
            for key in totals:
                totals[key] += meal.get(key, 0) or 0
        
        # Daily values for % calculation
        daily_values = {
            'vitamin_a_mcg': 900,
            'vitamin_c_mg': 90,
            'vitamin_d_mcg': 20,
            'vitamin_e_mg': 15,
            'vitamin_k_mcg': 120,
            'vitamin_b12_mcg': 2.4,
            'calcium_mg': 1300,
            'iron_mg': 18,
            'potassium_mg': 4700,
            'magnesium_mg': 420,
            'zinc_mg': 11,
            'cholesterol_mg': 300,
            'saturated_fat_g': 20,
            'fiber_g': 28
        }
        
        # Calculate percentages
        percentages = {}
        for key, value in totals.items():
            dv = daily_values.get(key, 100)
            percentages[key] = round((value / dv) * 100, 1) if dv > 0 else 0
        
        # Identify highlights (good and concerning)
        highlights = {
            'excellent': [],  # >80% DV
            'good': [],       # 50-80% DV
            'low': [],        # <20% DV
            'high': []        # >100% DV for cholesterol/sat fat
        }
        
        for key, pct in percentages.items():
            nutrient_name = key.replace('_', ' ').replace(' mg', '').replace(' mcg', '').replace(' g', '').title()
            
            if key in ['cholesterol_mg', 'saturated_fat_g']:
                if pct > 100:
                    highlights['high'].append(f"{nutrient_name}: {pct}% DV")
            else:
                if pct >= 80:
                    highlights['excellent'].append(f"{nutrient_name}: {pct}% DV")
                elif pct >= 50:
                    highlights['good'].append(f"{nutrient_name}: {pct}% DV")
                elif pct < 20:
                    highlights['low'].append(f"{nutrient_name}: {pct}% DV")
        
        return {
            "success": True,
            "date": str(target_date),
            "totals": totals,
            "daily_values": daily_values,
            "percentages": percentages,
            "highlights": highlights,
            "meals_count": len(meals)
        }
        
    except Exception as e:
        print(f"❌ Error getting micronutrient summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{user_id}")
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

@router.put("/{meal_id}")
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