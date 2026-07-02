"""
CLI entry point for the daily retention job (LIC-063).

Usage:
    python -m scripts.run_retention

Intended to run daily via cron, Azure Functions timer trigger, or similar scheduler.
"""
import sys
import os

# Ensure the backend package is importable when run from the scripts directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.logging import setup_logging
from app.core.config import settings
from app.services.retention import delete_expired_pliegos

if __name__ == "__main__":
    setup_logging(level=settings.LOG_LEVEL)
    result = delete_expired_pliegos()
    exit_code = 0 if result["errors"] == 0 else 1
    sys.exit(exit_code)
