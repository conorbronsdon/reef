---
id: cb_rollout_metrics
when: Compute the failed-request rate for an Atlas canary snapshot.
applies_to: [release_reviewer]
---

Call `rollout_metrics(project="atlas", snapshot_date="2026-09-30")`.
Returns counts and a computed percentage from synthetic traffic, not inference
performance. `@time_bounded(mode="validate")` rejects snapshots after the run
cutoff. Available snapshots: 2026-09-30 and 2026-10-02. Missing snapshots must
be reported as unavailable; do not extrapolate.
