# main.py
# FastAPI application entry point.
# Middleware: API key verification on all routes except /health.

import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import health, story, session, model

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="SeeSaw Cloud Agent",
    version=settings.app_version,
    description="Privacy-first cloud story generation for the SeeSaw children's AI companion.",
)

# CORS — allow iOS app to POST from any origin (no browser clients in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


# API key middleware — applied to all routes except /health
@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path != "/health":
        provided_key = request.headers.get("X-SeeSaw-Key", "")
        if provided_key != settings.seesaw_api_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)


# Register routers
app.include_router(health.router)
app.include_router(story.router,   prefix="/story",   tags=["Story"])
app.include_router(session.router, prefix="/session", tags=["Session"])
app.include_router(model.router,   prefix="/model",   tags=["Model"])
