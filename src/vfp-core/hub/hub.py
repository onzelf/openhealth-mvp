import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------

RUN_ID = os.getenv("RUN_ID", "local-medmnist-001")
RUNS_DIR = Path(os.getenv("RUNS_DIR", "/app/runs"))

DATASET = os.getenv("DATASET", "medmnist")
DATASET_SUBSET = os.getenv("DATASET_SUBSET", "pneumoniamnist")

FLOWER_ROUNDS = int(os.getenv("FLOWER_ROUNDS", "3"))
MIN_CLIENTS = int(os.getenv("MIN_CLIENTS", "2"))

FLOWER_BACKEND_URL = os.getenv("FLOWER_BACKEND_URL", "vfp-core-flower-server:8080")
GOVERNANCE_URL = os.getenv(
    "GOVERNANCE_URL",
    "http://vfp-governance-gatekeeper:8080/admission/check",
)

GOVERNANCE_MODE = os.getenv("GOVERNANCE_MODE", "pass_through")
FCAC_ENABLED = os.getenv("FCAC_ENABLED", "false").lower() == "true"

ORGS_JSON = os.getenv("ORGS_JSON", "{}")


# ---------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------

app = FastAPI(
    title="vfp-core hub",
    description=(
        "OpenHealth / VFP MVP hub. "
        "Coordinates experiment metadata, backend registration, and evidence artefacts. "
        "Does not implement FCaC."
    ),
    version="0.1.0",
)


# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------

class BackendRegistration(BaseModel):
    backend_id: str = Field(..., examples=["flower-local"])
    backend_type: str = Field(..., examples=["flower"])
    url: str = Field(..., examples=["vfp-core-flower-server:8080"])
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AdmissionRequest(BaseModel):
    participant_id: Optional[str] = None
    action: str
    resource: Optional[str] = None
    experiment_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExperimentInitialiseRequest(BaseModel):
    run_id: str = RUN_ID
    dataset: str = DATASET
    dataset_subset: str = DATASET_SUBSET
    rounds: int = FLOWER_ROUNDS
    min_clients: int = MIN_CLIENTS

class ClientRegistration(BaseModel):
    run_id: str = RUN_ID
    org_id: str
    org_label: Optional[str] = None
    data_partition: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ---------------------------------------------------------------------
# In-memory registry
# ---------------------------------------------------------------------

backend_registry: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------
# In-memory runtime state
# ---------------------------------------------------------------------

experiment_state: Dict[str, Any] = {
    "run_id": RUN_ID,
    "status": "waiting",
    "registered_clients": {},
    "min_clients": MIN_CLIENTS,
    "flower_server_ready": True,
}

# ---------------------------------------------------------------------
# Paths and evidence helpers
# ---------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_dir(run_id: str = RUN_ID) -> Path:
    path = RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def append_event(event_type: str, run_id: str = RUN_ID, **kwargs: Any) -> None:
    event = {
        "timestamp": utc_now(),
        "run_id": run_id,
        "component": "vfp-core/hub",
        "event_type": event_type,
        **kwargs,
    }

    path = run_dir(run_id) / "events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def current_experiment_status(run_id: str = RUN_ID) -> Dict[str, Any]:
    registered_clients = experiment_state.get("registered_clients", {})
    registered_client_ids = sorted(registered_clients.keys())
    registered_client_count = len(registered_client_ids)
    min_clients = int(experiment_state.get("min_clients", MIN_CLIENTS))

    return {
        "run_id": run_id,
        "status": experiment_state.get("status", "waiting"),
        "flower_server_ready": experiment_state.get("flower_server_ready", False),
        "registered_clients": registered_client_ids,
        "registered_client_count": registered_client_count,
        "min_clients": min_clients,
        "can_start": (
            experiment_state.get("status") == "waiting"
            and experiment_state.get("flower_server_ready", False)
            and registered_client_count >= min_clients
        ),
        "fcac_enabled": FCAC_ENABLED,
        "governance_mode": GOVERNANCE_MODE,
    }


