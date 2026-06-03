# api/frameworks.py
from fastapi import APIRouter, HTTPException

from services.supabase_service import get_supabase_service
from services.goal_frameworks import WeightGoalFrameworks

router = APIRouter()


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
