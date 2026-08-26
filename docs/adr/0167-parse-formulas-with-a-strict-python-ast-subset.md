# Parse Formulae with a strict Python AST subset

The compiler uses Python's expression parser only as transient syntax input and exhaustively translates an allowlisted arithmetic-and-Builtin subset into ThesisTrace's own Alpha Expression. Every other node is rejected, and Python output is never compiled, evaluated, executed, or persisted.
