# Exit Reasons (Reference)

Exit reasons are emitted by the monitoring/exit logic and appear in alerts and reports.

## Common exit categories

- **Stop loss**: price hit the current stop
- **Trailing stop**: price retraced from peak beyond trailing distance
- **Breakeven protection**: stop moved to (or above) entry + offset
- **Rapid exits**: early exits for weak momentum / adverse move
- **Portfolio health exits**: portfolio-level conditions triggered defensive exits
- **End-of-day**: forced closure at the configured time

## Source of truth

Search in `modules/` for the exit reason constants/labels used by alerts and trade history.


