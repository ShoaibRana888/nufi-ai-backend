# services/supabase_service.py
from supabase import create_client, Client
import os
from typing import Dict, List, Optional, Any
import uuid
from datetime import datetime, date, timezone, timedelta

class SupabaseService:
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables")
        
        self.client: Client = create_client(url, key)
        print("✅ Supabase client initialized")
    
    # User Management Operations
    async def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new user in the database"""
        try:
            print(f"🔍 Creating user in Supabase: {user_data.get('email')}")
            
            if 'water_intake_glasses' not in user_data:
                water_intake = user_data.get('water_intake', 2.0)
                user_data['water_intake_glasses'] = round(water_intake * 4)

            # Ensure we have an ID
            if 'id' not in user_data:
                user_data['id'] = str(uuid.uuid4())
            
            # Insert user into Supabase
            response = self.client.table('users').insert(user_data).execute()
            
            if response.data:
                print(f"✅ User created successfully: {response.data[0]['id']}")
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
                
        except Exception as e:
            print(f"❌ Error creating user in Supabase: {e}")
            raise Exception(f"Failed to create user: {str(e)}")
    
    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID from database"""
        try:
            response = self.client.table('users') \
                .select("*") \
                .eq('id', user_id) \
                .single() \
                .execute()
            
            return response.data if response.data else None
            
        except Exception as e:
            print(f"❌ Supabase fetch error: {str(e)}")
            return None
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email"""
        try:
            print(f"🔍 Getting user by email: {email}")
            
            response = self.client.table('users').select('*').eq('email', email).execute()
            
            if response.data:
                print(f"✅ User found by email: {email}")
                return response.data[0]
            else:
                print(f"❌ User not found by email: {email}")
                return None
                
        except Exception as e:
            print(f"❌ Error getting user by email: {e}")
            return None
    
    async def update_user(self, user_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update user profile in database
        Handles all Phase 1-3 fields
        """
        try:
            # Add timestamp
            update_data['updated_at'] = datetime.utcnow().isoformat()
            
            # Handle array fields properly for PostgreSQL
            array_fields = ['sleep_issues', 'dietary_preferences', 'preferred_workouts', 
                          'medical_conditions', 'available_equipment']
            
            for field in array_fields:
                if field in update_data:
                    # Ensure it's a list and not None
                    if update_data[field] is None:
                        update_data[field] = []
                    elif not isinstance(update_data[field], list):
                        update_data[field] = [update_data[field]]
            
            # Execute update query
            response = self.client.table('users') \
                .update(update_data) \
                .eq('id', user_id) \
                .execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]
            else:
                return None
                
        except Exception as e:
            print(f"❌ Supabase update error: {str(e)}")
            raise

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile including step goal"""
        try:
            response = self.client.table('users').select('*').eq('id', user_id).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error getting user: {e}")
            return None
    
    # Meal Operations (we'll expand this later)
    async def create_meal_entry(self, meal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new meal entry"""
        try:
            print(f"🔍 Creating meal entry with data: {meal_data}")
            
            # Ensure all nutrition fields are present
            required_fields = ['fiber_g', 'sugar_g', 'sodium_mg']
            for field in required_fields:
                if field not in meal_data:
                    print(f"⚠️ Missing {field} in meal_data, setting to 0")
                    meal_data[field] = 0
            
            response = self.client.table('meal_entries').insert(meal_data).execute()
            
            if response.data:
                created_meal = response.data[0]
                return created_meal
            else:
                raise Exception("No data returned from insert")
                
        except Exception as e:
            print(f"❌ Error creating meal entry: {e}")
            import traceback
            traceback.print_exc()
            raise e
        
    async def get_meal_by_id(self, meal_id: str):
        """Get meal by ID"""
        try:
            response = self.client.table('meal_entries')\
                .select('*')\
                .eq('id', meal_id)\
                .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting meal: {e}")
            return None
        
    async def update_meal(self, meal_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a meal entry"""
        try:
            response = self.client.table('meal_entries').update(update_data).eq('id', meal_id).execute()
            return response.data[0] if response.data else {}
        except Exception as e:
            print(f"❌ Error updating meal: {e}")
            raise

    async def delete_meal(self, meal_id: str):
        """Delete meal entry"""
        try:
            response = self.client.table('meal_entries')\
                .delete()\
                .eq('id', meal_id)\
                .execute()
            
            return True
        except Exception as e:
            print(f"Error deleting meal: {e}")
            return False

    async def get_daily_nutrition(self, user_id: str, date: str) -> Optional[Dict[str, Any]]:
        """Get daily nutrition summary for a specific date"""
        try:
            response = self.client.table('daily_nutrition')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', date)\
                .execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error getting daily nutrition: {e}")
            return None

    async def create_daily_nutrition(self, nutrition_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new daily nutrition entry"""
        try:
            # Add timestamps
            nutrition_data['created_at'] = datetime.now().isoformat()
            nutrition_data['updated_at'] = datetime.now().isoformat()
            
            response = self.client.table('daily_nutrition').insert(nutrition_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating daily nutrition: {e}")
            raise Exception(f"Failed to create daily nutrition: {str(e)}")

    async def update_daily_nutrition(self, entry_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing daily nutrition entry"""
        try:
            # Add timestamp
            update_data['updated_at'] = datetime.now().isoformat()
            
            response = self.client.table('daily_nutrition')\
                .update(update_data)\
                .eq('id', entry_id)\
                .execute()
            
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error updating daily nutrition: {e}")
            raise Exception(f"Failed to update daily nutrition: {str(e)}")

    async def get_daily_nutrition_range(self, user_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get daily nutrition summaries for a date range"""
        try:
            response = self.client.table('daily_nutrition')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', start_date)\
                .lte('date', end_date)\
                .order('date', desc=True)\
                .execute()
            
            return response.data or []
        except Exception as e:
            print(f"❌ Error getting daily nutrition range: {e}")
            return []
        
    async def get_meals_by_date(self, user_id: str, date: date) -> List[Dict[str, Any]]:
        """Get all meals for a specific date"""
        try:
            next_day = date + timedelta(days=1)
            
            response = self.client.table('meal_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('meal_date', str(date))\
                .lt('meal_date', str(next_day))\
                .execute()
            
            meals = response.data if response.data else []
            print(f"✅ Found {len(meals)} meals for {date}")
            return meals
        except Exception as e:
            print(f"❌ Error getting meals by date: {e}")
            return []
        
    async def create_meal_preset(self, preset_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new meal preset"""
        try:
            response = self.client.table('meal_presets').insert(preset_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"❌ Error creating meal preset: {e}")
            raise

    async def get_user_meal_presets(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all meal presets for a user"""
        try:
            response = self.client.table('meal_presets')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('usage_count', desc=True)\
                .execute()
            return response.data or []
        except Exception as e:
            print(f"❌ Error getting meal presets: {e}")
            return []

    async def update_preset_usage(self, preset_id: str) -> None:
        """Increment usage count when preset is used"""
        try:
            # Get current count
            response = self.client.table('meal_presets')\
                .select('usage_count')\
                .eq('id', preset_id)\
                .execute()
            
            if response.data:
                current_count = response.data[0].get('usage_count', 0)
                
                # Update count and last used timestamp
                self.client.table('meal_presets')\
                    .update({
                        'usage_count': current_count + 1,
                        'last_used_at': datetime.now().isoformat()
                    })\
                    .eq('id', preset_id)\
                    .execute()
        except Exception as e:
            print(f"⚠️ Error updating preset usage: {e}")

    async def search_cached_meal(self, user_id: str, food_item: str, quantity: str) -> Optional[Dict[str, Any]]:
        """Search for previously logged identical meal"""
        try:
            import hashlib
            # Generate consistent hash for this meal
            search_hash = hashlib.md5(
                f"{food_item.lower().strip()}::{quantity.lower().strip()}".encode()
            ).hexdigest()
            
            # Look for recent identical meal (last 30 days)
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            
            response = self.client.table('meal_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('search_hash', search_hash)\
                .gte('logged_at', thirty_days_ago)\
                .order('logged_at', desc=True)\
                .limit(1)\
                .execute()
            
            if response.data:
                print(f"✅ Found cached meal: {food_item}")
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error searching cached meal: {e}")
            return None

    async def get_recent_unique_meals(self, user_id: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Get recent unique meals for suggestions"""
        try:
            # Get more meals initially to ensure we have enough unique ones after deduplication
            response = self.client.table('meal_entries')\
                .select('food_item, quantity, calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, meal_type, logged_at, nutrition_data')\
                .eq('user_id', user_id)\
                .order('logged_at', desc=True)\
                .limit(100)\
                .execute()
            
            # Deduplicate by food_item only (not quantity) for more variety
            seen = set()
            unique_meals = []
            
            for meal in response.data or []:
                # Create a normalized key from food_item
                food_item = meal['food_item'].lower().strip()
                
                # Skip if we've already seen this exact food item
                if food_item not in seen:
                    seen.add(food_item)
                    unique_meals.append(meal)
                    
                    # Stop once we have enough unique meals
                    if len(unique_meals) >= limit:
                        break
            
            print(f"✅ Found {len(unique_meals)} unique meals from {len(response.data or [])} total meals")
            return unique_meals
            
        except Exception as e:
            print(f"❌ Error getting recent meals: {e}")
            return []
    
    # Chat/Conversation Operations (placeholder for later)
    async def create_conversation(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a conversation entry (placeholder for later)"""
        try:
            print(f"🔍 Creating conversation for user: {conversation_data.get('user_id')}")
            
            if 'id' not in conversation_data:
                conversation_data['id'] = str(uuid.uuid4())
            
            response = self.client.table('conversations').insert(conversation_data).execute()
            
            if response.data:
                print(f"✅ Conversation created: {response.data[0]['id']}")
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
                
        except Exception as e:
            print(f"❌ Error creating conversation: {e}")
            raise Exception(f"Failed to create conversation: {str(e)}")
    
    # Health check method
    async def health_check(self) -> Dict[str, Any]:
        """Check if Supabase connection is working"""
        try:
            # Simple query to test connection
            response = self.client.table('users').select('count').execute()
            
            return {
                "status": "healthy",
                "message": "Supabase connection working",
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Supabase connection failed: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }

    async def get_user_meals(self, user_id: str, limit: int = 20, date_from: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get user meals for date range"""
        try:
            print(f"🔍 Getting meals for user: {user_id}")
        
            query = self.client.table('meal_entries').select('*').eq('user_id', user_id)
        
            if date_from:
                query = query.gte('meal_date', date_from)
        
            response = query.order('meal_date', desc=True).limit(limit).execute()
        
            print(f"✅ Found {len(response.data)} meals")
            return response.data or []
        
        except Exception as e:
            print(f"❌ Error getting user meals: {e}")
            return []
        
    async def get_user_meals_by_date(self, user_id: str, date: str) -> List[Dict[str, Any]]:
        """Get user meals for a specific date"""
        try:
            print(f"🔍 Getting meals for user: {user_id}, date: {date}")
    
            # Handle different date formats
            if 'T' in date:
                date = date.split('T')[0]  # Extract just the date part
    
            # Query meals for the specific date - explicitly select all fields
            start_date = f"{date}T00:00:00"
            end_date = f"{date}T23:59:59"
    
            response = self.client.table('meal_entries').select(
                'id, user_id, food_item, quantity, meal_type, calories, '
                'protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, '
                'meal_date, logged_at, nutrition_data, preparation'
            ).eq(
                'user_id', user_id
            ).gte(
                'meal_date', start_date
            ).lte(
                'meal_date', end_date
            ).order('meal_date', desc=True).execute()
    
            meals = response.data or []
        
            # Debug: Check what we're getting
            print(f"✅ Found {len(meals)} meals for {date}")
            for meal in meals:
                print(f"   Meal: {meal.get('food_item')} - fiber: {meal.get('fiber_g')}, sugar: {meal.get('sugar_g')}, sodium: {meal.get('sodium_mg')}")
        
            return meals
    
        except Exception as e:
            print(f"❌ Error getting meals by date: {e}")
            import traceback
            traceback.print_exc()
            return []
        
    # water functions
    async def get_water_entry_by_date(self, user_id: str, entry_date: date) -> Optional[Dict[str, Any]]:
        """Get water entry for a specific date"""
        try:
            response = self.client.table('daily_water')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(entry_date))\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error getting water entry by date: {e}")
            return None
        
    async def get_water_by_date(self, user_id: str, date: date) -> Optional[Dict[str, Any]]:
        """Get water intake for a specific date - FIXED VERSION"""
        try:
            print(f"🔍 Getting water for user: {user_id}, date: {date}")
            
            # ✅ FIX: Check if your table uses 'date' or 'log_date' column
            # I'll provide both versions:
            
            # VERSION A: If column is called 'date'
            response = self.client.table('daily_water')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(date))\
                .execute()
            
            # VERSION B: If column is called 'log_date' (uncomment if needed)
            # response = self.client.table('daily_water')\
            #     .select('*')\
            #     .eq('user_id', user_id)\
            #     .eq('log_date', str(date))\
            #     .execute()
            
            if response.data:
                entry = response.data[0]
                print(f"✅ Found water entry for {date}: {entry.get('glasses_consumed')} glasses")
                return entry
            
            print(f"ℹ️ No water entry found for {date}")
            return None
        except Exception as e:
            print(f"❌ Error getting water by date: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def delete_water_entry(self, entry_id: str):
        """Delete water entry"""
        try:
            response = self.client.table('daily_water')\
                .delete()\
                .eq('id', entry_id)\
                .execute()
            
            return True
        except Exception as e:
            print(f"Error deleting water entry: {e}")
            return False

    async def create_water_entry(self, water_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new water entry"""
        try:
            response = self.client.table('daily_water').insert(water_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating water entry: {e}")
            raise Exception(f"Failed to create water entry: {str(e)}")

    async def update_water_entry(self, entry_id: str, water_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing water entry"""
        try:
            response = self.client.table('daily_water').update(water_data).eq('id', entry_id).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error updating water entry: {e}")
            raise Exception(f"Failed to update water entry: {str(e)}")

    async def get_water_history(self, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Get water intake history for a user"""
        try:
            print(f"🔍 Getting {limit} water entries for user: {user_id}")
            
            response = self.client.table('daily_water')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('date', desc=True)\
                .limit(limit)\
                .execute()
            
            if response.data:
                # Format the data to ensure consistency
                formatted_entries = []
                for entry in response.data:
                    formatted_entry = {
                        'id': entry['id'],
                        'user_id': entry['user_id'],
                        'date': entry['date'],
                        'glasses_consumed': entry.get('glasses_consumed', 0),
                        'total_ml': float(entry.get('total_ml', 0.0)),
                        'target_ml': float(entry.get('target_ml', 2000.0)),
                        'notes': entry.get('notes'),
                        'created_at': entry.get('created_at'),
                        'updated_at': entry.get('updated_at')
                    }
                    formatted_entries.append(formatted_entry)
                
                print(f"✅ Retrieved {len(formatted_entries)} water entries")
                return formatted_entries
            
            return []
        except Exception as e:
            print(f"❌ Error getting water history: {e}")
            return []

    async def get_water_entries_in_range(self, user_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get water entries within a date range"""
        try:
            response = self.client.table('daily_water')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', start_date)\
                .lte('date', end_date)\
                .order('date', desc=True)\
                .execute()
            
            return response.data or []
        except Exception as e:
            print(f"❌ Error getting water entries in range: {e}")
            return []
        
    # Step functions
    async def create_step_entry(self, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new step entry"""
        try:
            response = self.client.table('daily_steps').insert(step_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating step entry: {e}")
            raise Exception(f"Failed to create step entry: {str(e)}")

    async def update_step_entry(self, entry_id: str, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing step entry"""
        try:
            response = self.client.table('daily_steps').update(step_data).eq('id', entry_id).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error updating step entry: {e}")
            raise Exception(f"Failed to update step entry: {str(e)}")

    async def get_step_entry_by_date(self, user_id: str, entry_date: date) -> Optional[Dict[str, Any]]:
        """Get step entry for a specific date"""
        try:
            response = self.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(entry_date))\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error getting step entry by date: {e}")
            return None

    async def get_step_history(self, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Get step history for a user"""
        try:
            print(f"🔍 Getting {limit} step entries for user: {user_id}")
            
            response = self.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('date', desc=True)\
                .limit(limit)\
                .execute()
            
            if response.data:
                # Format the data to ensure consistency
                formatted_entries = []
                for entry in response.data:
                    formatted_entry = {
                        'id': entry['id'],
                        'userId': entry['user_id'],  # Convert to Flutter format
                        'date': entry['date'],
                        'steps': entry.get('steps', 0),
                        'goal': entry.get('goal', 10000),
                        'caloriesBurned': float(entry.get('calories_burned', 0.0)),
                        'distanceKm': float(entry.get('distance_km', 0.0)),
                        'activeMinutes': entry.get('active_minutes', 0),
                        'sourceType': entry.get('source_type', 'manual'),
                        'lastSynced': entry.get('last_synced'),
                        'createdAt': entry.get('created_at'),
                        'updatedAt': entry.get('updated_at')
                    }
                    formatted_entries.append(formatted_entry)
                
                print(f"✅ Retrieved {len(formatted_entries)} step entries")
                return formatted_entries
            
            return []
        except Exception as e:
            print(f"❌ Error getting step history: {e}")
            return []

    async def get_step_entries_in_range(self, user_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get step entries within a date range"""
        try:
            response = self.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', start_date)\
                .lte('date', end_date)\
                .order('date', desc=True)\
                .execute()
            
            if response.data:
                # Format for Flutter
                formatted_entries = []
                for entry in response.data:
                    formatted_entry = {
                        'id': entry['id'],
                        'userId': entry['user_id'],
                        'date': entry['date'],
                        'steps': entry.get('steps', 0),
                        'goal': entry.get('goal', 10000),
                        'caloriesBurned': float(entry.get('calories_burned', 0.0)),
                        'distanceKm': float(entry.get('distance_km', 0.0)),
                        'activeMinutes': entry.get('active_minutes', 0),
                        'sourceType': entry.get('source_type', 'manual'),
                        'lastSynced': entry.get('last_synced'),
                        'createdAt': entry.get('created_at'),
                        'updatedAt': entry.get('updated_at')
                    }
                    formatted_entries.append(formatted_entry)
                return formatted_entries
            
            return []
        except Exception as e:
            print(f"❌ Error getting step entries in range: {e}")
            return []

    async def delete_step_entry_by_date(self, user_id: str, entry_date: date) -> bool:
        """Delete step entry for a specific date"""
        try:
            response = self.client.table('daily_steps')\
                .delete()\
                .eq('user_id', user_id)\
                .eq('date', str(entry_date))\
                .execute()
            
            return True
        except Exception as e:
            print(f"❌ Error deleting step entry: {e}")
            return False
        
    async def get_steps_in_range(
        self, 
        user_id: str, 
        start_date: date, 
        end_date: date
    ) -> List[Dict[str, Any]]:
        """Get step entries for a date range"""
        try:
            response = self.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', str(start_date))\
                .lte('date', str(end_date))\
                .order('date', desc=False)\
                .execute()
            
            if response.data:
                return response.data
            return []
        except Exception as e:
            print(f"❌ Error getting steps in range: {e}")
            return []
        
    async def get_steps_by_date(self, user_id: str, date: date) -> Optional[Dict[str, Any]]:
        """Get step count for a specific date - FIXED VERSION"""
        try:
            print(f"🔍 Getting steps for user: {user_id}, date: {date}")
            
            response = self.client.table('daily_steps')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(date))\
                .execute()
            
            if response.data:
                entry = response.data[0]
                print(f"✅ Found step entry for {date}: {entry.get('steps')} steps")
                return entry
            
            print(f"ℹ️ No step entry found for {date}")
            return None
        except Exception as e:
            print(f"❌ Error getting steps by date: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    
    # Weight functions
    async def create_weight_entry(self, weight_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new weight entry"""
        try:
            response = self.client.table('weight_entries').insert(weight_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating weight entry: {e}")
            raise Exception(f"Failed to create weight entry: {str(e)}")

    async def get_weight_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get weight history for a user"""
        try:
            print(f"🔍 Getting {limit} weight entries for user: {user_id}")
            
            response = self.client.table('weight_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('date', desc=True)\
                .limit(limit)\
                .execute()
            
            if response.data:
                # Format the data to ensure consistency
                formatted_entries = []
                for entry in response.data:
                    formatted_entry = {
                        'id': entry['id'],
                        'user_id': entry['user_id'],
                        'date': entry['date'],
                        'weight': float(entry.get('weight', 0.0)),
                        'notes': entry.get('notes'),
                        'body_fat_percentage': float(entry['body_fat_percentage']) if entry.get('body_fat_percentage') else None,
                        'muscle_mass_kg': float(entry['muscle_mass_kg']) if entry.get('muscle_mass_kg') else None,
                        'created_at': entry.get('created_at'),
                        'updated_at': entry.get('updated_at')
                    }
                    formatted_entries.append(formatted_entry)
                
                print(f"✅ Retrieved {len(formatted_entries)} weight entries")
                return formatted_entries
            
            return []
        except Exception as e:
            print(f"❌ Error getting weight history: {e}")
            return []

    async def get_weight_entries(
        self,
        user_id: str,
        start_date: str = None,
        end_date: str = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get weight entries for a user, optionally filtered by a date range"""
        try:
            query = self.client.table('weight_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('date', desc=False)

            if start_date:
                query = query.gte('date', start_date)
            if end_date:
                query = query.lte('date', end_date)

            response = query.limit(limit).execute()
            return response.data or []
        except Exception as e:
            print(f"❌ Error getting weight entries: {e}")
            return []

    async def get_latest_weight(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest weight entry for a user"""
        try:
            response = self.client.table('weight_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('date', desc=True)\
                .limit(1)\
                .execute()
            
            if response.data:
                entry = response.data[0]
                return {
                    'id': entry['id'],
                    'user_id': entry['user_id'],
                    'date': entry['date'],
                    'weight': float(entry.get('weight', 0.0)),
                    'notes': entry.get('notes'),
                    'body_fat_percentage': float(entry['body_fat_percentage']) if entry.get('body_fat_percentage') else None,
                    'muscle_mass_kg': float(entry['muscle_mass_kg']) if entry.get('muscle_mass_kg') else None,
                    'created_at': entry.get('created_at'),
                    'updated_at': entry.get('updated_at')
                }
            return None
        except Exception as e:
            print(f"❌ Error getting latest weight: {e}")
            return None

    async def delete_weight_entry(self, entry_id: str) -> bool:
        """Delete a weight entry"""
        try:
            response = self.client.table('weight_entries')\
                .delete()\
                .eq('id', entry_id)\
                .execute()
            
            return True
        except Exception as e:
            print(f"❌ Error deleting weight entry: {e}")
            return False
        
    async def get_weight_entry_by_id(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Get a weight entry by ID"""
        try:
            response = self.client.table('weight_entries')\
                .select('*')\
                .eq('id', entry_id)\
                .limit(1)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error getting weight entry by ID: {e}")
            return None
        
    async def get_weight_by_date(self, user_id: str, date: date) -> Optional[Dict[str, Any]]:
        """Get weight entry for a specific date - FIXED VERSION"""
        try:
            print(f"🔍 Getting weight for user: {user_id}, date: {date}")
            
            response = self.client.table('weight_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(date))\
                .order('date', desc=True)\
                .limit(1)\
                .execute()
            
            if response.data:
                entry = response.data[0]
                print(f"✅ Found weight entry for {date}: {entry.get('weight')}kg")
                return {
                    'id': entry['id'],
                    'user_id': entry['user_id'],
                    'date': entry['date'],
                    'weight': float(entry.get('weight', 0.0)),
                    'notes': entry.get('notes'),
                    'body_fat_percentage': float(entry['body_fat_percentage']) if entry.get('body_fat_percentage') else None,
                    'muscle_mass_kg': float(entry['muscle_mass_kg']) if entry.get('muscle_mass_kg') else None,
                    'created_at': entry.get('created_at'),
                    'updated_at': entry.get('updated_at')
                }
            
            print(f"ℹ️ No weight entry found for {date}")
            return None
        except Exception as e:
            print(f"❌ Error getting weight by date: {e}")
            import traceback
            traceback.print_exc()
            return None
        
    async def update_user_weight(self, user_id: str, weight: float) -> bool:
        """Update user's current weight in the users table"""
        try:
            response = self.client.table('users')\
                .update({'weight': weight})\
                .eq('id', user_id)\
                .execute()
            
            print(f"✅ Updated user's weight to {weight} kg in profile")
            return True
        except Exception as e:
            print(f"❌ Error updating user weight: {e}")
            return False

    async def initialize_starting_weight(self, user_id: str) -> bool:
        """Initialize starting weight if not set (for new or existing users)"""
        try:
            user = await self.get_user_by_id(user_id)
            
            # Only initialize if starting_weight is not set
            if user and not user.get('starting_weight'):
                # Try to get the oldest weight entry
                oldest_entry_response = self.client.table('weight_entries')\
                    .select('weight, date')\
                    .eq('user_id', user_id)\
                    .order('date', desc=False)\
                    .limit(1)\
                    .execute()
                
                if oldest_entry_response.data:
                    # Use oldest entry
                    starting_weight = oldest_entry_response.data[0]['weight']
                    starting_date = oldest_entry_response.data[0]['date']
                else:
                    # Use current weight as starting weight
                    starting_weight = user.get('weight')
                    starting_date = user.get('created_at')
                
                if starting_weight:
                    self.client.table('users')\
                        .update({
                            'starting_weight': starting_weight,
                            'starting_weight_date': starting_date
                        })\
                        .eq('id', user_id)\
                        .execute()
                    
                    print(f"✅ Initialized starting weight to {starting_weight} kg for user {user_id}")
                    return True
            
            return False
        except Exception as e:
            print(f"❌ Error initializing starting weight: {e}")
            return False
        
    async def initialize_starting_weight_for_user(self, user_id: str) -> bool:
        """Initialize starting weight for a user who doesn't have it set"""
        try:
            user = await self.get_user_by_id(user_id)
            
            # Only initialize if starting_weight is not set
            if user and not user.get('starting_weight'):
                # Try to get the oldest weight entry
                oldest_entry_response = self.client.table('weight_entries')\
                    .select('weight, date')\
                    .eq('user_id', user_id)\
                    .order('date', desc=False)\
                    .limit(1)\
                    .execute()
                
                if oldest_entry_response.data:
                    # Use oldest entry - most accurate
                    starting_weight = oldest_entry_response.data[0]['weight']
                    starting_date = oldest_entry_response.data[0]['date']
                    print(f"📊 Using oldest weight entry: {starting_weight} kg from {starting_date}")
                else:
                    # Use current weight as starting weight
                    starting_weight = user.get('weight')
                    starting_date = user.get('created_at')
                    print(f"📊 Using profile weight as starting weight: {starting_weight} kg")
                
                if starting_weight:
                    self.client.table('users')\
                        .update({
                            'starting_weight': starting_weight,
                            'starting_weight_date': starting_date
                        })\
                        .eq('id', user_id)\
                        .execute()
                    
                    print(f"✅ Initialized starting weight to {starting_weight} kg for user {user_id}")
                    return True
            
            return False
        except Exception as e:
            print(f"❌ Error initializing starting weight: {e}")
            return False

    async def migrate_all_users_starting_weights(self) -> dict:
        """Migrate starting weights for all users who don't have it set"""
        try:
            # Get all users without starting_weight
            response = self.client.table('users')\
                .select('id, weight, created_at')\
                .is_('starting_weight', 'null')\
                .execute()
            
            users_to_migrate = response.data
            migrated_count = 0
            failed_count = 0
            
            print(f"📊 Found {len(users_to_migrate)} users to migrate")
            
            for user in users_to_migrate:
                try:
                    success = await self.initialize_starting_weight_for_user(user['id'])
                    if success:
                        migrated_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    print(f"❌ Failed to migrate user {user['id']}: {e}")
                    failed_count += 1
            
            return {
                'total': len(users_to_migrate),
                'migrated': migrated_count,
                'failed': failed_count
            }
        except Exception as e:
            print(f"❌ Error in migration: {e}")
            return {'error': str(e)}
        
    # sleep functions
    async def create_sleep_entry(self, sleep_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new sleep entry"""
        try:
            response = self.client.table('sleep_entries').insert(sleep_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating sleep entry: {e}")
            raise Exception(f"Failed to create sleep entry: {str(e)}")

    async def update_sleep_entry(self, entry_id: str, sleep_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing sleep entry"""
        try:
            response = self.client.table('sleep_entries').update(sleep_data).eq('id', entry_id).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error updating sleep entry: {e}")
            raise Exception(f"Failed to update sleep entry: {str(e)}")

    async def get_sleep_entry_by_date(self, user_id: str, entry_date: date) -> Optional[Dict[str, Any]]:
        """Get sleep entry for a specific date"""
        try:
            response = self.client.table('sleep_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('date', str(entry_date))\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error getting sleep entry by date: {e}")
            return None
        
    async def get_sleep_by_date(self, user_id: str, date: date) -> Optional[Dict[str, Any]]:
        """Get sleep entry for a specific date"""
        try:
            next_day = date + timedelta(days=1)
            
            response = self.client.table('sleep_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', str(date))\
                .lt('date', str(next_day))\
                .execute()
            
            if response.data:
                print(f"✅ Found sleep entry for {date}: {response.data[0].get('total_hours')}h")
                return response.data[0]
            
            return None
        except Exception as e:
            print(f"❌ Error getting sleep by date: {e}")
            return None
        
    async def get_sleep_entry_by_id(self, entry_id: str):
        """Get sleep entry by ID"""
        try:
            response = self.client.table('sleep_entries')\
                .select('*')\
                .eq('id', entry_id)\
                .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting sleep entry: {e}")
            return None

    async def get_sleep_history(self, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Get sleep history for a user"""
        try:
            print(f"🔍 Getting {limit} sleep entries for user: {user_id}")
            
            response = self.client.table('sleep_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('date', desc=True)\
                .limit(limit)\
                .execute()
            
            if response.data:
                print(f"✅ Retrieved {len(response.data)} sleep entries")
                return response.data
            
            return []
        except Exception as e:
            print(f"❌ Error getting sleep history: {e}")
            return []

    async def delete_sleep_entry(self, entry_id: str) -> bool:
        """Delete a sleep entry"""
        try:
            response = self.client.table('sleep_entries')\
                .delete()\
                .eq('id', entry_id)\
                .execute()
            
            return True
        except Exception as e:
            print(f"❌ Error deleting sleep entry: {e}")
            return False
        
    # supplements functions
    async def create_supplement_preference(self, preference_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new supplement preference"""
        try:
            response = self.client.table('supplement_preferences').insert(preference_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating supplement preference: {e}")
            raise Exception(f"Failed to create supplement preference: {str(e)}")

    async def get_supplement_preferences(self, user_id: str) -> List[Dict[str, Any]]:
        """Get supplement preferences for a user"""
        try:
            print(f"🔍 Getting supplement preferences for user: {user_id}")
            
            response = self.client.table('supplement_preferences')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('is_active', True)\
                .order('created_at', desc=False)\
                .execute()
            
            if response.data:
                print(f"✅ Retrieved {len(response.data)} supplement preferences")
                return response.data
            
            return []
        except Exception as e:
            print(f"❌ Error getting supplement preferences: {e}")
            return []

    async def clear_supplement_preferences(self, user_id: str) -> bool:
        """Clear all supplement preferences for a user (mark as inactive)"""
        try:
            response = self.client.table('supplement_preferences')\
                .update({'is_active': False, 'updated_at': datetime.now().isoformat()})\
                .eq('user_id', user_id)\
                .execute()
            
            return True
        except Exception as e:
            print(f"❌ Error clearing supplement preferences: {e}")
            return False

    async def create_supplement_log(self, log_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new supplement log entry"""
        try:
            response = self.client.table('supplement_logs').insert(log_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating supplement log: {e}")
            raise Exception(f"Failed to create supplement log: {str(e)}")

    async def update_supplement_log(self, log_id: str, log_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing supplement log entry"""
        try:
            response = self.client.table('supplement_logs').update(log_data).eq('id', log_id).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error updating supplement log: {e}")
            raise Exception(f"Failed to update supplement log: {str(e)}")

    async def get_supplement_log_by_date(self, user_id: str, supplement_name: str, entry_date: date) -> Optional[Dict[str, Any]]:
        """Get supplement log for a specific supplement and date"""
        try:
            response = self.client.table('supplement_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .eq('supplement_name', supplement_name)\
                .eq('date', str(entry_date))\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error getting supplement log by date: {e}")
            return None

    async def get_supplement_status_by_date(self, user_id: str, entry_date: date) -> Dict[str, Any]:
        """Get supplement status for all supplements on a specific date - FIXED VERSION"""
        try:
            print(f"🔍 Getting supplements for user: {user_id}, date: {entry_date}")
            
            response = self.client.table('supplement_logs')\
                .select('supplement_name, taken')\
                .eq('user_id', user_id)\
                .eq('date', str(entry_date))\
                .execute()
            
            status = {}
            if response.data:
                for log in response.data:
                    status[log['supplement_name']] = {
                        'taken': log['taken'],
                        'supplement_name': log['supplement_name']
                    }
                print(f"✅ Found {len(status)} supplement logs for {entry_date}")
            else:
                print(f"ℹ️ No supplement logs found for {entry_date}")
            
            return status
        except Exception as e:
            print(f"❌ Error getting supplement status by date: {e}")
            return {}

    async def get_supplement_history(self, user_id: str, supplement_name: Optional[str] = None, days: int = 30) -> List[Dict[str, Any]]:
        """Get supplement history for a user"""
        try:
            print(f"🔍 Getting supplement history for user: {user_id}")
            
            # Calculate date range
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=days)
            
            query = self.client.table('supplement_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('date', str(start_date))\
                .lte('date', str(end_date))\
                .order('date', desc=True)
            
            if supplement_name:
                query = query.eq('supplement_name', supplement_name)
            
            response = query.execute()
            
            if response.data:
                print(f"✅ Retrieved {len(response.data)} supplement history records")
                return response.data
            
            return []
        except Exception as e:
            print(f"❌ Error getting supplement history: {e}")
            return []

    async def delete_supplement_preference(self, preference_id: str) -> bool:
        """Delete a supplement preference"""
        try:
            response = self.client.table('supplement_preferences')\
                .update({'is_active': False, 'updated_at': datetime.now().isoformat()})\
                .eq('id', preference_id)\
                .execute()
            
            return True
        except Exception as e:
            print(f"❌ Error deleting supplement preference: {e}")
            return False
    
    # Exercise methods
    async def create_exercise_log(self, exercise_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new exercise log entry"""
        try:
            # Ensure muscle_group is included
            if 'muscle_group' not in exercise_data and 'exercise_type' in exercise_data:
                exercise_data['muscle_group'] = 'general'
                
            response = self.client.table('exercise_logs').insert(exercise_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating exercise log: {e}")
            raise Exception(f"Failed to create exercise log: {str(e)}")

    async def get_exercise_logs(self, user_id: str, exercise_type: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get exercise logs for a user"""
        try:
            print(f"🔍 Getting exercise logs for user: {user_id}")
            print(f"🔍 Filters - type: {exercise_type}, start: {start_date}, end: {end_date}, limit: {limit}")
            
            query = self.client.table('exercise_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('exercise_date', desc=True)\
                .limit(limit)
            
            # Apply date filters if provided
            if start_date and end_date:
                if start_date == end_date:
                    # ✅ For same day filtering, use date range for the entire day
                    start_datetime = f"{start_date}T00:00:00"
                    end_datetime = f"{end_date}T23:59:59"
                    query = query.gte('exercise_date', start_datetime).lte('exercise_date', end_datetime)
                    print(f"🔍 Same day filter: {start_datetime} to {end_datetime}")
                else:
                    # Different start and end dates
                    query = query.gte('exercise_date', start_date).lte('exercise_date', end_date)
                    print(f"🔍 Date range filter: {start_date} to {end_date}")
            elif start_date:
                query = query.gte('exercise_date', start_date)
                print(f"🔍 Start date filter: >= {start_date}")
            elif end_date:
                query = query.lte('exercise_date', end_date)
                print(f"🔍 End date filter: <= {end_date}")
                
            if exercise_type:
                query = query.eq('exercise_type', exercise_type)
                print(f"🔍 Exercise type filter: {exercise_type}")
            
            response = query.execute()
            
            logs = response.data or []
            print(f"✅ Retrieved {len(logs)} exercise logs")

            for log in logs:
                if log.get('duration_minutes') is None or log.get('duration_minutes') == 0:
                    print(f"⚠️ Warning: Exercise {log.get('exercise_name')} has no duration, calculating...")
                    # Calculate on the fly for old/corrupted records
                    if log.get('exercise_type') == 'strength' and log.get('sets'):
                        log['duration_minutes'] = log['sets'] * 2
                    else:
                        log['duration_minutes'] = 5
            
            # Debug the logs
            for i, log in enumerate(logs):
                print(f"🔍 Log {i+1}: {log.get('exercise_name')} - {log.get('duration_minutes')}min on {log.get('exercise_date')}")
            
            return logs
        except Exception as e:
            print(f"❌ Error getting exercise logs: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def delete_exercise_log(self, exercise_id: str) -> bool:
        """Delete an exercise log"""
        try:
            response = self.client.table('exercise_logs')\
                .delete()\
                .eq('id', exercise_id)\
                .execute()
            
            return True
        except Exception as e:
            print(f"❌ Error deleting exercise log: {e}")
            return False
        
    async def get_exercise_by_id(self, exercise_id: str):
        """Get exercise by ID"""
        try:
            response = self.client.table('exercise_logs')\
                .select('*')\
                .eq('id', exercise_id)\
                .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting exercise: {e}")
            return None
        
    async def get_exercises_by_date(self, user_id: str, date: date) -> List[Dict[str, Any]]:
        """Get all exercises for a specific date"""
        try:
            next_day = date + timedelta(days=1)
            
            response = self.client.table('exercise_logs')\
                .select('*')\
                .eq('user_id', user_id)\
                .gte('exercise_date', str(date))\
                .lt('exercise_date', str(next_day))\
                .execute()
            
            exercises = response.data or []
            print(f"✅ Found {len(exercises)} exercises for {date}")
            return exercises
        except Exception as e:
            print(f"❌ Error getting exercises by date: {e}")
            return []

    # Period methods
    async def create_period_entry(self, period_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new period entry"""
        try:
            response = self.client.table('period_entries').insert(period_data).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error creating period entry: {e}")
            raise Exception(f"Failed to create period entry: {str(e)}")

    async def update_period_entry(self, entry_id: str, period_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing period entry"""
        try:
            response = self.client.table('period_entries').update(period_data).eq('id', entry_id).execute()
            if response.data:
                return response.data[0]
            else:
                raise Exception("No data returned from Supabase")
        except Exception as e:
            print(f"❌ Error updating period entry: {e}")
            raise Exception(f"Failed to update period entry: {str(e)}")

    async def get_period_history(self, user_id: str, limit: int = 12) -> List[Dict[str, Any]]:
        """Get period history for a user"""
        try:
            response = self.client.table('period_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .order('start_date', desc=True)\
                .limit(limit)\
                .execute()
            
            return response.data or []
        except Exception as e:
            print(f"❌ Error getting period history: {e}")
            return []

    async def get_current_period(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get current ongoing period (no end date)"""
        try:
            response = self.client.table('period_entries')\
                .select('*')\
                .eq('user_id', user_id)\
                .is_('end_date', 'null')\
                .order('start_date', desc=True)\
                .limit(1)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"❌ Error getting current period: {e}")
            return None

    async def delete_period_entry(self, entry_id: str) -> bool:
        """Delete a period entry"""
        try:
            response = self.client.table('period_entries')\
                .delete()\
                .eq('id', entry_id)\
                .execute()
            
            return True
        except Exception as e:
            print(f"❌ Error deleting period entry: {e}")
            return False
    
    async def save_chat_message(self, user_id: str, message: str, is_user: bool) -> bool:
        """Save a chat message"""
        try:
            # Get or create today's session
            session_id = await self.get_or_create_daily_session(user_id)
            
            message_data = {
                "user_id": user_id,
                "message": message,
                "is_user": is_user,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Add session_id if we have one
            if session_id:
                message_data["session_id"] = session_id
            
            self.client.table("chat_messages").insert(message_data).execute()
            return True
        except Exception as e:
            print(f"Error saving chat message: {e}")
            return False

    async def get_chat_messages(self, user_id: str, limit: int = 50, session_id: str = None) -> List[Dict]:
        """Get chat messages for a user"""
        try:
            query = self.client.table("chat_messages")\
                .select("*")\
                .eq("user_id", user_id)\
                .order("created_at", desc=False)\
                .limit(limit)
            
            if session_id:
                query = query.eq("session_id", session_id)
            
            result = query.execute()
            return result.data if result.data else []
        except Exception as e:
            print(f"Error getting chat messages: {e}")
            return []

    async def clear_chat_messages(self, user_id: str) -> bool:
        """Clear all chat messages for a user"""
        try:
            self.client.table("chat_messages")\
                .delete()\
                .eq("user_id", user_id)\
                .execute()
            return True
        except Exception as e:
            print(f"Error clearing chat messages: {e}")
            return False

    async def get_recent_chat_context(self, user_id: str, limit: int = 10) -> List[Dict]:
        """Get recent messages for AI context"""
        try:
            result = self.client.table("chat_messages")\
                .select("message, is_user, created_at")\
                .eq("user_id", user_id)\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()
            
            messages = result.data if result.data else []
            return list(reversed(messages))  # Return in chronological order
        except Exception as e:
            print(f"Error getting recent chat context: {e}")
            return []
    
    async def create_chat_session(self, user_id: str, title: str = None) -> Dict[str, Any]:
        """Create a new chat session"""
        try:
            session_data = {
                "user_id": user_id,
                "title": title or "New Chat",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            response = self.client.table("chat_sessions").insert(session_data).execute()
            return response.data[0]
        except Exception as e:
            print(f"Error creating chat session: {e}")
            raise e

    async def get_or_create_daily_session(self, user_id: str) -> str:
        """Get today's session or create a new one"""
        try:
            today = datetime.now().date()
            
            # Look for today's session
            response = self.client.table("chat_sessions")\
                .select("id")\
                .eq("user_id", user_id)\
                .gte("created_at", f"{today}T00:00:00")\
                .lte("created_at", f"{today}T23:59:59")\
                .order("created_at", desc=True)\
                .limit(1)\
                .execute()
            
            if response.data:
                return response.data[0]["id"]
            
            # Create new session for today
            session = await self.create_chat_session(user_id, f"Health Chat - {today}")
            return session["id"]
        except Exception as e:
            print(f"Error getting/creating daily session: {e}")
            # Fallback - continue without session_id
            return None

# Global instance - we'll initialize this in main.py
supabase_service = None

def get_supabase_service() -> SupabaseService:
    """Get the global Supabase service instance"""
    global supabase_service
    if supabase_service is None:
        supabase_service = SupabaseService()
    return supabase_service

def init_supabase_service():
    """Initialize the global Supabase service"""
    global supabase_service
    supabase_service = SupabaseService()
    return supabase_service