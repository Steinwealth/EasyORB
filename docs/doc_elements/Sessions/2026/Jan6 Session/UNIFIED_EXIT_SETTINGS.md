# Unified Exit Settings (Reference)

Exit behavior is configured through env-style settings in `configs/` and implemented in the monitoring modules.

## What to edit

Look in `configs/` for the exit-related env files (risk management / trading parameters).

## What it controls

- breakeven thresholds + timing
- trailing activation + distances
- rapid-exit thresholds
- portfolio health check thresholds + cadence
- end-of-day close time

## Source of truth

The code is authoritative; this file exists to provide a stable reference point for “where to look”.


