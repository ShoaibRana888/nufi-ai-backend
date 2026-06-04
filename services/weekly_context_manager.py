# services/weekly_context_manager.py

from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta
import json
from services.supabase_service import get_supabase_service

class WeeklyContextManager:
    def __init__(self):
        self.supabase_service = get_supabase_service()
    
    def get_week_boundaries(self, target_date: date) -> tuple:
        """Get the start and end dates of the week containing target_date"""
        # Week starts on Monday
        days_since_monday = target_date.weekday()
        week_start = target_date - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        return week_start, week_end
    
    def get_week_number(self, target_date: date) -> tuple:
        """Get ISO week number and year"""
        iso_calendar = target_date.isocalendar()
        return iso_calendar[1], iso_calendar[0]  # week_number, year
    
    async def get_or_create_weekly_context(
        self, 
        user_id: str, 
        target_date: date = None
    ) -> Dict[str, Any]:
        """Get or create weekly context for a given date"""
        if target_date is None:
            target_date = datetime.now().date()
        
        week_start, week_end = self.get_week_boundaries(target_date)
        week_number, year = self.get_week_number(target_date)

        # The current (ongoing) week keeps accumulating data throughout the week,
        # so a cached snapshot would be stale. Always rebuild it from live data.
        # Past, completed weeks are safe to serve from cache.
        is_current_week = week_end >= datetime.now().date()

        try:
            # Check if weekly context exists
            response = self.supabase_service.client.table('weekly_contexts')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('week_start_date', str(week_start))\
                .execute()

            if response.data and not is_current_week:
                return {
                    'success': True,
                    'weekly_context': response.data[0]['context_data'],
                    'summary': response.data[0].get('summary_data', {}),
                    'week_start': str(week_start),
                    'week_end': str(week_end),
                    'version': response.data[0]['version']
                }

            # For the current week, drop any stale cached row first so we rebuild
            # cleanly from live daily data (avoids duplicate rows on re-aggregation).
            if response.data and is_current_week:
                self.supabase_service.client.table('weekly_contexts')\
                    .delete()\
                    .eq('user_id', user_id)\
                    .eq('week_start_date', str(week_start))\
                    .execute()

            # Create the weekly context from live daily data.
            return await self.create_weekly_context(
                user_id, week_start, week_end, week_number, year
            )
            
        except Exception as e:
            print(f"Error getting weekly context: {e}")
            return {'success': False, 'error': str(e)}
    
    async def create_weekly_context(
        self, 
        user_id: str,
        week_start: date,
        week_end: date,
        week_number: int,
        year: int
    ) -> Dict[str, Any]:
        """Create a new weekly context by aggregating daily data"""
        try:
            # Get user profile
            user = await self.supabase_service.get_user(user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Aggregate data for the entire week
            weekly_data = await self._aggregate_weekly_data(
                user_id, week_start, week_end
            )
            
            # Calculate weekly insights
            insights = self._calculate_weekly_insights(weekly_data, user)
            
            # Build weekly context structure
            context_data = {
                'week_info': {
                    'week_number': week_number,
                    'year': year,
                    'start_date': str(week_start),
                    'end_date': str(week_end),
                    'days_logged': weekly_data['days_with_data']
                },
                'nutrition_summary': {
                    'total_calories': weekly_data['total_calories'],
                    'avg_daily_calories': weekly_data['avg_calories'],
                    'total_protein': weekly_data['total_protein'],
                    'total_carbs': weekly_data['total_carbs'],
                    'total_fat': weekly_data['total_fat'],
                    'avg_daily_protein': weekly_data['avg_protein'],
                    'avg_daily_carbs': weekly_data['avg_carbs'],
                    'avg_daily_fat': weekly_data['avg_fat'],
                    'total_meals_logged': weekly_data['total_meals'],
                    'daily_breakdown': weekly_data['daily_nutrition']
                },
                'exercise_summary': {
                    'total_workouts': weekly_data['total_workouts'],
                    'total_minutes': weekly_data['total_exercise_minutes'],
                    'total_calories_burned': weekly_data['total_calories_burned'],
                    'workout_types': weekly_data['workout_types'],
                    'muscle_groups_worked': weekly_data['muscle_groups'],
                    'workout_days': weekly_data['workout_days'],
                    'rest_days': 7 - len(weekly_data['workout_days']),
                    'exercises_performed': weekly_data['exercises_list']
                },
                'hydration_summary': {
                    'total_water_glasses': weekly_data['total_water'],
                    'avg_daily_glasses': weekly_data['avg_water'],
                    'days_met_goal': weekly_data['days_water_goal_met'],
                    'hydration_consistency': weekly_data['hydration_consistency'],
                    'daily_breakdown': weekly_data['daily_water']
                },
                'activity_summary': {
                    'total_steps': weekly_data['total_steps'],
                    'avg_daily_steps': weekly_data['avg_steps'],
                    'days_met_step_goal': weekly_data['days_step_goal_met'],
                    'most_active_day': weekly_data['most_active_day'],
                    'least_active_day': weekly_data['least_active_day'],
                    'daily_breakdown': weekly_data['daily_steps']
                },
                'sleep_summary': {
                    'total_hours': weekly_data['total_sleep'],
                    'avg_nightly_hours': weekly_data['avg_sleep'],
                    'best_night': weekly_data['best_sleep_day'],
                    'worst_night': weekly_data['worst_sleep_day'],
                    'sleep_consistency': weekly_data['sleep_consistency'],
                    'daily_breakdown': weekly_data['daily_sleep']
                },
                'weight_progress': {
                    'starting_weight': weekly_data['week_start_weight'],
                    'ending_weight': weekly_data['week_end_weight'],
                    'weight_change': weekly_data['weight_change'],
                    'measurements': weekly_data['weight_measurements']
                },
                'supplement_adherence': {
                    'supplements_tracked': weekly_data['supplements_list'],
                    'adherence_rate': weekly_data['supplement_adherence'],
                    'daily_breakdown': weekly_data['daily_supplements']
                },
                'insights': insights,
                'goals_progress': {
                    'calorie_goal_achievement': weekly_data['calorie_goal_achievement'],
                    'water_goal_achievement': weekly_data['water_goal_achievement'],
                    'step_goal_achievement': weekly_data['step_goal_achievement'],
                    'workout_goal_achievement': weekly_data['workout_goal_achievement']
                }
            }
            
            # Create summary for quick reference
            summary_data = {
                'week_number': week_number,
                'year': year,
                'avg_calories': weekly_data['avg_calories'],
                'total_workouts': weekly_data['total_workouts'],
                'avg_sleep': weekly_data['avg_sleep'],
                'weight_change': weekly_data['weight_change'],
                'top_achievements': insights.get('achievements', []),
                'areas_for_improvement': insights.get('improvements', [])
            }
            
            # Save to database
            response = self.supabase_service.client.table('weekly_contexts')\
                .upsert({
                    'user_id': user_id,
                    'week_start_date': str(week_start),
                    'week_end_date': str(week_end),
                    'week_number': week_number,
                    'year': year,
                    'context_data': context_data,
                    'summary_data': summary_data,
                    'version': 1,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                })\
                .execute()
            
            print(f"✅ Weekly context created for week {week_number}/{year}")
            
            return {
                'success': True,
                'weekly_context': context_data,
                'summary': summary_data,
                'week_start': str(week_start),
                'week_end': str(week_end),
                'version': 1
            }
            
        except Exception as e:
            print(f"❌ Error creating weekly context: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
    
    async def _aggregate_weekly_data(
    self, 
    user_id: str, 
    week_start: date, 
    week_end: date
) -> Dict[str, Any]:
        """Aggregate all data for a week"""
        
        # Initialize data structure
        data = {
            # Nutrition
            'total_calories': 0,
            'total_protein': 0,
            'total_carbs': 0,
            'total_fat': 0,
            'total_meals': 0,
            'daily_nutrition': {},
            
            # Exercise  
            'total_workouts': 0,
            'total_exercise_minutes': 0,
            'total_calories_burned': 0,
            'workout_types': {},
            'muscle_groups': {},
            'workout_days': [],
            'exercises_list': [],
            
            # Hydration
            'total_water': 0,
            'daily_water': {},
            'days_water_goal_met': 0,
            
            # Activity
            'total_steps': 0,
            'daily_steps': {},
            'days_step_goal_met': 0,
            'most_active_day': None,
            'least_active_day': None,
            
            # Sleep
            'total_sleep': 0,
            'daily_sleep': {},
            'best_sleep_day': None,
            'worst_sleep_day': None,
            
            # Weight
            'week_start_weight': None,
            'week_end_weight': None,
            'weight_change': 0,
            'weight_measurements': [],
            
            # Supplements
            'supplements_list': set(),
            'daily_supplements': {},
            
            # Tracking
            'days_with_data': 0
        }
        
        days_with_any_data = set()
        max_steps = 0
        min_steps = float('inf')
        max_sleep = 0
        min_sleep = float('inf')
        
        # CRITICAL: Iterate through each day
        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            date_str = str(current_date)
            day_has_data = False
            
            print(f"\n📅 Processing {date_str} (Day {day_offset + 1}/7)")
            
            # Fetch meals
            try:
                meals = await self.supabase_service.get_meals_by_date(user_id, current_date)
                print(f"   📊 Raw meals returned: {len(meals)}")
                
                if meals and len(meals) > 0:
                    day_has_data = True
                    
                    # Calculate daily totals
                    daily_cals = 0
                    daily_protein = 0
                    daily_carbs = 0
                    daily_fat = 0
                    
                    for meal in meals:
                        # ✅ CRITICAL: Use .get() with default 0
                        daily_cals += float(meal.get('calories', 0) or 0)
                        daily_protein += float(meal.get('protein_g', 0) or 0)
                        daily_carbs += float(meal.get('carbs_g', 0) or 0)
                        daily_fat += float(meal.get('fat_g', 0) or 0)
                    
                    # ✅ CRITICAL: Add to weekly totals
                    data['total_calories'] += daily_cals
                    data['total_protein'] += daily_protein
                    data['total_carbs'] += daily_carbs
                    data['total_fat'] += daily_fat
                    data['total_meals'] += len(meals)
                    
                    # ✅ Store daily breakdown
                    data['daily_nutrition'][date_str] = {
                        'calories': daily_cals,
                        'protein': daily_protein,
                        'carbs': daily_carbs,
                        'fat': daily_fat,
                        'meals_count': len(meals)
                    }
                    
                    print(f"   ✅ Meals processed: {len(meals)} meals, {daily_cals} cals")
                else:
                    print(f"   ℹ️ No meals found for {date_str}")
                    
            except Exception as e:
                print(f"   ❌ Error fetching meals: {e}")
                import traceback
                traceback.print_exc()
            
            # Fetch exercises
            try:
                exercises = await self.supabase_service.get_exercises_by_date(user_id, current_date)
                print(f"   📊 Raw exercises returned: {len(exercises)}")
                
                if exercises and len(exercises) > 0:
                    day_has_data = True
                    data['workout_days'].append(date_str)
                    
                    # ✅ CRITICAL: Process each exercise
                    for ex in exercises:
                        # Add to total workouts
                        data['total_workouts'] += 1
                        
                        # ✅ CRITICAL: Use .get() with default 0 and handle None
                        duration = int(ex.get('duration_minutes', 0) or 0)
                        calories = float(ex.get('calories_burned', 0) or 0)
                        
                        data['total_exercise_minutes'] += duration
                        data['total_calories_burned'] += calories
                        
                        # Track exercise types
                        ex_type = ex.get('exercise_type', 'other') or 'other'
                        data['workout_types'][ex_type] = data['workout_types'].get(ex_type, 0) + 1
                        
                        # Track muscle groups
                        muscle_group = ex.get('muscle_group') or 'other'
                        if muscle_group:
                            data['muscle_groups'][muscle_group] = data['muscle_groups'].get(muscle_group, 0) + 1
                        
                        # Add to exercises list
                        data['exercises_list'].append({
                            'name': ex.get('exercise_name', 'Unknown'),
                            'date': date_str,
                            'type': ex_type,
                            'duration': duration
                        })
                    
                    print(f"   ✅ Exercises processed: {len(exercises)} exercises, {data['total_exercise_minutes']} mins")
                else:
                    print(f"   ℹ️ No exercises found for {date_str}")
                    
            except Exception as e:
                print(f"   ❌ Error fetching exercises: {e}")
                import traceback
                traceback.print_exc()
            
            # Fetch sleep
            try:
                sleep = await self.supabase_service.get_sleep_by_date(user_id, current_date)
                print(f"   📊 Sleep returned: {sleep is not None}")
                
                if sleep and sleep.get('total_hours'):
                    day_has_data = True
                    hours = float(sleep.get('total_hours', 0) or 0)
                    data['total_sleep'] += hours
                    
                    data['daily_sleep'][date_str] = {
                        'hours': hours,
                        'quality': sleep.get('quality', 'unknown')
                    }
                    
                    # Track best/worst sleep
                    if hours > max_sleep:
                        max_sleep = hours
                        data['best_sleep_day'] = {'date': date_str, 'hours': hours}
                    if hours < min_sleep and hours > 0:
                        min_sleep = hours
                        data['worst_sleep_day'] = {'date': date_str, 'hours': hours}
                    
                    print(f"   ✅ Sleep processed: {hours}h")
                else:
                    print(f"   ℹ️ No sleep found for {date_str}")
                    
            except Exception as e:
                print(f"   ❌ Error fetching sleep: {e}")
                import traceback
                traceback.print_exc()
            
            # Fetch water
            try:
                water = await self.supabase_service.get_water_by_date(user_id, current_date)
                if water and water.get('glasses_consumed'):
                    day_has_data = True
                    glasses = int(water.get('glasses_consumed', 0) or 0)
                    data['total_water'] += glasses
                    data['daily_water'][date_str] = glasses
                    
                    if glasses >= 8:
                        data['days_water_goal_met'] += 1
                    
                    print(f"   ✅ Water processed: {glasses} glasses")
            except Exception as e:
                print(f"   ❌ Error fetching water: {e}")
            
            # Fetch steps
            try:
                steps = await self.supabase_service.get_steps_by_date(user_id, current_date)
                if steps and steps.get('steps'):
                    day_has_data = True
                    step_count = int(steps.get('steps', 0) or 0)
                    data['total_steps'] += step_count
                    data['daily_steps'][date_str] = step_count
                    
                    if step_count > max_steps:
                        max_steps = step_count
                        data['most_active_day'] = {'date': date_str, 'steps': step_count}
                    if step_count < min_steps and step_count > 0:
                        min_steps = step_count
                        data['least_active_day'] = {'date': date_str, 'steps': step_count}
                    
                    if step_count >= 10000:
                        data['days_step_goal_met'] += 1
                    
                    print(f"   ✅ Steps processed: {step_count} steps")
            except Exception as e:
                print(f"   ❌ Error fetching steps: {e}")

            # Fetch weight
            try:
                weight = await self.supabase_service.get_weight_by_date(user_id, current_date)
                if weight and weight.get('weight'):
                    day_has_data = True
                    weight_kg = float(weight.get('weight', 0) or 0)
                    data['weight_measurements'].append({
                        'date': date_str,
                        'weight': weight_kg
                    })
                    print(f"   ✅ Weight processed: {weight_kg}kg")
            except Exception as e:
                print(f"   ❌ Error fetching weight: {e}")

            # Fetch supplements
            try:
                supplements = await self.supabase_service.get_supplement_status_by_date(user_id, current_date)
                if supplements:
                    day_has_data = True
                    taken_count = sum(1 for s in supplements.values() if s.get('taken'))
                    total_count = len(supplements)
                    for name in supplements.keys():
                        data['supplements_list'].add(name)
                    data['daily_supplements'][date_str] = {
                        'taken': taken_count,
                        'total': total_count
                    }
                    print(f"   ✅ Supplements processed: {taken_count}/{total_count} taken")
            except Exception as e:
                print(f"   ❌ Error fetching supplements: {e}")

            # Track days with data
            if day_has_data:
                days_with_any_data.add(date_str)
                print(f"   ✅ Day has data!")
            else:
                print(f"   ⚠️ No data found for this day")
        
        # Calculate final averages
        data['days_with_data'] = len(days_with_any_data)
        days_divisor = max(data['days_with_data'], 1)
        
        data['avg_calories'] = round(data['total_calories'] / days_divisor)
        data['avg_protein'] = round(data['total_protein'] / days_divisor, 1)
        data['avg_carbs'] = round(data['total_carbs'] / days_divisor, 1)
        data['avg_fat'] = round(data['total_fat'] / days_divisor, 1)
        data['avg_water'] = round(data['total_water'] / days_divisor, 1)
        data['avg_steps'] = round(data['total_steps'] / days_divisor)
        data['avg_sleep'] = round(data['total_sleep'] / days_divisor, 1) if data['total_sleep'] > 0 else 0
        
        # Calculate consistency metrics
        data['hydration_consistency'] = round((len(data['daily_water']) / 7) * 100)
        data['sleep_consistency'] = round((len(data['daily_sleep']) / 7) * 100)
        
        # Convert supplements set to list
        data['supplements_list'] = list(data['supplements_list'])

        # Weight progress: first vs last measurement of the week (chronological)
        if data['weight_measurements']:
            sorted_weights = sorted(data['weight_measurements'], key=lambda m: m['date'])
            data['week_start_weight'] = sorted_weights[0]['weight']
            data['week_end_weight'] = sorted_weights[-1]['weight']
            data['weight_change'] = round(
                sorted_weights[-1]['weight'] - sorted_weights[0]['weight'], 1
            )

        data['calorie_goal_achievement'] = 0
        data['water_goal_achievement'] = 0
        data['step_goal_achievement'] = 0
        data['workout_goal_achievement'] = 0
        data['supplement_adherence'] = 0

        # If we have days with data, calculate achievements
        if data['days_with_data'] > 0:
            # Calorie goal achievement (percentage of days tracked)
            data['calorie_goal_achievement'] = round((data['days_with_data'] / 7) * 100)

            # Water goal achievement
            data['water_goal_achievement'] = round((data['days_water_goal_met'] / 7) * 100)

            # Step goal achievement
            data['step_goal_achievement'] = round((data['days_step_goal_met'] / 7) * 100)

            # Workout goal achievement (3+ workouts = 100%)
            workout_goal = 3
            data['workout_goal_achievement'] = min(100, round((data['total_workouts'] / workout_goal) * 100))

            # Supplement adherence: taken vs scheduled across all logged days
            total_scheduled = sum(d['total'] for d in data['daily_supplements'].values())
            total_taken = sum(d['taken'] for d in data['daily_supplements'].values())
            if total_scheduled > 0:
                data['supplement_adherence'] = round((total_taken / total_scheduled) * 100)
        
        # Update the final print to show these new fields
        print(f"\n📊 WEEKLY AGGREGATION COMPLETE:")
        print(f"   Total Meals: {data['total_meals']}")
        print(f"   Total Calories: {data['total_calories']}")
        print(f"   Total Workouts: {data['total_workouts']}")
        print(f"   Total Exercise Minutes: {data['total_exercise_minutes']}")
        print(f"   Avg Sleep: {data['avg_sleep']}h")
        print(f"   Days with data: {data['days_with_data']}/7")
        print(f"   ✅ Calorie goal achievement: {data['calorie_goal_achievement']}%")
        print(f"   ✅ Workout goal achievement: {data['workout_goal_achievement']}%")
        
        return data
    
    def _calculate_weekly_insights(
        self, 
        weekly_data: Dict[str, Any], 
        user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate insights from weekly data"""
        insights = {
            'achievements': [],
            'improvements': [],
            'trends': [],
            'recommendations': []
        }
        
        # Check achievements
        if weekly_data['calorie_goal_achievement'] >= 80:
            insights['achievements'].append("Great calorie tracking consistency!")
        
        if weekly_data['total_workouts'] >= 3:
            insights['achievements'].append(f"Completed {weekly_data['total_workouts']} workouts!")
        
        if weekly_data['hydration_consistency'] >= 85:
            insights['achievements'].append("Excellent hydration habits!")
        
        if weekly_data['avg_sleep'] >= 7:
            insights['achievements'].append("Good sleep average maintained!")
        
        if weekly_data['weight_change'] < 0 and user.get('weight_goal') == 'lose_weight':
            insights['achievements'].append(f"Lost {abs(weekly_data['weight_change'])}kg this week!")
        elif weekly_data['weight_change'] > 0 and user.get('weight_goal') == 'gain_weight':
            insights['achievements'].append(f"Gained {weekly_data['weight_change']}kg this week!")
        
        # Check areas for improvement
        if weekly_data['total_workouts'] < 2:
            insights['improvements'].append("Try to add more workouts next week")
        
        if weekly_data['hydration_consistency'] < 60:
            insights['improvements'].append("Focus on daily water intake")
        
        if weekly_data['avg_sleep'] < 6:
            insights['improvements'].append("Prioritize getting more sleep")
        
        if weekly_data['days_with_data'] < 4:
            insights['improvements'].append("Log your activities more consistently")
        
        # Identify trends
        if weekly_data['avg_calories'] > 0:
            tdee = user.get('tdee', 2000)
            if weekly_data['avg_calories'] < tdee * 0.8:
                insights['trends'].append("Calorie intake is below target")
            elif weekly_data['avg_calories'] > tdee * 1.2:
                insights['trends'].append("Calorie intake is above target")
        
        # Add personalized recommendations
        weight_goal = user.get('weight_goal', '')
        
        if 'lose' in weight_goal.lower():
            if weekly_data['avg_calories'] > user.get('tdee', 2000):
                insights['recommendations'].append("Consider reducing portion sizes")
            if weekly_data['total_workouts'] < 3:
                insights['recommendations'].append("Add more cardio sessions")
        elif 'gain' in weight_goal.lower():
            if weekly_data['avg_protein'] < user.get('weight', 70) * 1.6:
                insights['recommendations'].append("Increase protein intake")
            if weekly_data['total_workouts'] < 3:
                insights['recommendations'].append("Add strength training sessions")
        
        return insights
    
    async def get_recent_weeks_context(
        self, 
        user_id: str, 
        weeks_count: int = 4
    ) -> List[Dict[str, Any]]:
        """Get context for recent weeks"""
        try:
            end_date = datetime.now().date()
            contexts = []
            
            for week_offset in range(weeks_count):
                target_date = end_date - timedelta(weeks=week_offset)
                week_context = await self.get_or_create_weekly_context(user_id, target_date)
                if week_context.get('success'):
                    contexts.append(week_context)
            
            return contexts
            
        except Exception as e:
            print(f"Error getting recent weeks: {e}")
            return []
    
    async def update_weekly_context(
        self, 
        user_id: str, 
        date: date = None
    ) -> Dict[str, Any]:
        """Update existing weekly context with new data"""
        if date is None:
            date = datetime.now().date()
        
        week_start, week_end = self.get_week_boundaries(date)
        
        try:
            # Delete existing context
            self.supabase_service.client.table('weekly_contexts')\
                .delete()\
                .eq('user_id', user_id)\
                .eq('week_start_date', str(week_start))\
                .execute()
            
            # Recreate with fresh data
            week_number, year = self.get_week_number(date)
            return await self.create_weekly_context(
                user_id, week_start, week_end, week_number, year
            )
            
        except Exception as e:
            print(f"Error updating weekly context: {e}")
            return {'success': False, 'error': str(e)}

# Singleton instance
_weekly_context_manager = None

def get_weekly_context_manager() -> WeeklyContextManager:
    global _weekly_context_manager
    if _weekly_context_manager is None:
        _weekly_context_manager = WeeklyContextManager()
    return _weekly_context_manager