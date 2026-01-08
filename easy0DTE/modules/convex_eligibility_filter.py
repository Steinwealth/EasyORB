#!/usr/bin/env python3
"""
Convex Eligibility Filter
=========================

Filters ORB signals to determine which trades deserve options exposure.
Not every ORB-qualified trade gets options—only the highest-conviction setups.

Easy 0DTE = selective convex amplification. Gamma > leverage.

Key Criteria (All Must Pass):
1. ORB Volatility Score ≥ Top X percentile
2. ORB range ≥ 0.25% of SYMBOL price OR 5-min ATR ≥ intraday minimum threshold
3. NOT a Red Day (trade execution disabled if Red Day detected)
4. ORB Break: Long requires price > ORB High, Short requires price < ORB Low
5. Volume > ORB volume average
6. VWAP Condition: Long requires Price ≥ VWAP, Short requires Price ≤ VWAP
7. Early momentum confirmation
8. Market regime = impulse/trend (NOT rotation)

Long Setup Requirements:
- Price breaks above ORB High
- Volume > ORB volume average
- Price ≥ VWAP

Short Setup Requirements:
- Price breaks below ORB Low
- Volume > ORB volume average
- Price ≤ VWAP

Trade Allowed ONLY if:
- ORB range ≥ 0.25% of SYMBOL price
- OR 5-min ATR ≥ intraday minimum threshold

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np

log = logging.getLogger(__name__)

@dataclass
class ConvexEligibilityResult:
    """Result of convex eligibility filtering"""
    signal: Dict[str, Any]
    eligibility_score: float
    is_eligible: bool
    eligibility_reasons: List[str]
    rejection_reasons: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'signal': self.signal,
            'eligibility_score': self.eligibility_score,
            'is_eligible': self.is_eligible,
            'eligibility_reasons': self.eligibility_reasons,
            'rejection_reasons': self.rejection_reasons
        }


class ConvexEligibilityFilter:
    """
    Convex Eligibility Filter for 0DTE Strategy
    
    Determines which ORB signals deserve options exposure based on:
    - Volatility score percentile
    - ORB range threshold
    - Red day status
    - Momentum confirmation
    - Market regime
    """
    
    def __init__(
        self,
        volatility_percentile_threshold: float = 0.80,  # Top 20%
        orb_range_min_pct: float = 0.25,  # 0.25% minimum (prevents theta chop)
        momentum_confirmation_required: bool = True,
        trend_day_required: bool = True
    ):
        """
        Initialize Convex Eligibility Filter
        
        Args:
            volatility_percentile_threshold: Minimum percentile for volatility score (0.0-1.0)
            orb_range_min_pct: Minimum ORB range percentage (e.g., 0.35 = 0.35%)
            momentum_confirmation_required: Require early momentum confirmation
            trend_day_required: Require trend/impulse day (not rotation)
        """
        self.volatility_percentile_threshold = volatility_percentile_threshold
        self.orb_range_min_pct = orb_range_min_pct
        self.momentum_confirmation_required = momentum_confirmation_required
        self.trend_day_required = trend_day_required
        
        log.info(f"Convex Eligibility Filter initialized:")
        log.info(f"  - Volatility percentile threshold: {volatility_percentile_threshold*100:.1f}%")
        log.info(f"  - ORB range minimum: {orb_range_min_pct:.2f}%")
        log.info(f"  - Momentum confirmation required: {momentum_confirmation_required}")
        log.info(f"  - Trend day required: {trend_day_required}")
    
    def calculate_eligibility_score(
        self,
        signal: Dict[str, Any],
        all_signals: Optional[List[Dict[str, Any]]] = None
    ) -> float:
        """
        Calculate eligibility score for a signal (0.0-1.0)
        
        Args:
            signal: ORB signal dictionary
            all_signals: All signals for percentile calculation (optional)
            
        Returns:
            Eligibility score (0.0 = not eligible, 1.0 = highly eligible)
        """
        score = 0.0
        max_score = 0.0
        
        # 1. Volatility Score (40% weight)
        # Use orb_volume_ratio if orb_volatility_score not available
        volatility_score = signal.get('orb_volatility_score', None)
        if volatility_score is None:
            # Fallback to orb_volume_ratio as proxy for volatility
            volatility_score = signal.get('orb_volume_ratio', 0.0)
        
        if all_signals:
            # Calculate percentile from available volatility scores
            volatility_scores = []
            for s in all_signals:
                vs = s.get('orb_volatility_score', None)
                if vs is None:
                    vs = s.get('orb_volume_ratio', 0.0)
                volatility_scores.append(vs)
            
            if volatility_scores:
                percentile = np.percentile(volatility_scores, self.volatility_percentile_threshold * 100)
                if volatility_score >= percentile:
                    score += 0.40
        else:
            # Fallback: use raw score if above threshold
            if volatility_score >= self.volatility_percentile_threshold:
                score += 0.40
        max_score += 0.40
        
        # 2. ORB Range OR 5-min ATR (25% weight)
        # Trade allowed ONLY if: ORB range ≥ 0.25% OR 5-min ATR ≥ intraday minimum threshold
        orb_range_pct = signal.get('orb_range_pct', 0.0)
        current_price = signal.get('current_price', 0.0)
        atr_5min = signal.get('atr_5min', None)
        atr_threshold_pct = signal.get('atr_threshold_pct', 0.25)
        
        orb_range_pass = orb_range_pct >= self.orb_range_min_pct
        
        # Check 5-min ATR as alternative
        atr_pass = False
        if not orb_range_pass and atr_5min is not None and current_price > 0:
            atr_threshold = current_price * (atr_threshold_pct / 100.0)
            atr_pass = atr_5min >= atr_threshold
        
        if orb_range_pass:
            # Scale score based on how much above threshold
            range_score = min(1.0, (orb_range_pct / self.orb_range_min_pct) * 0.5)
            score += 0.25 * range_score
        elif atr_pass:
            # ATR alternative passes - give partial score
            score += 0.20  # Slightly lower score for ATR alternative
        max_score += 0.25
        
        # 3. Red Day Status (15% weight) - must NOT be red day
        is_red_day = signal.get('is_red_day', False)
        if not is_red_day:
            score += 0.15
        max_score += 0.15
        
        # 4. Momentum Confirmation (10% weight)
        # Calculate momentum from available data if field not present
        has_momentum = signal.get('momentum_confirmed', None)
        if has_momentum is None:
            # Calculate momentum from MACD histogram or price action
            macd_histogram = signal.get('macd_histogram', 0)
            rs_vs_spy = signal.get('rs_vs_spy', 0)
            # Positive MACD histogram or positive RS indicates momentum
            has_momentum = macd_histogram > 0 or rs_vs_spy > 0
        
        if has_momentum or not self.momentum_confirmation_required:
            score += 0.10
        max_score += 0.10
        
        # 5. Market Regime (10% weight)
        # Calculate market regime from available data if field not present
        market_regime = signal.get('market_regime', None)
        if market_regime is None:
            # Infer from VWAP distance and RS vs SPY
            vwap_distance = signal.get('vwap_distance_pct', 0)
            rs_vs_spy = signal.get('rs_vs_spy', 0)
            # Strong VWAP distance or RS indicates trend/impulse
            if abs(vwap_distance) > 1.0 or abs(rs_vs_spy) > 2.0:
                market_regime = 'trend'
            else:
                market_regime = 'rotation'
        
        is_trend_day = market_regime in ['trend', 'impulse', 'BULL', 'BEAR']
        if is_trend_day or not self.trend_day_required:
            score += 0.10
        max_score += 0.10
        
        # Normalize score
        if max_score > 0:
            normalized_score = score / max_score
        else:
            normalized_score = 0.0
        
        return normalized_score
    
    def is_eligible(
        self,
        signal: Dict[str, Any],
        all_signals: Optional[List[Dict[str, Any]]] = None,
        min_score: float = 0.75
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Determine if signal is eligible for options trading
        
        Args:
            signal: ORB signal dictionary
            all_signals: All signals for percentile calculation
            min_score: Minimum eligibility score threshold
            
        Returns:
            Tuple of (is_eligible, eligibility_reasons, rejection_reasons)
        """
        eligibility_reasons = []
        rejection_reasons = []
        
        # Calculate eligibility score
        score = self.calculate_eligibility_score(signal, all_signals)
        
        # Check individual criteria
        checks = {
            'volatility': False,
            'orb_range_or_atr': False,  # ORB range ≥ 0.25% OR 5-min ATR ≥ threshold
            'not_red_day': False,
            'orb_break': False,  # Long: price > ORB High, Short: price < ORB Low
            'volume': False,  # Volume > ORB volume average
            'vwap': False,  # Long: Price ≥ VWAP, Short: Price ≤ VWAP
            'momentum': False,
            'trend_day': False
        }
        
        # 1. Volatility Score Check
        # Use orb_volume_ratio if orb_volatility_score not available
        volatility_score = signal.get('orb_volatility_score', None)
        if volatility_score is None:
            volatility_score = signal.get('orb_volume_ratio', 0.0)
        
        # Adjust threshold for leveraged ETFs (TQQQ, SPXL, etc.)
        symbol = signal.get('symbol', '')
        is_leveraged = any(x in symbol for x in ['TQQQ', 'SPXL', 'UPRO', 'SSO', 'QLD', 'SQQQ', 'SPXU', 'SPXS', 'SDS', 'QID'])
        volatility_threshold = self.volatility_percentile_threshold
        if is_leveraged:
            # Lower threshold for leveraged ETFs (they're inherently more volatile)
            volatility_threshold = max(0.60, volatility_threshold - 0.10)  # Top 30-40% instead of 20%
        
        if all_signals:
            volatility_scores = []
            for s in all_signals:
                vs = s.get('orb_volatility_score', None)
                if vs is None:
                    vs = s.get('orb_volume_ratio', 0.0)
                volatility_scores.append(vs)
            
            if volatility_scores:
                percentile = np.percentile(volatility_scores, volatility_threshold * 100)
                if volatility_score >= percentile:
                    checks['volatility'] = True
                    eligibility_reasons.append(f"Volatility score {volatility_score:.2f} ≥ {percentile:.2f} percentile ({'leveraged ETF' if is_leveraged else 'standard'})")
                else:
                    rejection_reasons.append(f"Volatility score {volatility_score:.2f} < {percentile:.2f} percentile ({'leveraged ETF' if is_leveraged else 'standard'})")
        else:
            if volatility_score >= volatility_threshold:
                checks['volatility'] = True
                eligibility_reasons.append(f"Volatility score {volatility_score:.2f} ≥ threshold ({'leveraged ETF' if is_leveraged else 'standard'})")
            else:
                rejection_reasons.append(f"Volatility score {volatility_score:.2f} < threshold ({'leveraged ETF' if is_leveraged else 'standard'})")
        
        # 2. ORB Range OR 5-min ATR Check
        # Trade allowed ONLY if: ORB range ≥ 0.25% OR 5-min ATR ≥ intraday minimum threshold
        orb_range_pct = signal.get('orb_range_pct', 0.0)
        current_price = signal.get('current_price', 0.0)
        atr_5min = signal.get('atr_5min', None)  # 5-minute ATR
        atr_threshold_pct = signal.get('atr_threshold_pct', 0.25)  # Default 0.25% of price
        
        symbol = signal.get('symbol', '')
        is_leveraged = any(x in symbol for x in ['TQQQ', 'SPXL', 'UPRO', 'SSO', 'QLD', 'SQQQ', 'SPXU', 'SPXS', 'SDS', 'QID'])
        range_threshold = self.orb_range_min_pct  # Defaults to 0.25%
        
        # Check ORB range first
        orb_range_pass = orb_range_pct >= range_threshold
        
        # Check 5-min ATR as alternative if ORB range doesn't pass
        atr_pass = False
        if not orb_range_pass and atr_5min is not None and current_price > 0:
            atr_threshold = current_price * (atr_threshold_pct / 100.0)
            atr_pass = atr_5min >= atr_threshold
        
        if orb_range_pass:
            checks['orb_range_or_atr'] = True
            eligibility_reasons.append(f"ORB range {orb_range_pct:.2f}% ≥ {range_threshold:.2f}% ({'leveraged ETF' if is_leveraged else 'standard'})")
        elif atr_pass:
            checks['orb_range_or_atr'] = True
            eligibility_reasons.append(f"5-min ATR ${atr_5min:.2f} ≥ ${atr_threshold:.2f} threshold (alternative to ORB range)")
        else:
            rejection_reasons.append(f"ORB range {orb_range_pct:.2f}% < {range_threshold:.2f}% AND 5-min ATR insufficient")
        
        # 3. Red Day Check
        is_red_day = signal.get('is_red_day', False)
        if not is_red_day:
            checks['not_red_day'] = True
            eligibility_reasons.append("NOT a Red Day")
        else:
            rejection_reasons.append("Red Day detected - skipping options")
        
        # 4. ORB High/Low Break Check
        # Long Setup: Price breaks above ORB High
        # Short Setup: Price breaks below ORB Low
        direction = signal.get('side', 'LONG').upper()
        orb_high = signal.get('orb_high', None)
        orb_low = signal.get('orb_low', None)
        current_price = signal.get('current_price', 0.0)
        
        orb_break_pass = False
        if direction == 'LONG' and orb_high is not None and current_price > 0:
            if current_price > orb_high:
                checks['orb_break'] = True
                orb_break_pass = True
                eligibility_reasons.append(f"LONG: Price ${current_price:.2f} > ORB High ${orb_high:.2f}")
            else:
                rejection_reasons.append(f"LONG: Price ${current_price:.2f} ≤ ORB High ${orb_high:.2f} (no breakout)")
        elif direction == 'SHORT' and orb_low is not None and current_price > 0:
            if current_price < orb_low:
                checks['orb_break'] = True
                orb_break_pass = True
                eligibility_reasons.append(f"SHORT: Price ${current_price:.2f} < ORB Low ${orb_low:.2f}")
            else:
                rejection_reasons.append(f"SHORT: Price ${current_price:.2f} ≥ ORB Low ${orb_low:.2f} (no breakdown)")
        else:
            # If ORB data missing, skip this check (don't reject)
            checks['orb_break'] = True
            orb_break_pass = True
            eligibility_reasons.append(f"ORB break check skipped (missing ORB data)")
        
        # 5. Volume Check
        # Volume > ORB volume average
        current_volume = signal.get('volume', 0)
        orb_volume_avg = signal.get('orb_volume_avg', None)
        
        if orb_volume_avg is not None and orb_volume_avg > 0:
            if current_volume > orb_volume_avg:
                checks['volume'] = True
                eligibility_reasons.append(f"Volume {current_volume:,} > ORB avg {orb_volume_avg:,.0f}")
            else:
                rejection_reasons.append(f"Volume {current_volume:,} ≤ ORB avg {orb_volume_avg:,.0f}")
        else:
            # If ORB volume data missing, skip this check (don't reject)
            checks['volume'] = True
            eligibility_reasons.append("Volume check skipped (missing ORB volume data)")
        
        # 6. VWAP Check
        # Long Setup: Price ≥ VWAP
        # Short Setup: Price ≤ VWAP
        vwap = signal.get('vwap', None)
        current_price = signal.get('current_price', 0.0)
        
        if vwap is not None and current_price > 0:
            if direction == 'LONG':
                if current_price >= vwap:
                    checks['vwap'] = True
                    eligibility_reasons.append(f"LONG: Price ${current_price:.2f} ≥ VWAP ${vwap:.2f}")
                else:
                    rejection_reasons.append(f"LONG: Price ${current_price:.2f} < VWAP ${vwap:.2f}")
            else:  # SHORT
                if current_price <= vwap:
                    checks['vwap'] = True
                    eligibility_reasons.append(f"SHORT: Price ${current_price:.2f} ≤ VWAP ${vwap:.2f}")
                else:
                    rejection_reasons.append(f"SHORT: Price ${current_price:.2f} > VWAP ${vwap:.2f}")
        else:
            # If VWAP data missing, skip this check (don't reject)
            checks['vwap'] = True
            eligibility_reasons.append("VWAP check skipped (missing VWAP data)")
        
        # 7. Momentum Confirmation Check
        if self.momentum_confirmation_required:
            has_momentum = signal.get('momentum_confirmed', None)
            if has_momentum is None:
                # Calculate momentum from available data
                macd_histogram = signal.get('macd_histogram', 0)
                rs_vs_spy = signal.get('rs_vs_spy', 0)
                vwap_distance = signal.get('vwap_distance_pct', 0)
                # Positive indicators suggest momentum
                has_momentum = macd_histogram > 0 or rs_vs_spy > 0.5 or vwap_distance > 0.5
            
            if has_momentum:
                checks['momentum'] = True
                eligibility_reasons.append("Momentum confirmed (from MACD/RS/VWAP)")
            else:
                rejection_reasons.append("Momentum confirmation missing")
        else:
            checks['momentum'] = True  # Not required
        
        # 8. Market Regime Check
        if self.trend_day_required:
            market_regime = signal.get('market_regime', None)
            if market_regime is None:
                # Infer from VWAP distance and RS vs SPY
                vwap_distance = signal.get('vwap_distance_pct', 0)
                rs_vs_spy = signal.get('rs_vs_spy', 0)
                # Strong VWAP distance or RS indicates trend/impulse
                if abs(vwap_distance) > 1.0 or abs(rs_vs_spy) > 2.0:
                    market_regime = 'trend'
                else:
                    market_regime = 'rotation'
            
            is_trend_day = market_regime in ['trend', 'impulse', 'BULL', 'BEAR']
            if is_trend_day:
                checks['trend_day'] = True
                eligibility_reasons.append(f"Market regime: {market_regime} (inferred from VWAP/RS)")
            else:
                rejection_reasons.append(f"Market regime: {market_regime} (not trend/impulse)")
        else:
            checks['trend_day'] = True  # Not required
        
        # Determine eligibility
        all_checks_pass = all(checks.values())
        score_pass = score >= min_score
        
        is_eligible = all_checks_pass and score_pass
        
        if is_eligible:
            eligibility_reasons.append(f"Eligibility score: {score:.2f} ≥ {min_score:.2f}")
        else:
            if not score_pass:
                rejection_reasons.append(f"Eligibility score: {score:.2f} < {min_score:.2f}")
        
        return is_eligible, eligibility_reasons, rejection_reasons
    
    def filter_signals(
        self,
        signals: List[Dict[str, Any]],
        min_score: float = 0.75,
        max_signals: Optional[int] = None
    ) -> List[ConvexEligibilityResult]:
        """
        Filter signals through convex eligibility criteria
        
        Args:
            signals: List of ORB signals
            min_score: Minimum eligibility score threshold
            max_signals: Maximum number of eligible signals to return (None = all)
            
        Returns:
            List of ConvexEligibilityResult objects
        """
        if not signals:
            log.warning("No signals provided to filter")
            return []
        
        log.info(f"Filtering {len(signals)} signals through Convex Eligibility Filter")
        
        # Calculate eligibility for all signals
        results = []
        for signal in signals:
            is_eligible, eligibility_reasons, rejection_reasons = self.is_eligible(
                signal, signals, min_score
            )
            
            score = self.calculate_eligibility_score(signal, signals)
            
            result = ConvexEligibilityResult(
                signal=signal,
                eligibility_score=score,
                is_eligible=is_eligible,
                eligibility_reasons=eligibility_reasons,
                rejection_reasons=rejection_reasons
            )
            
            results.append(result)
        
        # Sort by eligibility score (descending)
        results.sort(key=lambda x: x.eligibility_score, reverse=True)
        
        # Filter to eligible signals only
        eligible_results = [r for r in results if r.is_eligible]
        
        # Limit to max_signals if specified
        if max_signals and len(eligible_results) > max_signals:
            eligible_results = eligible_results[:max_signals]
        
        log.info(f"Convex Eligibility Filter Results:")
        log.info(f"  - Total signals: {len(signals)}")
        log.info(f"  - Eligible signals: {len(eligible_results)}")
        log.info(f"  - Rejected signals: {len(signals) - len(eligible_results)}")
        
        # Log top eligible signals
        if eligible_results:
            log.info(f"  ✅ Top {min(5, len(eligible_results))} Eligible Signals:")
            for i, result in enumerate(eligible_results[:5], 1):
                symbol = result.signal.get('symbol', 'UNKNOWN')
                score = result.eligibility_score
                reasons = result.eligibility_reasons[:3] if result.eligibility_reasons else ['No reasons provided']
                log.info(f"    {i}. {symbol}: Score {score:.2f}")
                log.info(f"       Reasons: {', '.join(reasons)}")
        else:
            # Log top rejection reasons if no signals passed (Rev 00232: Enhanced diagnostics, Rev 00233: Enhanced logging)
            rejection_reason_counts = {}
            for result in results:
                for reason in result.rejection_reasons:
                    rejection_reason_counts[reason] = rejection_reason_counts.get(reason, 0) + 1
            
            top_rejection_reasons = sorted(
                rejection_reason_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            
            if top_rejection_reasons:
                log.info(f"  📊 Top Rejection Reasons (why signals didn't qualify):")
                for i, (reason, count) in enumerate(top_rejection_reasons, 1):
                    pct = (count / len(signals)) * 100
                    log.info(f"    {i}. {reason}: {count}/{len(signals)} signals ({pct:.1f}%)")
            
            # Log top 5 signals with their scores and ALL rejection reasons (Rev 00233: Enhanced)
            log.info(f"  📋 Top 5 Signals (by score) - Detailed Rejection Analysis:")
            for i, result in enumerate(results[:5], 1):
                symbol = result.signal.get('symbol', 'UNKNOWN')
                score = result.eligibility_score
                all_reasons = result.rejection_reasons if result.rejection_reasons else ['Unknown']
                # Log all rejection reasons for better diagnostics
                log.info(f"    {i}. {symbol}: Score {score:.2f}")
                log.info(f"       Rejected for: {len(all_reasons)} reason(s)")
                for j, reason in enumerate(all_reasons, 1):
                    log.info(f"         {j}. {reason}")
                # Also log eligibility reasons if any (for debugging)
                if result.eligibility_reasons:
                    log.info(f"       Passed checks: {', '.join(result.eligibility_reasons[:3])}")
        
        return eligible_results
    
    def get_filter_stats(self, results: List[ConvexEligibilityResult]) -> Dict[str, Any]:
        """
        Get statistics about filtering results
        
        Args:
            results: List of ConvexEligibilityResult objects
            
        Returns:
            Dictionary with filter statistics
        """
        if not results:
            return {
                'total_signals': 0,
                'eligible_count': 0,
                'rejected_count': 0,
                'eligibility_rate': 0.0,
                'avg_eligibility_score': 0.0,
                'top_rejection_reasons': []
            }
        
        eligible = [r for r in results if r.is_eligible]
        rejected = [r for r in results if not r.is_eligible]
        
        # Count rejection reasons
        rejection_reason_counts = {}
        for result in rejected:
            for reason in result.rejection_reasons:
                rejection_reason_counts[reason] = rejection_reason_counts.get(reason, 0) + 1
        
        top_rejection_reasons = sorted(
            rejection_reason_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            'total_signals': len(results),
            'eligible_count': len(eligible),
            'rejected_count': len(rejected),
            'eligibility_rate': len(eligible) / len(results) if results else 0.0,
            'avg_eligibility_score': sum(r.eligibility_score for r in results) / len(results) if results else 0.0,
            'top_rejection_reasons': [{'reason': r[0], 'count': r[1]} for r in top_rejection_reasons]
        }

