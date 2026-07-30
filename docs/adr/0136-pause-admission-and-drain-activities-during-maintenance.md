---
status: accepted
---

# Pause admission and drain Activities during maintenance

Hosted Platform V2 pauses public admission, Temporal Schedules, and execution-outbox dispatch before maintenance, then gives running Activities a bounded drain period. Incomplete Activities remain nonterminal for safe Temporal redelivery after compatible services return, preventing maintenance from changing User intent or crossing an uncontrolled migration boundary.
