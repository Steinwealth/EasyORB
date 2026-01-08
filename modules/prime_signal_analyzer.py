#!/usr/bin/env python3
"""
Prime Signal Analyzer - Enhanced Red Day Detection
Date: November 25, 2025
Purpose: Analyze signal composition and market context for red day detection
"""

import logging
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)

class ETFType(Enum):
    """ETF directional classification"""
    BEAR = "BEAR"           # Inverse/Short ETFs
    BULL = "BULL"           # Leveraged Long ETFs  
    NEUTRAL = "NEUTRAL"     # Standard ETFs
    UNKNOWN = "UNKNOWN"     # Unable to classify

class SectorType(Enum):
    """Sector classification for concentration analysis"""
    TECHNOLOGY = "TECHNOLOGY"
    ENERGY = "ENERGY"
    FINANCIALS = "FINANCIALS"
    HEALTHCARE = "HEALTHCARE"
    CONSUMER = "CONSUMER"
    INDUSTRIALS = "INDUSTRIALS"
    MATERIALS = "MATERIALS"
    UTILITIES = "UTILITIES"
    REAL_ESTATE = "REAL_ESTATE"
    COMMUNICATIONS = "COMMUNICATIONS"
    UNKNOWN = "UNKNOWN"

@dataclass
class SignalCompositionAnalysis:
    """Results of signal composition analysis"""
    total_signals: int
    bear_count: int
    bull_count: int
    neutral_count: int
    bear_percentage: float
    bull_percentage: float
    neutral_percentage: float
    sector_concentration: Dict[str, float]
    max_sector_concentration: float
    risk_level: str
    risk_factors: List[str]
    recommendation: str

@dataclass
class MarketContextAnalysis:
    """Results of market context analysis"""
    spy_momentum: float
    vix_level: float
    market_direction: str
    signal_direction: str
    divergence_detected: bool
    divergence_severity: str
    risk_level: str
    risk_factors: List[str]

