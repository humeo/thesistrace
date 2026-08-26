# Make ResearchRun cancellation cooperative and confirmed

Cancelling running Research fences publication immediately but reaches terminal `cancelled` and releases its Data Generation only after the supervised child is confirmed exited. A lost supervisor may extend that confirmation beyond the normal five-second budget because safety takes priority over an early terminal state.
