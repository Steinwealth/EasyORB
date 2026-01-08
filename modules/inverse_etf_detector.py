"""
Inverse ETF Opportunity Detector

Detects inverse ETF opportunities when bull ETFs are declining significantly.
This module identifies when inverse pairs should be prioritized for maximum gains.
"""

import json
import os
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

log = logging.getLogger(__name__)

@dataclass
class InverseOpportunity:
    """Represents an inverse ETF trading opportunity"""
    bull_etf: str
    bear_etf: str
    bull_decline_pct: float
    expected_bear_gain_pct: float
    underlying: str
    leverage: str
    opportunity_score: float
    market_regime: str  # 'bear', 'bull', 'neutral'

class InverseETFDetector:
    """Detects inverse ETF opportunities based on bull ETF declines"""
    
    def __init__(self, sentiment_file_path: str = "data/watchlist/complete_sentiment_mapping.json"):
        self.sentiment_file_path = sentiment_file_path
        self.inverse_pairs = self._load_inverse_pairs()
        log.info(f"Inverse ETF Detector initialized with {len(self.inverse_pairs)} pairs")
    
    def _load_inverse_pairs(self) -> Dict[str, Dict]:
        """Load inverse pair mappings from sentiment file"""
        try:
            with open(self.sentiment_file_path, 'r') as f:
                data = json.load(f)
            
            bull_bear_pairs = data.get('bull_bear_pairs', {})
            inverse_pairs = {}
            
            for symbol, info in bull_bear_pairs.items():
                if 'bear_etf' in info:
                    # This is a bull ETF
                    inverse_pairs[symbol] = {
                        'inverse_etf': info['bear_etf'],
                        'underlying': info['underlying'],
                        'leverage': info['leverage'],
                        'category': info['category']
                    }
                elif 'bull_etf' in info:
                    # This is a bear ETF
                    inverse_pairs[symbol] = {
                        'inverse_etf': info['bull_etf'],
                        'underlying': info['underlying'],
                        'leverage': info['leverage'],
                        'category': info['category']
                    }
            
            return inverse_pairs
            
        except Exception as e:
            log.error(f"Failed to load inverse pairs: {e}")
            return {}
    
    def detect_opportunities(self, symbol_data: Dict[str, Dict]) -> List[InverseOpportunity]:
        """
        Detect inverse ETF opportunities based on current market data
        
        Args:
            symbol_data: Dict of {symbol: {'price_change_pct': float, 'current_price': float, ...}}
            
        Returns:
            List of InverseOpportunity objects sorted by opportunity score
        """
        opportunities = []
        
        for symbol, data in symbol_data.items():
            price_change_pct = data.get('price_change_pct', 0)
            
            volume_ratio = data.get('volume_ratio', 1.0)
            
            # REAL-TIME EARLY DETECTION: Catch momentum shifts early (1-3% declines)
            # Not waiting for massive -19% end-of-day moves
            early_decline = -0.02 <= price_change_pct <= -0.01  # -1% to -2% (early warning)
            momentum_decline = -0.05 <= price_change_pct < -0.02  # -2% to -5% (momentum building)
            volume_surge = volume_ratio > 1.5  # Volume spike indicates institutional selling
            
            if not ((early_decline or momentum_decline) and volume_surge):
                continue  # Skip if not meeting real-time criteria
                
            # Check if this symbol has an inverse pair
            if symbol not in self.inverse_pairs:
                continue
                
            pair_info = self.inverse_pairs[symbol]
            inverse_etf = pair_info['inverse_etf']
            leverage = pair_info['leverage']
            underlying = pair_info['underlying']
            
            # Calculate expected inverse gain based on momentum trajectory
            leverage_multiplier = self._parse_leverage(leverage)
            
            # MOMENTUM PROJECTION: Estimate where this decline is heading
            if early_decline:
                # Early stage - project 3-5x current decline
                projected_decline = price_change_pct * 4.0  # Project 4x current momentum
                expected_inverse_gain = abs(projected_decline) * leverage_multiplier
                confidence_multiplier = 0.8  # Lower confidence for early detection
            else:  # momentum_decline
                # Momentum building - project 2-3x current decline  
                projected_decline = price_change_pct * 2.5  # Project 2.5x current momentum
                expected_inverse_gain = abs(projected_decline) * leverage_multiplier
                confidence_multiplier = 1.2  # Higher confidence for momentum stage
            
            # Calculate opportunity score with momentum and volume factors
            base_score = expected_inverse_gain * 2.0
            volume_bonus = (volume_ratio - 1.0) * 10.0  # Bonus for volume surge
            momentum_bonus = abs(price_change_pct) * 50.0  # Bonus for current momentum
            opportunity_score = (base_score + volume_bonus + momentum_bonus) * confidence_multiplier
            
            # Create the opportunity (we already filtered for real-time criteria above)
            opportunity = InverseOpportunity(
                bull_etf=symbol,
                bear_etf=inverse_etf,
                bull_decline_pct=price_change_pct,
                expected_bear_gain_pct=expected_inverse_gain,
                underlying=underlying,
                leverage=leverage,
                opportunity_score=opportunity_score,
                market_regime='bear'
            )
            
            opportunities.append(opportunity)
            
            detection_stage = "EARLY" if early_decline else "MOMENTUM"
            log.info(f"🚀 REAL-TIME INVERSE: {symbol} down {price_change_pct:.2f}% ({detection_stage}) → {inverse_etf} projected +{expected_inverse_gain:.1f}% (Vol: {volume_ratio:.1f}x, Score: {opportunity_score:.1f})")
        
        # Sort by opportunity score (highest first)
        opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)
        
        log.info(f"Detected {len(opportunities)} inverse opportunities")
        return opportunities
    
    def _parse_leverage(self, leverage_str: str) -> float:
        """Parse leverage string to multiplier"""
        try:
            if '3x' in leverage_str:
                return 3.0
            elif '2x' in leverage_str:
                return 2.0
            elif '1x' in leverage_str:
                return 1.0
            else:
                return 1.0
        except:
            return 1.0
    
    def _calculate_opportunity_score(self, decline_pct: float, expected_gain: float, 
                                   underlying: str, leverage: float) -> float:
        """Calculate opportunity score for inverse ETF"""
        
        # Base score from expected gain
        base_score = expected_gain * 2.0  # 2x weight for expected gain
        
        # Leverage bonus (higher leverage = higher opportunity)
        leverage_bonus = leverage * 10.0
        
        # Decline magnitude bonus
        decline_bonus = min(decline_pct * 2.0, 50.0)  # Cap at 50
        
        # Underlying category bonus
        category_bonus = 0
        if 'index' in underlying.lower():
            category_bonus = 20  # Index ETFs are more liquid
        elif 'tech' in underlying.lower():
            category_bonus = 15  # Tech has high volatility
        elif 'crypto' in underlying.lower():
            category_bonus = 10  # Crypto is volatile but risky
        
        total_score = base_score + leverage_bonus + decline_bonus + category_bonus
        
        return min(total_score, 200.0)  # Cap at 200
    
    def get_inverse_symbol(self, symbol: str) -> Optional[str]:
        """Get the inverse ETF symbol for a given symbol"""
        if symbol in self.inverse_pairs:
            return self.inverse_pairs[symbol]['inverse_etf']
        return None
    
    def is_inverse_etf(self, symbol: str) -> bool:
        """Check if a symbol is an inverse ETF"""
        return symbol in self.inverse_pairs and 'inverse_etf' in self.inverse_pairs[symbol]
    
    def get_all_inverse_pairs(self) -> Dict[str, str]:
        """Get all inverse pairs as {bull_etf: bear_etf}"""
        pairs = {}
        for symbol, info in self.inverse_pairs.items():
            if 'inverse_etf' in info:
                pairs[symbol] = info['inverse_etf']
        return pairs

