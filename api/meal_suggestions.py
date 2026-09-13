# api/meal_suggestions.py

from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from services.supabase_service import get_supabase_service
from services.openai_service import get_openai_service
from utils.timezone_utils import get_timezone_offset, get_user_today
from utils.errors import internal_error

router = APIRouter(prefix="/suggestions", tags=["meal_suggestions"])


class MealSuggestionRequest(BaseModel):
    user_id: str
    meal_type: Optional[str] = None  # breakfast, lunch, dinner, snack
    consider_exercise: bool = True
    num_suggestions: int = 5


@router.post("/meals")
async def get_meal_suggestions(
    request: MealSuggestionRequest,
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Get AI-powered meal suggestions based on:
    - User's remaining macros/calories for the day
    - Dietary preferences and restrictions
    - Recent meals (to add variety)
    - Upcoming/completed workouts
    - User's fitness goals
    """
    try:
        supabase_service = get_supabase_service()
        openai_service = get_openai_service()
        
        # Get user profile
        user = await supabase_service.get_user_by_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        today = get_user_today(tz_offset)
        
        # Get today's nutrition
        daily_nutrition = await supabase_service.get_daily_nutrition(
            request.user_id, str(today)
        )
        
        # Get today's exercise
        exercise_logs = await supabase_service.get_exercise_logs(
            request.user_id,
            start_date=str(today),
            end_date=str(today)
        )
        
        calories_burned = sum(ex.get('calories_burned', 0) for ex in exercise_logs)
        
        # Calculate remaining nutrition
        tdee = user.get('tdee', 2000)
        primary_goal = user.get('primary_goal', 'maintain_weight')
        
        # Adjust calorie goal
        calorie_goal = tdee
        if primary_goal in ['lose_weight', 'weight_loss']:
            calorie_goal = tdee - 500
        elif primary_goal in ['gain_weight', 'weight_gain']:
            calorie_goal = tdee + 400
        elif primary_goal in ['gain_muscle', 'muscle_gain']:
            calorie_goal = tdee + 200
        
        # Add exercise calories back
        if request.consider_exercise:
            calorie_goal += calories_burned
        
        # Calculate consumed
        calories_consumed = daily_nutrition.get('calories_consumed', 0) if daily_nutrition else 0
        protein_consumed = daily_nutrition.get('protein_g', 0) if daily_nutrition else 0
        carbs_consumed = daily_nutrition.get('carbs_g', 0) if daily_nutrition else 0
        fat_consumed = daily_nutrition.get('fat_g', 0) if daily_nutrition else 0
        
        remaining_calories = calorie_goal - calories_consumed
        
        # Get recent meals for variety
        recent_meals_response = supabase_service.client.table('meal_entries')\
            .select('food_item')\
            .eq('user_id', request.user_id)\
            .order('logged_at', desc=True)\
            .limit(20)\
            .execute()
        
        recent_foods = [m['food_item'] for m in (recent_meals_response.data or [])]
        
        # Build context for AI
        context = {
            'user_name': user.get('name', 'User'),
            'primary_goal': primary_goal,
            'weight': user.get('weight', 70),
            'dietary_preferences': user.get('dietary_preferences', []),
            'medical_conditions': user.get('medical_conditions', []),
            'remaining_calories': max(remaining_calories, 200),  # Minimum suggestion size
            'remaining_protein': max(0, (calorie_goal * 0.3 / 4) - protein_consumed),
            'remaining_carbs': max(0, (calorie_goal * 0.4 / 4) - carbs_consumed),
            'remaining_fat': max(0, (calorie_goal * 0.3 / 9) - fat_consumed),
            'meal_type': request.meal_type or _suggest_meal_type(),
            'recent_foods': recent_foods[:10],
            'exercised_today': calories_burned > 0,
            'calories_burned': calories_burned
        }
        
        # Generate suggestions with OpenAI
        suggestions = await _generate_meal_suggestions(openai_service, context, request.num_suggestions)
        
        return {
            "success": True,
            "context": {
                "remaining_calories": round(remaining_calories),
                "meal_type": context['meal_type'],
                "exercised_today": context['exercised_today'],
                "dietary_preferences": context['dietary_preferences']
            },
            "suggestions": suggestions
        }
        
    except Exception as e:
        print(f"❌ Error generating meal suggestions: {e}")
        import traceback
        traceback.print_exc()
        raise internal_error(e)


def _suggest_meal_type() -> str:
    """Suggest meal type based on current time"""
    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "breakfast"
    elif 11 <= hour < 15:
        return "lunch"
    elif 15 <= hour < 18:
        return "snack"
    else:
        return "dinner"


async def _generate_meal_suggestions(openai_service, context: dict, num_suggestions: int) -> List[dict]:
    """Generate meal suggestions using OpenAI"""
    
    dietary_notes = ""
    if context['dietary_preferences']:
        dietary_notes = f"Dietary preferences: {', '.join(context['dietary_preferences'])}"
    
    medical_notes = ""
    if context['medical_conditions']:
        medical_notes = f"Health considerations: {', '.join(context['medical_conditions'])}"
    
    exercise_note = ""
    if context['exercised_today']:
        exercise_note = f"The user exercised today and burned {context['calories_burned']} calories. Consider suggesting foods that support recovery (protein-rich, complex carbs)."
    
    recent_foods_note = ""
    if context['recent_foods']:
        recent_foods_note = f"Recent meals (avoid repetition): {', '.join(context['recent_foods'][:5])}"
    
    prompt = f"""
    Generate {num_suggestions} meal suggestions for {context['meal_type']}.
    
    User Context:
    - Goal: {context['primary_goal']}
    - Remaining calories: {context['remaining_calories']} kcal
    - Remaining macros: ~{round(context['remaining_protein'])}g protein, ~{round(context['remaining_carbs'])}g carbs, ~{round(context['remaining_fat'])}g fat
    {dietary_notes}
    {medical_notes}
    {exercise_note}
    {recent_foods_note}
    
    Requirements:
    1. Each suggestion should fit within the remaining calories
    2. Prioritize protein if the user's goal involves muscle or weight loss
    3. Include a mix of quick/easy and more elaborate options
    4. Consider the meal type timing (breakfast should be breakfast-appropriate, etc.)
    5. Provide variety - different cuisines, ingredients, preparation methods
    
    Return ONLY a valid JSON array with this structure:
    [
        {{
            "name": "Meal name",
            "description": "Brief appealing description",
            "estimated_calories": number,
            "estimated_protein_g": number,
            "estimated_carbs_g": number,
            "estimated_fat_g": number,
            "prep_time_minutes": number,
            "difficulty": "easy" | "medium" | "hard",
            "tags": ["tag1", "tag2"],
            "why_suggested": "Brief reason this suits the user"
        }}
    ]
    """
    
    try:
        response = await openai_service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,  # Higher for more variety
            max_tokens=1500
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean JSON if wrapped in markdown
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        
        import json
        suggestions = json.loads(content)
        
        return suggestions
        
    except Exception as e:
        print(f"Error parsing AI suggestions: {e}")
        # Return fallback suggestions
        return [
            {
                "name": "Grilled Chicken Salad",
                "description": "Fresh greens with grilled chicken breast",
                "estimated_calories": 350,
                "estimated_protein_g": 35,
                "estimated_carbs_g": 15,
                "estimated_fat_g": 12,
                "prep_time_minutes": 15,
                "difficulty": "easy",
                "tags": ["high-protein", "low-carb", "quick"],
                "why_suggested": "High protein, fits your remaining calories"
            }
        ]


@router.get("/quick/{user_id}")
async def get_quick_suggestions(
    user_id: str,
    meal_type: Optional[str] = None,
    tz_offset: int = Depends(get_timezone_offset)
):
    """
    Get quick suggestions based on user's past meals.
    No AI call - just smart filtering of previous meals.
    """
    try:
        supabase_service = get_supabase_service()
        
        today = get_user_today(tz_offset)
        
        # Get user's remaining calories
        user = await supabase_service.get_user_by_id(user_id)
        daily_nutrition = await supabase_service.get_daily_nutrition(user_id, str(today))
        
        tdee = user.get('tdee', 2000) if user else 2000
        calories_consumed = daily_nutrition.get('calories_consumed', 0) if daily_nutrition else 0
        remaining_calories = tdee - calories_consumed
        
        # Get user's previous meals that fit the criteria
        meal_type_filter = meal_type or _suggest_meal_type()
        
        # Get frequent meals
        response = supabase_service.client.table('meal_entries')\
            .select('food_item, calories, protein_g, carbs_g, fat_g, meal_type')\
            .eq('user_id', user_id)\
            .eq('meal_type', meal_type_filter)\
            .lte('calories', remaining_calories + 100)\
            .order('logged_at', desc=True)\
            .limit(50)\
            .execute()
        
        meals = response.data or []
        
        # Deduplicate and count frequency
        meal_frequency = {}
        for meal in meals:
            key = meal['food_item'].lower().strip()
            if key not in meal_frequency:
                meal_frequency[key] = {
                    'food_item': meal['food_item'],
                    'calories': meal['calories'],
                    'protein_g': meal['protein_g'],
                    'carbs_g': meal['carbs_g'],
                    'fat_g': meal['fat_g'],
                    'meal_type': meal['meal_type'],
                    'frequency': 0
                }
            meal_frequency[key]['frequency'] += 1
        
        # Sort by frequency and return top suggestions
        sorted_meals = sorted(
            meal_frequency.values(),
            key=lambda x: x['frequency'],
            reverse=True
        )[:10]
        
        return {
            "success": True,
            "meal_type": meal_type_filter,
            "remaining_calories": round(remaining_calories),
            "suggestions": sorted_meals
        }
        
    except Exception as e:
        print(f"❌ Error getting quick suggestions: {e}")
        raise internal_error(e)