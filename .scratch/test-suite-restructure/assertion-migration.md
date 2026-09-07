# Test assertion migration

Status: implementation and acceptance in progress. No full gate success claimed.

| Original coverage | Current owner | Preservation |
| --- | --- | --- |
| RustFS readiness probe, 3 cases under tests/unit | tests/architecture/test_rustfs_readiness_probe.py | File moved unchanged; quick gate now collects it |
| ModelPicker, 4 cases | Web Vitest automatic src discovery | Assertions unchanged; omitted cases now collected |
| Composer layout, focus, input mode and touch | web/browser/chat-composer-layout.spec.ts | Moved unchanged with local fixture |
| Timeline scrolling and presentation | web/browser/chat-timeline-presentation.spec.ts | Moved unchanged with local fixtures |
| Chat completion, repeated prompts and concurrent Sessions | E2E chat-ui waitForChatTurn plus original E2E cases | Adds matching Turn terminal wait; original identities, counts and DB assertions retained |
| Operator navigation, capability hiding, revoked access, proof refusal | Operator access control and responsive navigation | Original sections retained; own Operator and ordinary identity |
| Operator invitation and Researcher lifecycle | Operator researchers and invitations | Original invite and Researcher sections retained; own directory and receipts |
| Market refresh validation, submission, proof and response recovery | Operator Market submission and response recovery | Original Market section retained; own fixture baseline |
| Financial/Industry refresh validation and response recovery | Operator Financial and Industry refresh and response recovery | Original sections retained; own fixture baseline |
| Operation pagination/status and Worker restart recovery | Operator Dataset operations and Worker recovery | Original business assertions retained; prepares its own three accepted operations |
| Mocked 5.2s polling, hidden/visible, focus, online and manual reload | web/src/operator/OperatorDatasetStatus.test.tsx | Executes mounted component with controlled clock; no fixed sleep |
| Production Operator permissions, refresh and response recovery | Image smoke selects Market submission and response recovery | Real permission check in fixture plus real Market submission/recovery; component clock checks excluded |
| Duplicate benchmark command | check:performance only | No performance scenario or threshold removed; duplicate alias removed |

The old Operator monolith is split by its contiguous acceptance sections.
Shared setup is invoked independently by each test. No IDs or receipts are
passed between cases. The Dataset operations case submits its own three refreshes
instead of inheriting Market/Financial/Industry receipts from preceding sections.
The access-control case uses its own issued invitation token when proving that
an unauthorized request is rejected. Unknown or unproven redundant tests remain.

Validation evidence will be recorded separately after each command exits.

Review follow-up: terminal polling retains the same operation while changing
accepted to succeeded and verifies Published; image-list and deletion failures
are recorded separately and fail the aggregate; the directory fixture is only
used by access/directory cases. Financial/Industry prepares its own Market
refresh through 2026-08-14 before testing its target. Chat wait requests use the
remaining model-wait budget, followed by a separate 5-second rendering budget.
