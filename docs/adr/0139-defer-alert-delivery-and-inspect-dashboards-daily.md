---
status: accepted
---

# Defer alert delivery and inspect dashboards daily

The first Hosted Platform V2 release does not deliver alerts through email,
SMTP, PagerDuty, Slack, SMS, or another paging service. Grafana presents
threshold states and the three accepted health dashboards, but it does not send
notifications.

An operator connects through the private SSH-tunnel path at least once every
calendar day and inspects System Health, Data Health, and Quantitative Semantic
Health. The review includes the latest successful off-node backup, disk
pressure, PostgreSQL and Storage readiness, Temporal and Worker state, oldest
queued P1 and P3 work, Dataset Publication freshness and failures, semantic and
equivalence failures, and OpenTelemetry export loss.

This deliberately accepts a failure-detection delay of up to approximately 24
hours. ADR-0127 therefore treats eight hours as the recovery-execution target
after detection and records an approximately 32-hour worst-case end-to-end
interruption target instead of claiming recovery within eight hours of failure
occurrence.

Active delivery is reconsidered when daily inspection is no longer sustainable
or the platform adopts a user-facing availability objective. Adding delivery
later does not change the dashboard, metric, or health-domain boundaries.
