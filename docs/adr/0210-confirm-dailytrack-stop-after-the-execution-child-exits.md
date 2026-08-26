# Confirm DailyTrack Stop after the execution child exits

Stop fences a running Tracking Advance immediately but reaches terminal `stopped` and releases its Data Generation only after the supervised child is confirmed exited. Stop without active execution is atomic, and lost ownership may extend recovery beyond the normal five-second budget rather than falsely reporting safety.
