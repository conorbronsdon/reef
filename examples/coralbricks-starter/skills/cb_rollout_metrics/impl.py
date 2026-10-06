import json
from pathlib import Path

from reef.decorators import time_bounded
from reef.skill_fn import skill_fn


@skill_fn(
    skill_id="cb_rollout_metrics",
    description="Compute the failure rate from a synthetic canary snapshot.",
    parameters={
        "type": "object",
        "properties": {
            "project": {"type": "string", "enum": ["atlas"]},
            "snapshot_date": {"type": "string"},
        },
        "required": ["project", "snapshot_date"],
    },
)
@time_bounded(asof_arg="snapshot_date", mode="validate")
def rollout_metrics(*, project: str, snapshot_date: str):
    if project != "atlas":
        raise ValueError("Only the synthetic atlas project is available")
    data = json.loads(
        (Path(__file__).resolve().parents[2] / "data/release.json").read_text(
            encoding="utf-8"
        )
    )
    for row in data["snapshots"]:
        if row["snapshot_date"] == snapshot_date:
            return {
                **row,
                "failure_rate_percent": 100 * row["failed_requests"] / row["requests"],
            }
    raise ValueError("No synthetic snapshot is available for that date")
