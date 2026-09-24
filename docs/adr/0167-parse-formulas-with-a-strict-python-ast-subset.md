# Parse Alpha Formulae with a strict Python AST subset

The compiler uses Python's expression parser only as transient syntax input and exhaustively translates allowlisted Alpha syntax into ThesisTrace's own Alpha Expression. Every other node is rejected, and the parser output is never executed as Python or published as an authoritative AST. This restriction belongs to Alpha Formulae; Researcher-authored Strategy Programs use the separate isolated execution boundary accepted in [ADR-0250](0250-admit-strategy-programs-with-explicit-simulation-coordinates.md).