class PrimeSignalAnalyzer:
    """
    Enhanced signal analyzer for red day detection
    
    Analyzes signal composition, market context, and directional bias
    to identify high-risk trading days before execution.
    """
    
    def __init__(self):
        """Initialize the signal analyzer"""
        self.etf_classification = self._build_etf_classification()
        self.sector_classification = self._build_sector_classification()
        
    def _build_etf_classification(self) -> Dict[str, ETFType]:
        """Build comprehensive ETF classification database"""
        return {
            # Bear/Inverse ETFs (Short positions)
            'SSG': ETFType.BEAR,      # Short Semiconductors
            'TSDD': ETFType.BEAR,     # Short Tech Daily
            'TSLS': ETFType.BEAR,     # Short Tesla
            'NVDQ': ETFType.BEAR,     # Short NASDAQ
            'AMDD': ETFType.BEAR,     # Short AMD
            'NVDD': ETFType.BEAR,     # Short NVIDIA
            'DRIP': ETFType.BEAR,     # Short Oil/Energy
            'SQQQ': ETFType.BEAR,     # Short QQQ 3x
            'SPXS': ETFType.BEAR,     # Short S&P 500 3x
            'SPXU': ETFType.BEAR,     # Short S&P 500 3x
            'SDOW': ETFType.BEAR,     # Short Dow 3x
            'SRTY': ETFType.BEAR,     # Short Russell 2000 3x
            'QID': ETFType.BEAR,      # Short QQQ 2x
            'TECS': ETFType.BEAR,     # Short Tech 3x
            'WEBS': ETFType.BEAR,     # Short Web 3x
            'LABD': ETFType.BEAR,     # Short Biotech 3x
            'DUST': ETFType.BEAR,     # Short Gold Miners 3x
            'YANG': ETFType.BEAR,     # Short China 3x
            
            # Bull/Leveraged Long ETFs
            'TQQQ': ETFType.BULL,     # Long QQQ 3x
            'UPRO': ETFType.BULL,     # Long S&P 500 3x
            'UDOW': ETFType.BULL,     # Long Dow 3x
            'TNA': ETFType.BULL,      # Long Russell 2000 3x
            'QLD': ETFType.BULL,      # Long QQQ 2x
            'SSO': ETFType.BULL,      # Long S&P 500 2x
            'TECL': ETFType.BULL,     # Long Tech 3x
            'LABU': ETFType.BULL,     # Long Biotech 3x
            'NUGT': ETFType.BULL,     # Long Gold Miners 3x
            'YINN': ETFType.BULL,     # Long China 3x
            'SOXL': ETFType.BULL,     # Long Semiconductors 3x
            'CURE': ETFType.BULL,     # Long Healthcare 3x
            'DFEN': ETFType.BULL,     # Long Defense 3x
            'RETL': ETFType.BULL,     # Long Retail 3x
            'WEBL': ETFType.BULL,     # Long Web 3x
            
            # Neutral/Standard ETFs
            'SPY': ETFType.NEUTRAL,   # S&P 500
            'QQQ': ETFType.NEUTRAL,   # NASDAQ 100
            'IWM': ETFType.NEUTRAL,   # Russell 2000
            'DIA': ETFType.NEUTRAL,   # Dow Jones
            'VTI': ETFType.NEUTRAL,   # Total Stock Market
            'XLF': ETFType.NEUTRAL,   # Financials
            'XLE': ETFType.NEUTRAL,   # Energy
            'XLK': ETFType.NEUTRAL,   # Technology
            'XLV': ETFType.NEUTRAL,   # Healthcare
            'XLI': ETFType.NEUTRAL,   # Industrials
            'XLP': ETFType.NEUTRAL,   # Consumer Staples
            'XLY': ETFType.NEUTRAL,   # Consumer Discretionary
            'XLU': ETFType.NEUTRAL,   # Utilities
            'XLB': ETFType.NEUTRAL,   # Materials
            'XLRE': ETFType.NEUTRAL,  # Real Estate
            'XLC': ETFType.NEUTRAL,   # Communications
        }
    
    def _build_sector_classification(self) -> Dict[str, SectorType]:
        """Build sector classification for concentration analysis"""
        return {
            # Technology
            'SSG': SectorType.TECHNOLOGY,    # Semiconductors
            'TSDD': SectorType.TECHNOLOGY,   # Tech Daily
            'TSLS': SectorType.TECHNOLOGY,   # Tesla
            'NVDQ': SectorType.TECHNOLOGY,   # NASDAQ (tech heavy)
            'AMDD': SectorType.TECHNOLOGY,   # AMD
            'NVDD': SectorType.TECHNOLOGY,   # NVIDIA
            'TQQQ': SectorType.TECHNOLOGY,   # QQQ (tech heavy)
            'QLD': SectorType.TECHNOLOGY,    # QQQ 2x
            'TECL': SectorType.TECHNOLOGY,   # Tech 3x
            'TECS': SectorType.TECHNOLOGY,   # Short Tech 3x
            'SOXL': SectorType.TECHNOLOGY,   # Semiconductors 3x
            'WEBL': SectorType.TECHNOLOGY,   # Web 3x
            'WEBS': SectorType.TECHNOLOGY,   # Short Web 3x
            
            # Energy
            'DRIP': SectorType.ENERGY,       # Short Oil
            'XLE': SectorType.ENERGY,        # Energy Sector
            
            # Financials
            'XLF': SectorType.FINANCIALS,    # Financial Sector
            
            # Healthcare/Biotech
            'LABU': SectorType.HEALTHCARE,   # Long Biotech 3x
            'LABD': SectorType.HEALTHCARE,   # Short Biotech 3x
            'XLV': SectorType.HEALTHCARE,    # Healthcare Sector
            'CURE': SectorType.HEALTHCARE,   # Long Healthcare 3x
            
            # Broad Market (Technology heavy but diversified)
            'SQQQ': SectorType.TECHNOLOGY,   # Short QQQ 3x
            'QID': SectorType.TECHNOLOGY,    # Short QQQ 2x
            'SPXS': SectorType.CONSUMER,     # Short S&P 500 3x (diversified)
            'SPXU': SectorType.CONSUMER,     # Short S&P 500 3x (diversified)
            'UPRO': SectorType.CONSUMER,     # Long S&P 500 3x (diversified)
            'SPY': SectorType.CONSUMER,      # S&P 500 (diversified)
            
            # Small Cap
            'SRTY': SectorType.INDUSTRIALS,  # Short Russell 2000 3x
            'TNA': SectorType.INDUSTRIALS,   # Long Russell 2000 3x
            'IWM': SectorType.INDUSTRIALS,   # Russell 2000
            
            # Industrial/Dow
            'SDOW': SectorType.INDUSTRIALS,  # Short Dow 3x
            'UDOW': SectorType.INDUSTRIALS,  # Long Dow 3x
            'DIA': SectorType.INDUSTRIALS,   # Dow Jones
        }
    
    def classify_etf(self, symbol: str) -> ETFType:
        """Classify ETF as bear, bull, or neutral"""
        return self.etf_classification.get(symbol.upper(), ETFType.UNKNOWN)
    
    def classify_sector(self, symbol: str) -> SectorType:
        """Classify ETF by sector"""
        return self.sector_classification.get(symbol.upper(), SectorType.UNKNOWN)
    
    def analyze_signal_composition(self, signals: List[Dict[str, Any]]) -> SignalCompositionAnalysis:
        """
        Analyze signal composition for directional bias and concentration risk
        
        Args:
            signals: List of signal dictionaries with 'symbol' key
            
        Returns:
            SignalCompositionAnalysis with risk assessment
        """
        if not signals:
            return SignalCompositionAnalysis(
                total_signals=0, bear_count=0, bull_count=0, neutral_count=0,
                bear_percentage=0, bull_percentage=0, neutral_percentage=0,
                sector_concentration={}, max_sector_concentration=0,
                risk_level="LOW", risk_factors=[], recommendation="NO_SIGNALS"
            )
        
        total_signals = len(signals)
        bear_count = 0
        bull_count = 0
        neutral_count = 0
        sector_counts = {}
        
        # Analyze each signal
        for signal in signals:
            symbol = signal.get('symbol', '').upper()
            
            # ETF type classification
            etf_type = self.classify_etf(symbol)
            if etf_type == ETFType.BEAR:
                bear_count += 1
            elif etf_type == ETFType.BULL:
                bull_count += 1
            elif etf_type == ETFType.NEUTRAL:
                neutral_count += 1
            
            # Sector classification
            sector = self.classify_sector(symbol)
            sector_name = sector.value
            sector_counts[sector_name] = sector_counts.get(sector_name, 0) + 1
        
        # Calculate percentages
        bear_percentage = (bear_count / total_signals) * 100
        bull_percentage = (bull_count / total_signals) * 100
        neutral_percentage = (neutral_count / total_signals) * 100
        
        # Calculate sector concentration
        sector_concentration = {
            sector: (count / total_signals) * 100 
            for sector, count in sector_counts.items()
        }
        max_sector_concentration = max(sector_concentration.values()) if sector_concentration else 0
        
        # Risk assessment
        risk_factors = []
        risk_level = "LOW"
        recommendation = "NORMAL_EXECUTION"
        
        # Check for extreme directional bias
        if bear_percentage >= 100:
            risk_factors.append("EXTREME_BEAR_BIAS_100PCT")
            risk_level = "EXTREME"
            recommendation = "SKIP_EXECUTION"
        elif bear_percentage >= 80:
            risk_factors.append("HIGH_BEAR_BIAS_80PCT")
            risk_level = "HIGH"
            recommendation = "REDUCE_POSITION_SIZE"
        elif bull_percentage >= 100:
            risk_factors.append("EXTREME_BULL_BIAS_100PCT")
            risk_level = "HIGH"
            recommendation = "MONITOR_CLOSELY"
        elif bull_percentage >= 80:
            risk_factors.append("HIGH_BULL_BIAS_80PCT")
            risk_level = "MEDIUM"
            recommendation = "MONITOR_CLOSELY"
        
        # Check for sector concentration
        if max_sector_concentration >= 80:
            risk_factors.append(f"HIGH_SECTOR_CONCENTRATION_{max_sector_concentration:.0f}PCT")
            if risk_level == "LOW":
                risk_level = "MEDIUM"
        elif max_sector_concentration >= 70:
            risk_factors.append(f"MEDIUM_SECTOR_CONCENTRATION_{max_sector_concentration:.0f}PCT")
        
        # Adjust recommendation based on combined factors
        if len(risk_factors) >= 2 and risk_level in ["HIGH", "EXTREME"]:
            recommendation = "SKIP_EXECUTION"
        elif len(risk_factors) >= 1 and risk_level == "HIGH":
            recommendation = "REDUCE_POSITION_SIZE"
        
        return SignalCompositionAnalysis(
            total_signals=total_signals,
            bear_count=bear_count,
            bull_count=bull_count,
            neutral_count=neutral_count,
            bear_percentage=bear_percentage,
            bull_percentage=bull_percentage,
            neutral_percentage=neutral_percentage,
            sector_concentration=sector_concentration,
            max_sector_concentration=max_sector_concentration,
            risk_level=risk_level,
            risk_factors=risk_factors,
            recommendation=recommendation
        )
    
    def analyze_market_context(self, spy_momentum: float = 0.0, vix_level: float = 15.0, 
                             signal_composition: SignalCompositionAnalysis = None) -> MarketContextAnalysis:
        """
        Analyze market context for divergence detection
        
        Args:
            spy_momentum: SPY momentum percentage (positive = bullish, negative = bearish)
            vix_level: VIX volatility level
            signal_composition: Results from signal composition analysis
            
        Returns:
            MarketContextAnalysis with divergence assessment
        """
        # Determine market direction
        if spy_momentum > 0.5:
            market_direction = "BULLISH"
        elif spy_momentum < -0.5:
            market_direction = "BEARISH"
        else:
            market_direction = "NEUTRAL"
        
        # Determine signal direction from composition
        if signal_composition:
            if signal_composition.bear_percentage > 60:
                signal_direction = "BEARISH"
            elif signal_composition.bull_percentage > 60:
                signal_direction = "BULLISH"
            else:
                signal_direction = "MIXED"
        else:
            signal_direction = "UNKNOWN"
        
        # Detect divergence
        divergence_detected = False
        divergence_severity = "NONE"
        risk_factors = []
        
        if market_direction == "BULLISH" and signal_direction == "BEARISH":
            divergence_detected = True
            if signal_composition and signal_composition.bear_percentage >= 100:
                divergence_severity = "EXTREME"
                risk_factors.append("EXTREME_DIVERGENCE_BULL_MARKET_BEAR_SIGNALS")
            elif signal_composition and signal_composition.bear_percentage >= 80:
                divergence_severity = "HIGH"
                risk_factors.append("HIGH_DIVERGENCE_BULL_MARKET_BEAR_SIGNALS")
            else:
                divergence_severity = "MEDIUM"
                risk_factors.append("MEDIUM_DIVERGENCE_BULL_MARKET_BEAR_SIGNALS")
        
        elif market_direction == "BEARISH" and signal_direction == "BULLISH":
            divergence_detected = True
            if signal_composition and signal_composition.bull_percentage >= 100:
                divergence_severity = "EXTREME"
                risk_factors.append("EXTREME_DIVERGENCE_BEAR_MARKET_BULL_SIGNALS")
            elif signal_composition and signal_composition.bull_percentage >= 80:
                divergence_severity = "HIGH"
                risk_factors.append("HIGH_DIVERGENCE_BEAR_MARKET_BULL_SIGNALS")
            else:
                divergence_severity = "MEDIUM"
                risk_factors.append("MEDIUM_DIVERGENCE_BEAR_MARKET_BULL_SIGNALS")
        
        # Check VIX for additional risk
        if vix_level > 25:
            risk_factors.append(f"HIGH_VOLATILITY_VIX_{vix_level:.1f}")
        elif vix_level > 20:
            risk_factors.append(f"ELEVATED_VOLATILITY_VIX_{vix_level:.1f}")
        
        # Determine overall risk level
        if divergence_severity == "EXTREME":
            risk_level = "EXTREME"
        elif divergence_severity == "HIGH" or vix_level > 25:
            risk_level = "HIGH"
        elif divergence_severity == "MEDIUM" or vix_level > 20:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
        
        return MarketContextAnalysis(
            spy_momentum=spy_momentum,
            vix_level=vix_level,
            market_direction=market_direction,
            signal_direction=signal_direction,
            divergence_detected=divergence_detected,
            divergence_severity=divergence_severity,
            risk_level=risk_level,
            risk_factors=risk_factors
        )
    
    def get_signal_summary(self, signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get a quick summary of signal characteristics"""
        composition = self.analyze_signal_composition(signals)
        
        return {
            'total_signals': composition.total_signals,
            'bear_percentage': composition.bear_percentage,
            'bull_percentage': composition.bull_percentage,
            'max_sector_concentration': composition.max_sector_concentration,
            'risk_level': composition.risk_level,
            'recommendation': composition.recommendation,
            'risk_factors': composition.risk_factors
        }

# Example usage and testing
if __name__ == "__main__":
    # Test with today's emergency exit signals
    analyzer = PrimeSignalAnalyzer()
    
    # Today's signals (Nov 25, 2025)
    todays_signals = [
        {'symbol': 'SSG'},   # Bear Tech
        {'symbol': 'TSDD'},  # Bear Tech  
        {'symbol': 'TSLS'},  # Bear Tech
        {'symbol': 'NVDQ'},  # Bear Tech
        {'symbol': 'AMDD'},  # Bear Tech
        {'symbol': 'NVDD'},  # Bear Tech
        {'symbol': 'DRIP'},  # Bear Energy
    ]
    
    # Analyze composition
    composition = analyzer.analyze_signal_composition(todays_signals)
    print(f"Signal Composition Analysis:")
    print(f"  Bear Percentage: {composition.bear_percentage:.1f}%")
    print(f"  Risk Level: {composition.risk_level}")
    print(f"  Recommendation: {composition.recommendation}")
    print(f"  Risk Factors: {composition.risk_factors}")
    
    # Analyze market context (estimated SPY +0.8%)
    market_context = analyzer.analyze_market_context(
        spy_momentum=0.8, 
        vix_level=14.5, 
        signal_composition=composition
    )
    print(f"\nMarket Context Analysis:")
    print(f"  Market Direction: {market_context.market_direction}")
    print(f"  Signal Direction: {market_context.signal_direction}")
    print(f"  Divergence: {market_context.divergence_detected} ({market_context.divergence_severity})")
    print(f"  Risk Level: {market_context.risk_level}")
    print(f"  Risk Factors: {market_context.risk_factors}")
