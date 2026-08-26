# Model historical industry membership as half-open intervals

Each SW2021 membership uses a left-closed, right-open effective-date interval, with at most one path per instrument and classification version on any date. Overlaps fail validation and gaps remain missing rather than extending neighbors, creating `UNKNOWN`, or backfilling the current classification.
