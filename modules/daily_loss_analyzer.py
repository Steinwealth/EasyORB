#!/usr/bin/env python3
"""
Daily Loss Analyzer - Rev 00044
================================

Automatically analyzes losing days to identify root causes and recommend improvements.

When daily P&L < -1%, this system:
1. Analyzes all losing trades
2. Categorizes why they lost money
3. Identifies if stops were too tight or signals were bad
4. Recommends specific improvements

Key Analysis Categories:
- Entry bar stop-outs (stopped in entry bar - too tight)
- No momentum trades (never moved, bad signal)
- Immediate reversals (wrong direction)
- Whipsaw trades (moved up then back down)
- Good trade, early exit (stopped out but reached good peak later)
"""

import logging
import statistics
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

log = logging.getLogger("daily_loss_analyzer")

# ============================================================================
# ENUMS
# ============================================================================

class LossCategory(Enum):
    """Categories of trade losses"""
    ENTRY_BAR_STOPOUT = "entry_bar_stopout"  # Stopped out in entry bar
    NO_MOMENTUM = "no_momentum"  # Never moved up (bad signal)
    IMMEDIATE_REVERSAL = "immediate_reversal"  # Reversed immediately
    WHIPSAW = "whipsaw"  # Moved up then reversed
    EARLY_EXIT = "early_exit"  # Good peak reached but exited too early
    GOOD_EXIT = "good_exit"  # Stopped out correctly (minimized loss)

class ImprovementType(Enum):
    """Types of improvements needed"""
    WIDER_STOP = "wider_stop"  # Need wider stop loss
    SKIP_SIGNAL = "skip_signal"  # Should not have entered
    TIGHTER_ENTRY = "tighter_entry"  # Need better entry confirmation
    BETTER_EXIT = "better_exit"  # Exit logic needs improvement
    NO_CHANGE = "no_change"  # System working correctly

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class TradeAnalysis:
    """Analysis of a single losing trade"""
    symbol: str
    entry_price: float
    exit_price: float
    peak_price: float
    pnl_pct: float
    peak_pnl_pct: float
    holding_minutes: int
    exit_bar: int  # Which bar exited in (1 = entry bar)
    entry_bar_vol: float
    orb_range_pct: float
    loss_category: LossCategory
    improvement_needed: ImprovementType
    analysis: str
    potential_saved: float  # % that could have been saved

@dataclass
class DayAnalysis:
    """Analysis of entire losing day"""
    date: str
    total_trades: int
    losing_trades: int
    total_pnl: float
    avg_pnl: float
    trade_analyses: List[TradeAnalysis]
    loss_categories: Dict[LossCategory, int]
    improvements_needed: Dict[ImprovementType, int]
    total_potential_saved: float
    recommendations: List[str]

# ============================================================================
# DAILY LOSS ANALYZER
# ============================================================================