def parse_orgs() -> Dict[str, Dict[str, Any]]:
    try:
        payload = json.loads(ORGS_JSON)
        if not isinstance(payload, dict):
            return {}
        return payload
    except json.JSONDecodeError:
        return {}


def write_participants(run_id: str = RUN_ID) -> None:
    orgs = parse_orgs()

    participants = {
        "run_id": run_id,
        "participants": [
            {
                "org_id": org_id,
                "label": org.get("label"),
                "partition": org.get("partition"),
                "enabled": org.get("enabled", True),
            }
            for org_id, org in orgs.items()
        ],
    }

    write_json(run_dir(run_id) / "participants.json", participants)


def write_experiment_config(req: ExperimentInitialiseRequest) -> None:
    config = {
        "run_id": req.run_id,
        "dataset": req.dataset,
        "dataset_subset": req.dataset_subset,
        "aggregation_strategy": "FedAvg",
        "rounds": req.rounds,
        "min_clients": req.min_clients,
        "local_epochs": int(os.getenv("LOCAL_EPOCHS", "1")),
        "batch_size": int(os.getenv("BATCH_SIZE", "32")),
        "learning_rate": float(os.getenv("LEARNING_RATE", "0.001")),
        "flower_backend_url": FLOWER_BACKEND_URL,
        "governance": {
            "mode": GOVERNANCE_MODE,
            "fcac_enabled": FCAC_ENABLED,
            "note": (
                "vfp-governance is pass-through in this MVP. "
                "FCaC verification is not implemented."
            ),
        },
        "scope": {
            "vfp_core": "implemented FL/FC infrastructure baseline",
            "vfp_governance": "placeholder only",
            "fcac": "not implemented",
        },
        "organisations": parse_orgs(),
    }

    write_json(run_dir(req.run_id) / "experiment_config.json", config)


def ensure_metrics_file(run_id: str = RUN_ID) -> None:
    path = run_dir(run_id) / "metrics.csv"
    if path.exists():
        return

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "run_id",
                "round",
                "fit_client_count",
                "fit_failure_count",
                "eval_client_count",
                "eval_failure_count",
                "loss",
                "accuracy",
                "train_loss",
                "train_accuracy",
            ]
        )


def write_reproduce_readme(req: ExperimentInitialiseRequest) -> None:
    content = f"""# Reproduce run `{req.run_id}`

This run belongs to the OpenHealth / VFP MVP.

## Scope

Implemented:

- local Docker-based FL/FC infrastructure baseline;
- Flower-based federated execution path;
- run metadata;
- lifecycle events;
- metrics evidence.

Not implemented:

- FCaC;
- cryptographic admission control;
- healthcare consent workflows;
- production governance-as-code;
- advanced privacy-enhancing technologies;
- clinical validation.

## Experiment

- Dataset: `{req.dataset}`
- Dataset subset: `{req.dataset_subset}`
- Aggregation strategy: `FedAvg`
- Rounds: `{req.rounds}`
- Minimum clients: `{req.min_clients}`
- Governance mode: `{GOVERNANCE_MODE}`
- FCaC enabled: `{FCAC_ENABLED}`

## Expected artefacts

- `experiment_config.json`
- `participants.json`
- `events.jsonl`
- `metrics.csv`
- `dataset_split_summary.csv`
- `final_model_metadata.json`

## Reproducibility note

The local deployment is managed by OpenTofu with the Docker provider.
"""
    path = run_dir(req.run_id) / "README_reproduce_this_run.md"
    path.write_text(content, encoding="utf-8")


