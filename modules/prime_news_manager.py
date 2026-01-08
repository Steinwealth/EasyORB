"""
Unified News Manager

This module consolidates ALL news-related functionality including:
- Multi-source news aggregation (Polygon, Finnhub, NewsAPI)
- Advanced VADER sentiment analysis with confidence scoring
- Market-aware news timing and relevance
- Intelligent caching and performance optimization
- Real-time confluence detection and market impact assessment
- Trading-specific relevance scoring
"""

import asyncio
import aiohttp
import json
import logging
import re
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .config_loader import get_config_value

log = logging.getLogger(__name__)

class NewsCategory(Enum):
    """News categories"""
    EARNINGS = "earnings"
    MERGER = "merger"
    PRODUCT = "product"
    REGULATORY = "regulatory"
    ANALYST = "analyst"
    GUIDANCE = "guidance"
    GENERAL = "general"
    BREAKING = "breaking"

class NewsSource(Enum):
    """News sources"""
    POLYGON = "polygon"
    FINNHUB = "finnhub"
    NEWSAPI = "newsapi"
    REUTERS = "reuters"
    BLOOMBERG = "bloomberg"
    CNBC = "cnbc"

class SentimentStrength(Enum):
    """Sentiment strength levels"""
    VERY_NEGATIVE = "very_negative"  # < -0.6
    NEGATIVE = "negative"            # -0.6 to -0.2
    NEUTRAL = "neutral"              # -0.2 to 0.2
    POSITIVE = "positive"            # 0.2 to 0.6
    VERY_POSITIVE = "very_positive"  # > 0.6

@dataclass
class NewsItem:
    """Enhanced news item with comprehensive sentiment analysis"""
    title: str
    summary: str
    timestamp: datetime
    source: str
    sentiment_score: float  # -1 to 1
    confidence: float  # 0 to 1
    relevance_score: float  # Trading relevance 0 to 1
    impact_score: float  # Market impact 0 to 1
    url: str = ""
    category: NewsCategory = NewsCategory.GENERAL
    keywords: List[str] = field(default_factory=list)
    market_cap_impact: float = 0.0  # 0 to 1, based on company size
    sector: str = "unknown"
    language: str = "en"
    symbols_mentioned: List[str] = field(default_factory=list)
    sentiment_strength: SentimentStrength = SentimentStrength.NEUTRAL
    
    def __post_init__(self):
        # Determine sentiment strength
        if self.sentiment_score <= -0.6:
            self.sentiment_strength = SentimentStrength.VERY_NEGATIVE
        elif self.sentiment_score <= -0.2:
            self.sentiment_strength = SentimentStrength.NEGATIVE
        elif self.sentiment_score >= 0.6:
            self.sentiment_strength = SentimentStrength.VERY_POSITIVE
        elif self.sentiment_score >= 0.2:
            self.sentiment_strength = SentimentStrength.POSITIVE
        else:
            self.sentiment_strength = SentimentStrength.NEUTRAL

@dataclass
class NewsSentimentResult:
    """Comprehensive news sentiment analysis result"""
    symbol: str
    overall_sentiment: float  # -1 to 1
    sentiment_confidence: float  # 0 to 1
    news_quality_score: float  # 0 to 1
    market_impact: float  # 0 to 1
    trading_implications: str  # strong_positive, positive, neutral, negative, strong_negative
    risk_adjustment: float  # Risk adjustment factor
    position_size_adjustment: float  # Position size adjustment
    expected_volatility: float  # Expected volatility
    news_count: int
    latest_news_time: datetime
    sentiment_trend: str  # improving, declining, stable
    breaking_news: bool
    earnings_related: bool
    high_impact_news: bool
    news_items: List[NewsItem] = field(default_factory=list)
    sentiment_distribution: Dict[str, int] = field(default_factory=dict)
    category_breakdown: Dict[str, int] = field(default_factory=dict)
    source_breakdown: Dict[str, int] = field(default_factory=dict)

