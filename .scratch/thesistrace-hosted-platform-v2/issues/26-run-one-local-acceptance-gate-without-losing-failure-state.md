# 26 — Run One Local Acceptance Gate without Losing Failure State

**Parent:** 24 — Deliver Hosted Local Acceptance on 2C4G.

**What to build:** Refactor the local acceptance entry point into explicit,
bounded gates so an agent can reproduce one failed boundary without paying for a
new reset, cold Compose start, or unrelated five-minute workflow wait.

**Blocked by:** 25 — Stabilize the Current Hosted Local Acceptance Baseline.

**Status:** ready-for-agent

- [ ] The runner exposes and documents a canonical ordered gate list; `--phase NAME` runs exactly one gate, while `--from NAME` and `--until NAME` select one contiguous range in that order.
- [ ] A selected gate refuses to run with an actionable prerequisite error unless its required state is present in the same acceptance session; it never silently resets, starts an unrequested blocker, or reorders gates.
- [ ] Every gate has a bounded timeout and writes its own result, timing, logs, resource samples, inputs, and first failed assertion into the local evidence directory before the process exits.
- [ ] Cleanup policy is explicit (`always`, `on-success`, or `never`); development failures default to preserving the exact debuggable state and print the command needed to retry or clean it.
- [ ] Project-name and path guards constrain every start, stop, and cleanup operation to the disposable local acceptance project. The runner cannot launch production, sign launch evidence, open invitations, or remove unrelated Docker resources.
- [ ] Unit and integration tests cover phase selection, range validation, prerequisite refusal, timeout, evidence writing, signal/error cleanup, and preserved-failure behavior without requiring a full end-to-end run.