def call_governance(action: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {
        "participant_id": "vfp-core-hub",
        "action": action,
        "resource": "openhealth-vfp-mvp",
        "experiment_id": RUN_ID,
        "metadata": metadata or {},
    }

    try:
        response = requests.post(GOVERNANCE_URL, json=payload, timeout=5)
        response.raise_for_status()
        result = response.json()
        append_event(
            "governance_response",
            action=action,
            response=result,
        )
        return result
    except Exception as exc:
        append_event(
            "governance_unavailable",
            action=action,
            error=str(exc),
        )
        return {
            "decision": "ALLOW",
            "mode": "hub_fallback",
            "reason": f"governance placeholder unavailable: {exc}",
        }


def initialise_default_run() -> None:
    req = ExperimentInitialiseRequest(
        run_id=RUN_ID,
        dataset=DATASET,
        dataset_subset=DATASET_SUBSET,
        rounds=FLOWER_ROUNDS,
        min_clients=MIN_CLIENTS,
    )

    write_experiment_config(req)
    write_participants(req.run_id)
    ensure_metrics_file(req.run_id)
    write_reproduce_readme(req)

    append_event(
        "experiment_initialised",
        dataset=req.dataset,
        dataset_subset=req.dataset_subset,
        rounds=req.rounds,
        min_clients=req.min_clients,
        governance_mode=GOVERNANCE_MODE,
        fcac_enabled=FCAC_ENABLED,
    )

    register_default_backend()


def register_default_backend() -> None:
    backend = {
        "backend_id": "flower-local",
        "backend_type": "flower",
        "url": FLOWER_BACKEND_URL,
        "metadata": {
            "run_id": RUN_ID,
            "rounds": FLOWER_ROUNDS,
            "min_clients": MIN_CLIENTS,
        },
        "registered_at": utc_now(),
    }

    backend_registry[backend["backend_id"]] = backend

    append_event(
        "backend_registered",
        backend_id=backend["backend_id"],
        backend_type=backend["backend_type"],
        url=backend["url"],
        metadata=backend["metadata"],
    )


# ---------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------

@app.on_event("startup")
def on_startup() -> None:
    run_dir(RUN_ID)

    append_event(
        "hub_starting",
        dataset=DATASET,
        dataset_subset=DATASET_SUBSET,
        flower_backend_url=FLOWER_BACKEND_URL,
        governance_url=GOVERNANCE_URL,
        fcac_enabled=FCAC_ENABLED,
    )

    call_governance(
        action="initialise_experiment",
        metadata={
            "dataset": DATASET,
            "dataset_subset": DATASET_SUBSET,
            "rounds": FLOWER_ROUNDS,
            "min_clients": MIN_CLIENTS,
        },
    )

    initialise_default_run()

    append_event("hub_ready")


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "component": "vfp-core/hub",
        "run_id": RUN_ID,
        "fcac_enabled": FCAC_ENABLED,
    }


@app.get("/status")
def status() -> Dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "dataset": DATASET,
        "dataset_subset": DATASET_SUBSET,
        "flower_rounds": FLOWER_ROUNDS,
        "min_clients": MIN_CLIENTS,
        "flower_backend_url": FLOWER_BACKEND_URL,
        "governance_mode": GOVERNANCE_MODE,
        "fcac_enabled": FCAC_ENABLED,
        "registered_backends": list(backend_registry.keys()),
    }


@app.post("/backend/register")
def backend_register(req: BackendRegistration) -> Dict[str, Any]:
    backend = req.model_dump()
    backend["registered_at"] = utc_now()

    backend_registry[req.backend_id] = backend

    call_governance(
        action="register_backend",
        metadata=backend,
    )

    append_event(
        "backend_registered",
        backend_id=req.backend_id,
        backend_type=req.backend_type,
        url=req.url,
        metadata=req.metadata,
    )

    return {
        "status": "registered",
        "backend": backend,
    }


@app.get("/backend/list")
def backend_list() -> Dict[str, Any]:
    return {
        "backends": list(backend_registry.values()),
    }


@app.post("/experiments/initialise")
def experiments_initialise(req: ExperimentInitialiseRequest) -> Dict[str, Any]:
    write_experiment_config(req)
    write_participants(req.run_id)
    ensure_metrics_file(req.run_id)
    write_reproduce_readme(req)

    call_governance(
        action="initialise_experiment",
        metadata=req.model_dump(),
    )

    append_event(
        "experiment_initialised",
        run_id=req.run_id,
        dataset=req.dataset,
        dataset_subset=req.dataset_subset,
        rounds=req.rounds,
        min_clients=req.min_clients,
    )

    return {
        "status": "initialised",
        "run_id": req.run_id,
        "run_dir": str(run_dir(req.run_id)),
    }


