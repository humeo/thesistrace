# Require explicit DailyTrack Refresh

A Dataset Head change never admits Tracking work by itself. An active,
lagging, idle DailyTrack advances only after one explicit, idempotent
DailyTrack Refresh queues one Tracking Advance. The Tracking Worker retains
durable asynchronous execution and bounded retries inside that accepted
Advance, while every later Advance requires another Refresh.
