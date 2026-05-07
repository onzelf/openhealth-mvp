import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import flwr as fl
from flwr.common import Metrics, Parameters, Scalar
from flwr.server.client_proxy import ClientProxy
from flwr.server.strategy import FedAvg


# ---------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------

RUN_ID = os.getenv("RUN_ID", "local-medmnist-001")
RUNS_DIR = Path(os.getenv("RUNS_DIR", "/app/runs"))

FLOWER_ROUNDS = int(os.getenv("FLOWER_ROUNDS", "3"))
MIN_CLIENTS = int(os.getenv("MIN_CLIENTS", "2"))

SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "0.0.0.0:8080")


# ---------------------------------------------------------------------
# Evidence paths
# ---------------------------------------------------------------------

def run_dir() -> Path:
    path = RUNS_DIR / RUN_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def events_path() -> Path:
    return run_dir() / "events.jsonl"


def metrics_path() -> Path:
    return run_dir() / "metrics.csv"


def participants_path() -> Path:
    return run_dir() / "participants.json"


def final_model_metadata_path() -> Path:
    return run_dir() / "final_model_metadata.json"


def experiment_config_path() -> Path:
    return run_dir() / "experiment_config.json"


# ---------------------------------------------------------------------
# Evidence logging
# ---------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_event(event_type: str, **kwargs: Any) -> None:
    event = {
        "timestamp": utc_now(),
        "run_id": RUN_ID,
        "component": "vfp-core/flower_server",
        "event_type": event_type,
        **kwargs,
    }

    with events_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def ensure_metrics_header() -> None:
    path = metrics_path()
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


def append_metrics_row(
    server_round: int,
    fit_client_count: int = 0,
    fit_failure_count: int = 0,
    eval_client_count: int = 0,
    eval_failure_count: int = 0,
    loss: Optional[float] = None,
    accuracy: Optional[float] = None,
    train_loss: Optional[float] = None,
    train_accuracy: Optional[float] = None,
) -> None:
    ensure_metrics_header()

    with metrics_path().open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                RUN_ID,
                server_round,
                fit_client_count,
                fit_failure_count,
                eval_client_count,
                eval_failure_count,
                "" if loss is None else loss,
                "" if accuracy is None else accuracy,
                "" if train_loss is None else train_loss,
                "" if train_accuracy is None else train_accuracy,
            ]
        )


def write_experiment_config() -> None:
    config = {
        "run_id": RUN_ID,
        "flower_rounds": FLOWER_ROUNDS,
        "min_clients": MIN_CLIENTS,
        "server_address": SERVER_ADDRESS,
        "scope": {
            "vfp_core": "implemented FL infrastructure baseline",
            "vfp_governance": "placeholder only",
            "fcac": "not implemented",
        },
    }

    with experiment_config_path().open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def write_final_model_metadata(rounds_completed: int) -> None:
    metadata = {
        "run_id": RUN_ID,
        "timestamp": utc_now(),
        "rounds_completed": rounds_completed,
        "model_artifact": None,
        "note": (
            "MVP metadata only. Model artifact persistence is reserved "
            "for a later milestone."
        ),
    }

    with final_model_metadata_path().open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def write_participants(participants: Dict[str, Dict[str, Any]]) -> None:
    payload = {
        "run_id": RUN_ID,
        "participants": participants,
    }

    with participants_path().open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# ---------------------------------------------------------------------
# Metric aggregation
# ---------------------------------------------------------------------

def weighted_average(metrics: List[Tuple[int, Metrics]], key: str) -> Optional[float]:
    total_examples = 0
    weighted_sum = 0.0

    for num_examples, metric in metrics:
        value = metric.get(key)
        if value is None:
            continue
        total_examples += num_examples
        weighted_sum += num_examples * float(value)

    if total_examples == 0:
        return None

    return weighted_sum / total_examples


def fit_metrics_aggregation_fn(metrics: List[Tuple[int, Metrics]]) -> Metrics:
    result: Metrics = {}

    train_loss = weighted_average(metrics, "train_loss")
    train_accuracy = weighted_average(metrics, "train_accuracy")

    if train_loss is not None:
        result["train_loss"] = train_loss
    if train_accuracy is not None:
        result["train_accuracy"] = train_accuracy

    return result


