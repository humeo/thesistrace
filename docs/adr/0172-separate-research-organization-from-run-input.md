---
status: accepted
---

# Separate Research organization from immutable Run input

A ResearchRun stores its Research Name and `folder_id` as mutable organization
metadata outside its immutable research input. The name is optional at Run
admission and receives a generated default when blank; users may later rename
the Research or move it to another Research Folder without creating another
Run, changing its identity, or altering execution provenance or results. The
name is not unique within or across Folders and never participates in move or
rename conflicts; `run_id` remains the identity, while lists also show creation
time, status, and a Formula summary to distinguish similarly named Research.
The submitted Formula, compiled Alpha Expression, Hypothesis, Requested Research
Dates, field bindings, Universe, neutralization, Strategy parameters, and
calculation contracts remain immutable. Neither the Research Name nor Folder
membership is duplicated inside that snapshot.
