---
status: accepted
---

# Apply board-specific A-share order-quantity rules

Strategy Backtest uses integer Execution Shares and rounds orders according to the instrument's A-share board: main-board and ChiNext buys and partial sells use 100-share lots, while STAR Market orders start at 200 shares and then use one-share increments. Complete liquidation sells the entire remaining position, and quantities below the applicable minimum produce no order so execution remains legally representable without persisting raw order details.
