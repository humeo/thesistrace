# Immutable financial candidate fixture

Generated using production financial_candidate.py from commit de55453, with the existing financial candidate test inputs plus a quarterly cash seed. The original module validated it before capture. Contains synthetic source records, same-observation conflicting values and the former annual-only cashflow seed. No credentials or real user data.

Candidate: `afd76a941766d3471ec95a22383a9ce9ce4e10ec558a530b3e2e0c12eacf9917`. The current projector must not regenerate these preserved facts during retention validation. New candidates still use the current projection rules.

`generation-de55453.zip` was generated and validated with the full production source tree from de55453. Its complete empty source receipts form a financial family declaring only the original six financial fields; the small market fixture declares close. Generation: `611f1a80a541819b29b57112eed4a2a9d2cef501d2388904e103ee3636f2ef0e`. This fixture tests retained Generation/GC, while the separate nonempty candidate exercises changed seed and conflict decisions.
