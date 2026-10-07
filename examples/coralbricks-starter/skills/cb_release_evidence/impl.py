import json
from pathlib import Path

from reef.decorators import time_bounded
from reef.skill_fn import skill_fn


@skill_fn(
    skill_id="cb_release_evidence",
    description="Read synthetic Atlas release evidence at a cutoff.",
    parameters={
        "type": "object",
        "properties": {
            "project": {"type": "string", "enum": ["atlas"]},
            "as_of_iso": {"type": "string"},
        },
        "required": ["project"],
    },
)
@time_bounded(asof_arg="as_of_iso", mode="clamp", filter_field="published_at")
def release_evidence(*, project: str, as_of_iso: str | None = None):
    if project != "atlas":
        raise ValueError("Only the synthetic atlas project is available")
    data = json.loads(
        (Path(__file__).resolve().parents[2] / "data/release.json").read_text(
            encoding="utf-8"
        )
    )
    # Deliberately return all dated rows: Reef's post-filter is exercised.
    return {"as_of_iso": as_of_iso, "rows": data["evidence"]}
