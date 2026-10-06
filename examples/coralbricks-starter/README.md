# Reef on CoralBricks: release-readiness starter

Review a synthetic Atlas search-service rollout with two routed Reef skills:
dated release evidence and canary failure-rate calculation. The default cutoff
is September 30. An October fix must not influence the September decision.

## Setup: target under ten minutes

Prerequisites: Git, Python 3.11 or 3.12, and internet access for installation.
Start at the repository root. The distribution is called `cb-ia`; its import
names are `reef` and `alphacumen`. These commands use this fork:

```bash
git clone https://github.com/conorbronsdon/reef.git
cd reef
git switch feat/coralbricks-starter  # until this PR is merged into the fork
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python examples/coralbricks-starter/starter.py offline
python -m pytest examples/coralbricks-starter -q
```

On Windows, replace the venv/activation commands with:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
# Or use .venv\Scripts\python.exe directly if activation is disabled.
```

The fixture path requires no key and makes no inference requests. It scripts
the model's routing turns while running Reef's actual loader, skill functions,
ReAct loop and constraint enforcer. Expected result: HOLD, 180 failures in
10,000 synthetic requests (1.8%), citations `REL-17` and `INC-42`, three tool
calls executed and a fourth refused. This proves dispatch and controls; it
does not measure model quality.

## Connect the live gateway

Create a key at [API keys](https://www.coralbricks.ai/api-keys) and add prepaid
credits at [Credits](https://www.coralbricks.ai/credits). Export configuration:

```bash
export CORAL_API_KEY='your-real-key'
export CORAL_BASE_URL='https://inference.coralbricks.ai/v1'
export CORAL_MODEL='glm-5.3-flash-fast'
python examples/coralbricks-starter/starter.py preflight
python examples/coralbricks-starter/starter.py smoke
python examples/coralbricks-starter/starter.py live --trace coral-demo.json
```

```powershell
$env:CORAL_API_KEY = 'your-real-key'
$env:CORAL_BASE_URL = 'https://inference.coralbricks.ai/v1'
$env:CORAL_MODEL = 'glm-5.3-flash-fast'
```

`.env.example` is a reference, not an automatically loaded secrets file.
`CORAL_MODEL` is the **raw gateway ID**, without an OpenCode provider prefix.
The example passes `coralbricks/<id>` to Reef, whose adapter strips that prefix
and uses the Coral environment variables. No OpenAI key is needed.

Preflight calls authenticated `GET /v1/models` and `GET /v1/quota`. It verifies
the selected ID and the effective `balance` in USD, including pending spend.
It does not generate tokens or establish that inference will succeed. The
smoke request does generate tokens and requires a response marker, identifier,
usage and `usage.cost`. It prints the gateway's USD cost and cache counters;
missing cost is unknown, never zero. `x-request-id` is preferred; if absent,
the completion ID is reported explicitly as `id_source: completion.id`.

The live workload uses the same synthetic local tools with actual inference.
It disables reasoning for this short demonstration and caps output per turn.
Model routing may differ from the fixture. Exit 1 and `status: incomplete`
mean the expected evidence or final response was not obtained.

## Common preflight failures

| Failure | Next step |
| --- | --- |
| Missing key | Export `CORAL_API_KEY`; do not paste it into source or trace files. |
| 401 | Check/rotate the key. New keys may take about 30 seconds to work. |
| 403 | Ask CoralBricks about endpoint access for the account. |
| 404 or model absent | Keep the base URL ending in `/v1`; choose the exact ID from the key's `/models`. |
| Zero effective balance / `insufficient_credits` | Top up. Balance can lag a top-up or charge by about 30 seconds. |
| 429 rate limit | Wait and retry with backoff; distinguish rate limit from insufficient credits. |
| 502 / 503 / 504, connection or TLS failure | Check service availability and retry a smaller request. Do not disable TLS verification. |

The [API reference](https://www.coralbricks.ai/docs) is the source for current
models, account limits, credits and billed cost. The October 6 catalog lists
GLM 5.3/Flash and DeepSeek V4.1 Flash; older `-fp4` aliases remain supported.
Do not assume Kimi is available: choose it only if the key's catalog lists it.
Cached reads are documented at $0; retained cache writes can be billed
separately. This example reports the returned buckets rather than estimating
charges from a static price table. Context limits are model/account dependent;
the example does not exercise a million-token context.

The [OpenCode guide](https://www.coralbricks.ai/docs/opencode) uses provider
prefixed picker IDs. The [Cursor guide](https://www.coralbricks.ai/docs/cursor)
uses raw IDs and requires a paid Cursor plan for custom model selection. Those
editors are optional; this example runs directly in Python.

## Controls and trace

```bash
python examples/coralbricks-starter/starter.py offline --trace coral-demo.json
python examples/coralbricks-starter/starter.py offline --tool-budget 2
python examples/coralbricks-starter/starter.py offline --asof 2026-10-02 --tool-budget 4
```

The smaller budget produces an incomplete decision and exit 1. The relaxed
cutoff admits `REL-18` and the fourth call executes. The offline script still
selects the September metric snapshot; changing the cutoff does not make a
fixture re-plan like a live model.

`HarnessConstraints` and `harness_context` enable Reef's `LocalEnforcer`.
`@time_bounded(mode="clamp", filter_field="published_at")` narrows the evidence
cutoff and filters later rows. The metric skill uses `mode="validate"` to
refuse a future snapshot. Both loading and dispatch consume the tool budget.
Reef can attempt more calls than the budget; the enforcer prevents their
execution. `max_steps=6` separately bounds model turns.

The demo-specific trace omits prompts, raw messages, arbitrary tool arguments,
provider exception bodies and model-generated answer text. It includes only
known skill names, synthetic evidence, constraint events and allowlisted
accounting fields. See [fixtures/demo-trace.json](fixtures/demo-trace.json).
Fixture identifiers/tokens are synthetic and cost is null. Live request costs
cover successful returned requests; retries or lost responses can incur charges
outside this total. Reconcile actual spending against gateway billing.

## Three-to-five-minute demonstration

1. **0:00–0:45:** Explain the rollout question, synthetic data and September
   cutoff. Show the persona's skill index and the two `SKILL.md` files.
2. **0:45–1:45:** Run offline with `--trace`. Point out skill loading, evidence
   dispatch, the clamped cutoff and the missing October fix.
3. **1:45–2:30:** Show 1.8%, the HOLD decision and the refused fourth call.
   Run with budget 2 to show incomplete evidence; restore budget 3.
4. **2:30–3:15:** Relax cutoff/budget and compare the trace. Explain that
   date enforcement applies to declared tools, not model memory or every
   possible backend.
5. **3:15–4:30:** With a test key, run preflight, smoke and live. Point to
   request ID, usage, cached reads/writes and returned USD cost. Without a key,
   show the missing-key failure and explain that fixture cost is unknown.

## Verification and limitations

See [VERIFICATION.md](VERIFICATION.md) for the clean-environment protocol,
observed timings, failures and remediation backlog. CI runs the offline demo
and tests on Python 3.11/3.12 without secrets; network connections are forbidden
inside the starter tests, including mocked SDK tests.

This is a single-process CLI example. Its scoped chat wrapper uses Python's
`unittest.mock.patch` to record accounting or replay fixtures; it is unsuitable
for concurrent independent runs within one process. The data is synthetic and
there is no web search, code editing, checkpoint persistence or production
telemetry pipeline. The starter lives in the source checkout (and sdist), not
the wheel. Install the wheel for Reef, then retain this example's files.

The as-of controls only constrain tools carrying the declaration and compatible
result shapes; they do not erase future knowledge from the model. Tool budgets
do not cap inference spending. This example does not claim an aggregate token
or dollar ceiling. Reef's synchronous watchdog normally clamps each model call
to 25 seconds, and the SDK/harness may retry requests. Long generations may
need a different runtime strategy. No live latency, cost savings, throughput,
model accuracy or unassisted setup claim has been measured here.
