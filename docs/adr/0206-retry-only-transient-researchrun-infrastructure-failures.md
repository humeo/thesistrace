# Retry only transient ResearchRun infrastructure failures

Automatic ResearchRun retry is bounded and limited to transient infrastructure unavailability or unexpected Worker loss, resuming only a fully validated private Checkpoint. Capacity, integrity, data, numeric, domain, contract, or publication-budget failures are terminal and never trigger replanning, fallback, or restart from unchecked state.
