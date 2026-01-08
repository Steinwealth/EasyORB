"""
Prime Symbol Score - Symbol Performance Tracking System

This module implements a sophisticated symbol scoring system that tracks profits
per $100 invested for each symbol, providing a normalized metric to compare
performance across different instruments regardless of position size.

The system maintains rolling averages of rank scores for each symbol and generates
daily priority lists for trade allocation optimization.

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import json
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import asyncio
import aiofiles

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class TradeResult:
    """Data class for individual trade results"""
    symbol: str
    trade_size: float
    profit_loss: float
    prime_score: float
    timestamp: datetime
    trade_id: str
    strategy_mode: str
    confidence: float

@dataclass
class SymbolRank:
    """Data class for symbol ranking information"""
    symbol: str
    avg_prime_score: float
    total_trades: int
    profitable_trades: int
    win_rate: float
    total_profit: float
    avg_trade_size: float
    last_updated: datetime
    recent_prime_scores: List[float]  # Last N prime scores

class PrimeSymbolScore:
    """
    Prime Symbol Score System
    
    Tracks and analyzes symbol performance using a normalized profit-per-$100 metric.
    Maintains rolling averages and generates daily priority lists for trade allocation.
    """
    
    def __init__(self, 
                 max_trades_per_symbol: int = 300,
                 data_file: str = "data/symbol_scores.json",
                 backup_interval: int = 100):
        """
        Initialize the Prime Symbol Score system
        
        Args:
            max_trades_per_symbol: Maximum number of trades to keep per symbol
            data_file: Path to persistent data storage file
            backup_interval: Number of trades before creating backup
        """
        self.max_trades_per_symbol = max_trades_per_symbol
        self.data_file = Path(data_file)
        self.backup_interval = backup_interval
        
        # In-memory storage
        self.symbol_trades: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_trades_per_symbol)
        )
        self.symbol_ranks: Dict[str, SymbolRank] = {}
        self.trade_counter = 0
        
        # Performance metrics
        self.total_trades_processed = 0
        self.last_backup_time = datetime.now()
        
        # Load existing data
        self._load_data()
        
        logger.info(f"Prime Symbol Score initialized with {len(self.symbol_trades)} symbols")
    
    def _load_data(self) -> None:
        """Load existing symbol score data from file"""
        try:
            if self.data_file.exists():
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                
                # Load symbol trades
                for symbol, trades_data in data.get('symbol_trades', {}).items():
                    trades = []
                    for trade in trades_data:
                        # Handle both old and new field names for backward compatibility
                        prime_score = trade.get('prime_score', trade.get('rank_score', 0.0))
                        trade_result = TradeResult(
                            symbol=trade['symbol'],
                            trade_size=trade['trade_size'],
                            profit_loss=trade['profit_loss'],
                            prime_score=prime_score,
                            timestamp=datetime.fromisoformat(trade['timestamp']),
                            trade_id=trade['trade_id'],
                            strategy_mode=trade['strategy_mode'],
                            confidence=trade['confidence']
                        )
                        trades.append(trade_result)
                    
                    self.symbol_trades[symbol] = deque(trades, maxlen=self.max_trades_per_symbol)
                
                # Load symbol ranks
                for symbol, rank_data in data.get('symbol_ranks', {}).items():
                    # Handle both old and new field names for backward compatibility
                    avg_prime_score = rank_data.get('avg_prime_score', rank_data.get('rank_score', 0.0))
                    recent_prime_scores = rank_data.get('recent_prime_scores', rank_data.get('recent_trades', []))
                    
                    self.symbol_ranks[symbol] = SymbolRank(
                        symbol=rank_data['symbol'],
                        avg_prime_score=avg_prime_score,
                        total_trades=rank_data['total_trades'],
                        profitable_trades=rank_data['profitable_trades'],
                        win_rate=rank_data['win_rate'],
                        total_profit=rank_data['total_profit'],
                        avg_trade_size=rank_data['avg_trade_size'],
                        last_updated=datetime.fromisoformat(rank_data['last_updated']),
                        recent_prime_scores=recent_prime_scores
                    )
                
                self.trade_counter = data.get('trade_counter', 0)
                logger.info(f"Loaded {len(self.symbol_trades)} symbols with {self.trade_counter} total trades")
                
        except Exception as e:
            logger.error(f"Error loading symbol score data: {e}")
            # Initialize with empty data
            self.symbol_trades = defaultdict(lambda: deque(maxlen=self.max_trades_per_symbol))
            self.symbol_ranks = {}
            self.trade_counter = 0
    
    async def _save_data(self) -> None:
        """Save symbol score data to file asynchronously"""
        try:
            # Ensure data directory exists
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Prepare data for serialization
            data = {
                'symbol_trades': {},
                'symbol_ranks': {},
                'trade_counter': self.trade_counter,
                'last_updated': datetime.now().isoformat()
            }
            
            # Serialize symbol trades
            for symbol, trades in self.symbol_trades.items():
                trades_data = []
                for trade in trades:
                    trades_data.append({
                        'symbol': trade.symbol,
                        'trade_size': trade.trade_size,
                        'profit_loss': trade.profit_loss,
                        'prime_score': trade.prime_score,
                        'timestamp': trade.timestamp.isoformat(),
                        'trade_id': trade.trade_id,
                        'strategy_mode': trade.strategy_mode,
                        'confidence': trade.confidence
                    })
                data['symbol_trades'][symbol] = trades_data
            
            # Serialize symbol ranks
            for symbol, rank in self.symbol_ranks.items():
                data['symbol_ranks'][symbol] = {
                    'symbol': rank.symbol,
                    'avg_prime_score': rank.avg_prime_score,
                    'total_trades': rank.total_trades,
                    'profitable_trades': rank.profitable_trades,
                    'win_rate': rank.win_rate,
                    'total_profit': rank.total_profit,
                    'avg_trade_size': rank.avg_trade_size,
                    'last_updated': rank.last_updated.isoformat(),
                    'recent_prime_scores': rank.recent_prime_scores
                }
            
            # Save to file
            async with aiofiles.open(self.data_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
            
            logger.debug(f"Symbol score data saved to {self.data_file}")
            
        except Exception as e:
            logger.error(f"Error saving symbol score data: {e}")
    
    def calculate_prime_score(self, trade_size: float, profit_loss: float) -> float:
        """
        Calculate prime score for a trade (profit per $100 invested)
        
        Formula: profit / (trade_size / 100) = (profit * 100) / trade_size
        
        Args:
            trade_size: Size of the trade in dollars
            profit_loss: Profit or loss from the trade in dollars
            
        Returns:
            Prime score (profit per $100 invested)
        """
        if trade_size <= 0:
            return 0.0
        
        prime_score = (profit_loss * 100) / trade_size
        return round(prime_score, 4)
    
    def add_trade_result(self, 
                        symbol: str,
                        trade_size: float,
                        profit_loss: float,
                        trade_id: str,
                        strategy_mode: str = "standard",
                        confidence: float = 0.0) -> float:
        """
        Add a completed trade result and calculate prime score
        
        Args:
            symbol: Trading symbol
            trade_size: Size of the trade in dollars
            profit_loss: Profit or loss from the trade in dollars
            trade_id: Unique identifier for the trade
            strategy_mode: Strategy mode used for the trade
            confidence: Confidence level of the trade
            
        Returns:
            Calculated prime score for this trade
        """
        # Calculate prime score
        prime_score = self.calculate_prime_score(trade_size, profit_loss)
        
        # Create trade result
        trade_result = TradeResult(
            symbol=symbol.upper(),
            trade_size=trade_size,
            profit_loss=profit_loss,
            prime_score=prime_score,
            timestamp=datetime.now(),
            trade_id=trade_id,
            strategy_mode=strategy_mode,
            confidence=confidence
        )
        
        # Add to symbol trades
        self.symbol_trades[symbol.upper()].append(trade_result)
        
        # Update symbol rank
        self._update_symbol_rank(symbol.upper())
        
        # Increment counters
        self.trade_counter += 1
        self.total_trades_processed += 1
        
        # Save data periodically
        if self.trade_counter % self.backup_interval == 0:
            asyncio.create_task(self._save_data())
        
        logger.info(f"Added trade result for {symbol}: ${profit_loss:.2f} profit on ${trade_size:.2f} trade (Prime Score: {prime_score:.2f})")
        
        return prime_score
    
    def _update_symbol_rank(self, symbol: str) -> None:
        """Update symbol rank based on recent trades (last 200 trades)"""
        trades = self.symbol_trades[symbol]
        
        if not trades:
            return
        
        # Get last 200 trades for rolling average
        recent_trades = list(trades)[-200:] if len(trades) > 200 else list(trades)
        
        # Calculate metrics
        prime_scores = [trade.prime_score for trade in recent_trades]
        profitable_trades = sum(1 for trade in recent_trades if trade.profit_loss > 0)
        total_profit = sum(trade.profit_loss for trade in recent_trades)
        avg_trade_size = sum(trade.trade_size for trade in recent_trades) / len(recent_trades)
        
        # Calculate average prime score (rolling 200-trade average)
        avg_prime_score = sum(prime_scores) / len(prime_scores)
        
        # Calculate win rate
        win_rate = (profitable_trades / len(recent_trades)) * 100 if recent_trades else 0
        
        # Update or create symbol rank
        self.symbol_ranks[symbol] = SymbolRank(
            symbol=symbol,
            avg_prime_score=round(avg_prime_score, 4),
            total_trades=len(trades),  # Total trades ever
            profitable_trades=profitable_trades,
            win_rate=round(win_rate, 2),
            total_profit=round(total_profit, 2),
            avg_trade_size=round(avg_trade_size, 2),
            last_updated=datetime.now(),
            recent_prime_scores=prime_scores[-10:]  # Keep last 10 scores for detailed analysis
        )
    
    def get_symbol_rank(self, symbol: str) -> Optional[SymbolRank]:
        """
        Get current rank information for a symbol
        
        Args:
            symbol: Trading symbol
            
        Returns:
            SymbolRank object or None if symbol not found
        """
        return self.symbol_ranks.get(symbol.upper())
    
    def get_daily_priority_list(self, min_trades: int = 5) -> List[Tuple[str, SymbolRank]]:
        """
        Get daily priority list of symbols sorted by average prime score
        
        Args:
            min_trades: Minimum number of trades required to include symbol
            
        Returns:
            List of (symbol, SymbolRank) tuples sorted by average prime score (descending)
        """
        # Filter symbols with minimum trade count
        qualified_symbols = [
            (symbol, rank) for symbol, rank in self.symbol_ranks.items()
            if rank.total_trades >= min_trades
        ]
        
        # Sort by average prime score (descending)
        sorted_symbols = sorted(
            qualified_symbols,
            key=lambda x: x[1].avg_prime_score,
            reverse=True
        )
        
        return sorted_symbols
    
    def get_top_performers(self, top_n: int = 10, min_trades: int = 5) -> List[Tuple[str, SymbolRank]]:
        """
        Get top N performing symbols
        
        Args:
            top_n: Number of top performers to return
            min_trades: Minimum number of trades required
            
        Returns:
            List of top performing symbols
        """
        priority_list = self.get_daily_priority_list(min_trades)
        return priority_list[:top_n]
    
    def get_symbol_performance_summary(self, symbol: str) -> Dict[str, Any]:
        """
        Get detailed performance summary for a symbol
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with performance metrics
        """
        rank = self.get_symbol_rank(symbol.upper())
        if not rank:
            return {}
        
        trades = self.symbol_trades[symbol.upper()]
        
        # Calculate additional metrics
        recent_10_trades = list(trades)[-10:] if trades else []
        recent_avg_prime = sum(t.prime_score for t in recent_10_trades) / len(recent_10_trades) if recent_10_trades else 0
        
        # Calculate volatility (standard deviation of prime scores)
        prime_scores = [trade.prime_score for trade in trades]
        if len(prime_scores) > 1:
            mean_prime = sum(prime_scores) / len(prime_scores)
            variance = sum((score - mean_prime) ** 2 for score in prime_scores) / len(prime_scores)
            volatility = variance ** 0.5
        else:
            volatility = 0
        
        return {
            'symbol': symbol.upper(),
            'avg_prime_score': rank.avg_prime_score,
            'total_trades': rank.total_trades,
            'profitable_trades': rank.profitable_trades,
            'win_rate': rank.win_rate,
            'total_profit': rank.total_profit,
            'avg_trade_size': rank.avg_trade_size,
            'recent_avg_prime': round(recent_avg_prime, 4),
            'volatility': round(volatility, 4),
            'last_updated': rank.last_updated.isoformat(),
            'recent_prime_scores': rank.recent_prime_scores
        }
    
    def get_all_symbols_summary(self) -> Dict[str, Any]:
        """Get summary of all symbols with their performance metrics"""
        summary = {}
        for symbol in self.symbol_ranks.keys():
            summary[symbol] = self.get_symbol_performance_summary(symbol)
        return summary
    
    def cleanup_old_data(self, days_to_keep: int = 90) -> None:
        """
        Clean up old trade data beyond specified days
        
        Args:
            days_to_keep: Number of days of data to keep
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        symbols_to_remove = []
        
        for symbol, trades in self.symbol_trades.items():
            # Remove old trades
            original_count = len(trades)
            while trades and trades[0].timestamp < cutoff_date:
                trades.popleft()
            
            # If no trades left, mark for removal
            if not trades:
                symbols_to_remove.append(symbol)
            else:
                # Update symbol rank
                self._update_symbol_rank(symbol)
        
        # Remove symbols with no trades
        for symbol in symbols_to_remove:
            del self.symbol_trades[symbol]
            if symbol in self.symbol_ranks:
                del self.symbol_ranks[symbol]
        
        logger.info(f"Cleaned up old data, removed {len(symbols_to_remove)} symbols")
    
    def export_priority_list(self, filename: str = None) -> str:
        """
        Export daily priority list to CSV file
        
        Args:
            filename: Output filename (optional)
            
        Returns:
            Path to exported file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"symbol_priority_list_{timestamp}.csv"
        
        filepath = Path(filename)
        
        # Get priority list
        priority_list = self.get_daily_priority_list()
        
        # Write CSV
        with open(filepath, 'w') as f:
            f.write("Rank,Symbol,Avg_Prime_Score,Total_Trades,Win_Rate,Total_Profit,Avg_Trade_Size,Last_Updated\n")
            
            for rank, (symbol, symbol_rank) in enumerate(priority_list, 1):
                f.write(f"{rank},{symbol},{symbol_rank.avg_prime_score:.4f},"
                       f"{symbol_rank.total_trades},{symbol_rank.win_rate:.2f}%,"
                       f"{symbol_rank.total_profit:.2f},{symbol_rank.avg_trade_size:.2f},"
                       f"{symbol_rank.last_updated.isoformat()}\n")
        
        logger.info(f"Priority list exported to {filepath}")
        return str(filepath)
    
    async def save_data(self) -> None:
        """Public method to save data"""
        await self._save_data()
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics"""
        total_symbols = len(self.symbol_ranks)
        total_trades = sum(rank.total_trades for rank in self.symbol_ranks.values())
        
        # Calculate overall performance
        all_prime_scores = []
        for trades in self.symbol_trades.values():
            all_prime_scores.extend([trade.prime_score for trade in trades])
        
        avg_prime_score = sum(all_prime_scores) / len(all_prime_scores) if all_prime_scores else 0
        
        return {
            'total_symbols': total_symbols,
            'total_trades': total_trades,
            'avg_prime_score': round(avg_prime_score, 4),
            'trades_processed': self.total_trades_processed,
            'last_backup': self.last_backup_time.isoformat(),
            'data_file': str(self.data_file)
        }


