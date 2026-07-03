"""FastAPI application entrypoint.

Run with:
    uvicorn app.main:app --reload
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config  # noqa: F401 - ensures .env is loaded on startup
from app.api.routes import router as api_router

app = FastAPI(title="AiStockQuote", version="1.0.0")
app.include_router(api_router)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
