# services/openai_service.py
import openai
import os
import json
from typing import Dict, Any

class OpenAIService:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY must be set in environment variables")
        
        self.client = openai.AsyncOpenAI(api_key=api_key)
        print("✅ OpenAI service initialized")
    
    async def analyze_meal_with_micronutrients(
    self, 
    food_item: str, 
    quantity: str, 
    user_context: Dict[str, Any]
) -> Dict[str, Any]:
        """Analyze meal nutrition including micronutrients"""
        try:
            print(f"🔍 Analyzing meal with micronutrients: {food_item} ({quantity})")
            
            prompt = f"""
            Analyze this meal and provide comprehensive nutrition information including micronutrients.
            
            Food: {food_item}
            Quantity: {quantity}
            
            User context:
            - Weight: {user_context.get('weight', 70)} kg
            - Goal: {user_context.get('primary_goal', 'maintain weight')}
            - TDEE: {user_context.get('tdee', 2000)} calories
            
            Return ONLY valid JSON with accurate values:
            {{
                "calories": integer,
                "protein_g": float,
                "carbs_g": float,
                "fat_g": float,
                "fiber_g": float,
                "sugar_g": float,
                "sodium_mg": integer,
                "saturated_fat_g": float,
                "trans_fat_g": float,
                "cholesterol_mg": float,
                "vitamin_a_mcg": float,
                "vitamin_c_mg": float,
                "vitamin_d_mcg": float,
                "vitamin_e_mg": float,
                "vitamin_k_mcg": float,
                "vitamin_b12_mcg": float,
                "calcium_mg": float,
                "iron_mg": float,
                "potassium_mg": float,
                "magnesium_mg": float,
                "zinc_mg": float,
                "serving_description": "string",
                "nutrition_notes": "string with micronutrient highlights",
                "healthiness_score": integer (1-10),
                "suggestions": "string"
            }}
            
            Be accurate with micronutrients - if a food is not a significant source of a nutrient, use 0.
            Highlight any nutrients where this food provides >20% of daily value.
            """
            
            response = await self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            
            content = response.choices[0].message.content.strip()
            
            # Clean JSON if needed
            if content.startswith('```json'):
                content = content[7:-3]
            elif content.startswith('```'):
                content = content[3:-3]
            
            import json
            result = json.loads(content)
            result['data_source'] = 'ChatGPT-micronutrients'
            
            return result
            
        except Exception as e:
            print(f"❌ Error in micronutrient analysis: {e}")
            # Return basic analysis as fallback
            return self._get_fallback_nutrition(food_item, quantity)

    def _get_fallback_nutrition(self, food_item: str, quantity: str) -> Dict[str, Any]:
        """Get fallback nutrition data when AI analysis fails"""
        return {
            "calories": 250,
            "protein_g": 12.0,
            "carbs_g": 30.0,
            "fat_g": 10.0,
            "fiber_g": 3.0,
            "sugar_g": 5.0,
            "sodium_mg": 300,
            "serving_description": f"Estimated for {quantity} of {food_item}",
            "nutrition_notes": "Estimated values due to analysis error",
            "healthiness_score": 6,
            "suggestions": "Consider tracking more detailed portion sizes for better accuracy"
        }
    
    def _get_quantity_guidance(self, food_item: str, quantity: str) -> str:
        """Generate specific guidance for quantity interpretation"""
        
        guidance = "QUANTITY INTERPRETATION:\n"
        
        if 'egg' in quantity.lower():
            num = re.search(r'(\d+)', quantity)
            if num:
                n = int(num.group(1))
                guidance += f"- {n} eggs means exactly {n} eggs (~{n*70} calories total)\n"
        
        if 'slice' in quantity.lower():
            num = re.search(r'(\d+)', quantity)
            if num:
                n = int(num.group(1))
                guidance += f"- {n} slices means exactly {n} slices of bread (~{n*75} calories total)\n"
        
        if 'cup' in quantity.lower():
            num = re.search(r'(\d+)', quantity)
            if num:
                n = float(num.group(1))
                guidance += f"- {n} cup means {n*8} oz of liquid\n"
        
        return guidance
    
    async def health_chat(self, message: str, user_context: Dict[str, Any]) -> str:
        """Health coaching chat"""
        try:
            print(f"🔍 Health chat message received")
            
            system_prompt = f"""
            You are a friendly AI health and nutrition coach. User context:
            - Name: {user_context.get('name', 'there')}
            - Goal: {user_context.get('primary_goal', 'general health')}
            - Weight: {user_context.get('weight', 'not specified')} kg
            - Activity: {user_context.get('activity_level', 'moderate')}
            
            Provide personalized, encouraging advice. Keep responses conversational and supportive.
            """
            
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            reply = response.choices[0].message.content.strip()
            print(f"✅ Chat response generated")
            return reply
            
        except Exception as e:
            print(f"❌ Error in chat: {e}")
            return "I'm sorry, I'm having trouble responding right now. Please try again later."

# Global instance
openai_service = None

def get_openai_service() -> OpenAIService:
    """Get the global OpenAI service instance"""
    global openai_service
    if openai_service is None:
        openai_service = OpenAIService()
    return openai_service

def init_openai_service():
    """Initialize the global OpenAI service"""
    global openai_service
    openai_service = OpenAIService()
    return openai_service