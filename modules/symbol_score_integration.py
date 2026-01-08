"""
Symbol Score Integration - Integration with Prime Trading System

This module provides integration between the Prime Symbol Score system
and the main trading system components.

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from prime_symbol_score import PrimeSymbolScore, SymbolRank

logger = logging.getLogger(__name__)

class SymbolScoreIntegration:
    """
    Integration class for Prime Symbol Score with trading system
    """
    
    def __init__(self, symbol_score: PrimeSymbolScore):
        self.symbol_score = symbol_score
    
    def on_trade_closed(self, 
                       symbol: str,
                       trade_size: float,
                       profit_loss: float,
                       trade_id: str,
                       strategy_mode: str = "standard",
                       confidence: float = 0.0) -> float:
        """
        Called when a trade is closed to update symbol scores
        
        Args:
            symbol: Trading symbol
            trade_size: Size of the trade in dollars
            profit_loss: Profit or loss from the trade in dollars
            trade_id: Unique identifier for the trade
            strategy_mode: Strategy mode used for the trade
            confidence: Confidence level of the trade
            
        Returns:
            Rank score for this trade
        """
        rank_score = self.symbol_score.add_trade_result(
            symbol=symbol,
            trade_size=trade_size,
            profit_loss=profit_loss,
            trade_id=trade_id,
            strategy_mode=strategy_mode,
            confidence=confidence
        )
        
        logger.info(f"Trade closed: {symbol} - ${profit_loss:.2f} profit on ${trade_size:.2f} trade (Rank: {rank_score:.2f})")
        return rank_score
    
    def get_symbol_priority_weights(self, 
                                   symbols: List[str],
                                   min_trades: int = 5,
                                   max_weight: float = 2.0) -> Dict[str, float]:
        """
        Get priority weights for symbols based on their performance
        
        Args:
            symbols: List of symbols to evaluate
            min_trades: Minimum trades required for consideration
            max_weight: Maximum weight multiplier
            
        Returns:
            Dictionary mapping symbols to their priority weights
        """
        weights = {}
        priority_list = self.symbol_score.get_daily_priority_list(min_trades)
        
        # Create ranking map
        symbol_ranks = {symbol: rank for rank, (symbol, _) in enumerate(priority_list)}
        
        for symbol in symbols:
            if symbol in symbol_ranks:
                # Calculate weight based on rank (higher rank = higher weight)
                rank = symbol_ranks[symbol]
                total_symbols = len(priority_list)
                
                if total_symbols > 0:
                    # Weight decreases as rank increases (rank 0 = best)
                    weight = max_weight * (1 - (rank / total_symbols))
                    weights[symbol] = max(1.0, weight)  # Minimum weight of 1.0
                else:
                    weights[symbol] = 1.0
            else:
                weights[symbol] = 1.0  # Default weight for unranked symbols
        
        return weights
    
    def get_top_priority_symbols(self, 
                                candidate_symbols: List[str],
                                top_n: int = 5,
                                min_trades: int = 5) -> List[str]:
        """
        Get top priority symbols from a list of candidates
        
        Args:
            candidate_symbols: List of candidate symbols
            top_n: Number of top symbols to return
            min_trades: Minimum trades required
            
        Returns:
            List of top priority symbols
        """
        priority_list = self.symbol_score.get_daily_priority_list(min_trades)
        ranked_symbols = [symbol for _, (symbol, _) in priority_list]
        
        # Filter to only include candidate symbols
        top_symbols = []
        for symbol in ranked_symbols:
            if symbol in candidate_symbols:
                top_symbols.append(symbol)
                if len(top_symbols) >= top_n:
                    break
        
        return top_symbols
    
    def should_increase_position_size(self, 
                                    symbol: str,
                                    base_size: float,
                                    max_increase: float = 1.5) -> float:
        """
        Determine if position size should be increased based on symbol performance
        
        Args:
            symbol: Trading symbol
            base_size: Base position size
            max_increase: Maximum increase multiplier
            
        Returns:
            Recommended position size multiplier
        """
        symbol_rank = self.symbol_score.get_symbol_rank(symbol)
        
        if not symbol_rank or symbol_rank.total_trades < 5:
            return 1.0  # No increase for insufficient data
        
        # Calculate multiplier based on prime score
        # Higher prime score = higher multiplier
        if symbol_rank.avg_prime_score > 10.0:  # Excellent performance
            return min(max_increase, 1.5)
        elif symbol_rank.avg_prime_score > 5.0:  # Good performance
            return min(max_increase, 1.3)
        elif symbol_rank.avg_prime_score > 0.0:  # Positive performance
            return min(max_increase, 1.1)
        else:  # Poor performance
            return 0.8  # Reduce position size
    
    def get_symbol_confidence_boost(self, symbol: str) -> float:
        """
        Get confidence boost for a symbol based on historical performance
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Confidence boost multiplier (1.0 = no boost)
        """
        symbol_rank = self.symbol_score.get_symbol_rank(symbol)
        
        if not symbol_rank or symbol_rank.total_trades < 3:
            return 1.0  # No boost for insufficient data
        
        # Calculate boost based on win rate and prime score
        win_rate_boost = symbol_rank.win_rate / 100.0  # Convert to decimal
        prime_score_boost = max(0, symbol_rank.avg_prime_score / 10.0)  # Normalize prime score
        
        # Combine boosts (capped at 1.5x)
        total_boost = 1.0 + (win_rate_boost * 0.3) + (prime_score_boost * 0.2)
        return min(1.5, total_boost)
    
    def generate_daily_report(self) -> str:
        """
        Generate daily performance report
        
        Returns:
            Formatted report string
        """
        priority_list = self.symbol_score.get_daily_priority_list()
        stats = self.symbol_score.get_system_stats()
        
        report = f"""
