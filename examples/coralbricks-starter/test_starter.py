import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from openai import OpenAI

from reef import llm
from reef.constraints import HarnessConstraints
from reef.context import harness_context
from reef.skill_tools import INVOKE_SKILL_FN
from reef.skills_loader import load_skills

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("coral_starter", HERE / "starter.py")
starter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = starter
spec.loader.exec_module(starter)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline tests must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_offline_runs_real_skills_and_constraints_without_credentials(monkeypatch):
    for name in ("CORAL_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    first, answer = starter.run_workload()
    second, second_answer = starter.run_workload()
    assert first == second
    assert first == json.loads(
        (HERE / "fixtures/demo-trace.json").read_text(encoding="utf-8")
    )
    assert answer == second_answer
    assert first["status"] == "complete"
    assert first["evidence"]["as_of_iso"] == "2026-09-30"
    assert [r["id"] for r in first["evidence"]["rows"]] == ["REL-17", "INC-42"]
    assert first["metrics"]["failed_requests"] == 180
    assert first["metrics"]["failure_rate_percent"] == 1.8
    assert "HOLD" in answer and "1.8%" in answer
    assert first["executed_tool_calls"] == 3
    assert first["attempted_tool_calls"] == 4
    assert first["events"][-1]["budget_rejected"] is True
    assert first["total_cost_usd"] is None


def test_budget_and_cutoff_controls_have_unrestricted_complements():
    trace, _ = starter.run_workload(tool_budget=4, asof="2026-10-02")
    assert trace["executed_tool_calls"] == 4
    assert not any(e["budget_rejected"] for e in trace["events"])
    assert [r["id"] for r in trace["evidence"]["rows"]] == [
        "REL-17",
        "INC-42",
        "REL-18",
    ]
    smaller, answer = starter.run_workload(tool_budget=2)
    assert smaller["status"] == "incomplete"
    assert smaller["metrics"] == {}
    assert "INCOMPLETE" in answer


def test_future_metric_rejected_but_same_date_executes():
    load_skills(HERE / "skills", module_prefix="coral_starter.skills")
    with harness_context(HarnessConstraints(asof="2026-09-30")):
        future = INVOKE_SKILL_FN.fn(
            skill_id="cb_rollout_metrics",
            fn="rollout_metrics",
            args={"project": "atlas", "snapshot_date": "2026-10-02"},
        )
        allowed = INVOKE_SKILL_FN.fn(
            skill_id="cb_rollout_metrics",
            fn="rollout_metrics",
            args={"project": "atlas", "snapshot_date": "2026-09-30"},
        )
    assert future["constraint_violation"] is True
    assert "AsofViolation" in future["error"]
    assert "failure_rate_percent" not in future
    assert allowed["failure_rate_percent"] == 1.8


@pytest.mark.parametrize(
    "base",
    [
        "http://gateway/v1",
        "https://key@gateway/v1",
        "https://gateway/v1?key=secret",
        "https://gateway/v1/chat/completions",
    ],
)
def test_config_rejects_unsafe_or_wrong_endpoint(monkeypatch, base):
    monkeypatch.setenv("CORAL_API_KEY", "test-secret")
    monkeypatch.setenv("CORAL_BASE_URL", base)
    with pytest.raises(ValueError, match="HTTPS gateway"):
        starter.Config.from_env()


def test_missing_key_and_provider_prefixed_model(monkeypatch):
    monkeypatch.delenv("CORAL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="CORAL_API_KEY"):
        starter.Config.from_env()
    monkeypatch.setenv("CORAL_API_KEY", "test-secret")
    monkeypatch.setenv("CORAL_MODEL", "coralbricks/glm-5.3-flash-fast")
    with pytest.raises(ValueError, match="raw gateway ID"):
        starter.Config.from_env()


def test_preflight_wire_contract_and_no_generation(monkeypatch):
    seen = []
    config = starter.Config(key="test-secret", model="enabled-model")

    def handler(request):
        seen.append(request.url.path)
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer test-secret"
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "enabled-model",
                            "object": "model",
                            "created": 0,
                            "owned_by": "test",
                        }
                    ]
                },
            )
        assert request.url.path == "/v1/quota"
        return httpx.Response(
            200,
            json={
                "currency": "USD",
                "balance": 0.4,
                "balance_cents": 100,
                "pending_charge_cents": 60,
            },
        )

    with OpenAI(
        api_key=config.key,
        base_url=config.base_url,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as api:
        report = starter.preflight(config, api)
    assert seen == ["/v1/models", "/v1/quota"]
    assert report["effective_balance_usd"] == 0.4


@pytest.mark.parametrize("balance", [0, -1, None, True, float("nan")])
def test_preflight_rejects_zero_or_unverified_credit(balance):
    api = SimpleNamespace(
        models=SimpleNamespace(
            list=lambda: [SimpleNamespace(id=starter.DEFAULT_MODEL)]
        ),
        get=lambda *a, **kw: {"currency": "USD", "balance": balance},
    )
    with pytest.raises(ValueError):
        starter.preflight(starter.Config(key="test-secret"), api)


def test_preflight_rejects_model_without_assuming_catalog_proves_inference():
    api = SimpleNamespace(models=SimpleNamespace(list=lambda: []))
    with pytest.raises(ValueError, match="not enabled"):
        starter.preflight(starter.Config(key="test-secret"), api)


@pytest.mark.parametrize(
    "status, code, expected",
    [
        (401, "invalid_api_key", "Key rejected"),
        (404, "model_not_accepted", "Endpoint/model"),
        (429, "insufficient_credits", "Insufficient credits"),
        (429, "rate_limit_exceeded", "Rate limited"),
        (503, "backend_unconfigured", "Backend unavailable"),
    ],
)
def test_common_error_hints_do_not_echo_secret(status, code, expected):
    exc = httpx.HTTPStatusError(
        "test-secret",
        request=httpx.Request("GET", "https://gateway"),
        response=httpx.Response(status),
    )
    exc.status_code = status
    exc.body = {"error": {"code": code, "message": "test-secret"}}
    hint = starter.error_hint(exc)
    assert expected in hint
    assert "test-secret" not in hint


def test_live_adapter_uses_coral_env_and_preserves_gateway_usage(monkeypatch):
    monkeypatch.setenv("CORAL_API_KEY", "test-secret")
    monkeypatch.setenv("CORAL_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("CORAL_MODEL", "custom-model")
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-provider")
    captured = []
    real_openai = OpenAI

    def handler(request):
        captured.append(json.loads(request.content))
        assert str(request.url) == "https://gateway.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            headers={"x-request-id": "req-123"},
            json={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "created": 0,
                "model": "custom-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "CORAL_REEF_OK"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "prompt_tokens_details": {
                        "cached_tokens": 7,
                        "billable_cache_write_tokens": 3,
                    },
                    "cost": 0.00001,
                    "cost_details": {
                        "currency": "USD",
                        "cached_input": 0,
                        "cache_write": 0.000004,
                        "output": 0.000006,
                    },
                },
            },
        )

    def factory(**kwargs):
        return real_openai(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )

    with patch("openai.OpenAI", side_effect=factory):
        report = starter.smoke(starter.Config.from_env())
    assert captured[0]["model"] == "custom-model"
    assert captured[0]["reasoning"] == {"enabled": False}
    assert report["request_id"] == "req-123"
    assert report["id_source"] == "x-request-id"
    assert report["usage"]["billable_cache_write_tokens"] == 3
    assert report["usage"]["cost_details"]["cached_input"] == 0
    assert report["cost_usd"] == 0.00001


def test_trace_accounting_is_allowlisted_and_missing_cost_is_unknown():
    result = starter.accounting(
        {
            "response": {
                "id": "chatcmpl-456",
                "usage": {"prompt_tokens": 1, "secret": "test-secret"},
                "prompt": "test-secret",
            },
            "request_id": "invalid secret with spaces",
        }
    )
    assert result["request_id"] == "chatcmpl-456"
    assert result["id_source"] == "completion.id"
    assert result["cost_usd"] is None
    assert "test-secret" not in json.dumps(result)


def test_smoke_rejects_missing_cost():
    with patch.object(
        llm,
        "chat",
        return_value={
            "response": {
                "id": "chatcmpl-1",
                "choices": [{"message": {"content": "CORAL_REEF_OK"}}],
                "usage": {"prompt_tokens": 2},
            }
        },
    ):
        with pytest.raises(ValueError, match="gateway cost"):
            starter.smoke(starter.Config(key="test-secret"))
