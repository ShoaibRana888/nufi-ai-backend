# services/chat_context_manager.py
from typing import Dict, Any, Optional, List
from datetime import datetime, date, timedelta
import json
from services.supabase_service import get_supabase_service

class ChatContextManager:
    def __init__(self):
        self.supabase_service = get_supabase_service()
    
    async def get_or_create_context(self, user_id: str, target_date: date = None) -> Dict[str, Any]:
        """Get existing context or create a new one for the specified date"""
        if target_date is None:
            # For today, use the ensure_daily_context method
            return await self.ensure_daily_context(user_id)
        
        # For specific dates, use the existing logic
        try:
            # Try to get existing context
            response = self.supabase_service.client.table('chat_contexts')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            
            if response.data:
                context_record = response.data[0]
                
                # Deduplicate context data before returning
                cleaned_context = self.deduplicate_context(context_record['context_data'])
                
                return {
                    'context': cleaned_context,
                    'version': context_record['version'],
                    'last_updated': context_record['last_updated']
                }
            
            # Create new context if none exists
            return await self.create_initial_context(user_id, target_date)
            
        except Exception as e:
            print(f"Error getting/creating context: {e}")
            # Fallback to generating fresh context
            return await self.generate_fresh_context(user_id, target_date)
    
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
    
    async def update_context_activity(
        self, 
        user_id: str, 
        activity_type: str, 
        data: Dict[str, Any],
        target_date: date = None
    ) -> Dict[str, Any]:
        """Update context when user logs an activity"""
        if target_date is None:
            target_date = datetime.now().date()
        
        try:
            # Get current context
            current = await self.get_or_create_context(user_id, target_date)
            context = current['context']
            version = current['version']
            
            # Update based on activity type
            if activity_type == 'meal':

                meal_id = data.get('id')
                existing_meal_ids = [m.get('id') for m in context['today_progress']['meals']]
                
                if meal_id not in existing_meal_ids:

                    # Add meal to list
                    meal_entry = {
                        'id': data.get('id'),
                        'food_item': data.get('food_item'),
                        'meal_type': data.get('meal_type'),
                        'calories': data.get('calories', 0),
                        'protein_g': data.get('protein_g', 0),
                        'carbs_g': data.get('carbs_g', 0),
                        'fat_g': data.get('fat_g', 0),
                        'fiber_g': data.get('fiber_g', 0),
                        'sugar_g': data.get('sugar_g', 0),
                        'sodium_mg': data.get('sodium_mg', 0),
                        'logged_at': data.get('created_at', datetime.now().isoformat())
                    }
                    context['today_progress']['meals'].append(meal_entry)
                    
                    context['today_progress']['totals']['calories'] += data.get('calories', 0)
                    context['today_progress']['totals']['protein'] += data.get('protein_g', 0)
                    context['today_progress']['totals']['carbs'] += data.get('carbs_g', 0)
                    context['today_progress']['totals']['fat'] += data.get('fat_g', 0)
                    context['today_progress']['totals']['fiber'] += data.get('fiber_g', 0)
                else:
                    print(f"⚠️ Meal {meal_id} already exists in context, skipping")
                
                context['today_progress']['meals_logged'] = len(context['today_progress']['meals'])
            
            elif activity_type == 'exercise':

                exercise_id = data.get('id')
                existing_exercise_ids = [e.get('id') for e in context['today_progress']['exercises']]
                
                if exercise_id not in existing_exercise_ids:

                    # Calculate duration if not provided
                    duration = data.get('duration_minutes')
                    if duration is None or duration == 0:
                        # Estimate based on sets and reps
                        if data.get('sets') and data.get('reps'):
                            # Rough estimate: 3 seconds per rep + 60 seconds rest between sets
                            duration = int((data['sets'] * data['reps'] * 3 + (data['sets'] - 1) * 60) / 60)
                        else:
                            duration = 15  # Default 15 minutes if no info
                    
                    exercise_entry = {
                        'id': data.get('id'),
                        'exercise_name': data.get('exercise_name'),
                        'muscle_group': data.get('muscle_group'),
                        'duration_minutes': duration, 
                        'calories_burned': data.get('calories_burned', 0),
                        'sets': data.get('sets'),
                        'reps': data.get('reps'),
                        'weight_kg': data.get('weight_kg'),
                        'logged_at': data.get('created_at', datetime.now().isoformat())
                    }
                
                    context['today_progress']['exercises'].append(exercise_entry)
                else:
                    print(f"⚠️ Exercise {exercise_id} already exists in context, skipping")
                
                context['today_progress']['exercises_done'] = len(context['today_progress']['exercises'])
                context['today_progress']['exercise_minutes'] = sum(
                    ex.get('duration_minutes', 0) for ex in context['today_progress']['exercises']
                )
            
            elif activity_type == 'water':
                context['today_progress']['water_glasses'] = data.get('glasses_consumed', 0)
            
            elif activity_type == 'steps':
                context['today_progress']['steps'] = data.get('steps', 0)
            
            elif activity_type == 'weight':
                context['today_progress']['weight'] = data.get('weight', 0)
            
            elif activity_type == 'sleep':
                context['today_progress']['sleep_hours'] = data.get('total_hours', 0)
            
            elif activity_type == 'supplement':
                if data.get('taken') and data.get('supplement_name'):
                    if data.get('supplement_name') not in context['today_progress']['supplements_taken']:
                        context['today_progress']['supplements_taken'].append(data.get('supplement_name'))
                elif not data.get('taken') and data.get('supplement_name'):
                    # Remove from list if marked as not taken
                    context['today_progress']['supplements_taken'] = [
                        s for s in context['today_progress']['supplements_taken'] 
                        if s != data.get('supplement_name')
                    ]
            
            # Update metadata
            context['context_metadata']['last_activity'] = activity_type
            context['context_metadata']['last_activity_time'] = datetime.now().isoformat()
            
            # Save updated context with optimistic locking
            response = self.supabase_service.client.table('chat_contexts')\
                .update({
                    'context_data': context,
                    'version': version + 1,
                    'last_updated': datetime.now().isoformat()
                })\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .eq('version', version)\
                .execute()
            
            if not response.data:
                # Version conflict, retry with fresh context
                return await self.update_context_activity(user_id, activity_type, data, target_date)
            
            return {
                'success': True,
                'context': context,
                'version': version + 1
            }
            
        except Exception as e:
            print(f"Error updating context: {e}")
            return {'success': False, 'error': str(e)}
    
    async def remove_from_context(
        self,
        user_id: str,
        activity_type: str,
        item_id: str,
        target_date: date = None
    ) -> Dict[str, Any]:
        """Remove an activity from context (for deletes)"""
        if target_date is None:
            target_date = datetime.now().date()
        
        try:
            # Get current context
            current = await self.get_or_create_context(user_id, target_date)
            context = current['context']
            version = current['version']
            
            if activity_type == 'meal':
                # Find and remove meal
                removed_meal = None
                for meal in context['today_progress']['meals']:
                    if meal.get('id') == item_id:
                        removed_meal = meal
                        break
                
                if removed_meal:
                    context['today_progress']['meals'].remove(removed_meal)
                    # Update totals
                    context['today_progress']['totals']['calories'] -= removed_meal.get('calories', 0)
                    context['today_progress']['totals']['protein'] -= removed_meal.get('protein_g', 0)
                    context['today_progress']['totals']['carbs'] -= removed_meal.get('carbs_g', 0)
                    context['today_progress']['totals']['fat'] -= removed_meal.get('fat_g', 0)
                    context['today_progress']['totals']['fiber'] -= removed_meal.get('fiber_g', 0)
            
            elif activity_type == 'exercise':
                # Find and remove exercise
                context['today_progress']['exercises'] = [
                    ex for ex in context['today_progress']['exercises']
                    if ex.get('id') != item_id
                ]
            
            # Save updated context
            response = self.supabase_service.client.table('chat_contexts')\
                .update({
                    'context_data': context,
                    'version': version + 1,
                    'last_updated': datetime.now().isoformat()
                })\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .eq('version', version)\
                .execute()
            
            return {
                'success': True,
                'context': context,
                'version': version + 1
            }
            
        except Exception as e:
            print(f"Error removing from context: {e}")
            return {'success': False, 'error': str(e)}
        
    async def generate_fresh_context(self, user_id: str, target_date: date) -> Dict[str, Any]:
        """Generate fresh context from source tables (fallback)"""
        try:
            # Get user profile
            user = await self.supabase_service.get_user_by_id(user_id)
            if not user:
                raise Exception("User not found")
            
            # ACTUALLY FETCH THE DATA FROM THE DATABASE
            # Get meals for today
            meals_response = self.supabase_service.client.table('meal_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('meal_date', f"{target_date}T00:00:00")\
                .lte('meal_date', f"{target_date}T23:59:59")\
                .execute()
            
            meals = meals_response.data if meals_response.data else []
            
            # Get exercises for today  
            exercise_response = self.supabase_service.client.table('exercise_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('exercise_date', f"{target_date}T00:00:00")\
                .lte('exercise_date', f"{target_date}T23:59:59")\
                .execute()
            
            exercises = exercise_response.data if exercise_response.data else []
            
            # Get water for today
            water_response = self.supabase_service.client.table('daily_water')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            
            water = water_response.data[0] if water_response.data else {}
            
            # Get steps for today
            steps_response = self.supabase_service.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            
            steps = steps_response.data[0] if steps_response.data else {}
            
            # Calculate totals from meals
            total_calories = sum(m.get('calories', 0) for m in meals)
            total_protein = sum(m.get('protein_g', 0) for m in meals)
            total_carbs = sum(m.get('carbs_g', 0) for m in meals)
            total_fat = sum(m.get('fat_g', 0) for m in meals)
            total_fiber = sum(m.get('fiber_g', 0) for m in meals)
            
            # Calculate exercise minutes
            total_exercise_minutes = sum(e.get('duration_minutes', 0) for e in exercises)
            
            # Build context with ACTUAL DATA
            context = {
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
                    'meals': [{'food_item': m['food_item'], 'calories': m['calories']} for m in meals],
                    'meals_logged': len(meals),
                    'total_calories': total_calories,
                    'total_protein': total_protein,
                    'total_carbs': total_carbs,
                    'total_fat': total_fat,
                    'exercises': [{'exercise_name': e['exercise_name'], 'duration': e.get('duration_minutes', 0)} for e in exercises],
                    'exercises_done': len(exercises),
                    'exercise_minutes': total_exercise_minutes,
                    'water_glasses': water.get('glasses_consumed', 0),
                    'steps': steps.get('steps', 0),
                    'weight': None,
                    'sleep_hours': None,
                    'supplements_taken': [],
                    'totals': {
                        'calories': total_calories,
                        'protein': total_protein,
                        'carbs': total_carbs,
                        'fat': total_fat,
                        'fiber': total_fiber
                    }
                },
                'weekly_summary': {
                    'avg_daily_calories': 0,
                    'total_workouts': 0,
                    'avg_sleep_hours': 0,
                    'weight_trend': 'unknown'
                },
                'goals_progress': {
                    'daily_calorie_goal': user.get('tdee', 2000),
                    'water_goal_glasses': user.get('water_intake_glasses', 8),
                    'step_goal': user.get('daily_step_goal', 10000),
                    'weight_progress': {
                        'current': user.get('weight'),
                        'target': user.get('target_weight'),
                        'status': 'in_progress'
                    }
                }
            }
            
            # Save the POPULATED context
            self.supabase_service.client.table('chat_contexts')\
                .upsert({
                    'user_id': user_id,
                    'date': str(target_date),
                    'context_data': context,
                    'version': 1,
                    'last_updated': datetime.now().isoformat()
                })\
                .execute()
            
            print(f"✅ Context rebuilt with {len(meals)} meals and {len(exercises)} exercises")
            
            return {
                'context': context,
                'version': 1,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Error generating fresh context: {e}")
            import traceback
            traceback.print_exc()
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
                'weekly_summary': await self._get_weekly_summary(user_id, target_date),
                'goals_progress': {
                    'daily_calorie_goal': user.get('tdee', 2000),
                    'water_goal_glasses': user.get('water_intake_glasses', 8),
                    'step_goal': user.get('daily_step_goal', 10000),
                    'weight_progress': {
                        'current': user.get('weight'),
                        'target': user.get('target_weight'),
                        'status': self._calculate_weight_status(
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
        """Fetch all activities for a specific date - COMPLETE IMPLEMENTATION"""
        activities = {}
        
        try:
            # Get meals - use correct column name 'meal_date'
            meals_response = self.supabase_service.client.table('meal_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('meal_date', str(target_date))\
                .execute()
            activities['meals'] = meals_response.data if meals_response.data else []
            print(f"  📋 Found {len(activities['meals'])} meals")
        except Exception as e:
            print(f"⚠️ Error fetching meals: {e}")
            activities['meals'] = []
        
        try:
            # Get water intake
            water_response = self.supabase_service.client.table('daily_water')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            activities['water'] = water_response.data[0] if water_response.data else {}
            print(f"  💧 Water: {activities['water'].get('glasses_consumed', 0)} glasses")
        except Exception as e:
            print(f"⚠️ Error fetching water: {e}")
            activities['water'] = {}
        
        try:
            # Get exercises
            exercise_response = self.supabase_service.client.table('exercise_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('exercise_date', str(target_date))\
                .execute()
            activities['exercise'] = exercise_response.data if exercise_response.data else []
            print(f"  💪 Found {len(activities['exercise'])} exercises")
        except Exception as e:
            print(f"⚠️ Error fetching exercise: {e}")
            activities['exercise'] = []
        
        try:
            # Get steps
            steps_response = self.supabase_service.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            activities['steps'] = steps_response.data[0] if steps_response.data else {}
            print(f"  👣 Steps: {activities['steps'].get('steps', 0)}")
        except Exception as e:
            print(f"⚠️ Error fetching steps: {e}")
            activities['steps'] = {}
        
        try:
            # Get sleep
            sleep_response = self.supabase_service.client.table('sleep_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            activities['sleep'] = sleep_response.data[0] if sleep_response.data else {}
            print(f"  😴 Sleep: {activities['sleep'].get('total_hours', 0)} hours")
        except Exception as e:
            print(f"⚠️ Error fetching sleep: {e}")
            activities['sleep'] = {}
        
        try:
            # Get weight
            weight_response = self.supabase_service.client.table('weight_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            activities['weight'] = weight_response.data[0] if weight_response.data else {}
            print(f"  ⚖️ Weight: {activities['weight'].get('weight', 'Not logged')} kg")
        except Exception as e:
            print(f"⚠️ Error fetching weight: {e}")
            activities['weight'] = {}
        
        try:
            # Get supplements
            activities['supplements'] = await self.supabase_service.get_supplement_status_by_date(
                user_id, target_date
            )
            print(f"  💊 Supplements logged")
        except Exception as e:
            print(f"⚠️ Error fetching supplements: {e}")
            activities['supplements'] = {}
        
        try:
            # Get period data (for female users)
            period_response = self.supabase_service.client.table('period_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .execute()
            activities['period'] = period_response.data[0] if period_response.data else {}
        except Exception as e:
            # Silent fail for period data (not all users need this)
            activities['period'] = {}
        
        return activities
    
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

    async def _get_weekly_summary(self, user_id: str, target_date: date) -> Dict[str, Any]:
        """Get weekly summary statistics"""
        try:
            # Calculate date range for past 7 days
            end_date = target_date
            start_date = end_date - timedelta(days=6)
            
            # Initialize summary
            summary = {
                'avg_daily_calories': 0,
                'total_workouts': 0,
                'avg_sleep_hours': 0,
                'weight_trend': 'unknown',
                'hydration_consistency': 0,
                'workout_streak': 0
            }
            
            # Fetch data for the week
            total_calories = 0
            days_with_meals = 0
            total_sleep = 0
            days_with_sleep = 0
            days_with_water = 0
            workout_days = set()
            
            for i in range(7):
                check_date = start_date + timedelta(days=i)
                
                # Get meals for calorie average
                meals = await self.supabase_service.get_meals_by_date(user_id, check_date)
                if meals:
                    daily_calories = sum(m.get('calories', 0) for m in meals)
                    if daily_calories > 0:
                        total_calories += daily_calories
                        days_with_meals += 1
                
                # Get sleep
                sleep = await self.supabase_service.get_sleep_by_date(user_id, check_date)
                if sleep and sleep.get('total_hours'):
                    total_sleep += sleep['total_hours']
                    days_with_sleep += 1
                
                # Get water
                water = await self.supabase_service.get_water_by_date(user_id, check_date)
                if water and water.get('glasses_consumed', 0) > 0:
                    days_with_water += 1
                
                # Get exercise
                exercises = await self.supabase_service.get_exercises_by_date(user_id, check_date)
                if exercises:
                    workout_days.add(str(check_date))
            
            # Calculate averages
            summary['avg_daily_calories'] = round(total_calories / days_with_meals) if days_with_meals > 0 else 0
            summary['total_workouts'] = len(workout_days)
            summary['avg_sleep_hours'] = round(total_sleep / days_with_sleep, 1) if days_with_sleep > 0 else 0
            summary['hydration_consistency'] = round((days_with_water / 7) * 100)
            
            # Get weight trend
            weight_entries = await self.supabase_service.get_weight_entries(
                user_id, 
                start_date=str(start_date),
                end_date=str(end_date)
            )
            summary['weight_trend'] = self._calculate_weight_trend(weight_entries)
            
            return summary
            
        except Exception as e:
            print(f"⚠️ Error getting weekly summary: {e}")
            return {
                'avg_daily_calories': 0,
                'total_workouts': 0,
                'avg_sleep_hours': 0,
                'weight_trend': 'unknown'
            }

    def _calculate_weight_status(self, current: float, target: float) -> str:
        """Calculate weight progress status"""
        if not current or not target:
            return 'no_data'
        
        diff = abs(current - target)
        if diff < 0.5:
            return 'at_goal'
        elif current > target:
            return f'lose_{diff:.1f}kg'
        else:
            return f'gain_{diff:.1f}kg'

    def _calculate_weight_trend(self, weight_entries: List[Dict]) -> str:
        """Calculate weight trend from entries"""
        if len(weight_entries) < 2:
            return 'insufficient_data'
        
        # Sort by date
        sorted_entries = sorted(weight_entries, key=lambda x: x.get('date', ''))
        
        if len(sorted_entries) >= 2:
            first_weight = sorted_entries[0].get('weight', 0)
            last_weight = sorted_entries[-1].get('weight', 0)
            change = last_weight - first_weight
            
            if abs(change) < 0.2:
                return 'stable'
            elif change > 0:
                return f'gaining_{abs(change):.1f}kg'
            else:
                return f'losing_{abs(change):.1f}kg'
        
        return 'insufficient_data'
    
    def deduplicate_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Remove duplicate entries from context"""
        
        # Deduplicate meals by ID
        seen_meal_ids = set()
        unique_meals = []
        for meal in context['today_progress']['meals']:
            meal_id = meal.get('id')
            if meal_id not in seen_meal_ids:
                unique_meals.append(meal)
                seen_meal_ids.add(meal_id)
        context['today_progress']['meals'] = unique_meals
        
        # Deduplicate exercises by ID
        seen_exercise_ids = set()
        unique_exercises = []
        for exercise in context['today_progress']['exercises']:
            exercise_id = exercise.get('id')
            if exercise_id not in seen_exercise_ids:
                unique_exercises.append(exercise)
                seen_exercise_ids.add(exercise_id)
        context['today_progress']['exercises'] = unique_exercises
        
        # Recalculate totals
        context['today_progress']['totals'] = {
            'calories': sum(m.get('calories', 0) for m in unique_meals),
            'protein': sum(m.get('protein_g', 0) for m in unique_meals),
            'carbs': sum(m.get('carbs_g', 0) for m in unique_meals),
            'fat': sum(m.get('fat_g', 0) for m in unique_meals),
            'fiber': sum(m.get('fiber_g', 0) for m in unique_meals)
        }
        
        context['today_progress']['meals_logged'] = len(unique_meals)
        context['today_progress']['exercises_done'] = len(unique_exercises)
        context['today_progress']['exercise_minutes'] = sum(
            e.get('duration_minutes', 0) for e in unique_exercises
        )
        
        return context

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

    async def ensure_daily_context(self, user_id: str) -> Dict[str, Any]:
        """Ensure a context exists for today"""
        today = datetime.now().date()
        
        try:
            response = self.supabase_service.client.table('chat_contexts')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(today))\
                .execute()
            
            if response.data:
                context_record = response.data[0]
                
                # Deduplicate context data before returning
                cleaned_context = self.deduplicate_context(context_record['context_data'])
                
                return {
                    'context': cleaned_context,
                    'version': context_record['version'],
                    'last_updated': context_record['last_updated']
                }
            
            # Create new context for today
            return await self.create_initial_context(user_id, today)
            
        except Exception as e:
            print(f"Error ensuring daily context: {e}")
            return await self.generate_fresh_context(user_id, today)

# Singleton instance
_context_manager = None

def get_context_manager() -> ChatContextManager:
    global _context_manager
    if _context_manager is None:
        _context_manager = ChatContextManager()
    return _context_manager