@app.get("/experiments/{run_id}")
def experiment_get(run_id: str) -> Dict[str, Any]:
    folder = run_dir(run_id)
    config_path = folder / "experiment_config.json"
    participants_path = folder / "participants.json"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}")

    return {
        "run_id": run_id,
        "experiment_config": json.loads(config_path.read_text(encoding="utf-8")),
        "participants": (
            json.loads(participants_path.read_text(encoding="utf-8"))
            if participants_path.exists()
            else None
        ),
    }


@app.get("/experiments/{run_id}/events")
def experiment_events(run_id: str, limit: int = 100) -> Dict[str, Any]:
    path = run_dir(run_id) / "events.jsonl"

    if not path.exists():
        return {
            "run_id": run_id,
            "events": [],
        }

    lines = path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines[-limit:] if line.strip()]

    return {
        "run_id": run_id,
        "events": events,
    }


@app.get("/experiments/{run_id}/metrics")
def experiment_metrics(run_id: str) -> Dict[str, Any]:
    path = run_dir(run_id) / "metrics.csv"

    if not path.exists():
        return {
            "run_id": run_id,
            "metrics": [],
        }

    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, Any]] = list(reader)

    return {
        "run_id": run_id,
        "metrics": rows,
    }

@app.post("/clients/register")
def clients_register(req: ClientRegistration) -> Dict[str, Any]:
    experiment_state["registered_clients"][req.org_id] = {
        "org_id": req.org_id,
        "org_label": req.org_label,
        "data_partition": req.data_partition,
        "metadata": req.metadata,
        "registered_at": utc_now(),
    }

    append_event(
        "client_registered",
        run_id=req.run_id,
        org_id=req.org_id,
        org_label=req.org_label,
        data_partition=req.data_partition,
        metadata=req.metadata,
    )

    return {
        "status": "registered",
        "client": experiment_state["registered_clients"][req.org_id],
        "experiment": current_experiment_status(req.run_id),
    }


@app.get("/experiments/{run_id}/status")
def experiment_status(run_id: str) -> Dict[str, Any]:
    return current_experiment_status(run_id)


@app.post("/experiments/{run_id}/start")
def experiment_start(run_id: str) -> Dict[str, Any]:
    status = current_experiment_status(run_id)

    if status["status"] == "running":
        return {
            "run_id": run_id,
            "status": "running",
            "message": "Experiment already running",
            "experiment": status,
        }

    if status["status"] == "completed":
        return {
            "run_id": run_id,
            "status": "completed",
            "message": "Experiment already completed",
            "experiment": status,
        }

    if not status["flower_server_ready"]:
        raise HTTPException(
            status_code=409,
            detail="Flower server is not ready",
        )

    if status["registered_client_count"] < status["min_clients"]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Not enough registered clients: "
                f"{status['registered_client_count']} < {status['min_clients']}"
            ),
        )

    call_governance(
        action="start_experiment",
        metadata=status,
    )

    experiment_state["status"] = "running"

    append_event(
        "experiment_started",
        run_id=run_id,
        registered_clients=status["registered_clients"],
        registered_client_count=status["registered_client_count"],
        min_clients=status["min_clients"],
    )

    return {
        "run_id": run_id,
        "status": "running",
        "message": "Experiment activated",
        "experiment": current_experiment_status(run_id),
    }


@app.post("/experiments/{run_id}/stop")
def experiment_stop(run_id: str) -> Dict[str, Any]:
    experiment_state["status"] = "stopped"

    append_event(
        "experiment_stopped",
        run_id=run_id,
    )

    return {
        "run_id": run_id,
        "status": "stopped",
        "message": "Experiment stopped",
        "experiment": current_experiment_status(run_id),
    }

@app.post("/experiments/{run_id}/complete")
def experiment_complete(run_id: str) -> Dict[str, Any]:
    experiment_state["status"] = "completed"

    append_event(
        "experiment_completed",
        run_id=run_id,
    )

    return {
        "run_id": run_id,
        "status": "completed",
        "message": "Experiment completed",
        "experiment": current_experiment_status(run_id),
    }