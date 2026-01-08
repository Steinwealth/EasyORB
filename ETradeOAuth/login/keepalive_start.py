#!/usr/bin/env python3
"""
Google Cloud Backend with OAuth Keep-Alive System
================================================

This script starts the FastAPI backend and initializes the OAuth keep-alive system
to maintain E*TRADE tokens active in Google Secret Manager.

The keep-alive system runs every 90 minutes to prevent token idle timeout.
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Global keep-alive task
keepalive_task = None

async def start_keepalive_system():
    """Start the OAuth keep-alive system"""
    global keepalive_task
    
    try:
        # Import oauth_keepalive module
        from keepalive_oauth import start_oauth_keepalive
        
        log.info("🔄 Starting OAuth keep-alive system...")
        success = await start_oauth_keepalive()
        
        if success:
            log.info("✅ OAuth keep-alive system started successfully")
        else:
            log.error("❌ Failed to start OAuth keep-alive system")
            
    except Exception as e:
        log.error(f"Error starting keep-alive system: {e}")

async def stop_keepalive_system():
    """Stop the OAuth keep-alive system"""
    try:
        from keepalive_oauth import stop_oauth_keepalive
        
        log.info("🛑 Stopping OAuth keep-alive system...")
        await stop_oauth_keepalive()
        log.info("✅ OAuth keep-alive system stopped")
        
    except Exception as e:
        log.error(f"Error stopping keep-alive system: {e}")

@asynccontextmanager
async def lifespan(app):
    """Application lifespan manager"""
    # Startup
    log.info("🚀 Starting ETrade OAuth Backend with Keep-Alive System")
    
    # Start keep-alive system
    await start_keepalive_system()
    
    yield
    
    # Shutdown
    log.info("🛑 Shutting down ETrade OAuth Backend")
    await stop_keepalive_system()

# Import and configure FastAPI app
from oauth_backend import app

# Add lifespan to the app
app.router.lifespan_context = lifespan

if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment (Cloud Run sets PORT)
    port = int(os.environ.get("PORT", 8080))
    
    log.info(f"🌐 Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

