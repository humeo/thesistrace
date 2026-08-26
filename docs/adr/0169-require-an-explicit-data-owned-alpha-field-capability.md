# Require an explicit Data-owned Alpha Field Capability

A numeric Canonical Field becomes Alpha-authorable only when its Data-owned definition explicitly fixes point-in-time meaning, grain, unit, availability, missingness, and a Series reader. Compiler, Kernel, and frontend derive the same capability instead of maintaining physical-column or field allowlists.
