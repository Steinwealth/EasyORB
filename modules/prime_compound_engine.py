#!/usr/bin/env python3
"""
Prime Compound Engine - Rev 00179

Compounds freed capital for new positions throughout the trading day.

Tracks all capital movements and makes freed capital from closed positions
immediately available for new ORR trades. Does NOT calculate position sizes
(that's Risk Manager's responsibility).

Key Features:
- Capital Compounding: Freed capital → New positions
- Real-Time Tracking: Updates after each position open/close
- Capital Availability: Answers "how much capital is available?"
- 90% Max Deployment: Maintains 10% reserve

Author: Easy Trading Software Team
Date: January 15, 2025
Revision: 00179
"""

import logging
from typing import Dict, Optional
from datetime import datetime
from dataclasses import dataclass

log = logging.getLogger("prime_compound_engine")

@dataclass
class CompoundState:
    """Current state of capital compounding"""
    total_account: float
    so_deployed: float = 0.0
    orr_deployed: float = 0.0
    freed_capital: float = 0.0  # Capital from closed positions
    reserved_capital: float = 0.0  # 10% reserve
    
    def get_total_deployed(self) -> float:
        """Get total capital currently deployed"""
        return self.so_deployed + self.orr_deployed
    
    def get_max_deployable(self) -> float:
        """Get maximum deployable capital (90% of account)"""
        return self.total_account * 0.90
    
    def get_remaining_capacity(self) -> float:
        """Get remaining deployment capacity"""
        max_deployable = self.get_max_deployable()
        current_deployed = self.get_total_deployed()
        return max(0, max_deployable - current_deployed)

