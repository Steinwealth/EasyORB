"""
Daily Run Tracker
=================

Provides persistence for daily ORB capture and SO signal collection/execution
markers so Cloud Run instance restarts do not repeat critical tasks or alerts.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9 fallback
    from pytz import timezone as ZoneInfo  # type: ignore

from .gcs_persistence import get_gcs_persistence

log = logging.getLogger("daily_run_tracker")

PT_TZ = ZoneInfo("America/Los_Angeles")
_MARKER_PREFIX = "daily_markers"


def _current_trading_date() -> date:
    """Return the current trading date in Pacific Time."""
    return datetime.now(PT_TZ).date()


class DailyRunTracker:
    """Persist daily run markers for ORB capture and SO processing."""

    def __init__(self) -> None:
        self._gcs = get_gcs_persistence()
        base_dir = os.getenv("DAILY_MARKER_DIR", "/tmp/easy_etrade_markers")
        self._base_path = Path(base_dir)
        self._base_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_today_state(self) -> Dict[str, Any]:
        """Load today's marker information."""
        date_key = self._date_key()
        marker = self._load_marker(date_key)
        return marker or {}

    def record_orb_capture(
        self,
        orb_snapshot: Dict[str, Dict[str, Any]],
        captured_count: int,
        total_symbols: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist ORB capture snapshot and metadata for the trading day."""
        if not orb_snapshot:
            return

        date_key = self._date_key()
        marker = self._load_marker(date_key) or {}

        marker["orb"] = {
            "captured": True,
            "captured_at": datetime.now(PT_TZ).isoformat(),
            "captured_epoch": datetime.now(PT_TZ).timestamp(),
            "captured_count": captured_count,
            "total_symbols": total_symbols,
            "snapshot": orb_snapshot,
            "metadata": metadata or {},
        }

        self._save_marker(date_key, marker)
        log.info(
            "📝 ORB marker recorded for %s (%s/%s symbols)",
            date_key,
            captured_count,
            total_symbols,
        )

    def record_signal_collection(
        self,
        signals: List[Dict[str, Any]],
        total_scanned: int,
        mode: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist SO signal collection summary for the trading day."""
        date_key = self._date_key()
        marker = self._load_marker(date_key) or {}

        sanitized_signals = self._sanitize_signals(signals)
        now_pt = datetime.now(PT_TZ)

        signals_entry = marker.get("signals", {})
        signals_entry.update(
            {
                "collected": True,
                "collection_time": now_pt.isoformat(),
                "collection_epoch": now_pt.timestamp(),
                "signal_count": len(sanitized_signals),
                "total_scanned": total_scanned,
                "mode": mode,
                "signals": sanitized_signals,
                "metadata": metadata or {},
            }
        )
        marker["signals"] = signals_entry

        self._save_marker(date_key, marker)
        log.info(
            "📝 Signal collection marker recorded for %s (%s signals)",
            date_key,
            len(sanitized_signals),
        )

    def record_signal_execution(
        self,
        executed_signals: List[Dict[str, Any]],
        rejected_signals: List[Dict[str, Any]],
        mode: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist SO execution results for the trading day."""
        date_key = self._date_key()
        marker = self._load_marker(date_key) or {}

        sanitized_executed = self._sanitize_signals(executed_signals)
        sanitized_rejected = self._sanitize_signals(rejected_signals)
        now_pt = datetime.now(PT_TZ)

        signals_entry = marker.get("signals", {})
        signals_entry.update(
            {
                "execution_completed": True,
                "execution_time": now_pt.isoformat(),
                "execution_epoch": now_pt.timestamp(),
                "executed_count": len(sanitized_executed),
                "rejected_count": len(sanitized_rejected),
                "executed_signals": sanitized_executed,
                "rejected_signals": sanitized_rejected,
                "mode": mode,
                "metadata": metadata or {},
            }
        )
        marker["signals"] = signals_entry

        self._save_marker(date_key, marker)
        log.info(
            "📝 Signal execution marker recorded for %s (executed=%s, rejected=%s)",
            date_key,
            len(sanitized_executed),
            len(sanitized_rejected),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _date_key(self, trading_date: Optional[date] = None) -> str:
        trading_date = trading_date or _current_trading_date()
        return trading_date.isoformat()

    def _marker_path(self, date_key: str) -> Path:
        return self._base_path / f"{date_key}.json"

    def _load_marker(self, date_key: str) -> Optional[Dict[str, Any]]:
        path = self._marker_path(date_key)
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception as exc:  # pragma: no cover - corrupted file edge case
                log.warning("⚠️ Failed to read local marker %s: %s", path, exc)

        gcs_content = self._gcs.read_string(f"{_MARKER_PREFIX}/{date_key}.json")
        if gcs_content:
            try:
                data = json.loads(gcs_content)
                # Cache locally for faster subsequent reads
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2, sort_keys=True)
                return data
            except Exception as exc:  # pragma: no cover - corrupted GCS content
                log.warning("⚠️ Failed to parse GCS marker %s: %s", date_key, exc)

        return None

    def _save_marker(self, date_key: str, marker: Dict[str, Any]) -> None:
        path = self._marker_path(date_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(marker, handle, indent=2, sort_keys=True)

        if self._gcs.enabled:
            self._gcs.upload_string(
                f"{_MARKER_PREFIX}/{date_key}.json",
                json.dumps(marker, sort_keys=True),
            )

        # Also sync a Priority Optimizer-style daily signals file (and enforce retention)
        # so we always have the SO signal list for Red Day analysis and P&L studies.
        try:
            self._sync_priority_optimizer_signals(date_key, marker)
        except Exception as exc:  # pragma: no cover - defensive logging only
            log.warning("⚠️ Failed to sync Priority Optimizer signals for %s: %s", date_key, exc)

    def _sync_priority_optimizer_signals(self, date_key: str, marker: Dict[str, Any]) -> None:
        """
        Create / update a Priority Optimizer daily signals file in GCS and
        enforce a rolling retention window (last 50 days).

        This ensures that:
        - Every SO signal collection (even on Red Days where execution is skipped)
          is persisted in a consistent format under:
              priority_optimizer/daily_signals/YYYY-MM-DD_signals.json
        - Only the last 50 daily lists are kept to avoid unbounded growth.
        """
        if not self._gcs.enabled:
            return

        signals_entry = marker.get("signals") or {}
        raw_signals = signals_entry.get("signals") or []
        if not raw_signals:
            # Nothing to persist for this day
            return

        # Sanitize signals to a compact, stable structure (reuses existing helper)
        sanitized_signals = self._sanitize_signals(raw_signals)

        payload: Dict[str, Any] = {
            "date": date_key,
            "mode": signals_entry.get("mode"),
            "total_scanned": signals_entry.get("total_scanned", 0),
            "signal_count": len(sanitized_signals),
            "signals": sanitized_signals,
            "metadata": signals_entry.get("metadata") or {},
        }

        gcs_path = f"priority_optimizer/daily_signals/{date_key}_signals.json"
        ok = self._gcs.upload_string(gcs_path, json.dumps(payload, sort_keys=True))
        if ok:
            log.info(
                "☁️ Priority Optimizer signal list saved for %s (%s signals) → %s",
                date_key,
                len(sanitized_signals),
                gcs_path,
            )
        else:
            log.warning(
                "⚠️ Failed to upload Priority Optimizer signal list for %s to %s",
                date_key,
                gcs_path,
            )
            return

        # Retention policy: keep only the last 50 daily signal lists
        prefix = "priority_optimizer/daily_signals/"
        all_paths = self._gcs.list_files(prefix=prefix)
        if not all_paths or len(all_paths) <= 50:
            return

        # Sort by path; files are named YYYY-MM-DD_signals.json so lexical order == chronological
        sorted_paths = sorted(p for p in all_paths if p.startswith(prefix))
        keep = set(sorted_paths[-50:])
        to_delete = [p for p in sorted_paths if p not in keep]

        deleted = 0
        for old_path in to_delete:
            if self._gcs.delete_file(old_path):
                deleted += 1

        if deleted:
            log.info(
                "🧹 Priority Optimizer retention: deleted %s old daily signal files (kept last 50)",
                deleted,
            )

    @staticmethod
    def _sanitize_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sanitized: List[Dict[str, Any]] = []
        for signal in signals or []:
            if not isinstance(signal, dict):
                continue
            sanitized.append(
                {
                    "symbol": signal.get("symbol"),
                    "original_symbol": signal.get("original_symbol"),
                    "signal_type": signal.get("signal_type"),
                    "side": signal.get("side"),
                    "price": signal.get("price"),
                    "confidence": signal.get("confidence"),
                    "position_size_pct": signal.get("position_size_pct"),
                    "reasoning": signal.get("reasoning"),
                    "inverse_symbol": signal.get("inverse_symbol"),
                    # Priority Ranking Formula v2.1 factors (Rev 00106, Nov 6, 2025)
                    "priority_score": signal.get("priority_score"),
                    "rank": signal.get("rank"),
                    "vwap_distance_pct": signal.get("vwap_distance_pct"),
                    "rs_vs_spy": signal.get("rs_vs_spy"),
                    "orb_volume_ratio": signal.get("orb_volume_ratio"),
                    "orb_range_pct": signal.get("orb_range_pct"),
                    "rsi": signal.get("rsi"),
                }
            )
        return sanitized


_tracker_instance: Optional[DailyRunTracker] = None


def get_daily_run_tracker() -> DailyRunTracker:
    """Return singleton instance of DailyRunTracker."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = DailyRunTracker()
    return _tracker_instance
