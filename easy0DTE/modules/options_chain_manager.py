#!/usr/bin/env python3
"""
Options Chain Manager
=====================

Manages SPX, QQQ & SPY options chains for 0DTE trading.
Handles chain fetching, liquidity analysis, and strike selection.
Priority Order: SPX (professional/institutional) → QQQ (momentum 0DTE) → SPY (most liquid)

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date
from dataclasses import dataclass
import asyncio

# Import ETrade Options API
try:
    from .etrade_options_api import ETradeOptionsAPI, ETradeOptionContract
    ETRADE_OPTIONS_AVAILABLE = True
except ImportError:
    ETRADE_OPTIONS_AVAILABLE = False
    logging.warning("ETrade Options API not available")

log = logging.getLogger(__name__)


@dataclass
class OptionContract:
    """Option contract data"""
    symbol: str
    strike: float
    expiry: str
    option_type: str  # 'call' or 'put'
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    delta: float
    gamma: float
    theta: float
    vega: float
    implied_volatility: float
    
    @property
    def mid_price(self) -> float:
        """Calculate mid price"""
        return (self.bid + self.ask) / 2.0
    
    @property
    def bid_ask_spread(self) -> float:
        """Calculate bid-ask spread"""
        return self.ask - self.bid
    
    @property
    def bid_ask_spread_pct(self) -> float:
        """Calculate bid-ask spread as percentage"""
        if self.mid_price > 0:
            return (self.bid_ask_spread / self.mid_price) * 100.0
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'strike': self.strike,
            'expiry': self.expiry,
            'option_type': self.option_type,
            'bid': self.bid,
            'ask': self.ask,
            'last': self.last,
            'volume': self.volume,
            'open_interest': self.open_interest,
            'delta': self.delta,
            'gamma': self.gamma,
            'theta': self.theta,
            'vega': self.vega,
            'implied_volatility': self.implied_volatility,
            'mid_price': self.mid_price,
            'bid_ask_spread': self.bid_ask_spread,
            'bid_ask_spread_pct': self.bid_ask_spread_pct
        }


@dataclass
class DebitSpread:
    """Debit spread structure"""
    symbol: str
    expiry: str
    option_type: str  # 'call' or 'put'
    long_strike: float
    short_strike: float
    long_contract: OptionContract
    short_contract: OptionContract
    debit_cost: float
    max_profit: float
    max_loss: float
    break_even: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'expiry': self.expiry,
            'option_type': self.option_type,
            'long_strike': self.long_strike,
            'short_strike': self.short_strike,
            'long_contract': self.long_contract.to_dict(),
            'short_contract': self.short_contract.to_dict(),
            'debit_cost': self.debit_cost,
            'max_profit': self.max_profit,
            'max_loss': self.max_loss,
            'break_even': self.break_even
        }


@dataclass
class CreditSpread:
    """Credit spread structure"""
    symbol: str
    expiry: str
    option_type: str  # 'call' or 'put'
    short_strike: float  # Short leg (sell this)
    long_strike: float  # Long leg (buy this for protection)
    short_contract: OptionContract
    long_contract: OptionContract
    credit_received: float  # Net credit received
    max_profit: float  # Max profit = credit received
    max_loss: float  # Max loss = spread_width - credit_received
    break_even: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'expiry': self.expiry,
            'option_type': self.option_type,
            'short_strike': self.short_strike,
            'long_strike': self.long_strike,
            'short_contract': self.short_contract.to_dict(),
            'long_contract': self.long_contract.to_dict(),
            'credit_received': self.credit_received,
            'max_profit': self.max_profit,
            'max_loss': self.max_loss,
            'break_even': self.break_even
        }


class OptionsChainManager:
    """
    Options Chain Manager for 0DTE Strategy
    
    Handles:
    - Fetching options chains from broker API
    - Analyzing liquidity (bid/ask spreads, open interest)
    - Selecting optimal strikes for debit spreads
    - Validating trade eligibility
    """
    
    def __init__(
        self,
        min_open_interest: int = 100,
        max_bid_ask_spread_pct: float = 15.0,  # 15% max spread (deterministic rule: reject if >15% of mid)
        min_volume: int = 50,
        min_risk_reward_ratio: float = 1.5,  # Minimum R:R ratio (1.5-2.5x)
        max_risk_reward_ratio: float = 2.5,  # Maximum R:R ratio (1.5-2.5x)
        chain_stale_threshold_seconds: int = 300,  # 5 minutes (reject if chain older than this)
        etrade_options_api: Optional[Any] = None,
        use_live_api: bool = False
    ):
        """
        Initialize Options Chain Manager
        
        Deterministic Contract/Spread Picker Rules:
        - Reject trade if bid/ask spread > 15% of mid
        - Reject trade if option volume < minimum
        - Reject trade if OI < minimum
        - Reject trade if chain update stale (>5 minutes)
        - Pick: ATM → slightly OTM long leg, Short leg at R:R ≥ 1.5–2.5x
        
        Args:
            min_open_interest: Minimum open interest for liquidity (reject if <minimum)
            max_bid_ask_spread_pct: Maximum bid-ask spread percentage (reject if >15% of mid)
            min_volume: Minimum volume for liquidity (reject if <minimum)
            min_risk_reward_ratio: Minimum risk:reward ratio for spread selection (1.5x)
            max_risk_reward_ratio: Maximum risk:reward ratio for spread selection (2.5x)
            chain_stale_threshold_seconds: Reject trade if chain update stale (seconds)
            etrade_options_api: ETradeOptionsAPI instance (optional)
            use_live_api: Use live ETrade API (False = demo/mock)
        """
        self.min_open_interest = min_open_interest
        self.max_bid_ask_spread_pct = max_bid_ask_spread_pct
        self.min_volume = min_volume
        self.min_risk_reward_ratio = min_risk_reward_ratio
        self.max_risk_reward_ratio = max_risk_reward_ratio
        self.chain_stale_threshold_seconds = chain_stale_threshold_seconds
        self.use_live_api = use_live_api
        
        # ETrade Options API
        if etrade_options_api:
            self.etrade_api = etrade_options_api
        elif use_live_api and ETRADE_OPTIONS_AVAILABLE:
            try:
                environment = os.getenv('ETRADE_ENVIRONMENT', 'prod')
                self.etrade_api = ETradeOptionsAPI(environment=environment)
            except Exception as e:
                log.warning(f"Failed to initialize ETrade Options API: {e}")
                self.etrade_api = None
        else:
            self.etrade_api = None
        
        # Cache for options chains (5-minute TTL)
        self.chain_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 300  # 5 minutes
        
        mode_label = "💰 LIVE API" if use_live_api and self.etrade_api else "🎮 DEMO/MOCK"
        log.info(f"Options Chain Manager initialized ({mode_label}):")
        log.info(f"  - Min open interest: {min_open_interest} (reject if <minimum)")
        log.info(f"  - Max bid-ask spread: {max_bid_ask_spread_pct:.1f}% of mid (reject if >15%)")
        log.info(f"  - Min volume: {min_volume} (reject if <minimum)")
        log.info(f"  - Risk:Reward ratio: {min_risk_reward_ratio:.1f}x - {max_risk_reward_ratio:.1f}x")
        log.info(f"  - Chain stale threshold: {chain_stale_threshold_seconds}s (reject if stale)")
        log.info(f"  - Live API enabled: {use_live_api and self.etrade_api is not None}")
    
    async def fetch_options_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None,
        use_cache: bool = True
    ) -> Dict[str, List[OptionContract]]:
        """
        Fetch options chain for symbol
        
        Args:
            symbol: Underlying symbol (SPX, QQQ, or SPY)
            expiry: Expiry date (YYYY-MM-DD format, None = 0DTE)
            use_cache: Use cached chain if available
            
        Returns:
            Dictionary with 'calls' and 'puts' lists
        """
        # Use today's date for 0DTE if expiry not specified
        if expiry is None:
            expiry = datetime.now().strftime('%Y-%m-%d')
        
        cache_key = f"{symbol}_{expiry}"
        
        # Check cache
        if use_cache and cache_key in self.chain_cache:
            cached_data = self.chain_cache[cache_key]
            cache_time = cached_data.get('timestamp', 0)
            cache_age_seconds = datetime.now().timestamp() - cache_time
            
            # Deterministic rule: Reject trade if chain update stale
            if cache_age_seconds > self.chain_stale_threshold_seconds:
                log.warning(f"⚠️ Chain update stale for {symbol} {expiry}: {cache_age_seconds:.0f}s > {self.chain_stale_threshold_seconds}s threshold")
                log.warning(f"   Rejecting trade - chain data too old (deterministic rule)")
                # Don't use stale cache, fetch fresh data
            elif cache_age_seconds < self.cache_ttl:
                log.debug(f"Using cached options chain for {symbol} {expiry} (age: {cache_age_seconds:.0f}s)")
                return cached_data['chain']
        
        # Live API: Fetch from ETrade
        if self.use_live_api and self.etrade_api and self.etrade_api.is_available():
            try:
                # Convert expiry format: YYYY-MM-DD -> YYYYMMDD
                expiry_etrade = expiry.replace('-', '')
                
                # Fetch from ETrade API
                etrade_chain = await self.etrade_api.fetch_options_chain(
                    symbol=symbol,
                    expiry=expiry_etrade,
                    strike_count=20,
                    include_greeks=True
                )
                
                # Convert ETradeOptionContract to OptionContract
                calls = []
                puts = []
                
                for etrade_call in etrade_chain.get('calls', []):
                    call = OptionContract(
                        symbol=etrade_call.symbol,
                        strike=etrade_call.strike,
                        expiry=expiry,
                        option_type='call',
                        bid=etrade_call.bid,
                        ask=etrade_call.ask,
                        last=etrade_call.last,
                        volume=etrade_call.volume,
                        open_interest=etrade_call.open_interest,
                        delta=etrade_call.delta or 0.0,
                        gamma=etrade_call.gamma or 0.0,
                        theta=etrade_call.theta or 0.0,
                        vega=etrade_call.vega or 0.0,
                        implied_volatility=etrade_call.implied_volatility or 0.0
                    )
                    calls.append(call)
                
                for etrade_put in etrade_chain.get('puts', []):
                    put = OptionContract(
                        symbol=etrade_put.symbol,
                        strike=etrade_put.strike,
                        expiry=expiry,
                        option_type='put',
                        bid=etrade_put.bid,
                        ask=etrade_put.ask,
                        last=etrade_put.last,
                        volume=etrade_put.volume,
                        open_interest=etrade_put.open_interest,
                        delta=etrade_put.delta or 0.0,
                        gamma=etrade_put.gamma or 0.0,
                        theta=etrade_put.theta or 0.0,
                        vega=etrade_put.vega or 0.0,
                        implied_volatility=etrade_put.implied_volatility or 0.0
                    )
                    puts.append(put)
                
                chain = {'calls': calls, 'puts': puts}
                
                # Cache result
                self.chain_cache[cache_key] = {
                    'chain': chain,
                    'timestamp': datetime.now().timestamp()
                }
                
                log.info(f"✅ Fetched options chain from ETrade: {len(calls)} calls, {len(puts)} puts")
                return chain
                
            except Exception as e:
                log.error(f"Failed to fetch options chain from ETrade: {e}")
                # Fall through to return empty chain
        
        # Demo/Mock mode: Return empty structure
        log.warning(f"Options chain fetching not available (Demo mode) for {symbol} {expiry}")
        log.info("In Demo mode, options chains are simulated. Use Live mode for real data.")
        
        # Placeholder structure
        chain = {
            'calls': [],
            'puts': []
        }
        
        # Cache result
        self.chain_cache[cache_key] = {
            'chain': chain,
            'timestamp': datetime.now().timestamp()
        }
        
        return chain
    
    def validate_liquidity(self, contract: OptionContract) -> Tuple[bool, List[str]]:
        """
        Validate contract liquidity (Deterministic Contract Picker Rules)
        
        Reject trade if:
        - Bid/ask spread > 15% of mid
        - Option volume < minimum
        - OI < minimum
        - Missing bid/ask prices
        
        Args:
            contract: Option contract to validate
            
        Returns:
            Tuple of (is_valid, reasons)
        """
        reasons = []
        is_valid = True
        
        # Deterministic Rule 1: Check open interest (reject if <minimum)
        if contract.open_interest < self.min_open_interest:
            is_valid = False
            reasons.append(f"Open interest {contract.open_interest} < {self.min_open_interest} (reject: OI < minimum)")
        
        # Deterministic Rule 2: Check bid-ask spread (reject if >15% of mid)
        if contract.bid_ask_spread_pct > self.max_bid_ask_spread_pct:
            is_valid = False
            reasons.append(f"Bid/ask spread {contract.bid_ask_spread_pct:.2f}% > {self.max_bid_ask_spread_pct:.1f}% of mid (reject: spread >15%)")
        
        # Deterministic Rule 3: Check volume (reject if <minimum)
        if contract.volume < self.min_volume:
            is_valid = False
            reasons.append(f"Volume {contract.volume} < {self.min_volume} (reject: volume < minimum)")
        
        # Deterministic Rule 4: Check if bid/ask exist (reject if missing)
        if contract.bid <= 0 or contract.ask <= 0:
            is_valid = False
            reasons.append("Missing bid/ask prices (reject: no pricing data)")
        
        return is_valid, reasons
    
    def select_debit_spread_strikes(
        self,
        chain: Dict[str, List[OptionContract]],
        option_type: str,
        target_delta: float,
        spread_width: float,
        current_price: float
    ) -> Optional[DebitSpread]:
        """
        Select optimal strikes for debit spread - Rev 00212
        
        Contract Selection Logic (Best Practices):
        - Premium: $0.20-$0.60 (cheap contracts for gamma explosion)
        - Delta: 10-30 (0.10-0.30) - cheap gamma that can explode
        - Strike: 1-3 strikes OTM (out of the money)
        - Why: Cheap contracts give gamma explosion, easy 5-20x with small moves
        
        Args:
            chain: Options chain dictionary
            option_type: 'call' or 'put'
            target_delta: Target delta for long leg (0.10-0.30) - Rev 00212
            spread_width: Spread width ($1 or $2 for QQQ/SPY, $5 or $10 for SPX)
            current_price: Current underlying price
            
        Returns:
            DebitSpread object or None if no valid spread found
        """
        contracts = chain.get(option_type + 's', [])
        
        if not contracts:
            log.warning(f"No {option_type} contracts available")
            return None
        
        # Rev 00212: Filter contracts by delta range (target ± 0.05 for tighter range)
        # Target delta is now 0.10-0.30, so range is tighter
        delta_min = max(0.10, target_delta - 0.05)  # Minimum 10 delta
        delta_max = min(0.30, target_delta + 0.05)  # Maximum 30 delta
        
        # Rev 00212: Filter by premium range $0.20-$0.60 (cheap contracts for gamma explosion)
        premium_min = 0.20
        premium_max = 0.60
        
        # Rev 00212: Filter by strike position (1-3 strikes OTM)
        # For calls: strike > current_price (OTM)
        # For puts: strike < current_price (OTM)
        candidate_long_legs = []
        
        # Get all strikes sorted for OTM calculation
        all_strikes = sorted(set(c.strike for c in contracts))
        
        for c in contracts:
                # Check delta range
                if not (delta_min <= abs(c.delta) <= delta_max):
                    continue
                
                # Check premium range (use mid price)
                premium = c.mid_price
                if not (premium_min <= premium <= premium_max):
                    log.debug(f"Rejecting {c.strike} {option_type}: premium ${premium:.2f} not in range [${premium_min:.2f}, ${premium_max:.2f}]")
                    continue
                
                # Check strike position (1-3 strikes OTM)
                if option_type == 'call':
                    # Call: strike should be above current price (OTM)
                    if c.strike <= current_price:
                        continue  # Not OTM
                    
                    # Count how many strikes are OTM between current_price and this strike
                    otm_strikes = [s for s in all_strikes if current_price < s <= c.strike]
                    strikes_otm = len(otm_strikes)
                    
                    if not (1 <= strikes_otm <= 3):
                        log.debug(f"Rejecting {c.strike} call: {strikes_otm} strikes OTM (need 1-3)")
                        continue
                else:  # put
                    # Put: strike should be below current price (OTM)
                    if c.strike >= current_price:
                        continue  # Not OTM
                    
                    # Count how many strikes are OTM between this strike and current_price
                    otm_strikes = [s for s in all_strikes if current_price > s >= c.strike]
                    strikes_otm = len(otm_strikes)
                    
                    if not (1 <= strikes_otm <= 3):
                        log.debug(f"Rejecting {c.strike} put: {strikes_otm} strikes OTM (need 1-3)")
                        continue
                
                candidate_long_legs.append(c)
        
        if not candidate_long_legs:
            log.warning(f"No contracts found with delta in range [{delta_min:.2f}, {delta_max:.2f}]")
            return None
        
        # Multi-factor optimization: Cheap gamma + Low decay + Peak gamma potential + Vega risk
        # Score = (gamma_score * gamma_weight) - (theta_score * theta_weight) - (vega_risk * vega_weight)
        # Higher score = better option
        
        def calculate_option_score(contract, target_delta):
            """Calculate multi-factor optimization score for option selection"""
            score = 0.0
            
            # 1. Gamma Score (40% weight) - Buy cheap gamma, maximize peak gamma potential
            # Higher gamma = better, but we want cheap gamma (OTM options)
            gamma_score = abs(contract.gamma) if contract.gamma else 0.0
            # Normalize gamma (assume max gamma around 0.05-0.10 for OTM options)
            gamma_normalized = min(gamma_score / 0.10, 1.0) if gamma_score > 0 else 0.0
            score += gamma_normalized * 0.40
            
            # 2. Theta Score (30% weight) - Minimize decay (lower absolute theta = better)
            # Lower theta (less negative) = less decay = better
            theta_score = abs(contract.theta) if contract.theta else 0.0
            # Normalize theta (assume max theta around 0.20-0.30 for 0DTE OTM options)
            # Lower theta is better, so invert: (max_theta - theta) / max_theta
            theta_normalized = max(0.0, (0.30 - theta_score) / 0.30) if theta_score > 0 else 1.0
            score += theta_normalized * 0.30
            
            # 3. Delta Proximity (20% weight) - Closest to target delta
            delta_diff = abs(abs(contract.delta) - target_delta)
            delta_score = max(0.0, 1.0 - (delta_diff / 0.10))  # Within ±0.10 range
            score += delta_score * 0.20
            
            # 4. Vega Risk (10% weight) - Minimize vega risk (lower vega = less IV sensitivity)
            # Lower vega = less sensitive to IV changes = better (for buying options)
            vega_score = abs(contract.vega) if contract.vega else 0.0
            # Normalize vega (assume max vega around 0.10-0.15 for OTM options)
            # Lower vega is better, so invert: (max_vega - vega) / max_vega
            vega_normalized = max(0.0, (0.15 - vega_score) / 0.15) if vega_score > 0 else 1.0
            score += vega_normalized * 0.10
            
            return score
        
        # Sort by multi-factor optimization score (descending)
        # This optimizes for: cheap gamma + low decay + peak gamma potential + low vega risk
        candidate_long_legs.sort(
            key=lambda x: (
                -calculate_option_score(x, target_delta),  # Higher score first (negative for descending)
                abs(abs(x.delta) - target_delta)  # Then closest delta to target (tiebreaker)
            )
        )
        
        # Try to find valid debit spread
        for long_contract in candidate_long_legs:
            long_strike = long_contract.strike
            
            # Find short leg (spread_width away)
            if option_type == 'call':
                short_strike = long_strike + spread_width
            else:  # put
                short_strike = long_strike - spread_width
            
            # Find short leg contract
            short_contract = next(
                (c for c in contracts if c.strike == short_strike),
                None
            )
            
            if not short_contract:
                continue
            
            # Validate both legs
            long_valid, long_reasons = self.validate_liquidity(long_contract)
            short_valid, short_reasons = self.validate_liquidity(short_contract)
            
            if not long_valid or not short_valid:
                log.debug(f"Invalid spread: long={long_valid}, short={short_valid}")
                continue
            
            # Calculate spread metrics
            debit_cost = long_contract.ask - short_contract.bid
            max_profit = spread_width - debit_cost
            max_loss = debit_cost
            
            # Deterministic Rule: Short leg at R:R ≥ 1.5–2.5x
            if max_loss > 0:
                risk_reward_ratio = max_profit / max_loss
            else:
                risk_reward_ratio = 0.0
            
            # Reject if R:R not in range 1.5-2.5x
            if risk_reward_ratio < self.min_risk_reward_ratio or risk_reward_ratio > self.max_risk_reward_ratio:
                log.debug(f"Rejecting spread: R:R {risk_reward_ratio:.2f}x not in range [{self.min_risk_reward_ratio:.1f}x, {self.max_risk_reward_ratio:.1f}x]")
                continue
            
            if option_type == 'call':
                break_even = long_strike + debit_cost
            else:  # put
                break_even = long_strike - debit_cost
            
            spread = DebitSpread(
                symbol=long_contract.symbol,
                expiry=long_contract.expiry,
                option_type=option_type,
                long_strike=long_strike,
                short_strike=short_strike,
                long_contract=long_contract,
                short_contract=short_contract,
                debit_cost=debit_cost,
                max_profit=max_profit,
                max_loss=max_loss,
                break_even=break_even
            )
            
            # Calculate optimization score for logging
            opt_score = calculate_option_score(long_contract, target_delta)
            
            log.info(f"✅ Selected debit spread: {spread.symbol} {option_type} {spread.long_strike}/{spread.short_strike}")
            log.info(f"  Debit: ${debit_cost:.2f}, Max Profit: ${max_profit:.2f}, Max Loss: ${max_loss:.2f}")
            log.info(f"  Risk:Reward Ratio: {risk_reward_ratio:.2f}x (within {self.min_risk_reward_ratio:.1f}x-{self.max_risk_reward_ratio:.1f}x range ✅)")
            log.info(f"  Long Leg: 1-3 strikes OTM (delta: {long_contract.delta:.2f}, premium: ${long_contract.mid_price:.2f})")
            log.info(f"  Short Leg: R:R {risk_reward_ratio:.2f}x ✅")
            log.info(f"  Long Leg Greeks: Gamma={long_contract.gamma:.4f}, Theta={long_contract.theta:.4f}, Vega={long_contract.vega:.4f}, IV={long_contract.implied_volatility:.2%}")
            log.info(f"  Optimization Score: {opt_score:.3f} (Gamma:40%, Theta:30%, Delta:20%, Vega:10%)")
            log.info(f"  Rev 00212: Premium ${premium:.2f} in range [${premium_min:.2f}, ${premium_max:.2f}] ✅")
            
            return spread
        
        log.warning(f"No valid debit spread found for {option_type} with delta {target_delta:.2f}")
        return None
    
    def select_lotto_strike(
        self,
        chain: Dict[str, List[OptionContract]],
        option_type: str,
        current_price: float,
        target_delta: float = 0.15  # Lower delta for lotto
    ) -> Optional[OptionContract]:
        """
        Select strike for lotto sleeve (single-leg option)
        
        Args:
            chain: Options chain dictionary
            option_type: 'call' or 'put'
            current_price: Current underlying price
            target_delta: Target delta (lower for lotto)
            
        Returns:
            OptionContract or None if no valid contract found
        """
        contracts = chain.get(option_type + 's', [])
        
        if not contracts:
            return None
        
        # Filter by delta range (target ± 0.05)
        delta_min = target_delta - 0.05
        delta_max = target_delta + 0.05
        
        candidates = [
            c for c in contracts
            if delta_min <= abs(c.delta) <= delta_max
        ]
        
        if not candidates:
            return None
        
        # Multi-factor optimization: Cheap gamma + Low decay + Peak gamma potential + Vega risk
        def calculate_lotto_score(contract, target_delta):
            """Calculate multi-factor optimization score for lotto selection"""
            score = 0.0
            
            # 1. Gamma Score (40% weight) - Buy cheap gamma, maximize peak gamma potential
            gamma_score = abs(contract.gamma) if contract.gamma else 0.0
            gamma_normalized = min(gamma_score / 0.10, 1.0) if gamma_score > 0 else 0.0
            score += gamma_normalized * 0.40
            
            # 2. Theta Score (30% weight) - Minimize decay (lower absolute theta = better)
            theta_score = abs(contract.theta) if contract.theta else 0.0
            theta_normalized = max(0.0, (0.30 - theta_score) / 0.30) if theta_score > 0 else 1.0
            score += theta_normalized * 0.30
            
            # 3. Delta Proximity (20% weight) - Closest to target delta
            delta_diff = abs(abs(contract.delta) - target_delta)
            delta_score = max(0.0, 1.0 - (delta_diff / 0.05))  # Within ±0.05 range for lottos
            score += delta_score * 0.20
            
            # 4. Vega Risk (10% weight) - Minimize vega risk (lower vega = less IV sensitivity)
            vega_score = abs(contract.vega) if contract.vega else 0.0
            vega_normalized = max(0.0, (0.15 - vega_score) / 0.15) if vega_score > 0 else 1.0
            score += vega_normalized * 0.10
            
            return score
        
        # Sort by multi-factor optimization score (descending)
        candidates.sort(
            key=lambda x: (
                -calculate_lotto_score(x, target_delta),  # Higher score first
                abs(abs(x.delta) - target_delta)  # Then closest delta to target
            )
        )
        
        for contract in candidates:
            is_valid, reasons = self.validate_liquidity(contract)
            if is_valid:
                opt_score = calculate_lotto_score(contract, target_delta)
                log.info(f"Selected lotto strike: {contract.symbol} {option_type} {contract.strike} @ ${contract.mid_price:.2f}")
                log.info(f"  Greeks: Gamma={contract.gamma:.4f}, Theta={contract.theta:.4f}, Vega={contract.vega:.4f}, IV={contract.implied_volatility:.2%}")
                log.info(f"  Optimization Score: {opt_score:.3f} (Gamma:40%, Theta:30%, Delta:20%, Vega:10%)")
                return contract
        
        return None
    
    def select_atm_momentum_scalper(
        self,
        chain: Dict[str, List[OptionContract]],
        option_type: str,
        current_price: float,
        strikes_otm: int = 1  # 1-2 strikes OTM for quick payoff
    ) -> Optional[DebitSpread]:
        """
        Select ATM Debit Spread for Momentum Scalper (Rev 00227: Level 2 Strategy)
        
        Use when: Expect quick 5-15 min expansion
        Structure: Buy ATM option, Sell 1-2 strikes out
        Why: Cheap entry, fast payoff, high % ROI potential
        
        Args:
            chain: Options chain dictionary
            option_type: 'call' or 'put'
            current_price: Current underlying price
            strikes_otm: Number of strikes OTM for short leg (1-2)
        
        Returns:
            DebitSpread or None if no valid spread found
        """
        contracts = chain.get(option_type + 's', [])
        
        if not contracts:
            return None
        
        # Find ATM or slightly ITM option for long leg
        # For calls: ATM or slightly ITM (strike <= current_price)
        # For puts: ATM or slightly ITM (strike >= current_price)
        if option_type == 'call':
            long_candidates = [
                c for c in contracts
                if c.strike <= current_price * 1.01  # ATM or slightly ITM (within 1%)
                and 0.30 <= abs(c.delta) <= 0.50  # 30-50 delta for ATM
            ]
        else:  # put
            long_candidates = [
                c for c in contracts
                if c.strike >= current_price * 0.99  # ATM or slightly ITM (within 1%)
                and 0.30 <= abs(c.delta) <= 0.50  # 30-50 delta for ATM
            ]
        
        if not long_candidates:
            return None
        
        # Sort by delta proximity to 0.40 (ideal ATM delta)
        long_candidates.sort(key=lambda x: abs(abs(x.delta) - 0.40))
        
        for long_contract in long_candidates[:5]:  # Try top 5 candidates
            # Find short leg: strikes_otm strikes away
            if option_type == 'call':
                target_short_strike = long_contract.strike + (strikes_otm * self._get_strike_increment(long_contract.strike))
            else:  # put
                target_short_strike = long_contract.strike - (strikes_otm * self._get_strike_increment(long_contract.strike))
            
            # Find closest short leg contract
            short_candidates = [
                c for c in contracts
                if abs(c.strike - target_short_strike) < (self._get_strike_increment(long_contract.strike) * 0.5)
            ]
            
            if not short_candidates:
                continue
            
            short_contract = min(short_candidates, key=lambda x: abs(x.strike - target_short_strike))
            
            # Validate liquidity
            long_valid, _ = self.validate_liquidity(long_contract)
            short_valid, _ = self.validate_liquidity(short_contract)
            
            if long_valid and short_valid:
                # Calculate spread details
                spread_width = abs(long_contract.strike - short_contract.strike)
                debit_cost = long_contract.mid_price - short_contract.mid_price
                max_profit = spread_width - debit_cost
                max_loss = debit_cost
                break_even = long_contract.strike + debit_cost if option_type == 'call' else long_contract.strike - debit_cost
                
                spread = DebitSpread(
                    symbol=long_contract.symbol,
                    expiry=long_contract.expiry,
                    option_type=option_type,
                    long_strike=long_contract.strike,
                    short_strike=short_contract.strike,
                    long_contract=long_contract,
                    short_contract=short_contract,
                    debit_cost=debit_cost,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    break_even=break_even
                )
                
                log.info(f"✅ Selected ATM Momentum Scalper: {spread.symbol} {option_type} {spread.long_strike}/{spread.short_strike}")
                log.info(f"   - Debit: ${debit_cost:.2f}, Max Profit: ${max_profit:.2f}, Max Loss: ${max_loss:.2f}")
                return spread
        
        return None
    
    def select_itm_probability_spread(
        self,
        chain: Dict[str, List[OptionContract]],
        option_type: str,
        current_price: float,
        target_delta: float = 0.65  # Deeper ITM (0.60-0.70 delta)
    ) -> Optional[DebitSpread]:
        """
        Select ITM Probability Spread (Rev 00229: Easy Mode Strategy)
        
        Use when: Market is valid but not explosive
        Structure: Buy deeper ITM option (Δ 0.60-0.70), Sell OTM option
        Why: Lower breakeven, higher probability, less dependent on speed
        
        Args:
            chain: Options chain dictionary
            option_type: 'call' or 'put'
            current_price: Current underlying price
            target_delta: Target delta for long leg (0.60-0.70 for ITM)
        
        Returns:
            DebitSpread or None if no valid spread found
        """
        contracts = chain.get(option_type + 's', [])
        
        if not contracts:
            return None
        
        # Find deeper ITM option for long leg (delta 0.60-0.70)
        if option_type == 'call':
            long_candidates = [
                c for c in contracts
                if c.strike <= current_price  # ITM for calls
                and 0.60 <= abs(c.delta) <= 0.70  # Deeper ITM delta
            ]
        else:  # put
            long_candidates = [
                c for c in contracts
                if c.strike >= current_price  # ITM for puts
                and 0.60 <= abs(c.delta) <= 0.70  # Deeper ITM delta
            ]
        
        if not long_candidates:
            return None
        
        # Sort by delta proximity to target (0.65)
        long_candidates.sort(key=lambda x: abs(abs(x.delta) - target_delta))
        
        for long_contract in long_candidates[:5]:  # Try top 5 candidates
            # Find short leg: 2-5 strikes OTM (wider spread for probability)
            if option_type == 'call':
                target_short_strike = long_contract.strike + (3 * self._get_strike_increment(long_contract.strike))  # 3 strikes OTM
            else:  # put
                target_short_strike = long_contract.strike - (3 * self._get_strike_increment(long_contract.strike))  # 3 strikes OTM
            
            # Find closest short leg contract
            short_candidates = [
                c for c in contracts
                if abs(c.strike - target_short_strike) < (self._get_strike_increment(long_contract.strike) * 0.5)
            ]
            
            if not short_candidates:
                continue
            
            short_contract = min(short_candidates, key=lambda x: abs(x.strike - target_short_strike))
            
            # Validate liquidity
            long_valid, _ = self.validate_liquidity(long_contract)
            short_valid, _ = self.validate_liquidity(short_contract)
            
            if long_valid and short_valid:
                # Calculate spread details
                spread_width = abs(long_contract.strike - short_contract.strike)
                debit_cost = long_contract.mid_price - short_contract.mid_price
                max_profit = spread_width - debit_cost
                max_loss = debit_cost
                break_even = long_contract.strike + debit_cost if option_type == 'call' else long_contract.strike - debit_cost
                
                spread = DebitSpread(
                    symbol=long_contract.symbol,
                    expiry=long_contract.expiry,
                    option_type=option_type,
                    long_strike=long_contract.strike,
                    short_strike=short_contract.strike,
                    long_contract=long_contract,
                    short_contract=short_contract,
                    debit_cost=debit_cost,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    break_even=break_even
                )
                
                log.info(f"✅ Selected ITM Probability Spread: {spread.symbol} {option_type} {spread.long_strike}/{spread.short_strike}")
                log.info(f"   - Debit: ${debit_cost:.2f}, Max Profit: ${max_profit:.2f}, Max Loss: ${max_loss:.2f}")
                log.info(f"   - Long Leg Delta: {long_contract.delta:.2f} (ITM), Higher Probability")
                return spread
        
        return None
    
    def _get_strike_increment(self, strike: float) -> float:
        """Get strike increment based on strike price"""
        if strike < 50:
            return 0.5
        elif strike < 200:
            return 1.0
        elif strike < 500:
            return 2.5
        else:
            return 5.0
    
    def select_credit_spread_strikes(
        self,
        chain: Dict[str, List[OptionContract]],
        option_type: str,
        target_delta: float,
        spread_width: float,
        current_price: float
    ) -> Optional[CreditSpread]:
        """
        Select optimal strikes for credit spread - Rev 00212
        
        Contract Selection Logic (Best Practices):
        - Premium: $0.20-$0.60 (cheap contracts for gamma explosion)
        - Delta: 10-30 (0.10-0.30) - cheap gamma that can explode
        - Strike: 1-3 strikes OTM (out of the money)
        - Why: Cheap contracts give gamma explosion, easy 5-20x with small moves
        
        For credit spreads:
        - CALL credit spread: Sell call at lower strike, buy call at higher strike (bearish)
        - PUT credit spread: Sell put at higher strike, buy put at lower strike (bullish)
        
        Args:
            chain: Options chain dictionary
            option_type: 'call' or 'put'
            target_delta: Target delta for short leg (0.10-0.30) - Rev 00212
            spread_width: Spread width ($1 or $2 for QQQ/SPY, $5 or $10 for SPX)
            current_price: Current underlying price
            
        Returns:
            CreditSpread object or None if no valid spread found
        """
        contracts = chain.get(option_type + 's', [])
        
        if not contracts:
            log.warning(f"No {option_type} contracts available")
            return None
        
        # Rev 00212: Filter contracts by delta range (target ± 0.05 for tighter range)
        delta_min = max(0.10, target_delta - 0.05)  # Minimum 10 delta
        delta_max = min(0.30, target_delta + 0.05)  # Maximum 30 delta
        
        # Rev 00212: Filter by premium range $0.20-$0.60 (cheap contracts for gamma explosion)
        premium_min = 0.20
        premium_max = 0.60
        
        # Get all strikes sorted for OTM calculation
        all_strikes = sorted(set(c.strike for c in contracts))
        
        # Rev 00212: Filter by strike position (1-3 strikes OTM) and premium
        candidate_short_legs = []
        for c in contracts:
            # Check delta range
            if not (delta_min <= abs(c.delta) <= delta_max):
                continue
            
            # Check premium range (use mid price)
            premium = c.mid_price
            if not (premium_min <= premium <= premium_max):
                continue
            
            # Check strike position (1-3 strikes OTM) - for credit spreads, short leg should be OTM
            if option_type == 'call':
                # CALL credit: Short call should be OTM (strike > current_price)
                if c.strike <= current_price:
                    continue  # Not OTM
                strikes_otm = sum(1 for s in all_strikes if current_price < s <= c.strike)
                if not (1 <= strikes_otm <= 3):
                    continue
            else:  # put
                # PUT credit: Short put should be OTM (strike < current_price)
                if c.strike >= current_price:
                    continue  # Not OTM
                strikes_otm = sum(1 for s in all_strikes if current_price > s >= c.strike)
                if not (1 <= strikes_otm <= 3):
                    continue
            
            candidate_short_legs.append(c)
        
        if not candidate_short_legs:
            log.warning(f"No contracts found with delta in range [{delta_min:.2f}, {delta_max:.2f}]")
            return None
        
        # For credit spreads: Consider gamma (for liquidity), but prioritize low vega risk
        # Credit spreads have negative gamma, so we accept that but minimize vega risk
        def calculate_credit_score(contract, target_delta):
            """Calculate optimization score for credit spread short leg"""
            score = 0.0
            
            # 1. Delta Proximity (40% weight) - Closest to target delta
            delta_diff = abs(abs(contract.delta) - target_delta)
            delta_score = max(0.0, 1.0 - (delta_diff / 0.10))
            score += delta_score * 0.40
            
            # 2. Vega Risk (30% weight) - Minimize vega risk (lower vega = less IV sensitivity)
            # For credit spreads, lower vega is better (less sensitive to IV changes)
            vega_score = abs(contract.vega) if contract.vega else 0.0
            vega_normalized = max(0.0, (0.15 - vega_score) / 0.15) if vega_score > 0 else 1.0
            score += vega_normalized * 0.30
            
            # 3. Gamma (20% weight) - Higher gamma for liquidity/spread quality
            # Accept negative gamma exposure, but use for liquidity selection
            gamma_score = abs(contract.gamma) if contract.gamma else 0.0
            gamma_normalized = min(gamma_score / 0.10, 1.0) if gamma_score > 0 else 0.0
            score += gamma_normalized * 0.20
            
            # 4. Theta Benefit (10% weight) - Higher theta benefits credit spreads (time decay helps)
            # For credit spreads, higher theta (more negative) is actually beneficial
            theta_score = abs(contract.theta) if contract.theta else 0.0
            theta_normalized = min(theta_score / 0.30, 1.0) if theta_score > 0 else 0.0
            score += theta_normalized * 0.10
            
            return score
        
        # Sort by credit spread optimization score (descending)
        candidate_short_legs.sort(
            key=lambda x: (
                -calculate_credit_score(x, target_delta),  # Higher score first
                abs(abs(x.delta) - target_delta)  # Then closest delta to target
            )
        )
        
        # Try to find valid credit spread
        for short_contract in candidate_short_legs:
            short_strike = short_contract.strike
            
            # Find long leg (spread_width away)
            if option_type == 'call':
                # CALL credit spread: Short at lower strike, long at higher strike
                long_strike = short_strike + spread_width
            else:  # put
                # PUT credit spread: Short at higher strike, long at lower strike
                long_strike = short_strike - spread_width
            
            # Find long leg contract
            long_contract = next(
                (c for c in contracts if c.strike == long_strike),
                None
            )
            
            if not long_contract:
                continue
            
            # Validate both legs
            short_valid, short_reasons = self.validate_liquidity(short_contract)
            long_valid, long_reasons = self.validate_liquidity(long_contract)
            
            if not short_valid or not long_valid:
                log.debug(f"Invalid credit spread: short={short_valid}, long={long_valid}")
                continue
            
            # Calculate spread metrics
            # Credit spread: Receive premium from short leg, pay premium for long leg
            credit_received = short_contract.bid - long_contract.ask
            
            # Ensure we receive a credit (positive net credit)
            if credit_received <= 0:
                log.debug(f"Invalid credit spread: credit_received ${credit_received:.2f} <= 0")
                continue
            
            max_profit = credit_received  # Max profit = credit received
            max_loss = spread_width - credit_received  # Max loss = spread width - credit
            
            # Deterministic Rule: Short leg at R:R ≥ 1.5–2.5x
            if max_loss > 0:
                risk_reward_ratio = max_profit / max_loss
            else:
                risk_reward_ratio = 0.0
            
            # Reject if R:R not in range 1.5-2.5x
            if risk_reward_ratio < self.min_risk_reward_ratio or risk_reward_ratio > self.max_risk_reward_ratio:
                log.debug(f"Rejecting credit spread: R:R {risk_reward_ratio:.2f}x not in range [{self.min_risk_reward_ratio:.1f}x, {self.max_risk_reward_ratio:.1f}x]")
                continue
            
            if option_type == 'call':
                # CALL credit spread: Break-even = short_strike + credit_received
                break_even = short_strike + credit_received
            else:  # put
                # PUT credit spread: Break-even = short_strike - credit_received
                break_even = short_strike - credit_received
            
            spread = CreditSpread(
                symbol=short_contract.symbol,
                expiry=short_contract.expiry,
                option_type=option_type,
                short_strike=short_strike,
                long_strike=long_strike,
                short_contract=short_contract,
                long_contract=long_contract,
                credit_received=credit_received,
                max_profit=max_profit,
                max_loss=max_loss,
                break_even=break_even
            )
            
            credit_score = calculate_credit_score(short_contract, target_delta)
            log.info(f"Selected credit spread: {spread.symbol} {option_type} {spread.short_strike}/{spread.long_strike}")
            log.info(f"  Credit: ${credit_received:.2f}, Max Profit: ${max_profit:.2f}, Max Loss: ${max_loss:.2f}")
            log.info(f"  Short Leg Greeks: Gamma={short_contract.gamma:.4f}, Theta={short_contract.theta:.4f}, Vega={short_contract.vega:.4f}, IV={short_contract.implied_volatility:.2%}")
            log.info(f"  Optimization Score: {credit_score:.3f} (Delta:40%, Vega:30%, Gamma:20%, Theta:10%)")
            
            return spread
        
        log.warning(f"No valid credit spread found for {option_type} with delta {target_delta:.2f}")
        return None

