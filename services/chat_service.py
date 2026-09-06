# services/chat_service.py
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta, date
from services.openai_service import get_openai_service
from services.supabase_service import get_supabase_service
from services.weekly_context_manager import get_weekly_context_manager
from services.guardrails import render_guardrail_prompt, post_check_response
from services.health_trends import weight_status

class HealthChatService:
    def __init__(self):
        try:
            self.openai_service = get_openai_service()
            print(f"✅ OpenAI service initialized: {self.openai_service is not None}")
        except Exception as e:
            print(f"❌ Failed to initialize OpenAI service: {e}")
            self.openai_service = None
            
        try:
            self.supabase_service = get_supabase_service()
            print(f"✅ Supabase service initialized: {self.supabase_service is not None}")
        except Exception as e:
            print(f"❌ Failed to initialize Supabase service: {e}")
            self.supabase_service = None

        try:
            self.weekly_manager = get_weekly_context_manager()
            print(f"✅ Weekly context manager initialized")
        except Exception as e:
            print(f"⚠️ Weekly context not available: {e}")
            self.weekly_manager = None
    
    def _check_topic_relevance(self, message: str) -> Tuple[bool, str]:
        """
        Check if message is health/fitness related
        Returns: (is_relevant, redirect_message)
        """
        message_lower = message.lower()
        
        # Health/fitness keywords (allow these)
        health_keywords = [
            'calorie', 'calories', 'protein', 'carb', 'carbs', 'fat', 'nutrition', 'meal', 'food', 'eat', 'eating',
            'workout', 'exercise', 'fitness', 'gym', 'weight', 'muscle', 'cardio', 'strength',
            'sleep', 'sleeping', 'water', 'hydration', 'drink', 'goal', 'goals', 'progress', 'lose', 'gain',
            'diet', 'dieting', 'recipe', 'supplement', 'vitamin', 'health', 'healthy', 'training',
            'run', 'running', 'yoga', 'steps', 'active', 'burn', 'burned', 'track', 'tracking',
            'breakfast', 'lunch', 'dinner', 'snack', 'hungry', 'full', 'macros', 'nutrients',
            'bulk', 'cut', 'maintain', 'body', 'metabolism', 'tdee', 'bmr', 'rest', 'recovery',
            'stretch', 'stretching', 'core', 'abs', 'arms', 'legs', 'chest', 'back', 'shoulders',
            'tired', 'energy', 'fatigue', 'motivation', 'motivated', 'habit', 'habits'
        ]
        
        # Off-topic keywords (reject these)
        off_topic_keywords = [
            'politics', 'political', 'election', 'president', 'government', 'congress', 'senate', 'war', 'news',
            'movie', 'film', 'tv show', 'television', 'music', 'song', 'album', 'celebrity', 'actor', 'actress',
            'code', 'coding', 'programming', 'python', 'javascript', 'html', 'css', 'software', 'debug',
            'math', 'mathematics', 'equation', 'calculation', 'formula', 'algebra', 'geometry',
            'weather', 'temperature', 'forecast', 'rain', 'snow', 'sunny',
            'stock', 'stocks', 'investment', 'crypto', 'cryptocurrency', 'bitcoin', 'ethereum',
            'game', 'gaming', 'video game', 'playstation', 'xbox', 'fortnite',
            'recipe for', 'how to make', 'travel', 'vacation', 'hotel', 'flight'
        ]
        
        # Check for health keywords
        has_health_keyword = any(keyword in message_lower for keyword in health_keywords)
        
        # Check for off-topic keywords
        has_off_topic = any(keyword in message_lower for keyword in off_topic_keywords)
        
        # Very short greetings are okay
        greetings = ['hi', 'hello', 'hey', 'good morning', 'good evening', 'good afternoon', 
                     'howdy', 'greetings', 'sup', 'yo', 'hiya']
        is_greeting = any(message_lower.strip() == greeting for greeting in greetings)
        
        # Simple questions that are okay
        simple_questions = ['how are you', 'what can you do', 'what do you do', 'help', 'help me']
        is_simple_question = any(question in message_lower for question in simple_questions)
        
        # Decision logic
        if is_greeting or is_simple_question:
            return True, ""  # Allow greetings and simple questions
        
        if has_off_topic and not has_health_keyword:
            # Clearly off-topic
            print(f"🚫 REJECTED - Off-topic: {message[:100]}")
            return False, "I'm your health and fitness coach! I can help with workouts, nutrition, and reaching your goals. What would you like to know about those topics?"

        # Default: allow it. The system prompt enforces health-only scope and
        # politely redirects genuine off-topic edge cases, so we no longer
        # hard-reject keyword-free messages (that wrongly blocked valid
        # health questions phrased without a hardcoded keyword).
        return True, ""
    
    def _add_safety_disclaimers(self, response: str, original_message: str) -> str:
        """
        Add safety disclaimers if response involves medical topics
        """
        message_lower = original_message.lower()
        response_lower = response.lower()
        
        # Medical condition triggers
        medical_triggers = [
            'diabetes', 'diabetic', 'heart disease', 'hypertension', 'high blood pressure',
            'pregnant', 'pregnancy', 'cancer', 'kidney', 'liver', 'thyroid',
            'eating disorder', 'anorexia', 'bulimia', 'binge', 'purge',
            'medication', 'medications', 'prescription', 'prescribe',
            'injury', 'injured', 'pain', 'hurt', 'doctor', 'hospital', 
            'medical condition', 'disease', 'illness', 'sick', 'diagnosis'
        ]
        
        # Emergency triggers (need urgent care)
        emergency_triggers = [
            'chest pain', 'can\'t breathe', 'difficulty breathing', 'dizzy', 'dizziness',
            'severe pain', 'blood', 'bleeding', 'unconscious', 'fainted', 'fainting',
            'heart attack', 'stroke', 'seizure'
        ]
        
        # Supplement triggers
        supplement_triggers = ['supplement', 'supplements', 'vitamin', 'vitamins', 
                               'pill', 'pills', 'medication', 'drug', 'drugs']
        
        # Check for emergency first
        has_emergency = any(trigger in message_lower for trigger in emergency_triggers)
        if has_emergency:
            print(f"🚨 EMERGENCY DETECTED: {original_message[:50]}")
            # Override response with urgent message
            return "🚨 **This sounds like a medical emergency.** Please seek immediate medical attention or call emergency services right away. Your safety is the top priority. I'm here for fitness guidance, but this requires urgent professional medical care."
        
        # Check for medical conditions
        has_medical = any(trigger in message_lower or trigger in response_lower 
                          for trigger in medical_triggers)
        
        # Check for supplements
        has_supplement = any(trigger in message_lower or trigger in response_lower 
                            for trigger in supplement_triggers)
        
        # Add disclaimers if needed
        if has_medical and "healthcare provider" not in response_lower and "consult" not in response_lower:
            response += "\n\n⚠️ **Important:** Please consult your healthcare provider before making changes to your health routine, especially with existing medical conditions."
            print(f"⚠️ MEDICAL DISCLAIMER ADDED for: {original_message[:50]}")
        
        if has_supplement and "doctor" not in response_lower and "healthcare" not in response_lower:
            response += "\n\n💊 **Note:** Always discuss supplements with your doctor or registered dietitian, as they can interact with medications and health conditions."
            print(f"💊 SUPPLEMENT DISCLAIMER ADDED for: {original_message[:50]}")
        
        return response
    
    async def get_today_activities(self, user_id: str, target_date: date) -> dict:
        """Fetch all activities for a specific date"""
        activities = {}
        
        try:
            # Get today's meals
            meals_response = self.supabase_service.client.table('meal_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('meal_date', f"{target_date}T00:00:00")\
                .lte('meal_date', f"{target_date}T23:59:59")\
                .eq('shared_with_chat', True)\
                .execute()
            activities['meals'] = meals_response.data if meals_response.data else []
        except Exception as e:
            print(f"⚠️ Error fetching meals: {e}")
            activities['meals'] = []
        
        try:
            # Get today's water intake
            water_response = self.supabase_service.client.table('daily_water')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .eq('shared_with_chat', True)\
                .execute()
            activities['water'] = water_response.data[0] if water_response.data else {}
        except Exception as e:
            print(f"⚠️ Error fetching water: {e}")
            activities['water'] = {}
        
        try:
            # Get today's exercise
            exercise_response = self.supabase_service.client.table('exercise_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('exercise_date', str(target_date))\
                .eq('shared_with_chat', True)\
                .execute()
            activities['exercise'] = exercise_response.data if exercise_response.data else []
        except Exception as e:
            print(f"⚠️ Error fetching exercise: {e}")
            activities['exercise'] = []
        
        try:
            # Get today's sleep
            sleep_response = self.supabase_service.client.table('sleep_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .eq('shared_with_chat', True)\
                .execute()
            activities['sleep'] = sleep_response.data[0] if sleep_response.data else {}
        except Exception as e:
            print(f"⚠️ Error fetching sleep: {e}")
            activities['sleep'] = {}
        
        try:
            # Get today's supplements
            activities['supplements'] = await self.supabase_service.get_supplement_status_by_date(user_id, target_date, shared_only=True)
        except Exception as e:
            print(f"⚠️ Error fetching supplements: {e}")
            activities['supplements'] = {}
        
        try:
            # Get today's weight
            # weight_entries.date is a timestamptz, so match the whole day with a range.
            weight_next_day = target_date + timedelta(days=1)
            weight_response = self.supabase_service.client.table('weight_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', str(target_date))\
                .lt('date', str(weight_next_day))\
                .eq('shared_with_chat', True)\
                .execute()
            activities['weight'] = weight_response.data[0] if weight_response.data else {}
        except Exception as e:
            print(f"⚠️ Error fetching weight: {e}")
            activities['weight'] = {}
        
        try:
            # Get today's steps
            steps_response = self.supabase_service.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(target_date))\
                .eq('shared_with_chat', True)\
                .execute()
            activities['steps'] = steps_response.data[0] if steps_response.data else {}
        except Exception as e:
            print(f"⚠️ Error fetching steps: {e}")
            activities['steps'] = {}
        
        return activities
    
    async def _get_recent_activity_summary(self, user_id: str) -> Dict[str, Any]:
        """Get recent activity summary for the past week"""
        try:
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=7)
            
            meals_count = 0
            workouts_count = 0
            total_sleep_hours = 0
            sleep_count = 0
            
            for i in range(7):
                date = start_date + timedelta(days=i)
                activities = await self.get_today_activities(user_id, date)
                
                # Count meals
                meals_count += len(activities.get('meals', []))
                
                # Count workouts
                workouts_count += len(activities.get('exercise', []))
                
                # Sum sleep hours
                sleep = activities.get('sleep', {})
                if sleep.get('total_hours'):
                    total_sleep_hours += sleep['total_hours']
                    sleep_count += 1
            
            avg_sleep = round(total_sleep_hours / sleep_count, 1) if sleep_count > 0 else 0
            
            return {
                'meals_this_week': meals_count,
                'workouts_this_week': workouts_count,
                'avg_sleep_hours': avg_sleep,
            }
            
        except Exception as e:
            print(f"Error getting recent activity: {e}")
            return {
                'meals_this_week': 0,
                'workouts_this_week': 0,
                'avg_sleep_hours': 0,
            }
    
    async def get_user_context(self, user_id: str) -> Dict[str, Any]:
        """Get comprehensive user context for chat"""
        try:
            # Get user profile
            user = await self.supabase_service.get_user_by_id(user_id)
            if not user:
                return {}
            
            # Get today's activities using your existing method
            today = datetime.now().date()
            activities = await self.get_today_activities(user_id, today)
            
            # Get yesterday's activities for sleep
            yesterday = today - timedelta(days=1)
            yesterday_activities = await self.get_today_activities(user_id, yesterday)
            
            # Calculate meal totals
            meals = activities.get('meals', [])
            total_calories = sum(meal.get('calories', 0) for meal in meals)
            total_protein = sum(meal.get('protein_g', 0) for meal in meals)
            total_carbs = sum(meal.get('carbs_g', 0) for meal in meals)
            total_fat = sum(meal.get('fat_g', 0) for meal in meals)
            
            # Calculate exercise totals
            exercises = activities.get('exercise', [])
            total_exercise_minutes = sum(
                ex.get('duration_minutes', 0) if ex.get('duration_minutes') is not None else 0 
                for ex in exercises
            )
            exercise_names = [ex.get('exercise_name', '') for ex in exercises]
            
            # Get water, steps, weight data
            water = activities.get('water', {})
            steps = activities.get('steps', {})
            weight = activities.get('weight', {})
            sleep = yesterday_activities.get('sleep', {})  # Use yesterday's sleep
            
            # Get recent activity
            recent_activity = await self._get_recent_activity_summary(user_id)
            
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
                    'date': str(today),
                    'meals_logged': len(meals),
                    'total_calories': total_calories,
                    'total_protein': total_protein,
                    'total_carbs': total_carbs,
                    'total_fat': total_fat,
                    'water_glasses': water.get('glasses_consumed', 0),
                    'water_ml': water.get('total_ml', 0),
                    'steps': steps.get('steps', 0),
                    'exercise_minutes': total_exercise_minutes,
                    'exercises_done': exercise_names,
                    'sleep_hours': sleep.get('total_hours', 0),
                    'sleep_quality': sleep.get('quality', 'Not logged'),
                    'weight_logged': weight.get('weight'),
                },
                'goals_progress': {
                    'daily_calorie_goal': user.get('tdee', 2000),
                    'water_goal_glasses': user.get('water_intake_glasses', 8),
                    'step_goal': user.get('step_goal', 10000),
                    'weight_progress': {
                        'current': user.get('weight'),
                        'target': user.get('target_weight'),
                        'status': weight_status(user.get('weight'), user.get('target_weight'))
                    }
                },
                'recent_activity': recent_activity,
            }
            
            return context
            
        except Exception as e:
            print(f"❌ Error getting user context: {e}")
            import traceback
            traceback.print_exc()
            return self._get_empty_context()
        
    async def get_enhanced_context(self, user_id: str) -> Dict[str, Any]:
        """Get enhanced context using cache"""
        try:
            from services.chat_context_manager import get_context_manager
            
            context_manager = get_context_manager()
            result = await context_manager.get_or_create_context(user_id)
            
            return result['context']
            
        except Exception as e:
            print(f"Error getting enhanced context: {e}")
            # Fallback to regular context
            return await self.get_user_context(user_id)
    
    def _get_empty_context(self) -> Dict[str, Any]:
        """Return empty context structure when error occurs"""
        return {
            'user_profile': {},
            'today_progress': {
                'date': str(datetime.now().date()),
                'meals_logged': 0,
                'total_calories': 0,
                'total_protein': 0,
                'total_carbs': 0,
                'total_fat': 0,
                'water_glasses': 0,
                'water_ml': 0,
                'steps': 0,
                'exercise_minutes': 0,
                'exercises_done': [],
                'sleep_hours': 0,
                'sleep_quality': 'Not logged',
                'weight_logged': None,
            },
            'goals_progress': {
                'daily_calorie_goal': 2000,
                'water_goal_glasses': 8,
                'step_goal': 10000,
                'weight_progress': {
                    'current': None,
                    'target': None,
                    'status': 'no_data'
                }
            },
            'recent_activity': {
                'meals_this_week': 0,
                'workouts_this_week': 0,
                'avg_sleep_hours': 0,
            }
        }
    
    def _create_system_prompt(self, context: Dict[str, Any]) -> str:
        """Create enhanced system prompt with guardrails and all activity data"""
        user_profile = context.get('user_profile', {})
        today_progress = context.get('today_progress', {})

        # Canonical macro totals live under today_progress['totals']. Some
        # fallback context builders only emit flat 'total_*' keys, so read
        # the canonical shape first and defensively fall back per-field.
        totals = today_progress.get('totals', {})

        def _macro(key: str) -> Any:
            return totals.get(key, today_progress.get(f'total_{key}', 0))

        meals_logged = today_progress.get('meals_logged', 0)
        total_calories = _macro('calories')
        total_protein = _macro('protein')
        total_carbs = _macro('carbs')
        total_fat = _macro('fat')
        
        water_glasses = today_progress.get('water_glasses', 0)
        steps = today_progress.get('steps', 0)
        exercise_minutes = today_progress.get('exercise_minutes', 0)
        
        # Handle exercises_done - could be a number or list
        exercises_done = today_progress.get('exercises_done', 0)
        if isinstance(exercises_done, list):
            exercises_done = len(exercises_done)
        
        # Build the prompt with GUARDRAILS and the ACTUAL data
        prompt = f"""You are a personalized AI health and fitness coach assistant, NOT a medical professional or doctor.

=== CORE IDENTITY & SCOPE ===
Your expertise includes: nutrition guidance, workout planning, progress tracking, motivation, general wellness habits, meal planning, and fitness advice.

You do NOT: diagnose medical conditions, prescribe medications, provide medical treatment advice, or replace professional healthcare.

=== STRICT BOUNDARIES ===
ONLY answer questions related to:
- Fitness and exercise (workouts, training, routines, form, techniques)
- Nutrition (meal planning, macros, calories, healthy eating, recipes)
- Weight management (healthy weight loss/gain strategies)
- General wellness (sleep habits, hydration, stress management)
- Progress tracking and motivation
- Habit building for health and fitness

REJECT politely (with redirect message):
- Politics, current events, news, world affairs
- Entertainment (movies, TV shows, music, celebrities)
- General knowledge unrelated to health
- Technology, coding, programming
- Math problems (unless nutrition/fitness calculations)
- Any topic unrelated to health, fitness, or wellness

=== MEDICAL SAFETY GUARDRAILS ===

**Serious Medical Conditions:**
If user mentions diabetes, heart disease, cancer, kidney disease, liver disease, thyroid issues, autoimmune conditions, or chronic illnesses:
- Acknowledge their condition empathetically
- Provide general guidance only
- ALWAYS emphasize: "Given your [condition], please work closely with your healthcare provider before making any changes to your diet or exercise routine."

**Pregnancy:**
If user mentions pregnancy or trying to conceive:
- Be extra cautious with exercise and nutrition advice
- ALWAYS say: "Congratulations! Please consult your doctor before starting any new exercise or nutrition program during pregnancy. Your healthcare provider can give you personalized guidance that's safe for you and your baby."

**Medications & Supplements:**
If user asks about medications, prescriptions, or supplement interactions:
- Do NOT provide specific advice about drug interactions
- Say: "I can provide general nutrition and fitness guidance, but please consult your doctor or pharmacist about how [medication/supplement] might interact with diet or exercise. Your safety is important!"
- For general supplement questions (vitamins, protein powder), give general info but add disclaimer

**Injuries & Pain:**
If user describes pain, injury, or physical discomfort:
- For minor soreness: suggest rest, ice, and gradual return to activity
- For persistent or severe pain: "If pain persists or is severe, please see a healthcare provider to rule out injury. I can help with general recovery strategies once you've been cleared by a professional."
- NEVER diagnose injuries

**Emergency Symptoms:**
If user mentions chest pain, difficulty breathing, severe pain, bleeding, fainting, or emergency symptoms:
- IMMEDIATELY respond: "This sounds serious and requires immediate medical attention. Please call emergency services or go to the nearest emergency room right away. Your safety is the top priority."

**Eating Disorders & Mental Health:**
If you detect signs of eating disorders (extreme restriction, purging mentions, obsessive behavior, body dysmorphia):
- Respond with empathy: "I'm concerned about what you're sharing. Your wellbeing matters most. Please consider speaking with a healthcare professional or counselor who specializes in nutrition and mental health. I'm here to support healthy, sustainable habits."
- NEVER encourage extreme diets, very low calories (<1200), excessive exercise, or unhealthy weight loss methods
- If user mentions depression, anxiety, or mental health struggles affecting their fitness: acknowledge kindly and suggest professional support

=== USER PROFILE ===
Name: {user_profile.get('name', 'User')}
Age: {user_profile.get('age')}, Weight: {user_profile.get('weight')}kg, Height: {user_profile.get('height')}cm
Primary Goal: {user_profile.get('primary_goal')}
Target Weight: {user_profile.get('target_weight')}kg
Activity Level: {user_profile.get('activity_level')}
Daily Calorie Target (TDEE): {user_profile.get('tdee')} calories
Preferred Workouts: {', '.join(user_profile.get('preferred_workouts', [])) or 'Not specified'}
Dietary Preferences: {', '.join(user_profile.get('dietary_preferences', [])) or 'None specified'}

=== TODAY'S ACTUAL DATA ({today_progress.get('date')}) ===
Meals Logged: {meals_logged}
Total Calories: {total_calories} / {user_profile.get('tdee', 2000)} target
Macros - Protein: {total_protein}g | Carbs: {total_carbs}g | Fat: {total_fat}g
Water: {water_glasses} glasses
Steps: {steps}
Exercise: {exercise_minutes} minutes ({exercises_done} exercises completed)

=== RESPONSE GUIDELINES ===
- Use the EXACT numbers provided above when discussing today's progress
- Be encouraging, supportive, and motivating
- Keep responses conversational and friendly (not overly formal)
- Provide actionable, specific advice
- Reference their actual logged data to personalize responses
- Celebrate small wins and progress
- For off-topic questions, politely redirect: "I'm your health and fitness coach! I can help with workouts, nutrition, and reaching your goals. What would you like to know about those topics?"
- Always prioritize user safety and wellbeing over any fitness goal"""

        # Layer 2: append body-state behavioral guardrails (cycle/sleep/calorie/
        # already-done). These are the facts + hard rules that keep suggestions
        # safe and non-redundant.
        guardrail_block = render_guardrail_prompt(context.get('body_state'))
        if guardrail_block:
            prompt += "\n" + guardrail_block

        return prompt
    
    async def generate_chat_response(self, user_id: str, message: str) -> str:
        """Generate chat response with message persistence and guardrails"""
        try:
            print(f"💬 Generating chat response for user: {user_id}")
            
            # ===== STEP 1: Check topic relevance FIRST =====
            is_relevant, redirect_msg = self._check_topic_relevance(message)
            if not is_relevant:
                print(f"🚫 Off-topic message blocked: {message[:50]}...")
                # Save both messages for analytics
                try:
                    await self.supabase_service.save_chat_message(user_id, message, is_user=True)
                    await self.supabase_service.save_chat_message(user_id, redirect_msg, is_user=False)
                except Exception as e:
                    print(f"⚠️ Error saving redirect messages: {e}")
                return redirect_msg
            # ================================================
            
            # Save user message
            try:
                await self.supabase_service.save_chat_message(user_id, message, is_user=True)
            except Exception as e:
                print(f"⚠️ Error saving user message: {e}")

            # Rebuild today's context from source tables before the AI reads it.
            # Activity logging is now fire-and-forget on the client (so logging
            # and the dashboard stay fast), which means the cached daily context
            # can be slightly stale. Rebuilding here guarantees the coach always
            # sees the latest logged activities, regardless of the client.
            try:
                from services.chat_context_manager import get_context_manager
                from datetime import datetime as _dt
                await get_context_manager().rebuild_context(user_id, _dt.now().date())
                print("🔄 Rebuilt today's context before generating reply")
            except Exception as e:
                print(f"⚠️ Could not rebuild today's context before reply (using cached): {e}")

            # Try comprehensive context first, fallback to basic
            try:
                user_context = await self.get_comprehensive_context(user_id, include_weeks=4)
                print(f"📊 Using comprehensive context with weekly data: {user_context.get('has_weekly_data', False)}")
            except Exception as e:
                print(f"⚠️ Falling back to basic context: {e}")
                user_context = await self.get_enhanced_context(user_id)
            
            # Get recent messages
            recent_messages = []
            try:
                recent_messages = await self.supabase_service.get_recent_chat_context(user_id, limit=10)
                print(f"💬 Retrieved {len(recent_messages)} recent messages")
            except Exception as e:
                print(f"⚠️ Error getting recent chat context: {e}")
            
            # Create enhanced system prompt
            system_prompt = self._create_enhanced_system_prompt(user_context)
            print(f"📝 System prompt created: {len(system_prompt)} characters")
            
            # Build conversation for OpenAI
            messages = [{"role": "system", "content": system_prompt}]
            
            # Add recent conversation context
            for msg in recent_messages:
                role = "user" if msg.get("is_user") else "assistant"
                messages.append({"role": role, "content": msg.get("message", "")})
            
            # Add current message
            messages.append({"role": "user", "content": message})
            
            print(f"🤖 Calling OpenAI with {len(messages)} messages...")
            
            # Get AI response
            response = await self.openai_service.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                max_tokens=600
            )
            
            reply = response.choices[0].message.content.strip()
            print(f"✅ OpenAI response received: {len(reply)} characters")
            
            # ===== STEP 2: Add safety disclaimers if needed =====
            reply = self._add_safety_disclaimers(reply, message)
            # ===================================================

            # ===== STEP 3: Layer-3 deterministic guardrail post-check =====
            # Appends a corrective caveat if the reply pushes intensity while
            # menstruating / sleep-deprived, or nudges more food while over target.
            try:
                reply = post_check_response(reply, user_context.get('body_state'))
            except Exception as e:
                print(f"⚠️ Guardrail post-check skipped: {e}")
            # =============================================================
            
            # Save AI response
            try:
                await self.supabase_service.save_chat_message(user_id, reply, is_user=False)
            except Exception as e:
                print(f"⚠️ Error saving AI response: {e}")
            
            return reply
            
        except Exception as e:
            print(f"❌ Error generating chat response: {str(e)}")
            import traceback
            traceback.print_exc()
            return f"I'm having trouble connecting to my AI service. Please try again."

    async def get_comprehensive_context(self, user_id: str, include_weeks: int = 4) -> Dict[str, Any]:
        """Get comprehensive context including daily and weekly data"""
        try:
            # Get basic context first
            basic_context = await self.get_enhanced_context(user_id)
            
            # Try to add weekly context if available
            if self.weekly_manager:
                try:
                    current_week = await self.weekly_manager.get_or_create_weekly_context(user_id)
                    previous_weeks = await self.weekly_manager.get_recent_weeks_context(user_id, weeks_count=include_weeks)
                    
                    # Add weekly data to context
                    basic_context['current_week'] = current_week.get('summary', {})
                    basic_context['recent_weeks'] = previous_weeks
                    basic_context['has_weekly_data'] = True
                    
                    print(f"✅ Added weekly context: {len(previous_weeks)} weeks")
                except Exception as e:
                    print(f"⚠️ Could not get weekly context: {e}")
                    basic_context['has_weekly_data'] = False
            else:
                basic_context['has_weekly_data'] = False
            
            return basic_context
            
        except Exception as e:
            print(f"Error getting comprehensive context: {e}")
            return await self.get_enhanced_context(user_id)

    def _create_enhanced_system_prompt(self, context: Dict[str, Any]) -> str:
        """Create system prompt with weekly context if available"""
        # Start with basic prompt (which includes guardrails)
        base_prompt = self._create_system_prompt(context)
        
        # Add weekly context if available
        if context.get('has_weekly_data'):
            current_week = context.get('current_week', {})
            recent_weeks = context.get('recent_weeks', [])
            
            weekly_section = f"""

=== WEEKLY PROGRESS (This Week) ===
Average Daily Calories: {current_week.get('avg_calories', 'N/A')}
Total Workouts: {current_week.get('total_workouts', 0)}
Average Sleep: {current_week.get('avg_sleep', 'N/A')}h
Weight Change: {current_week.get('weight_change', 'N/A')}kg

=== RECENT TRENDS ===
You have access to {len(recent_weeks)} weeks of historical data. Use this to provide insights about progress patterns and trends."""
            return base_prompt + weekly_section
        
        return base_prompt

# Global instance
chat_service = None

def get_chat_service() -> HealthChatService:
    global chat_service
    if chat_service is None:
        chat_service = HealthChatService()
    return chat_service

def init_chat_service():
    global chat_service
    chat_service = HealthChatService()
    return chat_service