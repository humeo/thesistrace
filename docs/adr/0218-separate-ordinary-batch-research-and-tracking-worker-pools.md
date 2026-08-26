# Separate ordinary Research, Batch Research, and Tracking Worker pools

One Production Image exposes mutually exclusive single-slot ordinary Research, Batch Research, and Tracking roles, each claiming only its own durable work and scaling independently. Supervisors alone own claims, fences, Data Generation protection, recovery, and publication; children share one Research Kernel and never fall back across roles or publish Product State.