# Example usage and testing
if __name__ == "__main__":
    # Test with the red day data from the user
    test_data = {
        'SOXL': {'price_change_pct': -19.02, 'current_price': 34.205},
        'TQQQ': {'price_change_pct': -10.49, 'current_price': 45.67},
        'UPRO': {'price_change_pct': -8.20, 'current_price': 78.90},
        'SPXL': {'price_change_pct': -8.19, 'current_price': 123.45},
        'TECL': {'price_change_pct': -12.20, 'current_price': 56.78},
        'NVDL': {'price_change_pct': -9.79, 'current_price': 89.12},
        'BITU': {'price_change_pct': -7.60, 'current_price': 23.45},
        'BITX': {'price_change_pct': -7.66, 'current_price': 34.56}
    }
    
    detector = InverseETFDetector()
    opportunities = detector.detect_opportunities(test_data)
    
    print("\n🚀 INVERSE ETF OPPORTUNITIES DETECTED:")
    print("=" * 60)
    for opp in opportunities:
        print(f"📉 {opp.bull_etf} down {opp.bull_decline_pct:.2f}%")
        print(f"📈 {opp.bear_etf} expected +{opp.expected_bear_gain_pct:.1f}%")
        print(f"🎯 Score: {opp.opportunity_score:.1f} | Leverage: {opp.leverage}")
        print("-" * 40)