class PrimeCompoundEngine:
    """
    Prime Compound Engine
    
    Compounds freed capital for new positions throughout the day.
    Tracks capital movements and provides availability queries.
    
    Does NOT calculate position sizes - that's Risk Manager's job!
    """
    
    def __init__(self, total_account: float):
        """
        Initialize compound engine
        
        Args:
            total_account: Total account value (cash + margin)
        """
        self.state = CompoundState(
            total_account=total_account,
            reserved_capital=total_account * 0.10  # 10% reserve
        )
        
        # Track position history
        self.closed_positions: list = []
        self.active_position_count: int = 0
        
        # Performance tracking
        self.total_capital_compounded: float = 0.0
        self.compound_count: int = 0
        
        log.info(f"💰 Prime Compound Engine initialized")
        log.info(f"   Total Account: ${total_account:,.2f}")
        log.info(f"   Max Deployable (90%): ${total_account * 0.90:,.2f}")
        log.info(f"   Reserve (10%): ${total_account * 0.10:,.2f}")
    
    # ========================================================================
    # CAPITAL TRACKING (Position Open/Close)
    # ========================================================================
    
    def on_position_opened(
        self,
        symbol: str,
        position_value: float,
        signal_type: str  # "SO" or "ORR"
    ) -> None:
        """
        Track position opening - updates deployed capital
        
        Args:
            symbol: Symbol opened
            position_value: Position value (calculated by Risk Manager!)
            signal_type: "SO" or "ORR"
        """
        # Update deployed capital
        if signal_type == "SO":
            self.state.so_deployed += position_value
        else:  # ORR
            self.state.orr_deployed += position_value
            
            # Consume freed capital first
            if self.state.freed_capital >= position_value:
                self.state.freed_capital -= position_value
                log.info(f"♻️ {symbol}: Compounded ${position_value:.2f} from freed capital pool")
            elif self.state.freed_capital > 0:
                remaining = position_value - self.state.freed_capital
                log.info(f"♻️ {symbol}: Compounded ${self.state.freed_capital:.2f} from freed capital, ${remaining:.2f} from base")
                self.state.freed_capital = 0
        
        self.active_position_count += 1
        
        log.debug(f"📊 Capital State after {symbol} open:")
        log.debug(f"   SO Deployed: ${self.state.so_deployed:.2f}")
        log.debug(f"   ORR Deployed: ${self.state.orr_deployed:.2f}")
        log.debug(f"   Freed Capital: ${self.state.freed_capital:.2f}")
        log.debug(f"   Total Deployed: ${self.state.get_total_deployed():.2f} ({self.state.get_total_deployed()/self.state.total_account*100:.1f}%)")
    
    def on_position_closed(
        self,
        symbol: str,
        position_value: float,
        signal_type: str,  # "SO" or "ORR"
        exit_reason: str,  # "PROFIT", "STOP_LOSS", "PROFIT_TIMEOUT", "REBALANCE", etc.
        pnl: float = 0.0
    ) -> float:
        """
        Track position closing - compounds capital immediately
        
        Args:
            symbol: Symbol closed
            position_value: Original position value
            signal_type: "SO" or "ORR"
            exit_reason: Why position closed
            pnl: Profit/loss amount
            
        Returns:
            Freed capital amount
        """
        # Update deployed capital
        if signal_type == "SO":
            self.state.so_deployed = max(0, self.state.so_deployed - position_value)
        else:  # ORR
            self.state.orr_deployed = max(0, self.state.orr_deployed - position_value)
        
        # CRITICAL: Compound capital immediately
        freed_amount = position_value + pnl  # Return original capital + profit (or - loss)
        self.state.freed_capital += freed_amount
        
        # 🔧 CRITICAL FIX (Rev 00180AE): Compound P&L into total account (account growth!)
        # This ensures account balance grows with profits and shrinks with losses
        self.state.total_account += pnl
        if pnl > 0:
            log.info(f"📈 Account grew: ${self.state.total_account:,.2f} (+${pnl:.2f} profit)")
        elif pnl < 0:
            log.warning(f"📉 Account shrunk: ${self.state.total_account:,.2f} (${pnl:.2f} loss)")
        
        # Track compounding
        self.total_capital_compounded += freed_amount
        self.compound_count += 1
        self.active_position_count = max(0, self.active_position_count - 1)
        
        # Track closed position
        self.closed_positions.append({
            'symbol': symbol,
            'type': signal_type,
            'exit_reason': exit_reason,
            'pnl': pnl,
            'freed': freed_amount,
            'time': datetime.utcnow()
        })
        
        log.info(f"♻️ CAPITAL COMPOUNDED: {symbol} closed ({exit_reason})")
        log.info(f"   Position Value: ${position_value:.2f}")
        log.info(f"   P&L: ${pnl:+.2f}")
        log.info(f"   Freed: ${freed_amount:.2f}")
        log.info(f"   Total Freed Capital: ${self.state.freed_capital:.2f} ✅")
        
        log.debug(f"📊 Capital State after {symbol} close:")
        log.debug(f"   SO Deployed: ${self.state.so_deployed:.2f}")
        log.debug(f"   ORR Deployed: ${self.state.orr_deployed:.2f}")
        log.debug(f"   Freed Capital: ${self.state.freed_capital:.2f}")
        log.debug(f"   Total Deployed: ${self.state.get_total_deployed():.2f} ({self.state.get_total_deployed()/self.state.total_account*100:.1f}%)")
        
        return freed_amount
    
    # ========================================================================
    # CAPITAL QUERIES (Risk Managers use these!)
    # ========================================================================
    
    def get_available_for_so(self) -> float:
        """
        Get available capital for SO trades (Rev 00180AE: 90% allocation)
        
        Returns:
            Available SO capital (90% of account, ORR disabled)
        """
        base_so = self.state.total_account * 0.90  # Rev 00180AE: 90% for SO (was 70%)
        available = base_so - self.state.so_deployed
        return max(0, available)
    
    def get_available_for_orr(self) -> float:
        """
        Get available capital for ORR trades (Rev 00180AE: DISABLED)
        
        ORR is currently disabled (0% allocation). All capital focused on SO profitability.
        When re-enabled, this will combine base ORR + freed capital + unused SO.
        
        Returns:
            0.0 (ORR disabled)
        """
        # Rev 00180AE: ORR DISABLED - Return 0 (no ORR trading)
        return 0.0
        
        # ARCHIVED: Will be re-enabled after SO optimization complete
        # base_orr = self.state.total_account * 0.0  # 0% base for ORR (disabled)
        # total_available = (base_orr - self.state.orr_deployed) + self.state.freed_capital
        # base_so = self.state.total_account * 0.90  # 90% for SO
        # unused_so = base_so - self.state.so_deployed
        # if unused_so > 0:
        #     total_available += unused_so
        # remaining_capacity = self.state.get_remaining_capacity()
        # return max(0, min(total_available, remaining_capacity))
    
    def can_open_position(self, required_capital: float, signal_type: str = "ORR") -> bool:
        """
        Check if we have enough capital to open position
        
        Args:
            required_capital: Capital needed for position
            signal_type: "SO" or "ORR"
            
        Returns:
            True if enough capital available
        """
        if signal_type == "SO":
            available = self.get_available_for_so()
        else:
            available = self.get_available_for_orr()
        
        can_open = available >= required_capital
        
        if not can_open:
            log.debug(f"⚠️ Insufficient capital for {signal_type}: Need ${required_capital:.2f}, Available ${available:.2f}")
        
        return can_open
    
    def get_freed_capital(self) -> float:
        """Get current freed capital amount"""
        return self.state.freed_capital
    
    def get_deployment_status(self) -> Dict:
        """
        Get comprehensive deployment status
        
        Returns:
            Dictionary with capital state
        """
        max_deployable = self.state.get_max_deployable()
        total_deployed = self.state.get_total_deployed()
        
        return {
            'total_account': self.state.total_account,
            'so_deployed': self.state.so_deployed,
            'orr_deployed': self.state.orr_deployed,
            'freed_capital': self.state.freed_capital,
            'total_deployed': total_deployed,
            'deployment_pct': total_deployed / self.state.total_account * 100,
            'max_deployable': max_deployable,
            'remaining_capacity': self.state.get_remaining_capacity(),
            'available_for_so': self.get_available_for_so(),
            'available_for_orr': self.get_available_for_orr(),
            'active_positions': self.active_position_count,
            'closed_positions': len(self.closed_positions),
            'total_compounded': self.total_capital_compounded,
            'compound_count': self.compound_count
        }
    
    def log_status(self) -> None:
        """Log current capital status"""
        status = self.get_deployment_status()
        
        log.info(f"💰 COMPOUND ENGINE STATUS:")
        log.info(f"   Total Account: ${status['total_account']:,.2f}")
        log.info(f"   SO Deployed: ${status['so_deployed']:,.2f}")
        log.info(f"   ORR Deployed: ${status['orr_deployed']:,.2f}")
        log.info(f"   Freed Capital: ${status['freed_capital']:,.2f} ♻️")
        log.info(f"   Total Deployed: ${status['total_deployed']:,.2f} ({status['deployment_pct']:.1f}%)")
        log.info(f"   Available for ORR: ${status['available_for_orr']:,.2f}")
        log.info(f"   Active Positions: {status['active_positions']}")
        log.info(f"   Total Compounded: ${status['total_compounded']:,.2f} ({status['compound_count']} times)")

# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def get_prime_compound_engine(total_account: float) -> PrimeCompoundEngine:
    """
    Get or create prime compound engine instance
    
    Args:
        total_account: Total account value
        
    Returns:
        PrimeCompoundEngine instance
    """
    return PrimeCompoundEngine(total_account)