@dataclass
class NewsConfig:
    """News analysis configuration"""
    # API configurations
    polygon_api_key: str = ""
    finnhub_api_key: str = ""
    newsapi_api_key: str = ""
    
    # Analysis settings
    lookback_hours: int = 24
    min_relevance_score: float = 0.3
    min_confidence_threshold: float = 0.5
    max_news_items: int = 50
    
    # Performance settings
    max_concurrent_requests: int = 5
    request_timeout_seconds: int = 30
    cache_ttl_seconds: int = 1800  # 30 minutes
    rate_limit_per_minute: int = 60
    
    # Market timing settings
    market_hours_boost: float = 1.5  # Boost relevance during market hours
    breaking_news_threshold_minutes: int = 60
    earnings_keywords: List[str] = field(default_factory=lambda: [
        'earnings', 'revenue', 'profit', 'eps', 'guidance', 'outlook'
    ])

@dataclass
class NewsPerformanceMetrics:
    """News analysis performance metrics"""
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    api_calls: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_response_time_ms: float = 0.0
    total_news_items: int = 0
    high_relevance_items: int = 0
    breaking_news_count: int = 0
    earnings_news_count: int = 0
    sentiment_accuracy: float = 0.0
    last_reset: datetime = field(default_factory=datetime.now)

