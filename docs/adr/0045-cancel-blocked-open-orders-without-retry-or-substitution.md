# Cancel blocked Open orders without retry or substitution

An order blocked at its single scheduled Open is cancelled immediately: buys leave cash, sells leave the position, and no substitute instrument or deferred retry is created. A later Rebalance starts from actual retained state and may create a new order under new evidence.