📊 Daily Symbol Performance Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

System Statistics:
- Total Symbols: {stats['total_symbols']}
- Total Trades: {stats['total_trades']}
- Average Prime Score: {stats['avg_prime_score']:.2f}

Top 10 Performing Symbols:
"""
        
        for rank, (symbol, symbol_rank) in enumerate(priority_list[:10], 1):
            report += f"{rank:2d}. {symbol:6s} | {symbol_rank.avg_prime_score:6.2f} per $100 | "
            report += f"{symbol_rank.total_trades:3d} trades | {symbol_rank.win_rate:5.1f}% win rate\n"
        
        return report
    
    def get_symbol_analysis(self, symbol: str) -> Dict:
        """
        Get detailed analysis for a specific symbol
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with analysis results
        """
        performance = self.symbol_score.get_symbol_performance_summary(symbol)
        
        if not performance:
            return {"error": f"No data available for {symbol}"}
        
        # Calculate additional metrics
        prime_score = performance['avg_prime_score']
        win_rate = performance['win_rate']
        total_trades = performance['total_trades']
        
        # Performance rating
        if prime_score > 10.0 and win_rate > 80:
            rating = "Excellent"
        elif prime_score > 5.0 and win_rate > 70:
            rating = "Good"
        elif prime_score > 0.0 and win_rate > 60:
            rating = "Average"
        else:
            rating = "Poor"
        
        # Recommendation
        if prime_score > 8.0 and total_trades >= 10:
            recommendation = "High Priority - Increase allocation"
        elif prime_score > 3.0 and total_trades >= 5:
            recommendation = "Medium Priority - Standard allocation"
        elif prime_score > 0.0:
            recommendation = "Low Priority - Reduce allocation"
        else:
            recommendation = "Avoid - Poor performance"
        
        analysis = {
            "symbol": symbol,
            "performance_rating": rating,
            "recommendation": recommendation,
            "prime_score": prime_score,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "total_profit": performance['total_profit'],
            "avg_trade_size": performance['avg_trade_size'],
            "volatility": performance['volatility'],
            "recent_avg_prime": performance['recent_avg_prime'],
            "last_updated": performance['last_updated']
        }
        
        return analysis


# Example integration with Prime Trading Manager
class PrimeTradingManagerIntegration:
    """
    Example integration with Prime Trading Manager
    """
    
    def __init__(self, symbol_score: PrimeSymbolScore):
        self.symbol_score_integration = SymbolScoreIntegration(symbol_score)
    
    def on_position_closed(self, position_data: Dict) -> None:
        """
        Called when a position is closed in the trading system
        
        Args:
            position_data: Dictionary containing position information
        """
        symbol = position_data.get('symbol')
        trade_size = position_data.get('trade_size', 0)
        profit_loss = position_data.get('profit_loss', 0)
        trade_id = position_data.get('trade_id', '')
        strategy_mode = position_data.get('strategy_mode', 'standard')
        confidence = position_data.get('confidence', 0.0)
        
        if symbol and trade_size > 0:
            rank_score = self.symbol_score_integration.on_trade_closed(
                symbol=symbol,
                trade_size=trade_size,
                profit_loss=profit_loss,
                trade_id=trade_id,
                strategy_mode=strategy_mode,
                confidence=confidence
            )
            
            logger.info(f"Position closed: {symbol} - Rank Score: {rank_score:.2f}")
    
    def get_position_size_recommendation(self, 
                                       symbol: str, 
                                       base_size: float) -> float:
        """
        Get position size recommendation based on symbol performance
        
        Args:
            symbol: Trading symbol
            base_size: Base position size
            
        Returns:
            Recommended position size
        """
        multiplier = self.symbol_score_integration.should_increase_position_size(
            symbol=symbol,
            base_size=base_size
        )
        
        return base_size * multiplier
    
    def get_symbol_priority_list(self, 
                               candidate_symbols: List[str],
                               top_n: int = 5) -> List[str]:
        """
        Get prioritized list of symbols for trading
        
        Args:
            candidate_symbols: List of candidate symbols
            top_n: Number of top symbols to return
            
        Returns:
            List of prioritized symbols
        """
        return self.symbol_score_integration.get_top_priority_symbols(
            candidate_symbols=candidate_symbols,
            top_n=top_n
        )


# Example usage
if __name__ == "__main__":
    # Initialize symbol score system
    symbol_score = PrimeSymbolScore()
    
    # Initialize integration
    integration = SymbolScoreIntegration(symbol_score)
    
    # Simulate some trades
    print("Simulating trades...")
    
    # Add some example trades
    trades = [
        ("TQQQ", 600.0, 73.21, "TQQQ_001", "standard", 0.95),
        ("TQQQ", 1200.0, 144.00, "TQQQ_002", "advanced", 0.98),
        ("TQQQ", 500.0, -20.00, "TQQQ_003", "standard", 0.85),
        ("SPY", 600.0, 30.00, "SPY_001", "standard", 0.90),
        ("SPY", 900.0, 36.00, "SPY_002", "standard", 0.92),
        ("SPY", 500.0, 15.00, "SPY_003", "standard", 0.88),
        ("QQQ", 800.0, 45.00, "QQQ_001", "standard", 0.87),
        ("QQQ", 1000.0, 60.00, "QQQ_002", "advanced", 0.93),
    ]
    
    for symbol, trade_size, profit_loss, trade_id, strategy_mode, confidence in trades:
        integration.on_trade_closed(
            symbol=symbol,
            trade_size=trade_size,
            profit_loss=profit_loss,
            trade_id=trade_id,
            strategy_mode=strategy_mode,
            confidence=confidence
        )
    
    # Generate daily report
    print("\n" + integration.generate_daily_report())
    
    # Get symbol analysis
    print("\nSymbol Analysis:")
    for symbol in ["TQQQ", "SPY", "QQQ"]:
        analysis = integration.get_symbol_analysis(symbol)
        print(f"\n{symbol}:")
        for key, value in analysis.items():
            print(f"  {key}: {value}")
    
    # Get priority weights
    print("\nPriority Weights:")
    weights = integration.get_symbol_priority_weights(["TQQQ", "SPY", "QQQ", "IWM"])
    for symbol, weight in weights.items():
        print(f"  {symbol}: {weight:.2f}x")
