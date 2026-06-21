"""API v1 router assembly."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, conversations, generate, guest, health, models, simulate

api_router = APIRouter(prefix="/api/v1")

# Auth endpoints: /api/v1/auth/*
api_router.include_router(auth.router)

# Conversation endpoints: /api/v1/conversations/*
api_router.include_router(conversations.router)

# Generation endpoint: /api/v1/conversations/{id}/messages
api_router.include_router(generate.router)

# Guest endpoints: /api/v1/guest/*
api_router.include_router(guest.router)

# Model endpoints: /api/v1/models/*
api_router.include_router(models.router)

# Simulation endpoints: /api/v1/models/* and /api/v1/models/simulations/*
api_router.include_router(simulate.router)

# Health check: /api/v1/health
api_router.include_router(health.router, prefix="")

# Also register health at root level
api_router.get("/health", include_in_schema=False)(health.health_check)
