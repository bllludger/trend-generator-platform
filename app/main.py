"""
Main FastAPI application for Trend Generator API.
Serves health, auth, trends, admin-ui (HTML), and metrics.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import health, auth, trends, playground, admin
from app.admin.ui import router as admin_ui_router
from app.utils.metrics import router as metrics_router


app = FastAPI(
    title="Trend Generator API",
    description="API and admin UI for Trend Generator",
    version="1.0.0",
)

# CORS
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if not origins:
    origins = ["http://localhost:3000", "http://127.0.0.1:3000", "http://admin-ui", "http://localhost:80"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, tags=["health"])
app.include_router(auth.router)
app.include_router(trends.router)
app.include_router(playground.router)
app.include_router(admin.router)
app.include_router(admin_ui_router)
app.include_router(metrics_router)
