---
status: accepted
---

# Use historical SW2021 industry classification

ThesisTrace V1 publishes the complete SW2021 L1, L2, and L3 hierarchy and each
stock's historical primary classification in the optional immutable
`equity.industry_membership` Dataset Family. A Dataset Generation that includes
this Family identifies its classification version and retains the membership
history needed to resolve an instrument's industry for every session inside the
Family's own Coverage. Research never substitutes a stock's current industry
for its historical one. Market publication may advance without this Family and
must reuse its exact manifest when it is present; Industry has an independent
collection, validation, candidate, and publication lifecycle.
ADR-0087 represents each historical membership as a left-closed,
right-open effective-date interval and rejects overlaps.

Industry neutralization defaults to SW2021 L1 because it provides useful sector
control without unnecessarily fragmenting the daily cross-section. V1 fixes
`industry` neutralization to SW2021 L1; L2 and L3 remain published canonical
data but are not authoring choices.

Neutralization is one immutable ResearchRun input: `none` or `industry`.
Both choices use the same ResearchRun lifecycle and produce one set of Alpha
Values. With `none`, those values are the Alpha's scores directly; with
`industry`, they are the industry-neutralized scores. The option does not
create separate run types or parallel result branches.

For every market session, industry neutralization subtracts the equal-weight
mean Alpha Expression output of each SW2021 L1 industry from every eligible
valid instrument in that industry. The calculation uses historical L1
membership fixed by the ResearchRun's immutable input after point-in-time ST
exclusion. ADR-0077 defines the complete ordered pipeline.

When neutralization is selected, an instrument without a valid historical
industry classification for a market session is excluded from that session's
Final Alpha Cross-Section and counted in missing-industry coverage. The system
does not create an `UNKNOWN` industry or backfill the missing value with the
instrument's current classification. A genuine source-history interval gap
remains missing rather than extending a neighboring membership.

An industry group must contain at least two valid instruments in a market
session after the preceding gates. A smaller group is excluded before
demeaning and counted as `insufficient_industry_group` coverage rather than
emitting an artificial zero.
