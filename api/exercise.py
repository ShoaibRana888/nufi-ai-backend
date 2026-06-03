# api/exercise.py
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime, timedelta
import uuid

from services.supabase_service import get_supabase_service
from services.chat_context_manager import get_context_manager
from utils.timezone_utils import get_timezone_offset, get_user_date, get_user_today, get_user_now

router = APIRouter()


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
