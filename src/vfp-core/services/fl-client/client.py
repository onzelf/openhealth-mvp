import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import flwr as fl
import medmnist
import numpy as np
import requests
import torch
import torch.nn as nn
import torch.nn.functional as F
from medmnist import INFO
from torch.utils.data import DataLoader, Subset
from torchvision import transforms


# ---------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------

HUB_URL = os.getenv("HUB_URL", "http://vfp-core-hub:8080")
CLIENT_POLL_SECONDS = int(os.getenv("CLIENT_POLL_SECONDS", "2"))
CLIENT_CONNECT_RETRY_SECONDS = int(os.getenv("CLIENT_CONNECT_RETRY_SECONDS", "2"))

RUN_ID = os.getenv("RUN_ID", "local-medmnist-001")
RUNS_DIR = Path(os.getenv("RUNS_DIR", "/app/runs"))

ORG_ID = os.getenv("ORG_ID", "org_unknown")
ORG_LABEL = os.getenv("ORG_LABEL", ORG_ID)
DATA_PARTITION = int(os.getenv("DATA_PARTITION", "0"))
NUM_PARTITIONS = int(os.getenv("NUM_PARTITIONS", "2"))

FLOWER_SERVER_URL = os.getenv("FLOWER_SERVER_URL", "http://vfp-core-flower-server:8080")
GOVERNANCE_URL = os.getenv(
    "GOVERNANCE_URL",
    "http://vfp-governance-gatekeeper:8080/admission/check",
)

DATASET_FLAG = os.getenv("MEDMNIST_DATASET", "pneumoniamnist")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "32"))
LOCAL_EPOCHS = int(os.getenv("LOCAL_EPOCHS", "3"))
LEARNING_RATE = float(os.getenv("LEARNING_RATE", "0.001"))

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def flower_server_address() -> str:
    """Flower expects host:port, not http://host:port."""
    return (
        FLOWER_SERVER_URL.replace("http://", "")
        .replace("https://", "")
        .rstrip("/")
    )


# ---------------------------------------------------------------------
# Evidence logging
# ---------------------------------------------------------------------

def run_dir() -> Path:
    path = RUNS_DIR / RUN_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def experiment_config_path() -> Path:
    return run_dir() / "experiment_config.json"


def configured_local_epochs() -> int:
    if not experiment_config_path().exists():
        return LOCAL_EPOCHS

    try:
        config = json.loads(experiment_config_path().read_text(encoding="utf-8"))
        local_epochs = int(config.get("local_epochs", LOCAL_EPOCHS))
        return max(1, local_epochs)
    except Exception as exc:
        write_event("experiment_config_read_failed", error=str(exc))
        return LOCAL_EPOCHS


