#!/usr/bin/env python3
"""
Prime Sentiment Tracker
======================

Advanced sentiment tracking system for the Easy ORB Strategy.
Tracks daily sentiment scores for all symbols in the core list,
integrates with news sentiment analysis, and provides real-time
sentiment context for trading decisions and confidence boosting.

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    from .prime_news_manager import PrimeNewsManager, NewsSentimentResult
    from .config_loader import get_config_value
except ImportError:
    from prime_news_manager import PrimeNewsManager, NewsSentimentResult
    from config_loader import get_config_value

log = logging.getLogger("prime_sentiment_tracker")

@dataclass
class SymbolSentiment:
    """Daily sentiment data for a symbol"""
    symbol: str
    date: str
    sentiment_score: float  # -1.0 to +1.0
    confidence: float       # 0.0 to 1.0
    news_count: int
    source_breakdown: Dict[str, int]  # News source counts
    keywords_matched: List[str]
    underlying: str
    category: str
    leverage: str
    is_bull: bool
    is_bear: bool
    bear_etf: Optional[str] = None
    bull_etf: Optional[str] = None
    timestamp: str = None

@dataclass
class DailySentimentSummary:
    """Summary of daily sentiment across all symbols"""
    date: str
    total_symbols: int
    positive_sentiment: int
    negative_sentiment: int
    neutral_sentiment: int
    average_sentiment: float
    high_confidence_count: int
    top_positive: List[str]
    top_negative: List[str]
    category_breakdown: Dict[str, Dict[str, int]]

class PrimeSentimentTracker:
    """
    Advanced sentiment tracking system for the Easy ORB Strategy.
    Tracks daily sentiment scores for all symbols in the core list,
    integrates with news sentiment analysis, and provides sentiment-based
    confidence boosting for trading decisions.
    """
    
    def __init__(self, sentiment_mapping_file: str = "data/watchlist/complete_sentiment_mapping.json"):
        self.sentiment_mapping_file = Path(sentiment_mapping_file)
        self.sentiment_data = self._load_sentiment_mapping()
        self.news_manager = PrimeNewsManager()
        
        # Configuration
        self.update_frequency = get_config_value("SENTIMENT_UPDATE_FREQUENCY", "hourly")
        self.retention_days = get_config_value("SENTIMENT_RETENTION_DAYS", 30)
        self.confidence_threshold = get_config_value("SENTIMENT_CONFIDENCE_THRESHOLD", 0.6)
        
        # Data storage
        self.daily_sentiments: Dict[str, List[SymbolSentiment]] = {}
        self.sentiment_history: Dict[str, List[SymbolSentiment]] = {}
        
        log.info("Prime Sentiment Tracker initialized")
    
    def _load_sentiment_mapping(self) -> Dict[str, Any]:
        """Load sentiment mapping data"""
        try:
            with open(self.sentiment_mapping_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error loading sentiment mapping: {e}")
            return {"bull_bear_pairs": {}}
    
    def get_symbol_context(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get sentiment context for a symbol"""
        return self.sentiment_data.get("bull_bear_pairs", {}).get(symbol)
    
    def get_sentiment_keywords(self, symbol: str) -> List[str]:
        """Get sentiment keywords for a symbol"""
        context = self.get_symbol_context(symbol)
        if context:
            return context.get("sentiment_keywords", [])
        return []
    
    def is_bull_etf(self, symbol: str) -> bool:
        """Check if symbol is a bull ETF"""
        context = self.get_symbol_context(symbol)
        if context:
            bear_etf = context.get("bear_etf")
            return bear_etf is not None and bear_etf != "N/A"
        return False
    
    def is_bear_etf(self, symbol: str) -> bool:
        """Check if symbol is a bear ETF"""
        context = self.get_symbol_context(symbol)
        if context:
            bull_etf = context.get("bull_etf")
            return bull_etf is not None and bull_etf != "N/A"
        return False
    
    async def analyze_symbol_sentiment(self, symbol: str, date: str = None) -> Optional[SymbolSentiment]:
        """Analyze sentiment for a specific symbol"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        context = self.get_symbol_context(symbol)
        if not context:
            log.warning(f"No sentiment context found for symbol: {symbol}")
            return None
        
        try:
            # Get sentiment keywords
            keywords = context.get("sentiment_keywords", [])
            
            # Analyze news sentiment
            sentiment_result = await self.news_manager.analyze_sentiment(
                keywords=keywords,
                date_range=1  # Last 24 hours
            )
            
            if not sentiment_result:
                log.warning(f"No sentiment data for {symbol}")
                return None
            
            # Determine if symbol is bull or bear
            is_bull = self.is_bull_etf(symbol)
            is_bear = self.is_bear_etf(symbol)
            
            # Create sentiment record
            sentiment = SymbolSentiment(
                symbol=symbol,
                date=date,
                sentiment_score=sentiment_result.overall_sentiment,
                confidence=sentiment_result.confidence,
                news_count=sentiment_result.news_count,
                source_breakdown=sentiment_result.source_breakdown,
                keywords_matched=sentiment_result.keywords_matched,
                underlying=context.get("underlying", ""),
                category=context.get("category", ""),
                leverage=context.get("leverage", ""),
                is_bull=is_bull,
                is_bear=is_bear,
                bear_etf=context.get("bear_etf"),
                bull_etf=context.get("bull_etf"),
                timestamp=datetime.now().isoformat()
            )
            
            return sentiment
            
        except Exception as e:
            log.error(f"Error analyzing sentiment for {symbol}: {e}")
            return None
    
    async def update_daily_sentiments(self, symbols: List[str], date: str = None) -> Dict[str, SymbolSentiment]:
        """Update daily sentiment scores for all symbols"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        log.info(f"Updating daily sentiments for {len(symbols)} symbols on {date}")
        
        daily_sentiments = {}
        
        # Process symbols in batches to avoid overwhelming news APIs
        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            # Analyze sentiment for batch
            tasks = [self.analyze_symbol_sentiment(symbol, date) for symbol in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for symbol, result in zip(batch, results):
                if isinstance(result, Exception):
                    log.error(f"Error processing {symbol}: {result}")
                elif result:
                    daily_sentiments[symbol] = result
            
            # Small delay between batches
            await asyncio.sleep(1)
        
        # Store daily sentiments
        self.daily_sentiments[date] = list(daily_sentiments.values())
        
        # Update history
        for symbol, sentiment in daily_sentiments.items():
            if symbol not in self.sentiment_history:
                self.sentiment_history[symbol] = []
            self.sentiment_history[symbol].append(sentiment)
        
        log.info(f"Updated sentiments for {len(daily_sentiments)} symbols")
        return daily_sentiments
    
    def calculate_confidence_boost(self, symbol: str, base_confidence: float) -> float:
        """Calculate confidence boost based on sentiment"""
        if date not in self.daily_sentiments:
            return 0.0
        
        # Find sentiment for symbol
        symbol_sentiment = None
        for sentiment in self.daily_sentiments[date]:
            if sentiment.symbol == symbol:
                symbol_sentiment = sentiment
                break
        
        if not symbol_sentiment or symbol_sentiment.confidence < self.confidence_threshold:
            return 0.0
        
        # Get boost factor based on leverage
        leverage = symbol_sentiment.leverage
        boost_factor = self.sentiment_data.get("confidence_boost_factors", {}).get(f"{leverage}_leverage", 0.2)
        
        # Calculate boost based on sentiment and symbol type
        if symbol_sentiment.is_bull:
            # Positive news on bull = positive boost
            # Negative news on bull = negative boost
            boost = symbol_sentiment.sentiment_score * boost_factor
        elif symbol_sentiment.is_bear:
            # Positive news on bear = negative boost (inverse)
            # Negative news on bear = positive boost (inverse)
            boost = -symbol_sentiment.sentiment_score * boost_factor
        else:
            # No boost for non-paired symbols
            boost = 0.0
        
        # Cap boost at ±50% of base confidence
        max_boost = base_confidence * 0.5
        return max(-max_boost, min(max_boost, boost))
    
    def get_daily_summary(self, date: str = None) -> Optional[DailySentimentSummary]:
        """Get daily sentiment summary"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        if date not in self.daily_sentiments:
            return None
        
        sentiments = self.daily_sentiments[date]
        
        # Calculate summary statistics
        total_symbols = len(sentiments)
        positive_count = sum(1 for s in sentiments if s.sentiment_score > 0.1)
        negative_count = sum(1 for s in sentiments if s.sentiment_score < -0.1)
        neutral_count = total_symbols - positive_count - negative_count
        
        average_sentiment = sum(s.sentiment_score for s in sentiments) / total_symbols if total_symbols > 0 else 0.0
        high_confidence_count = sum(1 for s in sentiments if s.confidence >= self.confidence_threshold)
        
        # Top positive and negative symbols
        sorted_sentiments = sorted(sentiments, key=lambda x: x.sentiment_score, reverse=True)
        top_positive = [s.symbol for s in sorted_sentiments[:5]]
        top_negative = [s.symbol for s in sorted_sentiments[-5:]]
        
        # Category breakdown
        category_breakdown = {}
        for sentiment in sentiments:
            category = sentiment.category
            if category not in category_breakdown:
                category_breakdown[category] = {"positive": 0, "negative": 0, "neutral": 0}
            
            if sentiment.sentiment_score > 0.1:
                category_breakdown[category]["positive"] += 1
            elif sentiment.sentiment_score < -0.1:
                category_breakdown[category]["negative"] += 1
            else:
                category_breakdown[category]["neutral"] += 1
        
        return DailySentimentSummary(
            date=date,
            total_symbols=total_symbols,
            positive_sentiment=positive_count,
            negative_sentiment=negative_count,
            neutral_sentiment=neutral_count,
            average_sentiment=average_sentiment,
            high_confidence_count=high_confidence_count,
            top_positive=top_positive,
            top_negative=top_negative,
            category_breakdown=category_breakdown
        )
    
    def save_sentiment_data(self, file_path: str = "data/sentiment_history.json"):
        """Save sentiment data to file"""
        try:
            data = {
                "daily_sentiments": {
                    date: [asdict(sentiment) for sentiment in sentiments]
                    for date, sentiments in self.daily_sentiments.items()
                },
                "sentiment_history": {
                    symbol: [asdict(sentiment) for sentiment in sentiments]
                    for symbol, sentiments in self.sentiment_history.items()
                },
                "last_updated": datetime.now().isoformat()
            }
            
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            log.info(f"Sentiment data saved to {file_path}")
            
        except Exception as e:
            log.error(f"Error saving sentiment data: {e}")
    
    def load_sentiment_data(self, file_path: str = "data/sentiment_history.json"):
        """Load sentiment data from file"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Load daily sentiments
            self.daily_sentiments = {}
            for date, sentiments_data in data.get("daily_sentiments", {}).items():
                self.daily_sentiments[date] = [
                    SymbolSentiment(**sentiment_data)
                    for sentiment_data in sentiments_data
                ]
            
            # Load sentiment history
            self.sentiment_history = {}
            for symbol, sentiments_data in data.get("sentiment_history", {}).items():
                self.sentiment_history[symbol] = [
                    SymbolSentiment(**sentiment_data)
                    for sentiment_data in sentiments_data
                ]
            
            log.info(f"Sentiment data loaded from {file_path}")
            
        except Exception as e:
            log.error(f"Error loading sentiment data: {e}")

# Global instance
_prime_sentiment_tracker = None

def get_prime_sentiment_tracker() -> PrimeSentimentTracker:
    """Get global prime sentiment tracker instance"""
    global _prime_sentiment_tracker
    if _prime_sentiment_tracker is None:
        _prime_sentiment_tracker = PrimeSentimentTracker()
    return _prime_sentiment_tracker

async def update_daily_sentiments(symbols: List[str]) -> Dict[str, SymbolSentiment]:
    """Update daily sentiments for all symbols"""
    tracker = get_prime_sentiment_tracker()
    return await tracker.update_daily_sentiments(symbols)

def get_confidence_boost(symbol: str, base_confidence: float, date: str = None) -> float:
    """Get confidence boost for a symbol based on sentiment"""
    tracker = get_prime_sentiment_tracker()
    return tracker.calculate_confidence_boost(symbol, base_confidence)

if __name__ == "__main__":
    # Test the sentiment tracker
    async def test_sentiment_tracker():
        tracker = PrimeSentimentTracker()
        
        # Test symbols
        test_symbols = ["TQQQ", "SQQQ", "UPRO", "SPXU", "TSLL", "TSLS"]
        
        # Update sentiments
        sentiments = await tracker.update_daily_sentiments(test_symbols)
        
        # Print results
        for symbol, sentiment in sentiments.items():
            print(f"{symbol}: {sentiment.sentiment_score:.3f} (confidence: {sentiment.confidence:.3f})")
        
        # Get summary
        summary = tracker.get_daily_summary()
        if summary:
            print(f"\nDaily Summary:")
            print(f"Total symbols: {summary.total_symbols}")
            print(f"Positive: {summary.positive_sentiment}")
            print(f"Negative: {summary.negative_sentiment}")
            print(f"Average sentiment: {summary.average_sentiment:.3f}")
    
    asyncio.run(test_sentiment_tracker())
