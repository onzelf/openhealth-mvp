import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field


RUN_ID = os.getenv("RUN_ID", "local-medmnist-001")
RUNS_DIR = Path(os.getenv("RUNS_DIR", "/app/runs"))
GOVERNANCE_MODE = os.getenv("GOVERNANCE_MODE", "pass_through")


app = FastAPI(
    title="vfp-governance gatekeeper",
    description=(
        "Pass-through governance placeholder for the OpenHealth / VFP MVP. "
        "This service records admission checks but does not implement FCaC."
    ),
    version="0.1.0",
)


class AdmissionRequest(BaseModel):
    participant_id: Optional[str] = Field(default=None)
    action: str
    resource: Optional[str] = Field(default=None)
    experiment_id: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_for(req: AdmissionRequest) -> str:
    return req.experiment_id or RUN_ID


def run_dir(run_id: str) -> Path:
    path = RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_event(run_id: str, event: Dict[str, Any]) -> None:
    path = run_dir(run_id) / "events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "component": "vfp-governance/gatekeeper",
        "mode": GOVERNANCE_MODE,
        "fcac_enabled": False,
    }


@app.post("/admission/check")
def admission_check(req: AdmissionRequest) -> Dict[str, Any]:
    run_id = run_id_for(req)

    response = {
        "decision": "ALLOW",
        "mode": GOVERNANCE_MODE,
        "reason": "vfp-governance placeholder: FCaC verification not enabled",
    }

    event = {
        "timestamp": utc_now(),
        "run_id": run_id,
        "component": "vfp-governance/gatekeeper",
        "event_type": "admission_check",
        "participant_id": req.participant_id,
        "action": req.action,
        "resource": req.resource,
        "experiment_id": req.experiment_id,
        "decision": response["decision"],
        "mode": response["mode"],
        "reason": response["reason"],
        "metadata": req.metadata,
    }

    append_event(run_id, event)

    return response