# Example usage and testing
if __name__ == "__main__":
    # Initialize the system
    symbol_score = PrimeSymbolScore()
    
    # Example trades
    print("Adding example trades...")
    
    # TQQQ trades
    symbol_score.add_trade_result("TQQQ", 600.0, 73.21, "TQQQ_001", "standard", 0.95)
    symbol_score.add_trade_result("TQQQ", 1200.0, 144.00, "TQQQ_002", "advanced", 0.98)
    symbol_score.add_trade_result("TQQQ", 500.0, -20.00, "TQQQ_003", "standard", 0.85)
    
    # SPY trades
    symbol_score.add_trade_result("SPY", 600.0, 30.00, "SPY_001", "standard", 0.90)
    symbol_score.add_trade_result("SPY", 900.0, 36.00, "SPY_002", "standard", 0.92)
    symbol_score.add_trade_result("SPY", 500.0, 15.00, "SPY_003", "standard", 0.88)
    
    # Get priority list
    print("\nDaily Priority List:")
    priority_list = symbol_score.get_daily_priority_list()
    for rank, (symbol, symbol_rank) in enumerate(priority_list, 1):
        print(f"{rank}. {symbol}: {symbol_rank.avg_prime_score:.2f} per $100 "
              f"({symbol_rank.total_trades} trades, {symbol_rank.win_rate:.1f}% win rate)")
    
    # Get system stats
    print("\nSystem Statistics:")
    stats = symbol_score.get_system_stats()
    for key, value in stats.items():
        print(f"{key}: {value}")
