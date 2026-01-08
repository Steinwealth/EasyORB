#!/usr/bin/env python3
"""
Health Check Endpoints for Cloud Scheduler Auto-Start
=====================================================

Provides HTTP endpoints for Cloud Scheduler to:
1. Start the trading system if not running
2. Verify the system is operational
3. Send alerts if system is down

Used by Cloud Scheduler jobs:
- trading-system-midnight-start (12:05 AM PT)
- trading-system-premarket-check (5:30 AM PT)
- trading-system-market-open-check (6:25 AM PT)
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

class TradingSystemHealthEndpoints:
    """Health check endpoints for auto-start system"""
    
    def __init__(self, trading_system, alert_manager):
        self.trading_system = trading_system
        self.alert_manager = alert_manager
        self.app = FastAPI()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup health check routes"""
        
        @self.app.post("/api/health/start")
        async def start_system(request: Request):
            """
            Start trading system if not running
            Called by Cloud Scheduler at midnight
            """
            try:
                body = await request.json()
                source = body.get('source', 'unknown')
                action = body.get('action', 'start')
                check_trading_day = body.get('check_trading_day', True)
                
                log.info(f"🤖 Health Check: Start request from {source}")
                
                # Check if it's a trading day
                if check_trading_day:
                    from .prime_market_manager import PrimeMarketManager
                    market_manager = PrimeMarketManager()
                    
                    if not market_manager.is_trading_day():
                        log.info(f"📅 Not a trading day - system will remain stopped")
                        
                        # Rev 00087: Use unified holiday checker instead of old method
                        # Holiday alert is now sent by morning alert at 5:30 AM PT
                        # This endpoint no longer sends duplicate holiday alerts
                        
                        return JSONResponse({
                            "status": "skipped",
                            "reason": "not_trading_day",
                            "message": "Market is closed today (weekend or holiday)",
                            "timestamp": datetime.now().isoformat()
                        })
                
                # Check if system is already running
                if self.trading_system and hasattr(self.trading_system, 'is_running'):
                    if self.trading_system.is_running():
                        log.info(f"✅ System already running - no action needed")
                        return JSONResponse({
                            "status": "running",
                            "message": "Trading system is already operational",
                            "uptime": self.trading_system.get_uptime(),
                            "timestamp": datetime.now().isoformat()
                        })
                
                # Start the system
                log.info(f"🚀 Starting trading system...")
                
                if self.trading_system and hasattr(self.trading_system, 'start'):
                    await self.trading_system.start()
                    
                    # Send startup alert
                    await self._send_startup_alert(source, action)
                    
                    return JSONResponse({
                        "status": "started",
                        "message": "Trading system started successfully",
                        "source": source,
                        "action": action,
                        "timestamp": datetime.now().isoformat()
                    })
                else:
                    log.error(f"❌ Trading system not available")
                    return JSONResponse({
                        "status": "error",
                        "message": "Trading system not initialized",
                        "timestamp": datetime.now().isoformat()
                    }, status_code=500)
                    
            except Exception as e:
                log.error(f"❌ Error in start endpoint: {e}", exc_info=True)
                await self._send_error_alert(str(e))
                return JSONResponse({
                    "status": "error",
                    "message": str(e),
                    "timestamp": datetime.now().isoformat()
                }, status_code=500)
        
        @self.app.post("/api/health/verify")
        async def verify_system(request: Request):
            """
            Verify trading system is running
            Called by Cloud Scheduler pre-market and at market open
            """
            try:
                body = await request.json()
                source = body.get('source', 'unknown')
                action = body.get('action', 'verify')
                alert_if_down = body.get('alert_if_down', True)
                critical = body.get('critical', False)
                
                log.info(f"🔍 Health Check: Verify request from {source}")
                
                # Check if system is running
                if self.trading_system and hasattr(self.trading_system, 'is_running'):
                    if self.trading_system.is_running():
                        # Get system status
                        status = await self._get_system_status()
                        
                        log.info(f"✅ System verification passed")
                        return JSONResponse({
                            "status": "healthy",
                            "message": "Trading system is operational",
                            "details": status,
                            "timestamp": datetime.now().isoformat()
                        })
                    else:
                        # System is not running
                        log.warning(f"⚠️ System verification failed - not running")
                        
                        if alert_if_down:
                            await self._send_down_alert(critical)
                        
                        return JSONResponse({
                            "status": "down",
                            "message": "Trading system is not running",
                            "critical": critical,
                            "timestamp": datetime.now().isoformat()
                        }, status_code=503)
                else:
                    log.error(f"❌ Trading system not initialized")
                    return JSONResponse({
                        "status": "error",
                        "message": "Trading system not initialized",
                        "timestamp": datetime.now().isoformat()
                    }, status_code=500)
                    
            except Exception as e:
                log.error(f"❌ Error in verify endpoint: {e}", exc_info=True)
                return JSONResponse({
                    "status": "error",
                    "message": str(e),
                    "timestamp": datetime.now().isoformat()
                }, status_code=500)
        
        @self.app.get("/api/health")
        async def health_check():
            """Simple health check endpoint"""
            return JSONResponse({
                "status": "ok",
                "service": "etrade-trading-system",
                "timestamp": datetime.now().isoformat()
            })
    
    async def _get_system_status(self) -> Dict[str, Any]:
        """Get current system status"""
        try:
            status = {
                "running": True,
                "uptime": self.trading_system.get_uptime() if hasattr(self.trading_system, 'get_uptime') else "unknown",
                "active_positions": len(self.trading_system.active_positions) if hasattr(self.trading_system, 'active_positions') else 0,
                "market_open": self.trading_system.market_manager.is_market_open() if hasattr(self.trading_system, 'market_manager') else False
            }
            return status
        except Exception as e:
            log.error(f"Error getting system status: {e}")
            return {"error": str(e)}
    
    async def _send_startup_alert(self, source: str, action: str):
        """Send system startup alert"""
        try:
            if self.alert_manager:
                message = (
                    "🚀 **TRADING SYSTEM STARTED**\n\n"
                    f"⏰ Time: {datetime.now().strftime('%I:%M:%S %p %Z')}\n"
                    f"📅 Date: {datetime.now().strftime('%A, %B %d, %Y')}\n"
                    f"🤖 Source: {source}\n"
                    f"⚙️ Action: {action}\n\n"
                    "✅ System is now operational\n"
                    "📊 Ready for trading day\n"
                    "🎯 Awaiting market open signals"
                )
                
                await self.alert_manager.send_custom_alert(
                    title="System Startup",
                    message=message,
                    alert_type="system_startup"
                )
        except Exception as e:
            log.error(f"Error sending startup alert: {e}")
    
    async def _send_down_alert(self, critical: bool = False):
        """Send system down alert"""
        try:
            if self.alert_manager:
                urgency = "🚨 CRITICAL" if critical else "⚠️ WARNING"
                
                message = (
                    f"{urgency} **TRADING SYSTEM DOWN**\n\n"
                    f"⏰ Time: {datetime.now().strftime('%I:%M:%S %p %Z')}\n"
                    f"📅 Date: {datetime.now().strftime('%A, %B %d, %Y')}\n\n"
                    "❌ System is not running\n"
                    "🔧 Manual intervention required\n"
                    "📋 Check system logs for errors\n\n"
                    f"{'🚨 URGENT: Market opens soon!' if critical else '⚠️ Please investigate'}"
                )
                
                await self.alert_manager.send_custom_alert(
                    title="System Down Alert",
                    message=message,
                    alert_type="system_down",
                    priority="high" if critical else "medium"
                )
        except Exception as e:
            log.error(f"Error sending down alert: {e}")
    
    async def _send_holiday_alert(self):
        """
        DEPRECATED (Rev 00087): Old holiday alert method
        
        Holiday alerts are now sent by prime_alert_manager.send_holiday_alert()
        at 5:30 AM PT (morning alert time) with proper bank/low-volume distinction.
        
        This method is no longer called as of Rev 00087.
        """
        # DEPRECATED - Do nothing
        log.info("🎃 Holiday alert skipped (handled by morning alert system - Rev 00087)")
        pass
    
    async def _send_error_alert(self, error: str):
        """Send error alert"""
        try:
            if self.alert_manager:
                message = (
                    "❌ **SYSTEM ERROR**\n\n"
                    f"⏰ Time: {datetime.now().strftime('%I:%M:%S %p %Z')}\n"
                    f"📅 Date: {datetime.now().strftime('%A, %B %d, %Y')}\n\n"
                    f"⚠️ Error: {error}\n\n"
                    "🔧 Manual intervention required\n"
                    "📋 Check system logs for details"
                )
                
                await self.alert_manager.send_custom_alert(
                    title="System Error",
                    message=message,
                    alert_type="system_error",
                    priority="high"
                )
        except Exception as e:
            log.error(f"Error sending error alert: {e}")

def create_health_endpoints(trading_system, alert_manager) -> FastAPI:
    """Create health check endpoints FastAPI app"""
    endpoints = TradingSystemHealthEndpoints(trading_system, alert_manager)
    return endpoints.app

