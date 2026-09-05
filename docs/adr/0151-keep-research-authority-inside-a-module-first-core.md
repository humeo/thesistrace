# Keep research authority inside a module-first Core

Core domain modules own Research lifecycle and PostgreSQL Product State while a shared Research Kernel owns deterministic calculation and RustFS stores immutable results. Separate Auth and Agent services supply identity and conversation without taking over Research authority, accepting explicit service boundaries while avoiding a distributed research workflow engine.
