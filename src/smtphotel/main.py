"""Main entry point for smtphotel.

AIDEV-NOTE: This module starts both the SMTP server and the HTTP/API server.
It also handles graceful shutdown and logs security warnings.
"""

import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import NoReturn

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from smtphotel.api.routes import router as api_router
from smtphotel.config import Settings, get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    AIDEV-NOTE: This function creates the FastAPI app with:
    - Security headers middleware
    - CORS configuration (restrictive by default)
    - API routes
    - Static file serving for web UI
    """
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="smtphotel",
        description="Development SMTP server that captures all incoming email",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # Add security headers middleware
    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        # Set security headers on all responses
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # CSP for the main application (not for HTML email rendering in iframes)
        # AIDEV-NOTE: script-src doesn't need unsafe-inline since we use external JS files.
        # style-src needs unsafe-inline for inline styles and CSS custom properties.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        return response

    # Configure CORS
    if settings.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
        )

    # Include API routes
    app.include_router(api_router)

    # Mount static files for web UI
    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


def print_banner(settings: Settings) -> None:
    """Print startup banner with security warning."""
    banner = f"""
╔═══════════════════════════════════════════════════════════════╗
║                         smtphotel                              ║
║              Development SMTP Server v0.1.0                    ║
╠═══════════════════════════════════════════════════════════════╣
║  SMTP: {settings.bind_address}:{settings.smtp_port:<5}                                      ║
║  HTTP: {settings.bind_address}:{settings.http_port:<5}                                      ║
╠═══════════════════════════════════════════════════════════════╣
║  ⚠️  WARNING: This server captures ALL email.                  ║
║  Captured messages may contain sensitive data.                 ║
║  Use only in development/testing environments.                 ║
╚═══════════════════════════════════════════════════════════════╝
"""
    print(banner)


async def run_servers() -> NoReturn:
    """Run SMTP and HTTP servers concurrently."""
    from smtphotel.smtp.server import get_smtp_server, stop_smtp_server
    from smtphotel.storage.database import close_database, get_database
    from smtphotel.tasks import start_prune_task, stop_prune_task

    settings = get_settings()

    # Initialize database
    await get_database()
    logger.info("Database connected")

    # Setup signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(sig: signal.Signals) -> None:
        logger.info("Received signal %s, shutting down...", sig.name)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, partial(handle_signal, sig))

    # Start SMTP server (using global instance so health check can access it)
    smtp_server = await get_smtp_server(settings)
    await smtp_server.start()

    # Start background prune task
    await start_prune_task()

    # Create FastAPI app
    app = create_app(settings)

    # Configure uvicorn
    config = uvicorn.Config(
        app,
        host=settings.bind_address,
        port=settings.http_port,
        log_level="info",
        access_log=True,
    )
    http_server = uvicorn.Server(config)

    try:
        print_banner(settings)
        logger.info("smtphotel started")

        # Run HTTP server in a task
        http_task = asyncio.create_task(http_server.serve())

        # Wait for shutdown signal
        await shutdown_event.wait()

        # Graceful shutdown
        http_server.should_exit = True
        await http_task

    finally:
        # Cleanup
        await stop_prune_task()
        await smtp_server.stop()
        await stop_smtp_server()
        await close_database()
        logger.info("smtphotel shutdown complete")

    # This should never be reached but satisfies type checker
    sys.exit(0)


def main() -> None:
    """Main entry point."""
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_servers())


if __name__ == "__main__":
    main()
