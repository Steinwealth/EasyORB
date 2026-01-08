#!/usr/bin/env python3
"""
Prime Trade Prioritizer
======================

Handles confidence-based prioritization of trade opportunities to ensure
the highest confidence trades are executed first when position capacity is limited.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from modules.prime_models import PrimeSignal, SignalQuality

log = logging.getLogger(__name__)

@dataclass
class PrioritizedTrade:
    """Represents a trade opportunity with priority scoring"""
    signal: PrimeSignal
    priority_score: float
    estimated_position_value: float
    can_execute: bool
    reasoning: str

class PrimeTradePrioritizer:
    """
    Prioritizes trade opportunities based on confidence, strategy agreement,
    and market conditions to ensure optimal trade execution order.
    """
    
    def __init__(self):
        self.log = logging.getLogger(__name__)
    
    def prioritize_trades(
        self, 
        signals: List[PrimeSignal], 
        market_data_list: List[Dict[str, Any]],
        available_cash: float,
        current_positions: List[Any] = None
    ) -> List[PrioritizedTrade]:
        """
        Prioritize trade opportunities based on confidence and available capital
        
        Args:
            signals: List of trading signals to prioritize
            market_data_list: Corresponding market data for each signal
            available_cash: Available cash for new positions
            current_positions: Current open positions (for capacity calculation)
            
        Returns:
            List of PrioritizedTrade objects sorted by priority (highest first)
        """
        if not signals or len(signals) != len(market_data_list):
            self.log.warning("Invalid signals or market data provided")
            return []
        
        prioritized_trades = []
        total_portfolio_value = available_cash + (sum(pos.value for pos in current_positions) if current_positions else 0)
        
        for signal, market_data in zip(signals, market_data_list):
            try:
                # Calculate priority score
                priority_score = self._calculate_priority_score(signal, market_data)
                
                # Estimate position value
                estimated_position_value = self._estimate_position_value(
                    signal, market_data, total_portfolio_value
                )
                
                # Check if trade can be executed
                can_execute, reasoning = self._can_execute_trade(
                    estimated_position_value, available_cash, signal
                )
                
                prioritized_trade = PrioritizedTrade(
                    signal=signal,
                    priority_score=priority_score,
                    estimated_position_value=estimated_position_value,
                    can_execute=can_execute,
                    reasoning=reasoning
                )
                
                prioritized_trades.append(prioritized_trade)
                
            except Exception as e:
                self.log.error(f"Error prioritizing trade for {signal.symbol}: {e}")
                continue
        
        # Sort by priority score (highest first)
        prioritized_trades.sort(key=lambda x: x.priority_score, reverse=True)
        
        # Execute trades in priority order until capacity is reached
        executed_trades = self._execute_prioritized_trades(
            prioritized_trades, available_cash
        )
        
        self.log.info(f"Prioritized {len(signals)} signals, {len(executed_trades)} can be executed")
        
        return executed_trades
    
    def _calculate_priority_score(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> float:
        """
        Calculate priority score for a trade signal
        
        Higher scores indicate higher priority trades that should be executed first
        """
        base_score = 0.0
        
        # 1. Confidence Score (0-100 points)
        confidence_score = signal.confidence * 100
        base_score += confidence_score
        
        # 2. Strategy Agreement Bonus (0-50 points)
        agreement_level = market_data.get("strategy_agreement_level", "NONE")
        agreement_bonuses = {
            'NONE': 0,
            'LOW': 5,
            'MEDIUM': 15,
            'HIGH': 30,
            'MAXIMUM': 50
        }
        base_score += agreement_bonuses.get(agreement_level, 0)
        
        # 3. Signal Quality Bonus (0-25 points)
        quality_bonuses = {
            SignalQuality.ULTRA_HIGH: 25,
            SignalQuality.VERY_HIGH: 20,
            SignalQuality.HIGH: 15,
            SignalQuality.MEDIUM: 10
        }
        base_score += quality_bonuses.get(signal.quality, 0)
        
        # 4. Volume Surge Bonus (0-20 points)
        volume_ratio = market_data.get("volume_ratio", 1.0)
        if volume_ratio >= 2.0:
            base_score += 20
        elif volume_ratio >= 1.5:
            base_score += 15
        elif volume_ratio >= 1.2:
            base_score += 10
        elif volume_ratio >= 1.1:
            base_score += 5
        
        # 5. Momentum Bonus (0-15 points)
        momentum = market_data.get("momentum", 0.0)
        if momentum >= 0.05:  # 5%+ momentum
            base_score += 15
        elif momentum >= 0.03:  # 3%+ momentum
            base_score += 10
        elif momentum >= 0.01:  # 1%+ momentum
            base_score += 5
        
        # 6. RSI Strength Bonus (0-10 points)
        rsi = market_data.get("rsi", 50.0)
        if rsi >= 70:  # Strong momentum
            base_score += 10
        elif rsi >= 65:
            base_score += 7
        elif rsi >= 60:
            base_score += 5
        elif rsi >= 55:
            base_score += 3
        
        # 7. News Sentiment Bonus (0-10 points)
        sentiment_score = market_data.get("sentiment_score", 0.0)
        if sentiment_score >= 0.8:  # Very positive sentiment
            base_score += 10
        elif sentiment_score >= 0.6:
            base_score += 7
        elif sentiment_score >= 0.4:
            base_score += 5
        elif sentiment_score >= 0.2:
            base_score += 3
        
        # 8. Time-based Priority (0-5 points)
        # Higher priority for earlier signals (first come, first served for equal scores)
        time_bonus = 5.0  # All signals get base time bonus
        base_score += time_bonus
        
        return base_score
    
    def _estimate_position_value(
        self, 
        signal: PrimeSignal, 
        market_data: Dict[str, Any], 
        total_portfolio_value: float
    ) -> float:
        """
        Estimate position value for capacity planning
        
        Uses simplified calculation for prioritization (actual sizing done by risk manager)
        """
        try:
            # Simplified position sizing estimation
            # 80% of total portfolio value divided by estimated concurrent positions
            estimated_concurrent_positions = market_data.get("num_concurrent_positions", 3)
            fair_share = (total_portfolio_value * 0.80) / max(1, estimated_concurrent_positions)
            
            # Apply confidence multiplier
            confidence_multiplier = 1.0
            if signal.confidence >= 0.995:
                confidence_multiplier = 2.5
            elif signal.confidence >= 0.99:
                confidence_multiplier = 2.5
            elif signal.confidence >= 0.975:
                confidence_multiplier = 2.0
            elif signal.confidence >= 0.95:
                confidence_multiplier = 1.0
            
            # Apply agreement bonus
            agreement_bonus = 0.0
            agreement_level = market_data.get("strategy_agreement_level", "NONE")
            if agreement_level == "MAXIMUM":
                agreement_bonus = 1.0
            elif agreement_level == "HIGH":
                agreement_bonus = 0.5
            elif agreement_level == "MEDIUM":
                agreement_bonus = 0.25
            
            estimated_position_value = fair_share * confidence_multiplier * (1 + agreement_bonus)
            
            # Cap at 35% of total portfolio value
            max_position_value = total_portfolio_value * 0.35
            estimated_position_value = min(estimated_position_value, max_position_value)
            
            return estimated_position_value
            
        except Exception as e:
            self.log.error(f"Error estimating position value for {signal.symbol}: {e}")
            return 0.0
    
    def _can_execute_trade(
        self, 
        estimated_position_value: float, 
        available_cash: float, 
        signal: PrimeSignal
    ) -> tuple[bool, str]:
        """
        Check if trade can be executed with available cash
        
        Returns:
            (can_execute: bool, reasoning: str)
        """
        if estimated_position_value <= 0:
            return False, "Invalid position value"
        
        if estimated_position_value > available_cash:
            if available_cash < 50.0:  # Minimum $50 position
                return False, f"Insufficient cash (${available_cash:.2f} < $50 minimum)"
            else:
                return True, f"Position size will be reduced to available cash (${available_cash:.2f})"
        
        return True, "Sufficient cash available"
    
    def _execute_prioritized_trades(
        self, 
        prioritized_trades: List[PrioritizedTrade], 
        available_cash: float
    ) -> List[PrioritizedTrade]:
        """
        Execute trades in priority order until capacity is reached
        
        Returns only trades that can be executed within available cash
        """
        executable_trades = []
        remaining_cash = available_cash
        
        for trade in prioritized_trades:
            if not trade.can_execute:
                trade.reasoning = f"SKIPPED: {trade.reasoning}"
                continue
            
            # Check if we have enough cash for this trade
            if trade.estimated_position_value <= remaining_cash:
                executable_trades.append(trade)
                remaining_cash -= trade.estimated_position_value
                
                self.log.info(
                    f"EXECUTABLE: {trade.signal.symbol} "
                    f"(Priority: {trade.priority_score:.1f}, "
                    f"Est. Value: ${trade.estimated_position_value:.2f}, "
                    f"Remaining: ${remaining_cash:.2f})"
                )
            else:
                # Not enough cash for this trade
                trade.can_execute = False
                trade.reasoning = f"INSUFFICIENT CASH: Need ${trade.estimated_position_value:.2f}, have ${remaining_cash:.2f}"
                
                self.log.info(
                    f"SKIPPED: {trade.signal.symbol} "
                    f"(Priority: {trade.priority_score:.1f}) - {trade.reasoning}"
                )
        
        return executable_trades
    
    def get_prioritization_summary(self, prioritized_trades: List[PrioritizedTrade]) -> Dict[str, Any]:
        """
        Get summary of trade prioritization results
        
        Returns:
            Dictionary with prioritization summary statistics
        """
        if not prioritized_trades:
            return {"total_signals": 0, "executable_trades": 0, "total_value": 0.0}
        
        total_signals = len(prioritized_trades)
        executable_trades = [t for t in prioritized_trades if t.can_execute]
        total_value = sum(t.estimated_position_value for t in executable_trades)
        
        # Calculate priority score statistics
        priority_scores = [t.priority_score for t in prioritized_trades]
        avg_priority = sum(priority_scores) / len(priority_scores) if priority_scores else 0
        
        # Group by signal quality
        quality_counts = {}
        for trade in prioritized_trades:
            quality = trade.signal.quality.name if trade.signal.quality else "UNKNOWN"
            quality_counts[quality] = quality_counts.get(quality, 0) + 1
        
        return {
            "total_signals": total_signals,
            "executable_trades": len(executable_trades),
            "skipped_trades": total_signals - len(executable_trades),
            "total_estimated_value": total_value,
            "average_priority_score": avg_priority,
            "quality_distribution": quality_counts,
            "top_priority_symbols": [
                {"symbol": t.signal.symbol, "score": t.priority_score, "value": t.estimated_position_value}
                for t in executable_trades[:5]  # Top 5
            ]
        }

# Factory function for trade prioritizer
_trade_prioritizer_instance = None

def get_prime_trade_prioritizer() -> PrimeTradePrioritizer:
    """Get singleton instance of prime trade prioritizer"""
    global _trade_prioritizer_instance
    if _trade_prioritizer_instance is None:
        _trade_prioritizer_instance = PrimeTradePrioritizer()
    return _trade_prioritizer_instance