def evaluate_metrics_aggregation_fn(metrics: List[Tuple[int, Metrics]]) -> Metrics:
    result: Metrics = {}

    accuracy = weighted_average(metrics, "accuracy")

    if accuracy is not None:
        result["accuracy"] = accuracy

    return result


# ---------------------------------------------------------------------
# Evidence-aware Flower strategy
# ---------------------------------------------------------------------

class EvidenceFedAvg(FedAvg):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.participants: Dict[str, Dict[str, Any]] = {}

    def configure_fit(
        self,
        server_round: int,
        parameters: Parameters,
        client_manager: Any,
    ):
        write_event(
            "round_fit_configured",
            round=server_round,
            min_clients=MIN_CLIENTS,
        )
        return super().configure_fit(server_round, parameters, client_manager)

    def aggregate_fit(
        self,
        server_round: int,
        results: List[Tuple[ClientProxy, Any]],
        failures: List[Any],
    ):
        parameters_aggregated, metrics_aggregated = super().aggregate_fit(
            server_round,
            results,
            failures,
        )

        for _client, fit_res in results:
            org_id = fit_res.metrics.get("org_id")
            if org_id:
                self.participants[str(org_id)] = {
                    "org_id": str(org_id),
                    "last_seen_round": server_round,
                    "last_event": "fit_completed",
                }

        write_participants(self.participants)

        write_event(
            "round_fit_aggregated",
            round=server_round,
            client_count=len(results),
            failure_count=len(failures),
            metrics=metrics_aggregated,
        )

        append_metrics_row(
            server_round=server_round,
            fit_client_count=len(results),
            fit_failure_count=len(failures),
            train_loss=metrics_aggregated.get("train_loss"),
            train_accuracy=metrics_aggregated.get("train_accuracy"),
        )

        return parameters_aggregated, metrics_aggregated

    def configure_evaluate(
        self,
        server_round: int,
        parameters: Parameters,
        client_manager: Any,
    ):
        write_event(
            "round_evaluate_configured",
            round=server_round,
        )
        return super().configure_evaluate(server_round, parameters, client_manager)

    def aggregate_evaluate(
        self,
        server_round: int,
        results: List[Tuple[ClientProxy, Any]],
        failures: List[Any],
    ):
        loss_aggregated, metrics_aggregated = super().aggregate_evaluate(
            server_round,
            results,
            failures,
        )

        for _client, eval_res in results:
            org_id = eval_res.metrics.get("org_id")
            if org_id:
                self.participants[str(org_id)] = {
                    "org_id": str(org_id),
                    "last_seen_round": server_round,
                    "last_event": "evaluate_completed",
                }

        write_participants(self.participants)

        write_event(
            "round_evaluate_aggregated",
            round=server_round,
            client_count=len(results),
            failure_count=len(failures),
            loss=loss_aggregated,
            metrics=metrics_aggregated,
        )

        append_metrics_row(
            server_round=server_round,
            eval_client_count=len(results),
            eval_failure_count=len(failures),
            loss=loss_aggregated,
            accuracy=metrics_aggregated.get("accuracy"),
        )

        return loss_aggregated, metrics_aggregated


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    run_dir()
    ensure_metrics_header()
    write_experiment_config()

    write_event(
        "server_starting",
        server_address=SERVER_ADDRESS,
        flower_rounds=FLOWER_ROUNDS,
        min_clients=MIN_CLIENTS,
        strategy="FedAvg",
    )

    strategy = EvidenceFedAvg(
        fraction_fit=1.0,
        fraction_evaluate=1.0,
        min_fit_clients=MIN_CLIENTS,
        min_evaluate_clients=MIN_CLIENTS,
        min_available_clients=MIN_CLIENTS,
        fit_metrics_aggregation_fn=fit_metrics_aggregation_fn,
        evaluate_metrics_aggregation_fn=evaluate_metrics_aggregation_fn,
    )

    fl.server.start_server(
        server_address=SERVER_ADDRESS,
        config=fl.server.ServerConfig(num_rounds=FLOWER_ROUNDS),
        strategy=strategy,
    )

    write_final_model_metadata(rounds_completed=FLOWER_ROUNDS)
    write_event(
        "server_completed",
        flower_rounds=FLOWER_ROUNDS,
    )


if __name__ == "__main__":
    main()