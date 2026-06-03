# api/daily_summary.py
from fastapi import APIRouter, HTTPException, Depends

from services.supabase_service import get_supabase_service
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today

router = APIRouter()


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