class DailyLossAnalyzer:
    """Analyzes losing days to identify root causes and improvements"""
    
    def __init__(self):
        self.min_loss_threshold = -1.0  # Analyze days with <-1% P&L
        log.info("Daily Loss Analyzer initialized (Rev 00044)")
    
    def analyze_trade(self, trade_data: Dict[str, Any]) -> TradeAnalysis:
        """
        Analyze a single losing trade to categorize the loss and recommend improvement
        
        Args:
            trade_data: {
                'symbol': str,
                'entry_price': float,
                'exit_price': float,
                'peak_price': float,
                'pnl_pct': float,
                'holding_minutes': int,
                'exit_bar': int,
                'entry_bar_high': float,
                'entry_bar_low': float,
                'orb_high': float,
                'orb_low': float
            }
        
        Returns:
            TradeAnalysis with categorization and recommendations
        """
        symbol = trade_data['symbol']
        entry_price = trade_data['entry_price']
        exit_price = trade_data['exit_price']
        peak_price = trade_data['peak_price']
        pnl_pct = trade_data['pnl_pct']
        holding_minutes = trade_data.get('holding_minutes', 0)
        exit_bar = trade_data.get('exit_bar', 1)
        
        # Calculate metrics
        peak_pnl_pct = (peak_price - entry_price) / entry_price * 100
        entry_bar_high = trade_data.get('entry_bar_high', entry_price * 1.02)
        entry_bar_low = trade_data.get('entry_bar_low', entry_price * 0.98)
        entry_bar_vol = ((entry_bar_high - entry_bar_low) / entry_bar_low) * 100
        
        orb_high = trade_data.get('orb_high', 0)
        orb_low = trade_data.get('orb_low', 0)
        orb_range_pct = ((orb_high - orb_low) / orb_low) * 100 if orb_low > 0 else 0
        
        # Categorize the loss
        loss_category = self._categorize_loss(
            pnl_pct, peak_pnl_pct, holding_minutes, exit_bar, entry_bar_vol
        )
        
        # Determine improvement needed
        improvement_needed, analysis, potential_saved = self._determine_improvement(
            loss_category, pnl_pct, peak_pnl_pct, entry_bar_vol, orb_range_pct
        )
        
        return TradeAnalysis(
            symbol=symbol,
            entry_price=entry_price,
            exit_price=exit_price,
            peak_price=peak_price,
            pnl_pct=pnl_pct,
            peak_pnl_pct=peak_pnl_pct,
            holding_minutes=holding_minutes,
            exit_bar=exit_bar,
            entry_bar_vol=entry_bar_vol,
            orb_range_pct=orb_range_pct,
            loss_category=loss_category,
            improvement_needed=improvement_needed,
            analysis=analysis,
            potential_saved=potential_saved
        )
    
    def _categorize_loss(self, pnl_pct: float, peak_pnl_pct: float, 
                        holding_minutes: int, exit_bar: int, entry_bar_vol: float) -> LossCategory:
        """Categorize why the trade lost money"""
        
        # Category 1: Stopped out in entry bar
        if exit_bar == 1 or holding_minutes < 15:
            return LossCategory.ENTRY_BAR_STOPOUT
        
        # Category 2: Never showed momentum (peak < +0.5%)
        if peak_pnl_pct < 0.5:
            return LossCategory.NO_MOMENTUM
        
        # Category 3: Immediate reversal (< 30 min, never profitable)
        if holding_minutes < 30 and peak_pnl_pct < 0.3:
            return LossCategory.IMMEDIATE_REVERSAL
        
        # Category 4: Whipsaw (good peak but gave it all back)
        if peak_pnl_pct > 2.0 and pnl_pct < -0.5:
            return LossCategory.WHIPSAW
        
        # Category 5: Early exit (decent peak reached but stopped out)
        if peak_pnl_pct > 1.0 and pnl_pct < 0:
            return LossCategory.EARLY_EXIT
        
        # Category 6: Good exit (minimized loss correctly)
        return LossCategory.GOOD_EXIT
    
    def _determine_improvement(self, category: LossCategory, pnl_pct: float, 
                               peak_pnl_pct: float, entry_bar_vol: float, 
                               orb_range_pct: float) -> tuple:
        """Determine what improvement is needed"""
        
        if category == LossCategory.ENTRY_BAR_STOPOUT:
            # Entry bar stop-out
            if entry_bar_vol > 6.0:
                # Very high volatility - need MUCH wider stop
                improvement = ImprovementType.WIDER_STOP
                analysis = f"Entry bar volatility {entry_bar_vol:.2f}% - need 7% stop (currently stopped in entry bar)"
                potential_saved = min(abs(pnl_pct) + peak_pnl_pct, 5.0)  # Could have saved up to 5%
            elif entry_bar_vol > 3.0:
                # High volatility - need wider stop
                improvement = ImprovementType.WIDER_STOP
                analysis = f"Entry bar volatility {entry_bar_vol:.2f}% - need 4% stop"
                potential_saved = min(abs(pnl_pct) + peak_pnl_pct, 3.0)
            else:
                # Moderate volatility - 3% stop should work
                improvement = ImprovementType.WIDER_STOP
                analysis = f"Entry bar volatility {entry_bar_vol:.2f}% - need 3% stop"
                potential_saved = min(abs(pnl_pct) + peak_pnl_pct, 2.0)
        
        elif category == LossCategory.NO_MOMENTUM:
            # Never moved - bad signal
            if peak_pnl_pct < 0.3:
                improvement = ImprovementType.SKIP_SIGNAL
                analysis = f"Peak only {peak_pnl_pct:+.2f}% - bad signal, should have skipped"
                potential_saved = abs(pnl_pct)  # Full loss could have been avoided
            else:
                improvement = ImprovementType.TIGHTER_ENTRY
                analysis = f"Peak {peak_pnl_pct:+.2f}% - need better entry confirmation"
                potential_saved = abs(pnl_pct) * 0.7  # 70% could have been saved
        
        elif category == LossCategory.IMMEDIATE_REVERSAL:
            # Immediate reversal - wrong direction
            improvement = ImprovementType.SKIP_SIGNAL
            analysis = f"Reversed immediately (peak {peak_pnl_pct:+.2f}%) - bad signal"
            potential_saved = abs(pnl_pct) * 0.8  # 80% could have been saved with rapid exit
        
        elif category == LossCategory.WHIPSAW:
            # Whipsaw - good move but gave back too much
            improvement = ImprovementType.BETTER_EXIT
            analysis = f"Peaked at {peak_pnl_pct:+.2f}% but gave back to {pnl_pct:+.2f}% - exit too late"
            potential_saved = peak_pnl_pct - pnl_pct  # Difference between peak and exit
        
        elif category == LossCategory.EARLY_EXIT:
            # Early exit - stopped out too soon
            if orb_range_pct < 1.5:
                # Low volatility day - stops were appropriate
                improvement = ImprovementType.NO_CHANGE
                analysis = f"Low volatility day (ORB {orb_range_pct:.2f}%) - stop was correct"
                potential_saved = 0.0
            else:
                # Could have held longer
                improvement = ImprovementType.WIDER_STOP
                analysis = f"Peaked at {peak_pnl_pct:+.2f}% - stop too tight for ORB {orb_range_pct:.2f}%"
                potential_saved = peak_pnl_pct * 0.5  # Could have captured 50% of peak
        
        else:
            # Good exit - system working correctly
            improvement = ImprovementType.NO_CHANGE
            analysis = f"Loss minimized correctly ({pnl_pct:+.2f}%, peak {peak_pnl_pct:+.2f}%)"
            potential_saved = 0.0
        
        return improvement, analysis, potential_saved
    
    def analyze_losing_day(self, day_trades: List[Dict[str, Any]], date: str) -> DayAnalysis:
        """
        Analyze entire losing day to identify patterns and recommend improvements
        
        Args:
            day_trades: List of trade data dictionaries
            date: Date string (YYYY-MM-DD)
        
        Returns:
            DayAnalysis with comprehensive analysis and recommendations
        """
        # Analyze each trade
        trade_analyses = []
        for trade in day_trades:
            if trade.get('pnl_pct', 0) <= 0:  # Only analyze losing trades
                analysis = self.analyze_trade(trade)
                trade_analyses.append(analysis)
        
        # Calculate day metrics
        total_trades = len(day_trades)
        losing_trades = len(trade_analyses)
        total_pnl = sum([t.get('pnl_pct', 0) for t in day_trades])
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
        
        # Categorize losses
        loss_categories = {}
        improvements_needed = {}
        total_potential_saved = 0.0
        
        for analysis in trade_analyses:
            # Count loss categories
            if analysis.loss_category not in loss_categories:
                loss_categories[analysis.loss_category] = 0
            loss_categories[analysis.loss_category] += 1
            
            # Count improvement types
            if analysis.improvement_needed not in improvements_needed:
                improvements_needed[analysis.improvement_needed] = 0
            improvements_needed[analysis.improvement_needed] += 1
            
            # Sum potential savings
            total_potential_saved += analysis.potential_saved
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            loss_categories, improvements_needed, total_potential_saved, total_pnl
        )
        
        return DayAnalysis(
            date=date,
            total_trades=total_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            avg_pnl=avg_pnl,
            trade_analyses=trade_analyses,
            loss_categories=loss_categories,
            improvements_needed=improvements_needed,
            total_potential_saved=total_potential_saved,
            recommendations=recommendations
        )
    
    def _generate_recommendations(self, loss_categories: Dict[LossCategory, int],
                                 improvements_needed: Dict[ImprovementType, int],
                                 total_potential_saved: float,
                                 total_pnl: float) -> List[str]:
        """Generate actionable recommendations based on analysis"""
        recommendations = []
        
        total_losses = sum(loss_categories.values())
        
        # Recommendation 1: Entry bar stop-outs
        entry_bar_stops = loss_categories.get(LossCategory.ENTRY_BAR_STOPOUT, 0)
        if entry_bar_stops > total_losses * 0.4:  # >40% stopped in entry bar
            pct = (entry_bar_stops / total_losses) * 100
            recommendations.append(
                f"🚨 CRITICAL: {entry_bar_stops}/{total_losses} trades ({pct:.0f}%) stopped out in entry bar. "
                f"Entry bar protection (Rev 00043) should prevent this. "
                f"Potential saved: +{total_potential_saved * 0.5:.2f}%"
            )
        
        # Recommendation 2: No momentum trades
        no_momentum = loss_categories.get(LossCategory.NO_MOMENTUM, 0)
        if no_momentum > total_losses * 0.3:  # >30% had no momentum
            pct = (no_momentum / total_losses) * 100
            recommendations.append(
                f"⚠️ HIGH: {no_momentum}/{total_losses} trades ({pct:.0f}%) showed no momentum (peak < +0.5%). "
                f"Rapid exit system (Rev 00044) should exit these at 15 min. "
                f"Potential saved: +{total_potential_saved * 0.3:.2f}%"
            )
        
        # Recommendation 3: Immediate reversals
        reversals = loss_categories.get(LossCategory.IMMEDIATE_REVERSAL, 0)
        if reversals > total_losses * 0.2:  # >20% reversed immediately
            pct = (reversals / total_losses) * 100
            recommendations.append(
                f"⚠️ MEDIUM: {reversals}/{total_losses} trades ({pct:.0f}%) reversed immediately. "
                f"Need stricter entry confirmation (close strong, momentum > +0.2%). "
                f"Potential saved: +{total_potential_saved * 0.2:.2f}%"
            )
        
        # Recommendation 4: Skip signals
        should_skip = improvements_needed.get(ImprovementType.SKIP_SIGNAL, 0)
        if should_skip > total_losses * 0.4:  # >40% should have been skipped
            pct = (should_skip / total_losses) * 100
            recommendations.append(
                f"🚫 CRITICAL: {should_skip}/{total_losses} trades ({pct:.0f}%) were bad signals. "
                f"Consider: Skip days with avg ORB < 1.5% OR avg peak < 1.5%. "
                f"Potential saved: +{abs(total_pnl) * 0.6:.2f}%"
            )
        
        # Recommendation 5: Wider stops needed
        wider_stops = improvements_needed.get(ImprovementType.WIDER_STOP, 0)
        if wider_stops > total_losses * 0.3:  # >30% need wider stops
            pct = (wider_stops / total_losses) * 100
            recommendations.append(
                f"📊 MEDIUM: {wider_stops}/{total_losses} trades ({pct:.0f}%) need wider stops. "
                f"Entry bar protection (Rev 00043) addresses this. "
                f"Potential saved: +{total_potential_saved * 0.25:.2f}%"
            )
        
        # Recommendation 6: Better exits
        better_exits = improvements_needed.get(ImprovementType.BETTER_EXIT, 0)
        if better_exits > 0:
            pct = (better_exits / total_losses) * 100
            recommendations.append(
                f"📈 LOW: {better_exits}/{total_losses} trades ({pct:.0f}%) exited too late (whipsaw). "
                f"Consider: Tighten trailing after +5% move. "
                f"Potential saved: +{total_potential_saved * 0.15:.2f}%"
            )
        
        # Overall summary
        if total_potential_saved > abs(total_pnl) * 0.5:
            recommendations.insert(0, 
                f"💡 OVERALL: Could have saved {total_potential_saved:.2f}% of {abs(total_pnl):.2f}% loss "
                f"({total_potential_saved / abs(total_pnl) * 100:.0f}% of losses preventable!)"
            )
        
        return recommendations
    
    def generate_daily_report(self, day_analysis: DayAnalysis) -> str:
        """Generate formatted daily loss analysis report"""
        
        report = f"""
{'='*120}
📊 DAILY LOSS ANALYSIS - {day_analysis.date}
{'='*120}

📈 PERFORMANCE SUMMARY:
  Total Trades: {day_analysis.total_trades}
  Losing Trades: {day_analysis.losing_trades} ({day_analysis.losing_trades/day_analysis.total_trades*100:.0f}%)
  Total P&L: {day_analysis.total_pnl:+.2f}%
  Average P&L: {day_analysis.avg_pnl:+.2f}%
  Potential Saved: {day_analysis.total_potential_saved:+.2f}%

🔍 LOSS CATEGORIZATION:
"""
        
        # Sort categories by count
        sorted_categories = sorted(day_analysis.loss_categories.items(), key=lambda x: x[1], reverse=True)
        for category, count in sorted_categories:
            pct = (count / day_analysis.losing_trades) * 100 if day_analysis.losing_trades > 0 else 0
            report += f"  {category.value}: {count} trades ({pct:.0f}%)\n"
        
        report += f"\n🔧 IMPROVEMENTS NEEDED:\n"
        sorted_improvements = sorted(day_analysis.improvements_needed.items(), key=lambda x: x[1], reverse=True)
        for improvement, count in sorted_improvements:
            pct = (count / day_analysis.losing_trades) * 100 if day_analysis.losing_trades > 0 else 0
            report += f"  {improvement.value}: {count} trades ({pct:.0f}%)\n"
        
        report += f"\n💡 RECOMMENDATIONS:\n"
        for i, rec in enumerate(day_analysis.recommendations, 1):
            report += f"  {i}. {rec}\n"
        
        report += f"\n📊 TOP 5 WORST TRADES (What went wrong):\n"
        worst_trades = sorted(day_analysis.trade_analyses, key=lambda x: x.pnl_pct)[:5]
        for trade in worst_trades:
            report += f"\n  {trade.symbol}: {trade.pnl_pct:+.2f}% (peak: {trade.peak_pnl_pct:+.2f}%)\n"
            report += f"    Category: {trade.loss_category.value}\n"
            report += f"    Improvement: {trade.improvement_needed.value}\n"
            report += f"    Analysis: {trade.analysis}\n"
            report += f"    Could save: {trade.potential_saved:+.2f}%\n"
        
        report += f"\n{'='*120}\n"
        report += f"✅ ANALYSIS COMPLETE\n"
        report += f"{'='*120}\n"
        
        return report
    
    async def analyze_if_losing_day(self, daily_pnl: float, trades: List[Dict[str, Any]], 
                                   date: str, alert_manager=None) -> Optional[DayAnalysis]:
        """
        Analyze day if it's a losing day (<-1%) and send alert
        
        Args:
            daily_pnl: Total daily P&L percentage
            trades: List of trade data
            date: Date string
            alert_manager: Alert manager for sending analysis
        
        Returns:
            DayAnalysis if day was analyzed, None if not a losing day
        """
        if daily_pnl >= self.min_loss_threshold:
            # Not a losing day - skip analysis
            return None
        
        log.warning(f"🚨 LOSING DAY DETECTED: {date} ({daily_pnl:+.2f}%)")
        log.warning(f"🔍 Analyzing {len(trades)} trades to identify improvements...")
        
        # Perform analysis
        day_analysis = self.analyze_losing_day(trades, date)
        
        # Generate report
        report = self.generate_daily_report(day_analysis)
        
        # Log report
        log.warning(report)
        
        # Send Telegram alert with analysis
        if alert_manager:
            try:
                # Create compact alert version
                top_categories = sorted(day_analysis.loss_categories.items(), key=lambda x: x[1], reverse=True)[:3]
                category_text = '\n'.join([
                    f"  • {cat.value}: {count} trades ({count/day_analysis.losing_trades*100:.0f}%)"
                    for cat, count in top_categories
                ])
                
                top_recs = day_analysis.recommendations[:3]  # Top 3 recommendations
                rec_text = '\n'.join([f"  {i}. {rec}" for i, rec in enumerate(top_recs, 1)])
                
                await alert_manager.send_telegram_message(
                    f"🚨 <b>LOSING DAY ANALYSIS</b>\n\n"
                    f"📅 Date: {date}\n"
                    f"📊 Total P&L: {day_analysis.total_pnl:+.2f}%\n"
                    f"📉 Losing Trades: {day_analysis.losing_trades}/{day_analysis.total_trades}\n\n"
                    f"🔍 <b>Top Loss Categories:</b>\n{category_text}\n\n"
                    f"💰 <b>Potential Saved:</b> {day_analysis.total_potential_saved:+.2f}%\n\n"
                    f"💡 <b>Top Recommendations:</b>\n{rec_text}\n\n"
                    f"<i>Full analysis logged for review</i>",
                    level=None
                )
                
                log.info(f"📱 Daily loss analysis alert sent")
            except Exception as e:
                log.error(f"Failed to send daily loss analysis alert: {e}")
        
        return day_analysis

# ============================================================================
# FACTORY FUNCTION
# ============================================================================

_daily_loss_analyzer_instance = None

def get_daily_loss_analyzer() -> DailyLossAnalyzer:
    """Get singleton Daily Loss Analyzer instance"""
    global _daily_loss_analyzer_instance
    if _daily_loss_analyzer_instance is None:
        _daily_loss_analyzer_instance = DailyLossAnalyzer()
    return _daily_loss_analyzer_instance

