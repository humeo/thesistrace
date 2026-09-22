# Use the daily first-traded price as the Open coordinate

The Open coordinate is the valid daily bar's first traded price, which may occur after an opening suspension and is not fixed to 09:30. Raw Open supplies the reference for execution and quoted-price constraints, while the corresponding Adjusted Open supplies research valuation and Labels; a slippage-adjusted Simulated Fill does not redefine either observed coordinate. A confirmed full-session suspension has no traded Open.