class PrimeNewsManager:
    """
    Unified news manager that consolidates ALL news functionality
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, market_manager=None):
        self.config = config or {}
        self.market_manager = market_manager
        
        # News configuration
        self.news_config = NewsConfig(
            polygon_api_key=get_config_value('POLYGON_API_KEY', ''),
            finnhub_api_key=get_config_value('FINNHUB_API_KEY', ''),
            newsapi_api_key=get_config_value('NEWSAPI_API_KEY', ''),
            lookback_hours=get_config_value('NEWS_LOOKBACK_HOURS', 24),
            min_relevance_score=get_config_value('MIN_NEWS_RELEVANCE', 0.3),
            min_confidence_threshold=get_config_value('MIN_NEWS_CONFIDENCE', 0.5),
            max_news_items=get_config_value('MAX_NEWS_ITEMS', 50),
            max_concurrent_requests=get_config_value('MAX_NEWS_REQUESTS', 5),
            request_timeout_seconds=get_config_value('NEWS_TIMEOUT', 30),
            cache_ttl_seconds=get_config_value('NEWS_CACHE_TTL', 1800),
            rate_limit_per_minute=get_config_value('NEWS_RATE_LIMIT', 60)
        )
        
        # Sentiment analyzer
        self.sentiment_analyzer = SentimentIntensityAnalyzer()
        
        # Caching
        self.cache = {}
        self.cache_timestamps = {}
        self.rate_limiters = defaultdict(deque)
        
        # Performance metrics
        self.metrics = NewsPerformanceMetrics()
        
        # Session for HTTP requests
        self.session: Optional[aiohttp.ClientSession] = None
        
        log.info("Unified News Manager initialized")
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self._close_session()
    
    async def _ensure_session(self):
        """Ensure aiohttp session is available"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.news_config.request_timeout_seconds)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def _close_session(self):
        """Close aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def _generate_cache_key(self, symbol: str, lookback_hours: int, source: str = "all") -> str:
        """Generate cache key for news sentiment"""
        key_data = f"{symbol}_{lookback_hours}_{source}_{datetime.now().strftime('%Y%m%d%H')}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cache entry is valid"""
        if cache_key not in self.cache_timestamps:
            return False
        
        age = time.time() - self.cache_timestamps[cache_key]
        return age < self.news_config.cache_ttl_seconds
    
    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Get value from cache if valid"""
        if self._is_cache_valid(cache_key):
            self.metrics.cache_hits += 1
            return self.cache.get(cache_key)
        
        self.metrics.cache_misses += 1
        return None
    
    def _set_cache(self, cache_key: str, value: Any):
        """Set value in cache"""
        self.cache[cache_key] = value
        self.cache_timestamps[cache_key] = time.time()
    
    def _check_rate_limit(self, source: str) -> bool:
        """Check if we can make a request to source"""
        now = time.time()
        minute_ago = now - 60
        
        # Remove old requests
        while self.rate_limiters[source] and self.rate_limiters[source][0] < minute_ago:
            self.rate_limiters[source].popleft()
        
        # Check if under limit
        if len(self.rate_limiters[source]) >= self.news_config.rate_limit_per_minute:
            return False
        
        # Add current request
        self.rate_limiters[source].append(now)
        return True
    
    def _classify_news_category(self, title: str, summary: str) -> NewsCategory:
        """Classify news into categories"""
        text = f"{title} {summary}".lower()
        
        if any(keyword in text for keyword in self.news_config.earnings_keywords):
            return NewsCategory.EARNINGS
        elif any(keyword in text for keyword in ['merger', 'acquisition', 'buyout', 'takeover']):
            return NewsCategory.MERGER
        elif any(keyword in text for keyword in ['product', 'launch', 'release', 'innovation']):
            return NewsCategory.PRODUCT
        elif any(keyword in text for keyword in ['regulation', 'fda', 'approval', 'compliance']):
            return NewsCategory.REGULATORY
        elif any(keyword in text for keyword in ['analyst', 'rating', 'upgrade', 'downgrade']):
            return NewsCategory.ANALYST
        elif any(keyword in text for keyword in ['guidance', 'forecast', 'outlook', 'target']):
            return NewsCategory.GUIDANCE
        elif any(keyword in text for keyword in ['breaking', 'urgent', 'alert']):
            return NewsCategory.BREAKING
        else:
            return NewsCategory.GENERAL
    
    def _extract_symbols(self, text: str) -> List[str]:
        """Extract stock symbols from text"""
        # Simple symbol extraction - could be enhanced
        import re
        
        # Look for patterns like $AAPL or AAPL
        symbol_pattern = r'\$?([A-Z]{1,5})\b'
        matches = re.findall(symbol_pattern, text.upper())
        
        # Filter out common words that look like symbols
        common_words = {'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER', 'WAS', 'ONE', 'OUR'}
        symbols = [match for match in matches if match not in common_words and len(match) <= 5]
        
        return list(set(symbols))  # Remove duplicates
    
    def _calculate_relevance_score(self, news_item: NewsItem, target_symbol: str) -> float:
        """Calculate trading relevance score"""
        relevance = 0.0
        
        # Symbol mention
        if target_symbol.upper() in news_item.symbols_mentioned:
            relevance += 0.4
        elif target_symbol.upper() in news_item.title.upper():
            relevance += 0.3
        elif target_symbol.upper() in news_item.summary.upper():
            relevance += 0.2
        
        # Category relevance
        category_weights = {
            NewsCategory.EARNINGS: 0.3,
            NewsCategory.MERGER: 0.25,
            NewsCategory.ANALYST: 0.2,
            NewsCategory.GUIDANCE: 0.2,
            NewsCategory.REGULATORY: 0.15,
            NewsCategory.PRODUCT: 0.1,
            NewsCategory.GENERAL: 0.05,
            NewsCategory.BREAKING: 0.2
        }
        relevance += category_weights.get(news_item.category, 0.05)
        
        # Source reliability
        source_weights = {
            'reuters': 0.2,
            'bloomberg': 0.2,
            'cnbc': 0.15,
            'marketwatch': 0.15,
            'yahoo': 0.1,
            'seekingalpha': 0.1
        }
        for source, weight in source_weights.items():
            if source in news_item.source.lower():
                relevance += weight
                break
        else:
            relevance += 0.05  # Unknown source
        
        # Time relevance (boost recent news)
        hours_old = (datetime.now() - news_item.timestamp).total_seconds() / 3600
        if hours_old < 1:
            relevance += 0.1
        elif hours_old < 6:
            relevance += 0.05
        
        # Market timing boost
        if self.market_manager:
            news_relevance = self.market_manager.get_news_relevance(news_item.timestamp)
            if hasattr(news_relevance, 'name'):
                if news_relevance.name == 'CRITICAL':
                    relevance *= 1.5
                elif news_relevance.name == 'HIGH':
                    relevance *= 1.2
        
        return min(1.0, relevance)
    
    def _analyze_sentiment(self, text: str) -> Tuple[float, float]:
        """Analyze sentiment using VADER"""
        try:
            scores = self.sentiment_analyzer.polarity_scores(text)
            
            # Calculate overall sentiment (-1 to 1)
            sentiment = scores['compound']
            
            # Calculate confidence based on intensity
            confidence = max(abs(scores['pos']), abs(scores['neg']), scores['neu'])
            
            return sentiment, confidence
            
        except Exception as e:
            log.error(f"Error analyzing sentiment: {e}")
            return 0.0, 0.0
    
    def _calculate_market_impact(self, news_item: NewsItem, target_symbol: str) -> float:
        """Calculate market impact score"""
        impact = 0.0
        
        # Base impact from sentiment strength
        sentiment_impact = abs(news_item.sentiment_score) * news_item.confidence
        impact += sentiment_impact * 0.3
        
        # Category impact
        category_impact = {
            NewsCategory.EARNINGS: 0.4,
            NewsCategory.MERGER: 0.5,
            NewsCategory.ANALYST: 0.3,
            NewsCategory.GUIDANCE: 0.35,
            NewsCategory.REGULATORY: 0.3,
            NewsCategory.PRODUCT: 0.2,
            NewsCategory.BREAKING: 0.4,
            NewsCategory.GENERAL: 0.1
        }
        impact += category_impact.get(news_item.category, 0.1)
        
        # Relevance impact
        impact += news_item.relevance_score * 0.3
        
        # Market timing impact
        if self.market_manager:
            try:
                if self.market_manager.is_market_open(news_item.timestamp):
                    impact *= 1.3  # Higher impact during market hours
                elif self.market_manager.get_market_phase(news_item.timestamp).name == 'PREP':
                    impact *= 1.2  # Moderate impact during pre-market
            except:
                pass  # Fallback if market manager not available
        
        return min(1.0, impact)
    
    async def _fetch_polygon_news(self, symbol: str, from_time: datetime) -> List[NewsItem]:
        """Fetch news from Polygon API"""
        if not self.news_config.polygon_api_key or not self._check_rate_limit('polygon'):
            return []
        
        try:
            await self._ensure_session()
            
            from_str = from_time.strftime('%Y-%m-%d')
            url = f"https://api.polygon.io/v2/reference/news"
            params = {
                'ticker': symbol,
                'published_utc.gte': from_str,
                'limit': 20,
                'apikey': self.news_config.polygon_api_key
            }
            
            start_time = time.time()
            async with self.session.get(url, params=params) as response:
                self.metrics.api_calls += 1
                response_time = (time.time() - start_time) * 1000
                self.metrics.avg_response_time_ms = (
                    (self.metrics.avg_response_time_ms * (self.metrics.api_calls - 1) + response_time) / 
                    self.metrics.api_calls
                )
                
                if response.status == 200:
                    data = await response.json()
                    news_items = []
                    
                    for article in data.get('results', []):
                        title = article.get('title', '')
                        summary = article.get('description', '')
                        
                        if not title or not summary:
                            continue
                        
                        # Parse timestamp
                        published_utc = article.get('published_utc', '')
                        try:
                            timestamp = datetime.fromisoformat(published_utc.replace('Z', '+00:00'))
                        except:
                            timestamp = datetime.now()
                        
                        # Analyze sentiment
                        combined_text = f"{title} {summary}"
                        sentiment, confidence = self._analyze_sentiment(combined_text)
                        
                        # Extract symbols
                        symbols = self._extract_symbols(combined_text)
                        
                        # Create news item
                        news_item = NewsItem(
                            title=title,
                            summary=summary,
                            timestamp=timestamp,
                            source='polygon',
                            sentiment_score=sentiment,
                            confidence=confidence,
                            relevance_score=0.0,  # Will be calculated later
                            impact_score=0.0,  # Will be calculated later
                            url=article.get('article_url', ''),
                            symbols_mentioned=symbols
                        )
                        
                        # Classify category
                        news_item.category = self._classify_news_category(title, summary)
                        
                        news_items.append(news_item)
                    
                    self.metrics.successful_requests += 1
                    return news_items
                else:
                    log.warning(f"Polygon API error: {response.status}")
                    self.metrics.failed_requests += 1
                    return []
                    
        except Exception as e:
            log.error(f"Error fetching Polygon news: {e}")
            self.metrics.failed_requests += 1
            return []
    
    async def _fetch_finnhub_news(self, symbol: str, from_time: datetime) -> List[NewsItem]:
        """Fetch news from Finnhub API"""
        if not self.news_config.finnhub_api_key or not self._check_rate_limit('finnhub'):
            return []
        
        try:
            await self._ensure_session()
            
            from_timestamp = int(from_time.timestamp())
            to_timestamp = int(datetime.now().timestamp())
            
            url = f"https://finnhub.io/api/v1/company-news"
            params = {
                'symbol': symbol,
                'from': from_timestamp,
                'to': to_timestamp,
                'token': self.news_config.finnhub_api_key
            }
            
            start_time = time.time()
            async with self.session.get(url, params=params) as response:
                self.metrics.api_calls += 1
                response_time = (time.time() - start_time) * 1000
                self.metrics.avg_response_time_ms = (
                    (self.metrics.avg_response_time_ms * (self.metrics.api_calls - 1) + response_time) / 
                    self.metrics.api_calls
                )
                
                if response.status == 200:
                    data = await response.json()
                    news_items = []
                    
                    for article in data:
                        title = article.get('headline', '')
                        summary = article.get('summary', '')
                        
                        if not title:
                            continue
                        
                        # Parse timestamp
                        timestamp = datetime.fromtimestamp(article.get('datetime', 0))
                        
                        # Analyze sentiment
                        combined_text = f"{title} {summary}"
                        sentiment, confidence = self._analyze_sentiment(combined_text)
                        
                        # Extract symbols
                        symbols = self._extract_symbols(combined_text)
                        
                        # Create news item
                        news_item = NewsItem(
                            title=title,
                            summary=summary,
                            timestamp=timestamp,
                            source='finnhub',
                            sentiment_score=sentiment,
                            confidence=confidence,
                            relevance_score=0.0,  # Will be calculated later
                            impact_score=0.0,  # Will be calculated later
                            url=article.get('url', ''),
                            symbols_mentioned=symbols
                        )
                        
                        # Classify category
                        news_item.category = self._classify_news_category(title, summary)
                        
                        news_items.append(news_item)
                    
                    self.metrics.successful_requests += 1
                    return news_items
                else:
                    log.warning(f"Finnhub API error: {response.status}")
                    self.metrics.failed_requests += 1
                    return []
                    
        except Exception as e:
            log.error(f"Error fetching Finnhub news: {e}")
            self.metrics.failed_requests += 1
            return []
    
    async def _fetch_newsapi_news(self, symbol: str, from_time: datetime) -> List[NewsItem]:
        """Fetch news from NewsAPI"""
        if not self.news_config.newsapi_api_key or not self._check_rate_limit('newsapi'):
            return []
        
        try:
            await self._ensure_session()
            
            # Convert symbol to search query
            search_query = symbol
            if symbol in ["Nasdaq-100", "S&P 500", "Russell 2000", "Dow Jones"]:
                # Map underlying assets to searchable terms
                search_mapping = {
                    "Nasdaq-100": "NASDAQ QQQ",
                    "S&P 500": "S&P 500 SPY",
                    "Russell 2000": "Russell 2000 IWM", 
                    "Dow Jones": "Dow Jones DIA"
                }
                search_query = search_mapping.get(symbol, symbol)
            
            url = "https://newsapi.org/v2/everything"
            params = {
                'q': search_query,
                'from': from_time.strftime('%Y-%m-%d'),
                'sortBy': 'publishedAt',
                'language': 'en',
                'pageSize': 20,
                'apiKey': self.news_config.newsapi_api_key
            }
            
            start_time = time.time()
            async with self.session.get(url, params=params) as response:
                self.metrics.api_calls += 1
                response_time = (time.time() - start_time) * 1000
                self.metrics.avg_response_time_ms = (
                    (self.metrics.avg_response_time_ms * (self.metrics.api_calls - 1) + response_time) / 
                    self.metrics.api_calls
                )
                
                if response.status == 200:
                    data = await response.json()
                    news_items = []
                    
                    for article in data.get('articles', []):
                        title = article.get('title', '')
                        summary = article.get('description', '')
                        
                        if not title:
                            continue
                        
                        # Parse timestamp
                        published_at = article.get('publishedAt', '')
                        try:
                            timestamp = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                        except:
                            timestamp = datetime.now()
                        
                        # Analyze sentiment
                        combined_text = f"{title} {summary}"
                        sentiment, confidence = self._analyze_sentiment(combined_text)
                        
                        # Extract symbols
                        symbols = self._extract_symbols(combined_text)
                        
                        # Create news item
                        news_item = NewsItem(
                            title=title,
                            summary=summary,
                            timestamp=timestamp,
                            source='newsapi',
                            sentiment_score=sentiment,
                            confidence=confidence,
                            relevance_score=0.0,  # Will be calculated later
                            impact_score=0.0,  # Will be calculated later
                            url=article.get('url', ''),
                            symbols_mentioned=symbols
                        )
                        
                        # Classify category
                        news_item.category = self._classify_news_category(title, summary)
                        
                        news_items.append(news_item)
                    
                    self.metrics.successful_requests += 1
                    return news_items
                else:
                    log.warning(f"NewsAPI error: {response.status}")
                    self.metrics.failed_requests += 1
                    return []
                    
        except Exception as e:
            log.error(f"Error fetching NewsAPI news: {e}")
            self.metrics.failed_requests += 1
            return []
    
    def _map_underlying_to_symbols(self, underlying: str) -> List[str]:
        """Map underlying asset to searchable symbols for news APIs"""
        mapping = {
            "Nasdaq-100": ["QQQ", "NDX", "NASDAQ"],
            "S&P 500": ["SPY", "SPX", "S&P"],
            "Russell 2000": ["IWM", "RUT", "Russell"],
            "Dow Jones": ["DIA", "DJI", "Dow"],
            "Tesla": ["TSLA", "Tesla"],
            "NVIDIA": ["NVDA", "NVIDIA"],
            "Apple": ["AAPL", "Apple"],
            "Microsoft": ["MSFT", "Microsoft"],
            "Meta": ["META", "Facebook", "Meta"],
            "Google": ["GOOGL", "GOOG", "Alphabet"],
            "Amazon": ["AMZN", "Amazon"],
            "Bitcoin": ["BTC", "Bitcoin", "BTC-USD"],
            "Ethereum": ["ETH", "Ethereum", "ETH-USD"],
            "XRP": ["XRP", "XRP-USD"],
            "Gold": ["GLD", "Gold", "XAU"],
            "Oil": ["USO", "Oil", "WTI", "CL"],
            "Natural Gas": ["UNG", "Natural Gas", "NG"]
        }
        return mapping.get(underlying, [underlying])
    
    async def analyze_news_sentiment(self, symbol: str, lookback_hours: int = None) -> NewsSentimentResult:
        """
        Comprehensive news sentiment analysis for a symbol or underlying asset
        """
        if lookback_hours is None:
            lookback_hours = self.news_config.lookback_hours
        
        # Check cache first
        cache_key = self._generate_cache_key(symbol, lookback_hours)
        cached_result = self._get_from_cache(cache_key)
        if cached_result:
            return cached_result
        
        self.metrics.total_requests += 1
        
        # Calculate time window
        from_time = datetime.now() - timedelta(hours=lookback_hours)
        
        # Get search terms for the symbol/underlying
        search_terms = self._map_underlying_to_symbols(symbol)
        
        # Fetch news from multiple sources using all search terms
        all_news_items = []
        
        # Try each search term to get comprehensive coverage
        for search_term in search_terms:
            # Polygon news
            polygon_news = await self._fetch_polygon_news(search_term, from_time)
            all_news_items.extend(polygon_news)
            
            # Finnhub news
            finnhub_news = await self._fetch_finnhub_news(search_term, from_time)
            all_news_items.extend(finnhub_news)
            
            # NewsAPI news (if configured)
            if self.news_config.newsapi_api_key:
                newsapi_news = await self._fetch_newsapi_news(search_term, from_time)
                all_news_items.extend(newsapi_news)
        
        # Calculate relevance and impact scores
        for news_item in all_news_items:
            news_item.relevance_score = self._calculate_relevance_score(news_item, symbol)
            news_item.impact_score = self._calculate_market_impact(news_item, symbol)
        
        # Filter by relevance
        relevant_news = [
            item for item in all_news_items 
            if item.relevance_score >= self.news_config.min_relevance_score
        ]
        
        # Sort by relevance and timestamp
        relevant_news.sort(key=lambda x: (x.relevance_score, x.timestamp), reverse=True)
        
        # Limit number of items
        relevant_news = relevant_news[:self.news_config.max_news_items]
        
        # Calculate overall sentiment metrics
        if not relevant_news:
            result = NewsSentimentResult(
                symbol=symbol,
                overall_sentiment=0.0,
                sentiment_confidence=0.0,
                news_quality_score=0.0,
                market_impact=0.0,
                trading_implications="neutral",
                risk_adjustment=1.0,
                position_size_adjustment=1.0,
                expected_volatility=0.3,
                news_count=0,
                latest_news_time=datetime.now(),
                sentiment_trend="stable",
                breaking_news=False,
                earnings_related=False,
                high_impact_news=False
            )
        else:
            # Weighted sentiment calculation
            total_weight = sum(item.relevance_score * item.confidence for item in relevant_news)
            if total_weight > 0:
                overall_sentiment = sum(
                    item.sentiment_score * item.relevance_score * item.confidence 
                    for item in relevant_news
                ) / total_weight
            else:
                overall_sentiment = 0.0
            
            # Average confidence
            sentiment_confidence = sum(item.confidence for item in relevant_news) / len(relevant_news)
            
            # News quality score
            news_quality_score = sum(item.relevance_score for item in relevant_news) / len(relevant_news)
            
            # Market impact
            market_impact = max(item.impact_score for item in relevant_news)
            
            # Trading implications
            if overall_sentiment > 0.6:
                trading_implications = "strong_positive"
            elif overall_sentiment > 0.2:
                trading_implications = "positive"
            elif overall_sentiment < -0.6:
                trading_implications = "strong_negative"
            elif overall_sentiment < -0.2:
                trading_implications = "negative"
            else:
                trading_implications = "neutral"
            
            # Risk and position adjustments
            risk_adjustment = 1.0 - (abs(overall_sentiment) * 0.3)
            position_size_adjustment = 0.8 + (overall_sentiment * 0.4)
            expected_volatility = 0.3 + (abs(overall_sentiment) * 0.4)
            
            # Detect breaking news and earnings
            breaking_news = any(
                item.category == NewsCategory.BREAKING or 
                (datetime.now() - item.timestamp).total_seconds() < 3600 
                for item in relevant_news
            )
            
            earnings_related = any(
                item.category == NewsCategory.EARNINGS 
                for item in relevant_news
            )
            
            high_impact_news = any(
                item.impact_score > 0.7 
                for item in relevant_news
            )
            
            # Sentiment trend analysis
            if len(relevant_news) >= 3:
                recent_sentiment = sum(
                    item.sentiment_score for item in relevant_news[:len(relevant_news)//2]
                ) / (len(relevant_news)//2)
                
                older_sentiment = sum(
                    item.sentiment_score for item in relevant_news[len(relevant_news)//2:]
                ) / (len(relevant_news) - len(relevant_news)//2)
                
                if recent_sentiment > older_sentiment + 0.1:
                    sentiment_trend = "improving"
                elif recent_sentiment < older_sentiment - 0.1:
                    sentiment_trend = "declining"
                else:
                    sentiment_trend = "stable"
            else:
                sentiment_trend = "stable"
            
            # Create sentiment distribution
            sentiment_distribution = {
                'very_positive': len([i for i in relevant_news if i.sentiment_strength == SentimentStrength.VERY_POSITIVE]),
                'positive': len([i for i in relevant_news if i.sentiment_strength == SentimentStrength.POSITIVE]),
                'neutral': len([i for i in relevant_news if i.sentiment_strength == SentimentStrength.NEUTRAL]),
                'negative': len([i for i in relevant_news if i.sentiment_strength == SentimentStrength.NEGATIVE]),
                'very_negative': len([i for i in relevant_news if i.sentiment_strength == SentimentStrength.VERY_NEGATIVE])
            }
            
            # Create category breakdown
            category_breakdown = {}
            for category in NewsCategory:
                category_breakdown[category.value] = len([
                    i for i in relevant_news if i.category == category
                ])
            
            # Create source breakdown
            source_breakdown = {}
            for item in relevant_news:
                source_breakdown[item.source] = source_breakdown.get(item.source, 0) + 1
            
            result = NewsSentimentResult(
                symbol=symbol,
                overall_sentiment=overall_sentiment,
                sentiment_confidence=sentiment_confidence,
                news_quality_score=news_quality_score,
                market_impact=market_impact,
                trading_implications=trading_implications,
                risk_adjustment=risk_adjustment,
                position_size_adjustment=position_size_adjustment,
                expected_volatility=expected_volatility,
                news_count=len(relevant_news),
                latest_news_time=max(item.timestamp for item in relevant_news),
                sentiment_trend=sentiment_trend,
                breaking_news=breaking_news,
                earnings_related=earnings_related,
                high_impact_news=high_impact_news,
                news_items=relevant_news,
                sentiment_distribution=sentiment_distribution,
                category_breakdown=category_breakdown,
                source_breakdown=source_breakdown
            )
        
        # Update metrics
        self.metrics.total_news_items += len(all_news_items)
        self.metrics.high_relevance_items += len(relevant_news)
        
        if result.breaking_news:
            self.metrics.breaking_news_count += 1
        if result.earnings_related:
            self.metrics.earnings_news_count += 1
        
        # Cache the result
        self._set_cache(cache_key, result)
        
        return result
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get news manager performance metrics"""
        return {
            'total_requests': self.metrics.total_requests,
            'cache_hits': self.metrics.cache_hits,
            'cache_misses': self.metrics.cache_misses,
            'cache_hit_rate': self.metrics.cache_hits / max(1, self.metrics.cache_hits + self.metrics.cache_misses),
            'api_calls': self.metrics.api_calls,
            'successful_requests': self.metrics.successful_requests,
            'failed_requests': self.metrics.failed_requests,
            'success_rate': self.metrics.successful_requests / max(1, self.metrics.api_calls),
            'avg_response_time_ms': self.metrics.avg_response_time_ms,
            'total_news_items': self.metrics.total_news_items,
            'high_relevance_items': self.metrics.high_relevance_items,
            'breaking_news_count': self.metrics.breaking_news_count,
            'earnings_news_count': self.metrics.earnings_news_count,
            'sentiment_accuracy': self.metrics.sentiment_accuracy,
            'last_reset': self.metrics.last_reset.isoformat()
        }
    
    def reset_metrics(self):
        """Reset performance metrics"""
        self.metrics = NewsPerformanceMetrics()
        log.info("News manager metrics reset")

# Factory function
def get_prime_news_manager(config: Optional[Dict[str, Any]] = None, market_manager=None) -> PrimeNewsManager:
    """Get unified news manager instance"""
    return PrimeNewsManager(config, market_manager)
