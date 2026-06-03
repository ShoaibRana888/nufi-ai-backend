# main.py
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from utils.keep_alive import start_keep_alive
from services.supabase_service import init_supabase_service
from api import users, flutter_compat
from api import fcm
from api import chat
from api import debug
from api import notifications
from api import notification_preferences
from api.meals import router as meals_router
from api.water import router as water_router
from api.steps import router as steps_router
from api.sleep import router as sleep_router
from api.weight import router as weight_router
from api.supplements import router as supplements_router
from api.periods import router as periods_router
from api.weekly_context import router as weekly_router
from api.activity_check import router as activity_check_router
from api.meal_suggestions import router as suggestions_router

# Load environment variables
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown - ALL initialization happens here"""
    print("🚀 Starting Health AI Backend...")
    
    try:
        # Initialize Supabase
        init_supabase_service()
        print("✅ Supabase service initialized")
        
        # Initialize OpenAI
        from services.openai_service import init_openai_service
        init_openai_service()
        print("✅ OpenAI service initialized")

        # Initialize Firebase
        fcm.initialize_firebase()
        print("✅ Firebase initialized")
        
        # Setup notification scheduler
        fcm.setup_notification_scheduler()
        print("✅ FCM notification scheduler started")
        
        # Initialize USDA service
        try:
            from services.usda_service import init_usda_service
            init_usda_service()
            print("✅ USDA service initialized")
        except ImportError:
            print("⚠️ USDA service not found - using ChatGPT only")
        
        # Initialize Meal Analysis service
        try:
            from services.meal_analysis_service import init_meal_analysis_service
            init_meal_analysis_service()
            print("✅ Meal Analysis service initialized")
        except ImportError:
            print("⚠️ Meal Analysis service not found")
        
        # Initialize Meal Parser service
        try:
            from services.meal_parser_service import get_meal_parser_service
            get_meal_parser_service()
            print("✅ Meal Parser service initialized")
        except ImportError:
            print("⚠️ Meal Parser service not found")
        
        # Start keep-alive
        start_keep_alive()
        print("✅ Keep-alive service started")
        
        print("🎉 Backend startup complete!")
        
    except Exception as e:
        print(f"❌ Error during startup: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    yield
    
    print("👋 Shutting down...")


# Initialize FastAPI app
app = FastAPI(
    lifespan=lifespan,
    title="Health AI Backend",
    description="AI-powered health tracking backend with user management",
    version="2.0.0"
)

# Add CORS middleware for your Flutter app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(fcm.router)
app.include_router(meals_router, prefix="/api/health/meals", tags=["meals"])
app.include_router(flutter_compat.router, prefix="/api/health", tags=["flutter-health"])
app.include_router(water_router, prefix="/api/health", tags=["water"])
app.include_router(steps_router, prefix="/api/health", tags=["steps"])
app.include_router(sleep_router, prefix="/api/health", tags=["sleep"])
app.include_router(weight_router, prefix="/api/health", tags=["weight"])
app.include_router(supplements_router, prefix="/api/health", tags=["supplements"])
app.include_router(periods_router, prefix="/api/health", tags=["period"])
app.include_router(chat.router, prefix="/api/health")
app.include_router(weekly_router, prefix="/api/health")
app.include_router(activity_check_router, prefix="/api/health")
app.include_router(debug.router)
app.include_router(notifications.router, tags=["notifications"])
app.include_router(notification_preferences.router, tags=["notification-preferences"])
app.include_router(suggestions_router, prefix="/api/health", tags=["meal_suggestions"])


# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Health AI Backend API",
        "version": "2.0.0",
        "status": "running",
        "features": ["user_management", "ai_meal_analysis", "health_chat", "fcm_notifications"]
    }

@app.options("/{rest_of_path:path}")
async def preflight_handler(request: Request, rest_of_path: str):
    """Handle CORS preflight requests"""
    response = Response()
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

# Health check endpoint
@app.get("/health")
async def health_check():
    from services.supabase_service import get_supabase_service
    from services.openai_service import get_openai_service
    
    try:
        supabase_service = get_supabase_service()
        supabase_health = await supabase_service.health_check()
        
        # Test OpenAI connection
        openai_service = get_openai_service()
        openai_health = {
            "status": "healthy",
            "message": "OpenAI service is initialized"
        }

        return {
            "status": "healthy",
            "services": {
                "api": "healthy",
                "supabase": supabase_health,
                "openai": openai_health
            },
            "message": "All services are running"
        }
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "message": "Some services are down"
        }
    
@app.post("/test/ai")
async def test_openai(test_data: dict):
    """Quick test of OpenAI service"""
    try:
        from services.openai_service import get_openai_service
        
        openai_service = get_openai_service()
        
        # Test meal analysis
        if test_data.get("type") == "meal":
            result = await openai_service.analyze_meal(
                food_item=test_data.get("food", "apple"),
                quantity=test_data.get("quantity", "1 medium"),
                user_context={"weight": 70, "primary_goal": "maintain", "activity_level": "moderate", "tdee": 2000}
            )
            return {"success": True, "result": result}
        
        # Test chat
        elif test_data.get("type") == "chat":
            result = await openai_service.health_chat(
                message=test_data.get("message", "Hello!"),
                user_context={"name": "Test User", "primary_goal": "lose weight", "weight": 70}
            )
            return {"success": True, "result": result}
        
        else:
            return {"error": "Specify type: 'meal' or 'chat'"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    import os
    
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)