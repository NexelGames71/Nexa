"""Vercel entrypoint: exposes the FastAPI app to Vercel's Python runtime."""

from nexa.main import create_app

app = create_app()
