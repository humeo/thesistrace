# Keep MCP ingress protection outside Product quotas

MCP ingress applies fixed bounded request, response, rate, and concurrency
limits, while existing Core admission and lifecycle rules remain the only
Research and DailyTrack capacity authority. The single-installation product
does not add User quota, credit, billing, or Agent Campaign state, and ingress
limits never reinterpret or replace ResearchRun, Research Batch, or DailyTrack
admission.
