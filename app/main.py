from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, engine
from app.routers import auth, admin, ravitailleur, depot, user, user_public, driver, tracking, logistics
from app.websocket_manager import manager
from app import models  # Import des modèles AVANT create_all

# Créer les tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(ravitailleur.router)
app.include_router(depot.router)
app.include_router(driver.router, prefix="/api/driver", tags=["driver"])
app.include_router(tracking.router, prefix="/api/tracking", tags=["tracking"])
app.include_router(logistics.router)
app.include_router(user.router)
app.include_router(user_public.router)  # Nouveau router public sans auth

# WebSocket global
@app.websocket("/ws/admin/{user_id}")
async def admin_websocket(websocket: WebSocket, user_id: int):
    """WebSocket pour l'admin"""
    await manager.connect(f"admin_{user_id}", websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except:
        manager.disconnect(f"admin_{user_id}", websocket)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": settings.PROJECT_NAME}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)