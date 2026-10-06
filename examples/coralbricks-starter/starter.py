"""One-process Reef demo; only the chat boundary is replaced for fixtures."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from reef import llm, react
from reef.constraints import HarnessConstraints
from reef.context import harness_context
from reef.enforcement import LocalEnforcer
from reef.skill_tools import INVOKE_SKILL_FN, make_load_skill_tool
from reef.skills_loader import load_skills, render_index, render_loaded

HERE = Path(__file__).resolve().parent
DEFAULT_URL = "https://inference.coralbricks.ai/v1"
DEFAULT_MODEL = "glm-5.3-flash-fast"
QUESTION = "Should we expand the Atlas canary as of the cutoff? Cite blockers and the failure rate."
SKILL_IDS = ("cb_release_evidence", "cb_rollout_metrics")


@dataclass(frozen=True)
class Config:
    key: str = field(repr=False)
    base_url: str = DEFAULT_URL
    model: str = DEFAULT_MODEL

    @classmethod
    def from_env(cls):
        from urllib.parse import urlsplit

        key = os.environ.get("CORAL_API_KEY", "").strip()
        if not key or key in {"replace-with-your-key", "cb_..."}:
            raise ValueError(
                "Set CORAL_API_KEY to a real key from coralbricks.ai/api-keys."
            )
        base = os.environ.get("CORAL_BASE_URL", DEFAULT_URL).strip().rstrip("/")
        url = urlsplit(base)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path != "/v1"
        ):
            raise ValueError(
                "CORAL_BASE_URL must be an HTTPS gateway URL ending in /v1."
            )
        model = os.environ.get("CORAL_MODEL", DEFAULT_MODEL).strip()
        if not model or model.startswith("coralbricks/"):
            raise ValueError(
                "CORAL_MODEL must be the raw gateway ID, without coralbricks/."
            )
        return cls(key=key, base_url=base, model=model)


def error_hint(exc):
    """Never print arbitrary exception bodies, URLs, headers or credentials."""
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    code = error.get("code") if isinstance(error, dict) else None
    if code == "insufficient_credits":
        return "Insufficient credits: top up at coralbricks.ai/credits; balance may lag ~30s."
    status = getattr(exc, "status_code", None)
    hints = {
        400: "Bad request: check the model and supported parameters.",
        401: "Key rejected: check CORAL_API_KEY; new keys may take ~30s to work.",
        403: "Access denied: contact CoralBricks about this account's endpoint access.",
        404: "Endpoint/model not found: check /v1 and the exact ID from /models.",
        429: "Rate limited: wait and retry with backoff; also check /quota for credits.",
        502: "Upstream failure: retry later.",
        503: "Backend unavailable: retry later.",
        504: "Gateway timeout: retry a smaller request; Reef uses synchronous Chat Completions.",
    }
    return hints.get(
        status,
        "Connection or response failure: check DNS, TLS and gateway availability.",
    )


def preflight(config, client=None):
    """Read-only authentication, model and effective-credit checks; no generation."""
    from openai import OpenAI

    def check(api):
        try:
            ids = {row.id for row in api.models.list()}
            if config.model not in ids:
                raise ValueError(
                    "CORAL_MODEL is not enabled for this key; select an ID from /v1/models."
                )
            quota = api.get("/quota", cast_to=dict)
            balance = quota.get("balance")
            if (
                quota.get("currency") != "USD"
                or isinstance(balance, bool)
                or not isinstance(balance, (int, float))
                or not math.isfinite(balance)
            ):
                raise ValueError(
                    "Unexpected /quota response; cannot verify effective credits."
                )
            if balance <= 0:
                raise ValueError(
                    "No effective credits: top up at coralbricks.ai/credits."
                )
            return {
                "status": "ready",
                "model": config.model,
                "effective_balance_usd": balance,
            }
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(error_hint(exc)) from None

    if client is not None:
        return check(client)
    with OpenAI(
        api_key=config.key, base_url=config.base_url, timeout=10, max_retries=0
    ) as api:
        return check(api)


def safe_id(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value)
        else None
    )


def accounting(envelope, *, fixture=False):
    response = envelope.get("response") or {}
    usage = response.get("usage") or {}
    header_id = safe_id(envelope.get("request_id"))
    body_id = safe_id(response.get("id"))
    allowed = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens", "cost"):
        value = usage.get(name)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        ):
            allowed[name] = value
    details = usage.get("prompt_tokens_details") or {}
    for name in ("cached_tokens", "cache_write_tokens", "billable_cache_write_tokens"):
        value = details.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            allowed[name] = value
    costs = usage.get("cost_details") or {}
    if costs.get("currency") == "USD":
        allowed["cost_details"] = {"currency": "USD"}
        for name in ("input", "cached_input", "cache_write", "output"):
            value = costs.get(name)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                allowed["cost_details"][name] = value
    return {
        "request_id": header_id or body_id,
        "id_source": "x-request-id"
        if header_id
        else "completion.id"
        if body_id
        else "missing",
        "usage": allowed,
        "cost_usd": None if fixture else allowed.get("cost"),
        "accounting_source": "synthetic fixture; not billed"
        if fixture
        else "gateway response",
    }


class FixtureChat:
    """Scripted model routing, actual Reef tool execution and evidence-based final."""

    def __init__(self):
        self.messages = json.loads(
            (HERE / "fixtures/chat.json").read_text(encoding="utf-8")
        )
        self.index = 0

    def __call__(self, **kwargs):
        if self.index < len(self.messages):
            message = copy.deepcopy(self.messages[self.index])
        else:
            results = []
            for item in kwargs["messages"]:
                if item["role"] == "tool" and item.get("name") == "invoke_skill_fn":
                    try:
                        results.append(json.loads(item["content"]))
                    except ValueError:
                        continue
            evidence = next((r for r in results if "rows" in r), {})
            metric = next((r for r in results if "failure_rate_percent" in r), {})
            citations = ", ".join(r["id"] for r in evidence.get("rows", []))
            if metric and citations:
                rate = metric["failure_rate_percent"]
                content = f"HOLD: {rate:.1f}% failed requests at {metric['snapshot_date']}; evidence {citations}. Synthetic demonstration only."
            else:
                content = "INCOMPLETE: insufficient evidence within the cutoff and tool budget. Synthetic demonstration only."
            message = {"role": "assistant", "content": content}
        self.index += 1
        return {
            "response": {
                "id": f"fixture-{self.index}",
                "choices": [{"message": message}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            }
        }


def run_workload(*, offline=True, asof="2026-09-30", tool_budget=3):
    skills = load_skills(HERE / "skills", module_prefix="coral_starter.skills")
    load = make_load_skill_tool(lambda ids: render_loaded(list(ids), skills=skills))
    prompt = (
        (HERE / "analyst.md")
        .read_text(encoding="utf-8")
        .replace("{skill_index}", render_index(skills))
    )
    constraints = HarnessConstraints(asof=asof, tool_budget=tool_budget)
    enforcer = LocalEnforcer()
    requests = []
    original_chat = llm.chat
    chat = FixtureChat() if offline else original_chat

    def record_chat(**kwargs):
        envelope = chat(**kwargs)
        requests.append(accounting(envelope, fixture=offline))
        return envelope

    model = (
        "coralbricks/fixture" if offline else "coralbricks/" + Config.from_env().model
    )
    # Scoped to this CLI process. No reusable tracing/serialization API is added.
    with (
        patch.object(react.cb_llm, "chat", record_chat),
        harness_context(constraints, enforcer),
    ):
        trajectory = react.run_react(
            model=model,
            system_prompt=prompt,
            user_message=f"{QUESTION} Cutoff: {asof}.",
            tools=[load, INVOKE_SKILL_FN],
            max_steps=6,
            max_tokens=2048,
            temperature=0,
            capture_tools=["invoke_skill_fn"],
            min_tool_calls_before_final=3,
            extra_chat_kwargs={"extra_body": {"reasoning": {"enabled": False}}},
        )
    # Demo trace deliberately omits prompts, credentials, arbitrary model text,
    # exception bodies and raw tool arguments. Only known synthetic evidence is kept.
    results = trajectory.captured_tool_results.get("invoke_skill_fn", [])
    evidence = next((r for r in results if isinstance(r, dict) and "rows" in r), {})
    metrics = next(
        (r for r in results if isinstance(r, dict) and "failure_rate_percent" in r), {}
    )
    events = []
    for step in trajectory.steps:
        if step.kind != "tool":
            continue
        skill = step.arguments.get("skill_id")
        events.append(
            {
                "tool": step.name
                if step.name in {"load_skill", "invoke_skill_fn"}
                else "unknown",
                "skill_id": skill if skill in SKILL_IDS else None,
                "budget_rejected": step.has_error
                and "BudgetExceeded" in (step.error_message or ""),
            }
        )
    final = (trajectory.final_message or {}).get("content") or ""
    trace = {
        "mode": "offline" if offline else "live",
        "dataset": "synthetic Atlas rollout",
        "constraints": {
            "asof": constraints.asof_iso,
            "tool_budget": tool_budget,
            "max_steps": 6,
        },
        "status": "complete"
        if not trajectory.error and final and evidence.get("rows") and metrics
        else "incomplete",
        "executed_tool_calls": enforcer.calls_used,
        "attempted_tool_calls": trajectory.token_usage["tool_calls"],
        "events": events,
        "evidence": evidence,
        "metrics": metrics,
        "requests": requests,
        "total_cost_usd": sum(r["cost_usd"] for r in requests)
        if requests and all(r["cost_usd"] is not None for r in requests)
        else None,
        "cost_limitation": "Only successful returned requests are accounted; use gateway billing for reconciliation.",
    }
    return trace, final


def smoke(config):
    # Uses the same Reef provider adapter as the workload, after preflight.
    envelope = llm.chat(
        model="coralbricks/" + config.model,
        messages=[{"role": "user", "content": "Reply with CORAL_REEF_OK."}],
        max_completion_tokens=256,
        temperature=0,
        timeout_s=25,
        extra_body={"reasoning": {"enabled": False}},
    )
    report = accounting(envelope)
    choices = (envelope.get("response") or {}).get("choices") or []
    content = (
        ((choices[0].get("message") or {}).get("content") or "") if choices else ""
    )
    if (
        not report["request_id"]
        or "prompt_tokens" not in report["usage"]
        or "completion_tokens" not in report["usage"]
        or report["cost_usd"] is None
        or "CORAL_REEF_OK" not in content
    ):
        raise ValueError(
            "Smoke response lacks the marker, a valid ID, usage or gateway cost; inspect account logs."
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["offline", "preflight", "smoke", "live"])
    parser.add_argument("--asof", default="2026-09-30")
    parser.add_argument("--tool-budget", type=int, default=3)
    parser.add_argument(
        "--trace", type=Path, help="Write a demo-specific redacted JSON trace"
    )
    args = parser.parse_args()
    try:
        if args.mode != "offline":
            config = Config.from_env()
            readiness = preflight(config)
            if args.mode == "preflight":
                print(json.dumps(readiness, indent=2))
                return 0
            if args.mode == "smoke":
                print(json.dumps(smoke(config), indent=2))
                return 0
        trace, answer = run_workload(
            offline=args.mode == "offline", asof=args.asof, tool_budget=args.tool_budget
        )
        if args.trace:
            args.trace.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        print(answer)
        print(json.dumps(trace, indent=2))
        return 0 if trace["status"] == "complete" else 1
    except OSError as exc:
        print(
            f"Local file operation failed ({type(exc).__name__}): check the trace path and example files."
        )
        return 1
    except ValueError as exc:
        print(f"Preflight/run failed: {exc}")
        return 1
    except Exception as exc:
        print(error_hint(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