def json_safe(value: Any) -> Any:
    """Convert values to JSON-serialisable representations for evidence logs."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]

    # Flower sometimes passes ConfigRecord or other typed records.
    # For MVP evidence logs, string representation is sufficient.
    return str(value)


def write_event(event_type: str, **kwargs: Any) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "component": "vfp-core/flower_client",
        "event_type": event_type,
        "org_id": ORG_ID,
        "org_label": ORG_LABEL,
        "data_partition": DATA_PARTITION,
        **kwargs,
    }

    safe_event = json_safe(event)

    with (run_dir() / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe_event) + "\n") 


def admission_check(action: str, resource: str = "medmnist-baseline") -> Dict[str, Any]:
    payload = {
        "participant_id": ORG_ID,
        "action": action,
        "resource": resource,
        "experiment_id": RUN_ID,
        "metadata": {
            "org_label": ORG_LABEL,
            "data_partition": DATA_PARTITION,
            "dataset": DATASET_FLAG,
        },
    }

    try:
        response = requests.post(GOVERNANCE_URL, json=payload, timeout=5)
        response.raise_for_status()
        result = response.json()
        write_event("admission_response", action=action, response=result)
        return result
    except Exception as exc:
        write_event("admission_error", action=action, error=str(exc))
        # MVP behaviour: do not block FL execution if placeholder governance is unavailable.
        return {
            "decision": "ALLOW",
            "mode": "client_fallback",
            "reason": f"governance placeholder unavailable: {exc}",
        }


# ---------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------

def load_partition() -> Tuple[DataLoader, DataLoader, int]:
    info = INFO[DATASET_FLAG]
    data_class = getattr(medmnist, info["python_class"])
    n_classes = len(info["label"])

    transform = transforms.Compose(
        [
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.5], std=[0.5]),
        ]
    )

    train_dataset = data_class(split="train", transform=transform, download=True)
    test_dataset = data_class(split="test", transform=transform, download=True)

    train_indices = [
        idx for idx in range(len(train_dataset))
        if idx % NUM_PARTITIONS == DATA_PARTITION
    ]

    test_indices = [
        idx for idx in range(len(test_dataset))
        if idx % NUM_PARTITIONS == DATA_PARTITION
    ]

    train_subset = Subset(train_dataset, train_indices)
    test_subset = Subset(test_dataset, test_indices)

    write_dataset_summary(
        train_count=len(train_subset),
        test_count=len(test_subset),
        n_classes=n_classes,
    )

    train_loader = DataLoader(train_subset, batch_size=BATCH_SIZE, shuffle=True)
    test_loader = DataLoader(test_subset, batch_size=BATCH_SIZE, shuffle=False)

    return train_loader, test_loader, n_classes


def write_dataset_summary(train_count: int, test_count: int, n_classes: int) -> None:
    summary_path = run_dir() / "dataset_split_summary.csv"
    header_needed = not summary_path.exists()

    with summary_path.open("a", encoding="utf-8") as f:
        if header_needed:
            f.write("run_id,org_id,org_label,dataset,partition,num_partitions,train_count,test_count,n_classes\n")
        f.write(
            f"{RUN_ID},{ORG_ID},{ORG_LABEL},{DATASET_FLAG},{DATA_PARTITION},"
            f"{NUM_PARTITIONS},{train_count},{test_count},{n_classes}\n"
        )


# ---------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------

class SmallCNN(nn.Module):
    def __init__(self, num_classes: int):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 16, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc1 = nn.Linear(32 * 7 * 7, 64)
        self.fc2 = nn.Linear(64, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.pool(F.relu(self.conv1(x)))  # 28x28 -> 14x14
        x = self.pool(F.relu(self.conv2(x)))  # 14x14 -> 7x7
        x = x.view(x.size(0), -1)
        x = F.relu(self.fc1(x))
        return self.fc2(x)


def get_parameters(model: nn.Module) -> List[np.ndarray]:
    return [val.cpu().numpy() for _, val in model.state_dict().items()]


def set_parameters(model: nn.Module, parameters: List[np.ndarray]) -> None:
    state_dict = model.state_dict()
    new_state_dict = {
        key: torch.tensor(value)
        for key, value in zip(state_dict.keys(), parameters)
    }
    model.load_state_dict(new_state_dict, strict=True)


def train_one_round(
    model: nn.Module,
    train_loader: DataLoader,
    local_epochs: int,
) -> Tuple[float, float]:
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.CrossEntropyLoss()

    total_loss = 0.0
    correct = 0
    total = 0

    for _ in range(local_epochs):
        for images, labels in train_loader:
            images = images.to(DEVICE)
            labels = labels.squeeze().long().to(DEVICE)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * labels.size(0)
            preds = outputs.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

    avg_loss = total_loss / max(total, 1)
    accuracy = correct / max(total, 1)
    return avg_loss, accuracy


def evaluate_model(model: nn.Module, test_loader: DataLoader) -> Tuple[float, float]:
    model.eval()
    criterion = nn.CrossEntropyLoss()

    total_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for images, labels in test_loader:
            images = images.to(DEVICE)
            labels = labels.squeeze().long().to(DEVICE)

            outputs = model(images)
            loss = criterion(outputs, labels)

            total_loss += loss.item() * labels.size(0)
            preds = outputs.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

    avg_loss = total_loss / max(total, 1)
    accuracy = correct / max(total, 1)
    return avg_loss, accuracy


# ---------------------------------------------------------------------
# Flower client
# ---------------------------------------------------------------------

class VfpFlowerClient(fl.client.NumPyClient):
    def __init__(self, model: nn.Module, train_loader: DataLoader, test_loader: DataLoader):
        self.model = model
        self.train_loader = train_loader
        self.test_loader = test_loader

    def get_parameters(self, config: Dict[str, Any]) -> List[np.ndarray]:
        write_event("get_parameters")
        return get_parameters(self.model)

    def fit(
        self,
        parameters: List[np.ndarray],
        config: Dict[str, Any],
    ) -> Tuple[List[np.ndarray], int, Dict[str, Any]]:
        admission_check("train_local")
        set_parameters(self.model, parameters)
        local_epochs = configured_local_epochs()

        write_event("fit_started", config=config, local_epochs=local_epochs)
        loss, accuracy = train_one_round(
            self.model,
            self.train_loader,
            local_epochs,
        )
        write_event("fit_completed", loss=loss, accuracy=accuracy, local_epochs=local_epochs)

        admission_check("submit_update")

        num_examples = len(self.train_loader.dataset)
        return get_parameters(self.model), num_examples, {
            "train_loss": float(loss),
            "train_accuracy": float(accuracy),
            "org_id": ORG_ID,
        }

    def evaluate(
        self,
        parameters: List[np.ndarray],
        config: Dict[str, Any],
    ) -> Tuple[float, int, Dict[str, Any]]:
        admission_check("evaluate")
        set_parameters(self.model, parameters)

        loss, accuracy = evaluate_model(self.model, self.test_loader)
        write_event("evaluate_completed", loss=loss, accuracy=accuracy)

        num_examples = len(self.test_loader.dataset)
        return float(loss), num_examples, {
            "accuracy": float(accuracy),
            "org_id": ORG_ID,
        }


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    write_event(
        "client_starting",
        dataset=DATASET_FLAG,
        device=str(DEVICE),
        flower_server=flower_server_address(),
    )

    admission_check("join_experiment")

    train_loader, test_loader, n_classes = load_partition()
    model = SmallCNN(num_classes=n_classes).to(DEVICE)

    client = VfpFlowerClient(model, train_loader, test_loader)

    # regisatyer with Hub and wait for starting.
    register_with_hub()
    if not wait_for_experiment_start():
        return

    start_flower_client_with_retry(client)

    write_event("client_completed")


def start_flower_client_with_retry(client: VfpFlowerClient) -> None:
    while True:
        write_event("client_connecting", flower_server=flower_server_address())

        try:
            fl.client.start_numpy_client(
                server_address=flower_server_address(),
                client=client,
            )
            return
        except Exception as exc:
            status = current_experiment_status()
            write_event(
                "client_connection_failed",
                error=str(exc),
                retry_seconds=CLIENT_CONNECT_RETRY_SECONDS,
                experiment_status=status.get("status"),
            )

            if status.get("status") in {"stopped", "completed", "failed"}:
                raise

            time.sleep(CLIENT_CONNECT_RETRY_SECONDS)

def register_with_hub() -> None:
    payload = {
        "run_id": RUN_ID,
        "org_id": ORG_ID,
        "org_label": ORG_LABEL,
        "data_partition": DATA_PARTITION,
        "metadata": {
            "dataset": DATASET_FLAG,
            "num_partitions": NUM_PARTITIONS,
        },
    }

    try:
        response = requests.post(
            f"{HUB_URL}/clients/register",
            json=payload,
            timeout=5,
        )
        response.raise_for_status()
        write_event("hub_registration_completed", response=response.json())
    except Exception as exc:
        write_event("hub_registration_failed", error=str(exc))
        raise


def wait_for_experiment_start() -> bool:
    write_event(
        "client_waiting_for_start",
        hub_url=HUB_URL,
        poll_seconds=CLIENT_POLL_SECONDS,
    )

    while True:
        try:
            response = requests.get(
                f"{HUB_URL}/experiments/{RUN_ID}/status",
                timeout=5,
            )
            response.raise_for_status()
            status = response.json()

            write_event(
                "client_polled_experiment_status",
                status=status.get("status"),
                can_start=status.get("can_start"),
                registered_client_count=status.get("registered_client_count"),
                min_clients=status.get("min_clients"),
            )

            registered_clients = status.get("registered_clients") or []
            if status.get("status") == "waiting" and ORG_ID not in registered_clients:
                write_event("client_reregistering", registered_clients=registered_clients)
                register_with_hub()

            if status.get("status") == "running":
                write_event("client_activation_received")
                return True

            if status.get("status") in {"stopped", "completed", "failed"}:
                write_event(
                    "client_waiting_aborted",
                    status=status.get("status"),
                )
                return False

        except Exception as exc:
            write_event("client_activation_poll_error", error=str(exc))

        time.sleep(CLIENT_POLL_SECONDS)


def current_experiment_status() -> Dict[str, Any]:
    try:
        response = requests.get(
            f"{HUB_URL}/experiments/{RUN_ID}/status",
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        write_event("client_status_check_failed", error=str(exc))
        return {}


if __name__ == "__main__":
    main()
