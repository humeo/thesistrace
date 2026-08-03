---
status: superseded by ADR-0151
---

# Protect the single node with three disk-pressure levels

The single-node deployment uses three configurable disk-pressure levels, initially warning at 70% usage, rejecting new Personal Workspace payload-producing work at 80%, and rejecting all payload growth at 90%, while reads and storage-reducing operations remain available. Threshold crossings do not terminate running work, and a final atomic publication check prevents disk exhaustion from exposing partial results.
