# services/chat_context_manager.py
from typing import Dict, Any, Optional, List
from datetime import datetime, date, timedelta
import json
from services.supabase_service import get_supabase_service
from services.guardrails import compute_body_state
from services.health_trends import weight_status

class ChatContextManager:
    def __init__(self):
        self.supabase_service = get_supabase_service()
    
    async def get_or_create_context(self, user_id: str, target_date: date) -> Dict[str, Any]:
        """Get existing context or create a new one for the specified date.

        The date is required. It used to default to the server clock, and
        the coach read its context through that default -- a different day
        from the one the trackers write for any user not on UTC. Callers
        know whose day they mean; say so.

        The stored row is served as it is. The per-read cleanup that once
        ran here (`deduplicate_context`, for rows the old incremental merge
        left with repeated meals and drifted flat totals) is gone, and the
        rows it existed for were repaired first by running it once at rest
        (2026-09-14). On the rebuild-failed fallback this read serves a row
        without rewriting it, so a legacy row here would have been served
        as it was -- which is why the rows had to be fixed before the code
        went. ADR-0010.
        """
        try:
            # Try to get existing context
            response = self.supabase_service.client.table('chat_contexts')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            
            if response.data:
                context_record = response.data[0]
                return {
                    'context': context_record['context_data'],
                    'version': context_record['version'],
                    'last_updated': context_record['last_updated']
                }

            # Create new context if none exists
            return await self.create_initial_context(user_id, target_date)
            
        except Exception as e:
            print(f"Error getting/creating context: {e}")
            # The cached read failed; build the day from the source tables.
            # This used to call `generate_fresh_context`, a second rebuilder
            # with a poorer shape (no body_state, no meal ids). One rebuilder.
            return await self.rebuild_context(user_id, target_date)
    
    async def create_initial_context(self, user_id: str, target_date: date) -> Dict[str, Any]:
        """Create initial context for a new day"""
        try:
            # Get user profile
            user = await self.supabase_service.get_user_by_id(user_id)
            if not user:
                raise Exception("User not found")
            
            # Initialize empty context structure
            initial_context = {
                'user_profile': {
                    'name': user.get('name', ''),
                    'age': user.get('age'),
                    'weight': user.get('weight'),
                    'height': user.get('height'),
                    'primary_goal': user.get('primary_goal'),
                    'weight_goal': user.get('weight_goal'),
                    'activity_level': user.get('activity_level'),
                    'tdee': user.get('tdee'),
                    'target_weight': user.get('target_weight'),
                    'dietary_preferences': user.get('dietary_preferences', []),
                    'medical_conditions': user.get('medical_conditions', []),
                },
                'today_progress': {
                    'date': str(target_date),
                    'meals': [],
                    'meals_logged': 0,
                    'exercises': [],
                    'exercises_done': 0,
                    'exercise_minutes': 0,
                    'water_glasses': 0,
                    'steps': 0,
                    'weight': None,
                    'sleep_hours': None,
                    'supplements_taken': [],
                    'totals': {
                        'calories': 0,
                        'protein': 0,
                        'carbs': 0,
                        'fat': 0,
                        'fiber': 0
                    }
                },
                'context_metadata': {
                    'created_at': datetime.now().isoformat(),
                    'version': 1,
                    'day_of_week': target_date.strftime('%A'),
                }
            }
            
            # Save to database
            response = self.supabase_service.client.table('chat_contexts')\
                .upsert({
                    'user_id': user_id,
                    'date': str(target_date),
                    'context_data': initial_context,
                    'version': 1
                })\
                .execute()
            
            return {
                'context': initial_context,
                'version': 1,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Error creating initial context: {e}")
            raise
    
    async def rebuild_context(self, user_id: str, target_date: date) -> Dict[str, Any]:
        """Rebuild context from scratch with all daily activities"""
        try:
            print(f"🔄 Rebuilding context for {user_id} on {target_date}")
            
            # Get user profile
            user = await self.supabase_service.get_user(user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Fetch ALL activities for the target date
            activities = await self._fetch_all_daily_activities(user_id, target_date)
            
            # Process meals
            meals = activities.get('meals', [])
            total_calories = sum(m.get('calories', 0) for m in meals)
            total_protein = sum(m.get('protein_g', 0) for m in meals)
            total_carbs = sum(m.get('carbs_g', 0) for m in meals)
            total_fat = sum(m.get('fat_g', 0) for m in meals)
            total_fiber = sum(m.get('fiber_g', 0) for m in meals)
            total_sugar = sum(m.get('sugar_g', 0) for m in meals)
            total_sodium = sum(m.get('sodium_mg', 0) for m in meals)
            
            # Format meals for context
            formatted_meals = []
            for meal in meals:
                formatted_meals.append({
                    'id': meal.get('id'),
                    'food_item': meal.get('food_item'),
                    'meal_type': meal.get('meal_type'),
                    'calories': meal.get('calories', 0),
                    'protein_g': meal.get('protein_g', 0),
                    'carbs_g': meal.get('carbs_g', 0),
                    'fat_g': meal.get('fat_g', 0),
                    'fiber_g': meal.get('fiber_g', 0),
                    'sugar_g': meal.get('sugar_g', 0),
                    'sodium_mg': meal.get('sodium_mg', 0),
                    'logged_at': meal.get('created_at', datetime.now().isoformat())
                })
            
            # Process exercises
            exercises = activities.get('exercise', [])
            total_exercise_minutes = sum(
                ex.get('duration_minutes', 0) if ex.get('duration_minutes') else 0 
                for ex in exercises
            )
            
            formatted_exercises = []
            for ex in exercises:
                formatted_exercises.append({
                    'id': ex.get('id'),
                    'exercise_name': ex.get('exercise_name'),
                    'exercise_type': ex.get('exercise_type'),
                    'muscle_group': ex.get('muscle_group'),
                    'duration_minutes': ex.get('duration_minutes', 0),
                    'calories_burned': ex.get('calories_burned', 0),
                    'sets': ex.get('sets'),
                    'reps': ex.get('reps'),
                    'weight_kg': ex.get('weight_kg'),
                    'logged_at': ex.get('created_at', datetime.now().isoformat())
                })
            
            # Get other activities - YES, this will work!
            water = activities.get('water', {})
            steps = activities.get('steps', {})
            weight = activities.get('weight', {})
            sleep = activities.get('sleep', {})
            supplements = activities.get('supplements', {})
            
            # Build the complete context
            context = {
                'user_profile': {
                    'id': user_id,
                    'name': user.get('name', ''),
                    'age': user.get('age'),
                    'weight': user.get('weight'),
                    'height': user.get('height'),
                    'primary_goal': user.get('primary_goal'),
                    'weight_goal': user.get('weight_goal'),
                    'target_weight': user.get('target_weight'),
                    'activity_level': user.get('activity_level'),
                    'tdee': user.get('tdee'),
                    'gender': user.get('gender'),
                    'preferred_workouts': user.get('preferred_workouts', []),
                    'dietary_preferences': user.get('dietary_preferences', []),
                },
                'today_progress': {
                    'date': str(target_date),
                    'meals': formatted_meals,
                    'meals_logged': len(formatted_meals),
                    'total_calories': total_calories,
                    'total_protein': total_protein,
                    'total_carbs': total_carbs,
                    'total_fat': total_fat,
                    'total_fiber': total_fiber,
                    'total_sugar': total_sugar,
                    'total_sodium': total_sodium,
                    'exercises': formatted_exercises,
                    'exercises_done': len(formatted_exercises),
                    'exercise_minutes': total_exercise_minutes,
                    'water_glasses': water.get('glasses_consumed', 0),
                    'water_ml': water.get('total_ml', 0),
                    'steps': steps.get('steps', 0),
                    'weight': weight.get('weight') if weight else None,
                    'sleep_hours': sleep.get('total_hours', 0) if sleep else None,
                    'supplements_taken': self._get_supplements_taken(supplements),
                    'totals': {
                        'calories': total_calories,
                        'protein': total_protein,
                        'carbs': total_carbs,
                        'fat': total_fat,
                        'fiber': total_fiber,
                        'sugar': total_sugar,
                        'sodium': total_sodium
                    }
                },
                'goals_progress': {
                    'daily_calorie_goal': user.get('tdee', 2000),
                    'water_goal_glasses': user.get('water_intake_glasses', 8),
                    'step_goal': user.get('daily_step_goal', 10000),
                    'weight_progress': {
                        'current': user.get('weight'),
                        'target': user.get('target_weight'),
                        'status': weight_status(
                            user.get('weight'),
                            user.get('target_weight')
                        )
                    }
                },
                'context_metadata': {
                    'last_updated': datetime.now().isoformat(),
                    'version': 1,
                    'rebuild_reason': 'manual_rebuild'
                }
            }

            # Layer 1: distil raw activities into a decision-ready body_state
            # (cycle phase, sleep, calorie balance, what's already done today)
            # so the chat guardrails can read it without re-querying source tables.
            try:
                context['body_state'] = compute_body_state(
                    user,
                    activities,
                    {
                        'calories': total_calories,
                        'protein': total_protein,
                        'carbs': total_carbs,
                        'fat': total_fat,
                    },
                    target_date,
                )
            except Exception as e:
                print(f"⚠️ Could not compute body_state guardrails: {e}")
                context['body_state'] = {}

            # Save the rebuilt context
            await self._save_context(user_id, target_date, context, 1)
            
            print(f"✅ Context rebuilt with {len(formatted_meals)} meals, "
                  f"{len(formatted_exercises)} exercises, and other activities")
            
            return {
                'context': context,
                'version': 1,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Error rebuilding context: {e}")
            import traceback
            traceback.print_exc()
            raise

    async def _fetch_all_daily_activities(self, user_id: str, target_date: date) -> dict:
        """The user's shared activities for a date.

        Delegates to the store's single read (candidate #1). This used to be
        seven raw table queries here, including `.eq()` on exercise_date and
        sleep_entries.date where the store uses a half-open range -- the store
        form is correct whether the column holds a date or a timestamp, and
        exercise_date is written both ways.

        Sits in the rebuild-before-every-reply path, so a per-section failure
        must never fail the whole read; the store keeps sections independent
        and reports failures under `_read_errors`.
        """
        return await self.supabase_service.get_shared_activities_for_date(
            user_id, target_date
        )
    
    def _get_supplements_taken(self, supplements_data: Any) -> List[str]:
        """Extract list of supplements taken from supplements data"""
        if not supplements_data:
            return []
        
        taken = []
        if isinstance(supplements_data, dict):
            # If it's the status format from get_supplement_status_by_date
            for supp_name, supp_data in supplements_data.items():
                if isinstance(supp_data, dict) and supp_data.get('taken'):
                    taken.append(supp_name)
        elif isinstance(supplements_data, list):
            # If it's a list of supplement logs
            for supp in supplements_data:
                if supp.get('taken'):
                    taken.append(supp.get('supplement_name', ''))
        
        return taken

    async def _save_context(self, user_id: str, target_date: date, context: Dict, version: int):
        """Save context to database"""
        try:
            self.supabase_service.client.table('chat_contexts')\
                .upsert({
                    'user_id': user_id,
                    'date': str(target_date),
                    'context_data': context,
                    'version': version,
                    'last_updated': datetime.now().isoformat()
                }, on_conflict='user_id,date')\
                .execute()
        except Exception as e:
            print(f"⚠️ Error saving context: {e}")

# Singleton instance
_context_manager = None

def get_context_manager() -> ChatContextManager:
    global _context_manager
    if _context_manager is None:
        _context_manager = ChatContextManager()
    return _context_manager