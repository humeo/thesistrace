# Make the backend Alpha Compiler the diagnostic authority

The backend compiler alone decides Formula syntax, identifiers, types, arguments, lookback, and admission-budget validity and returns source-ranged structured Diagnostics. Browser feedback may call that authority, but Run admission recompiles and never trusts a frontend parser or earlier verdict.
