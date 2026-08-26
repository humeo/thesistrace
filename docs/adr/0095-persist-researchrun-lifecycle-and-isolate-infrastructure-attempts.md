# Persist ResearchRun lifecycle and isolate infrastructure Attempts

A ResearchRun has one durable user-visible lifecycle and immutable input, while transient infrastructure retries create fenced Attempts beneath that identity. Idempotent admission, validated private recovery state, and terminal cleanup prevent retries from becoming duplicate Research or partial Results.
