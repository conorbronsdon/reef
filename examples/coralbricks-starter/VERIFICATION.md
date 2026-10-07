# Setup evidence and remediation backlog

Observed October 6, 2026, against the fork's `e0b9d6a` baseline plus this PR.
The live path was skipped because this environment has no `CORAL_API_KEY`.
No live request ID, billed cost, latency or model-quality result is claimed.

## Clean-environment protocol

1. Use Python 3.11 or 3.12 and a source checkout of this PR. Start a stopwatch
   before creating a fresh venv, with no installed packages inherited.
2. Install with `python -m pip install -e '.[dev]'` from the repository root.
3. Run `python -m pytest reef/tests alphacumen/tests examples/coralbricks-starter -q`.
4. Run `python examples/coralbricks-starter/starter.py offline`. Stop the clock
   after successful exit and record all errors, assistance and cache conditions.
5. Build with `python -m build`. In a separate venv install `dist/*.whl`; change
   to a directory outside the checkout before importing `reef` and `alphacumen`.
   Run the starter by absolute path with that interpreter to prove wheel use.
6. When a test key is supplied, separately measure key creation/top-up,
   preflight, smoke and live workload. Keep that timing distinct from offline
   installation. Save only the demo's redacted trace and gateway accounting.

## Observed timings

These were assisted Windows runs from an existing source checkout, using a
warm pip cache and fresh venvs. The two version runs overlapped. Git clone,
Python installation, signup, key creation and credit top-up are excluded.
They are not evidence of an unassisted or cold-cache onboarding result.

| Stage | Python 3.11 | Python 3.12 |
| --- | ---: | ---: |
| Fresh venv | 26.823 s | 14.301 s |
| Editable install and development tools | 211.501 s | 208.315 s |
| Full offline tests | 19.138 s | 21.302 s |
| Offline workload | 2.928 s | 0.902 s |
| Total | **260.392 s (4m 20s)** | **244.823 s (4m 05s)** |

The sub-ten-minute target was met under these conditions. A live first-workload
setup time remains unmeasured. Dependency installation dominates these runs.

## Verification results

- The timed Python 3.11 and 3.12 runs: **245 passed**, with no skips or xfails,
  across Reef, AlphaCumen and the original 23 parametrized starter cases. A
  subsequent review fix adds checks for whitespace-pasted Coral credentials/
  endpoints and local trace-write errors (25 starter cases total); final suite
  and CI counts are recorded on the PR.
- Baseline before edits: **217 passed, 4 failed** in Reef/AlphaCumen. The
  failures were an incomplete convenience tool list, two obsolete expectations
  that stripped document prefixes, and an unmocked graph actor-ID lookup.
  The repair preserves full document IDs and tests actual numeric seed
  resolution rather than restoring the older behavior.
- Root correctness lint passed. Starter default lint/import checks and format
  checks passed. Existing files receive correctness checks; repository-wide
  formatting is a separate backlog item.
- Wheel and sdist built successfully. Outside-checkout wheel import passed;
  **44** bundled AlphaCumen skills loaded and the starter's offline workload
  completed with the wheel. The sdist includes the starter's source, skills,
  data, environment template and fixture trace. The wheel excludes examples.
- The fixture trace is deterministic and compared with its checked-in JSON.
  It shows a future-date clamp, two surviving evidence rows, a 1.8% calculation,
  three executed calls and a refused fourth call. A larger cutoff/budget
  admits the future row and extra dispatch; budget 2 yields an incomplete run.
- Three mutation checks each produced a failing targeted test: bypassing the
  date post-filter, bypassing the tool budget, and replacing Coral credential
  routing with OpenAI routing. These mutations were scoped in-memory patches,
  not committed source changes.
- Mocked HTTP tests exercise the real OpenAI SDK against a local mock transport:
  `/models`, `/quota`, Chat Completions, Coral auth/model routing, request-header
  ID, returned usage/cost, free cached-read and billable cache-write fields.
  Starter tests prohibit socket connections and require no credentials.
- Missing-key preflight exits 1 with setup guidance before network access.

CI runs the package suite/build/fresh-wheel import and an independent offline
starter job on Python 3.11/3.12. GitHub's checks on the PR are the authoritative
Linux CI results; local Windows results do not establish that those jobs passed.

## Failures and assistance observed

The original workflow used the missing `context_prep/` directory, nonexistent
examples/extras and Python 3.10 despite the package's 3.11 minimum. Installation
links pointed to the renamed repository, and the root README described separate
Reef/AlphaCumen package files that do not exist. Those references are corrected
in separate commits from the starter.

The Windows launcher did not resolve the uv-managed Python 3.11 installation;
using its installed interpreter directly fixed that local setup issue. Sandbox
network/temporary-file restrictions required the host's authorized execution
lane for installation/build. An initial PowerShell measurement wrapper treated
pip's stderr update notice as an exception after a successful install; the
reported timings come from a new fresh-venv run using subprocess exit codes.
These harness failures are not counted as Reef test failures.

## Remediation backlog

Estimates are planning estimates, not measured implementation time.

| Priority | Work and evidence | Owner | Estimate | Dependency / verification |
| --- | --- | --- | --- | --- |
| P1 | Run live preflight, smoke and workload; no test key was available. Confirm the chosen model, marker, request ID source and billed usage/cost. | CoralBricks maintainer | 1–2 h | Stable funded test account. Compare trace with gateway request/billing logs. |
| P1 | Measure cold-cache clean-clone and unassisted setup. Current results are assisted and cache-warm. | Starter maintainer | Half day for a small pilot | Integrated fork branch, new users and test credits. Record all assistance/errors and time to first representative workload. |
| P2 | Resolve setuptools license and namespace-discovery warnings. Build succeeds and skill data loads, but the packaging metadata emits deprecations. | Package maintainer | 1–3 h | Choose supported setuptools/release contract; verify wheel and sdist data after the change. |
| P2 | Plan broader formatting/strict lint adoption. This PR checks existing-code correctness and starter style without a large formatting rewrite. | Reef maintainer | 4–8 h | Agree rule set and avoid mixing format churn with behavioral changes; run the complete relevant suite. |
| P2 | Evaluate synchronous watchdog/retry behavior on the selected Coral model. The current default watchdog is 25 s; no live reliability measurement exists. | Reef + CoralBricks maintainers | 2–4 h | Funded test key and bounded workloads; record timeouts, retries and billed requests. |
| P3 | Replace synthetic tools for a real domain or add reusable concurrent tracing only when the use case needs it. This starter uses a single-process scoped chat wrapper. | Example owner | Scope before estimating | Domain corpus/access, concurrency contract and privacy requirements; preserve deterministic offline tests. |

Maintainers control merge, release, package publication and production gateway
changes. This PR performs none of those actions.
