---
id: cb_release_evidence
when: Review release notes and unresolved blockers for the Atlas rollout.
applies_to: [release_reviewer]
---

Call `release_evidence(project="atlas", as_of_iso=<cutoff>)` before deciding.
Returns synthetic dated evidence with citation IDs. Reef clamps a requested
future cutoff and post-filters rows via `@time_bounded`. No live search backend
is used. Do not assume that a later fix was already available at the cutoff.
