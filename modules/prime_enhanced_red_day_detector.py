#!/usr/bin/env python3
"""
Prime Enhanced Red Day Detector - Multi-Factor Risk Assessment
Date: November 25, 2025
Purpose: Enhanced red day detection using multiple risk factors
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import asyncio

from .prime_signal_analyzer import PrimeSignalAnalyzer, SignalCompositionAnalysis, MarketContextAnalysis

log = logging.getLogger(__name__)

@dataclass
class TechnicalWeaknessAnalysis:
    """Results of technical weakness analysis"""
    avg_rsi: float
    rsi_weakness_pct: float
    avg_volume_ratio: float
    volume_weakness_pct: float
    macd_weakness_pct: float
    combined_weakness_score: float
    risk_level: str
    risk_factors: List[str]

@dataclass
class RedDayRiskAssessment:
    """Comprehensive red day risk assessment"""
    composite_risk_score: float
    risk_level: str
    recommendation: str
    position_size_multiplier: float
    confidence: float
    
    # Component analyses
    signal_composition: SignalCompositionAnalysis
    market_context: MarketContextAnalysis
    technical_weakness: TechnicalWeaknessAnalysis
    
    # Risk factors and reasoning
    all_risk_factors: List[str]
    primary_risk_reason: str
    prevention_amount_estimate: float

class PrimeEnhancedRedDayDetector:
    """
    Enhanced Red Day Detector using multi-factor risk assessment
    
    Combines signal composition, market context, technical weakness,
    and historical patterns to provide accurate red day detection.
    """
    
    def __init__(self):
        """Initialize the enhanced red day detector"""
        self.signal_analyzer = PrimeSignalAnalyzer()
        
        # Risk scoring weights (REVISED - focus on technical indicators)
        self.risk_weights = {
            'signal_composition': 0.0,     # 0% - REMOVED per user feedback
            'market_context': 0.10,       # 10% - Only VIX volatility
            'technical_weakness': 0.60,   # 60% - Primary focus on RSI/MACD/Volume
            'volume_analysis': 0.20,      # 20% - Volume patterns
            'historical_patterns': 0.10   # 10% - Technical pattern matching
        }
        
        # Risk thresholds
        self.risk_thresholds = {
            'EXTREME': 0.80,     # Skip execution
            'HIGH': 0.75,        # Skip execution  
            'MEDIUM_HIGH': 0.60, # Reduce to 25%
            'MEDIUM': 0.50,      # Reduce to 50%
            'LOW_MEDIUM': 0.35,  # Reduce to 75%
            'LOW': 0.25          # Normal execution
        }
        
        # Historical red day patterns (REVISED - technical indicators only)
        self.known_patterns = {
            'TECHNICAL_WEAKNESS': {
                'description': 'High RSI weakness + volume weakness (Nov 4 pattern)',
                'rsi_threshold': 70,
                'volume_threshold': 80,
                'risk_multiplier': 1.0
            },
            'EXTREME_TECHNICAL_WEAKNESS': {
                'description': 'Very high RSI weakness + MACD weakness',
                'rsi_threshold': 80,
                'macd_weakness_threshold': 90,
                'risk_multiplier': 1.2
            },
            'VOLUME_COLLAPSE': {
                'description': 'Extremely low volume across signals',
                'volume_threshold': 0.5,
                'risk_multiplier': 1.1
            }
        }
    
    async def analyze_red_day_risk(self, signals: List[Dict[str, Any]], 
                                 spy_momentum: float = 0.0, 
                                 vix_level: float = 15.0) -> RedDayRiskAssessment:
        """
        Comprehensive red day risk analysis
        
        Args:
            signals: List of signal dictionaries
            spy_momentum: SPY momentum percentage
            vix_level: VIX volatility level
            
        Returns:
            RedDayRiskAssessment with recommendation
        """
        try:
            # Component 1: Signal Composition Analysis
            signal_composition = self.signal_analyzer.analyze_signal_composition(signals)
            composition_risk_score = self._calculate_composition_risk_score(signal_composition)
            
            # Component 2: Market Context Analysis  
            market_context = self.signal_analyzer.analyze_market_context(
                spy_momentum, vix_level, signal_composition
            )
            context_risk_score = self._calculate_context_risk_score(market_context)
            
            # Component 3: Technical Weakness Analysis
            technical_weakness = self._analyze_technical_weakness(signals)
            technical_risk_score = self._calculate_technical_risk_score(technical_weakness)
            
            # Component 4: Volume Analysis
            volume_risk_score = self._calculate_volume_risk_score(signals)
            
            # Component 5: Historical Pattern Matching
            historical_risk_score = self._calculate_historical_risk_score(
                signal_composition, market_context, technical_weakness
            )
            
            # Calculate composite risk score
            composite_risk_score = (
                composition_risk_score * self.risk_weights['signal_composition'] +
                context_risk_score * self.risk_weights['market_context'] +
                technical_risk_score * self.risk_weights['technical_weakness'] +
                volume_risk_score * self.risk_weights['volume_analysis'] +
                historical_risk_score * self.risk_weights['historical_patterns']
            )
            
            # Determine risk level and recommendation
            risk_level, recommendation, position_multiplier = self._determine_recommendation(composite_risk_score)
            
            # Calculate confidence and prevention estimate
            confidence = self._calculate_confidence(composite_risk_score, signal_composition, market_context)
            prevention_estimate = self._estimate_prevention_amount(composite_risk_score, len(signals))
            
            # Compile all risk factors
            all_risk_factors = (
                signal_composition.risk_factors +
                market_context.risk_factors +
                technical_weakness.risk_factors
            )
            
            # Determine primary risk reason
            primary_risk_reason = self._determine_primary_risk_reason(
                composition_risk_score, context_risk_score, technical_risk_score
            )
            
            return RedDayRiskAssessment(
                composite_risk_score=composite_risk_score,
                risk_level=risk_level,
                recommendation=recommendation,
                position_size_multiplier=position_multiplier,
                confidence=confidence,
                signal_composition=signal_composition,
                market_context=market_context,
                technical_weakness=technical_weakness,
                all_risk_factors=all_risk_factors,
                primary_risk_reason=primary_risk_reason,
                prevention_amount_estimate=prevention_estimate
            )
            
        except Exception as e:
            log.error(f"Error in red day risk analysis: {e}")
            # Return safe default (skip execution on error)
            return self._get_error_fallback_assessment(signals)
    
    def _calculate_composition_risk_score(self, composition: SignalCompositionAnalysis) -> float:
        """Calculate risk score from signal composition - DISABLED per user feedback"""
        # REMOVED: Bear/Bull ETF detection and sector concentration analysis
        # These are NOT reliable red day indicators and would prevent profitable trades
        # Red day detection should focus on technical weakness, not directional bias
        return 0.0  # No risk from composition - directional bias can be profitable
    
    def _calculate_context_risk_score(self, context: MarketContextAnalysis) -> float:
        """Calculate risk score from market context - REVISED per user feedback"""
        # REMOVED: Market divergence analysis (bear vs bull market)
        # This would prevent profitable bear ETF trades during actual bear markets
        # Focus only on volatility indicators
        if context.vix_level > 30:
            return 0.8  # Very high volatility
        elif context.vix_level > 25:
            return 0.6  # High volatility
        elif context.vix_level > 20:
            return 0.3  # Elevated volatility
        else:
            return 0.1  # Normal volatility
    
    def _analyze_technical_weakness(self, signals: List[Dict[str, Any]]) -> TechnicalWeaknessAnalysis:
        """Analyze technical weakness in signals"""
        if not signals:
            return TechnicalWeaknessAnalysis(
                avg_rsi=50, rsi_weakness_pct=0, avg_volume_ratio=1.0, 
                volume_weakness_pct=0, macd_weakness_pct=0, combined_weakness_score=0,
                risk_level="LOW", risk_factors=[]
            )
        
        # Extract technical indicators (with fallbacks)
        rsi_values = []
        volume_ratios = []
        macd_negative_count = 0
        
        for signal in signals:
            # RSI analysis
            rsi = signal.get('rsi', signal.get('rsi_14', 50))
            rsi_values.append(rsi)
            
            # Volume analysis
            volume_ratio = signal.get('volume_ratio', signal.get('exec_volume_ratio', 1.0))
            volume_ratios.append(volume_ratio)
            
            # MACD analysis
            macd_hist = signal.get('macd_histogram', 0)
            if macd_hist < 0:
                macd_negative_count += 1
        
        # Calculate averages and weakness percentages
        avg_rsi = sum(rsi_values) / len(rsi_values) if rsi_values else 50
        rsi_weakness_pct = (sum(1 for rsi in rsi_values if rsi < 40) / len(rsi_values)) * 100
        
        avg_volume_ratio = sum(volume_ratios) / len(volume_ratios) if volume_ratios else 1.0
        volume_weakness_pct = (sum(1 for vol in volume_ratios if vol < 1.0) / len(volume_ratios)) * 100
        
        macd_weakness_pct = (macd_negative_count / len(signals)) * 100
        
        # Combined weakness score
        combined_weakness_score = (rsi_weakness_pct + volume_weakness_pct + macd_weakness_pct) / 3
        
        # Risk assessment
        risk_factors = []
        if rsi_weakness_pct >= 70:
            risk_factors.append(f"HIGH_RSI_WEAKNESS_{rsi_weakness_pct:.0f}PCT")
        if volume_weakness_pct >= 80:
            risk_factors.append(f"HIGH_VOLUME_WEAKNESS_{volume_weakness_pct:.0f}PCT")
        if macd_weakness_pct >= 80:
            risk_factors.append(f"HIGH_MACD_WEAKNESS_{macd_weakness_pct:.0f}PCT")
        
        if combined_weakness_score >= 70:
            risk_level = "HIGH"
        elif combined_weakness_score >= 50:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
        
        return TechnicalWeaknessAnalysis(
            avg_rsi=avg_rsi,
            rsi_weakness_pct=rsi_weakness_pct,
            avg_volume_ratio=avg_volume_ratio,
            volume_weakness_pct=volume_weakness_pct,
            macd_weakness_pct=macd_weakness_pct,
            combined_weakness_score=combined_weakness_score,
            risk_level=risk_level,
            risk_factors=risk_factors
        )
    
    def _calculate_technical_risk_score(self, technical: TechnicalWeaknessAnalysis) -> float:
        """Calculate risk score from technical weakness"""
        return min(1.0, technical.combined_weakness_score / 100)
    
    def _calculate_volume_risk_score(self, signals: List[Dict[str, Any]]) -> float:
        """Calculate risk score from volume analysis"""
        if not signals:
            return 0.5
        
        volume_ratios = []
        for signal in signals:
            volume_ratio = signal.get('volume_ratio', signal.get('exec_volume_ratio', 1.0))
            volume_ratios.append(volume_ratio)
        
        avg_volume = sum(volume_ratios) / len(volume_ratios)
        
        # High volume can indicate panic/risk, low volume indicates weakness
        if avg_volume > 3.0:
            return 0.7  # High volume risk
        elif avg_volume < 0.5:
            return 0.8  # Very low volume risk
        elif avg_volume < 1.0:
            return 0.6  # Low volume risk
        else:
            return 0.3  # Normal volume
    
    def _calculate_historical_risk_score(self, composition: SignalCompositionAnalysis,
                                       context: MarketContextAnalysis,
                                       technical: TechnicalWeaknessAnalysis) -> float:
        """Calculate risk score from historical pattern matching - TECHNICAL ONLY"""
        pattern_matches = 0
        total_patterns = len(self.known_patterns)
        
        # Check TECHNICAL_WEAKNESS pattern (Nov 4)
        if (technical.rsi_weakness_pct >= self.known_patterns['TECHNICAL_WEAKNESS']['rsi_threshold'] and
            technical.volume_weakness_pct >= self.known_patterns['TECHNICAL_WEAKNESS']['volume_threshold']):
            pattern_matches += 1
        
        # Check EXTREME_TECHNICAL_WEAKNESS pattern
        if (technical.rsi_weakness_pct >= self.known_patterns['EXTREME_TECHNICAL_WEAKNESS']['rsi_threshold'] and
            technical.macd_weakness_pct >= self.known_patterns['EXTREME_TECHNICAL_WEAKNESS']['macd_weakness_threshold']):
            pattern_matches += 1
        
        # Check VOLUME_COLLAPSE pattern
        if technical.avg_volume_ratio <= self.known_patterns['VOLUME_COLLAPSE']['volume_threshold']:
            pattern_matches += 1
        
        return pattern_matches / total_patterns
    
    def _determine_recommendation(self, risk_score: float) -> tuple[str, str, float]:
        """Determine recommendation based on risk score"""
        if risk_score >= self.risk_thresholds['HIGH']:
            return "EXTREME", "SKIP_EXECUTION", 0.0
        elif risk_score >= self.risk_thresholds['MEDIUM_HIGH']:
            return "HIGH", "REDUCE_POSITION_SIZE_MAJOR", 0.25
        elif risk_score >= self.risk_thresholds['MEDIUM']:
            return "MEDIUM", "REDUCE_POSITION_SIZE", 0.50
        elif risk_score >= self.risk_thresholds['LOW_MEDIUM']:
            return "LOW_MEDIUM", "REDUCE_POSITION_SIZE_MINOR", 0.75
        else:
            return "LOW", "NORMAL_EXECUTION", 1.0
    
    def _calculate_confidence(self, risk_score: float, composition: SignalCompositionAnalysis,
                           context: MarketContextAnalysis) -> float:
        """Calculate confidence in the risk assessment"""
        confidence = 0.7  # Base confidence
        
        # High confidence for extreme patterns
        if composition.bear_percentage >= 100 or composition.bull_percentage >= 100:
            confidence += 0.2
        
        # High confidence for market divergence
        if context.divergence_detected and context.divergence_severity == "EXTREME":
            confidence += 0.15
        
        # Lower confidence for mixed signals
        if 0.4 < risk_score < 0.6:
            confidence -= 0.1
        
        return min(0.99, max(0.5, confidence))
    
    def _estimate_prevention_amount(self, risk_score: float, signal_count: int) -> float:
        """Estimate potential loss prevention amount"""
        # Based on historical data: avg loss per signal on red days
        avg_loss_per_signal = 1.5  # Estimated $1.50 per signal
        base_prevention = signal_count * avg_loss_per_signal
        
        # Scale by risk score
        return base_prevention * risk_score
    
    def _determine_primary_risk_reason(self, composition_score: float, 
                                     context_score: float, technical_score: float) -> str:
        """Determine the primary risk factor"""
        scores = {
            'Signal Composition': composition_score,
            'Market Context': context_score,
            'Technical Weakness': technical_score
        }
        
        primary_factor = max(scores.keys(), key=lambda k: scores[k])
        return f"{primary_factor} (score: {scores[primary_factor]:.2f})"
    
    def _get_error_fallback_assessment(self, signals: List[Dict[str, Any]]) -> RedDayRiskAssessment:
        """Return safe fallback assessment on error"""
        from .prime_signal_analyzer import SignalCompositionAnalysis, MarketContextAnalysis
        
        # Create minimal safe assessment
        safe_composition = SignalCompositionAnalysis(
            total_signals=len(signals), bear_count=0, bull_count=0, neutral_count=len(signals),
            bear_percentage=0, bull_percentage=0, neutral_percentage=100,
            sector_concentration={}, max_sector_concentration=0,
            risk_level="UNKNOWN", risk_factors=["ERROR_IN_ANALYSIS"], 
            recommendation="SKIP_EXECUTION"
        )
        
        safe_context = MarketContextAnalysis(
            spy_momentum=0, vix_level=20, market_direction="UNKNOWN", signal_direction="UNKNOWN",
            divergence_detected=False, divergence_severity="NONE",
            risk_level="UNKNOWN", risk_factors=["ERROR_IN_ANALYSIS"]
        )
        
        safe_technical = TechnicalWeaknessAnalysis(
            avg_rsi=50, rsi_weakness_pct=0, avg_volume_ratio=1.0,
            volume_weakness_pct=0, macd_weakness_pct=0, combined_weakness_score=0,
            risk_level="UNKNOWN", risk_factors=["ERROR_IN_ANALYSIS"]
        )
        
        return RedDayRiskAssessment(
            composite_risk_score=0.9,  # High risk due to error
            risk_level="ERROR",
            recommendation="SKIP_EXECUTION",
            position_size_multiplier=0.0,
            confidence=0.5,
            signal_composition=safe_composition,
            market_context=safe_context,
            technical_weakness=safe_technical,
            all_risk_factors=["ERROR_IN_ANALYSIS"],
            primary_risk_reason="Analysis Error",
            prevention_amount_estimate=len(signals) * 2.0
        )

# Example usage and testing
if __name__ == "__main__":
    import asyncio
    
    async def test_detector():
        detector = PrimeEnhancedRedDayDetector()
        
        # Test with today's emergency exit signals (Nov 25, 2025)
        todays_signals = [
            {'symbol': 'SSG', 'rsi': 45, 'volume_ratio': 1.8, 'macd_histogram': -0.05},
            {'symbol': 'TSDD', 'rsi': 42, 'volume_ratio': 2.2, 'macd_histogram': -0.03},
            {'symbol': 'TSLS', 'rsi': 48, 'volume_ratio': 1.9, 'macd_histogram': -0.01},
            {'symbol': 'NVDQ', 'rsi': 44, 'volume_ratio': 1.7, 'macd_histogram': -0.04},
            {'symbol': 'AMDD', 'rsi': 43, 'volume_ratio': 2.0, 'macd_histogram': -0.03},
            {'symbol': 'NVDD', 'rsi': 46, 'volume_ratio': 1.6, 'macd_histogram': -0.06},
            {'symbol': 'DRIP', 'rsi': 41, 'volume_ratio': 2.1, 'macd_histogram': -0.02},
        ]
        
        # Analyze with market context (SPY +0.8%, VIX 14.5)
        assessment = await detector.analyze_red_day_risk(
            signals=todays_signals,
            spy_momentum=0.8,
            vix_level=14.5
        )
        
        print("Enhanced Red Day Detection Analysis:")
        print(f"  Composite Risk Score: {assessment.composite_risk_score:.3f}")
        print(f"  Risk Level: {assessment.risk_level}")
        print(f"  Recommendation: {assessment.recommendation}")
        print(f"  Position Size Multiplier: {assessment.position_size_multiplier}")
        print(f"  Confidence: {assessment.confidence:.1%}")
        print(f"  Primary Risk: {assessment.primary_risk_reason}")
        print(f"  Prevention Estimate: ${assessment.prevention_amount_estimate:.2f}")
        print(f"  Risk Factors: {assessment.all_risk_factors}")
    
    # Run test
    asyncio.run(test_detector())
