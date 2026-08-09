# 12 — Save and reopen Requested Research Dates

**What to build:** Let a research author save, edit, and reopen natural
`start_date` and `end_date` values with a Research Definition while retaining
the existing incomplete-draft workflow.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Definition Save accepts independently nullable ISO natural `start_date` and `end_date` values and detail responses return the exact saved values after reopen.
- [ ] A draft may save neither date or only one date without inventing a default, exchange-session boundary, or 252-plus-504 range.
- [ ] Malformed natural dates, wrong types, and unknown fields are rejected with stable authoring errors and do not create a misleading successful revision.
- [ ] Date edits participate in the existing expected-revision conflict protection and request replay rules; a stale edit cannot overwrite a newer Definition.
- [ ] Definition content, revision, and dates survive API and database restart unchanged.
- [ ] The Web authoring form displays both date inputs, restores their saved values, and preserves current user input while showing an actionable Save failure.
- [ ] Authoring Options remain limited to fields, operators, Universes, neutralization, and numeric bounds; dates do not become catalog entries.
- [ ] Public Definition HTTP against real PostgreSQL proves save, conflict, restart, and reopen semantics; a focused rendered-form round trip proves visible inputs, while saving dates alone creates no ResearchRun, reads no Dataset Head, and submits no data operation.
