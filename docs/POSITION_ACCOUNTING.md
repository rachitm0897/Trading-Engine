# Position accounting

Portfolio and strategy-attributed positions use perpetual weighted-average cost accounting.

- A fill that increases an existing long or short position recalculates average cost from absolute quantities and execution prices.
- A fill that reduces a position leaves the remaining position's average cost unchanged.
- Closing a position resets average cost to zero.
- A fill that crosses through zero realizes P&L on the closed quantity and starts the reversed position at the crossing fill price.
- Long realized P&L is `(exit price - average cost) * closed quantity`; short realized P&L reverses that direction.
- Commissions are recorded separately in the immutable cash ledger. Position realized P&L is gross of commission so fees are not counted twice.
- Every execution is keyed by the broker execution ID. Duplicate callbacks return the existing fill before changing orders, ledgers, or positions.

`PortfolioPosition.realized_pnl` is the cumulative gross realized P&L for the portfolio/instrument position. Each `PositionLedgerEntry.realized_pnl` records the amount realized by that individual fill.
