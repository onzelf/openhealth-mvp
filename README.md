# OpenHealth / VFP Federated Computing MVP

Minimal, reproducible Federated Computing infrastructure scaffold for OpenHealth/VFP, using OpenTofu-managed Docker services, Flower, MedMNIST, and a pass-through governance placeholder.

## Purpose

This repository provides an educational and research-oriented baseline for Federated Computing infrastructure.

The MVP demonstrates how to run a small federated-learning experiment across simulated organisations while preserving a clear separation between:

- `vfp-core`: the working federated execution and orchestration substrate;
- `vfp-governance`: a placeholder for future governance/admission-control extensions;
- `infra/opentofu`: infrastructure-as-code deployment authority;
- `runs`: generated evidence artefacts.

The goal is not to build a production OpenHealth platform. The goal is to provide a transparent scaffold that students and researchers can inspect, run, extend, and later port to AWS.

## Current status

The current local MVP already supports:

- OpenTofu-managed local Docker deployment;
- one local Docker network;
- shared run artefact volume;
- `vfp-core-hub` FastAPI orchestration service;
- `vfp-governance-gatekeeper` pass-through admission placeholder;
- Flower server for aggregation;
- two simulated organisation clients;
- MedMNIST / PneumoniaMNIST dataset partitioning;
- FedAvg execution;
- metrics generation;
- event logging;
- dataset split summary;
- reproducible run artefacts under `runs/<run_id>/`.

The first validated run uses:

- dataset: `pneumoniamnist`;
- organisations: `org_a`, `org_b`;
- clients: 2;
- aggregation: FedAvg;
- rounds: configurable through OpenTofu;
- governance mode: pass-through;
- FCaC: not enabled.

## Repository structure

```text
src/
├── datasets/
│   └── medmnist/
├── docs/
├── experiments/
├── infra/
│   └── opentofu/
│       ├── aws/
│       ├── local-docker/
│       └── modules/
│           ├── docker_network/
│           ├── docker_service/
│           └── docker_volume/
├── runs/
├── vfp-core/
│   ├── services/
│   │   ├── fl-client/
│   │   └── fl-server/
│   ├── frontend/
│   └── hub/
└── vfp-governance/
    ├── gatekeeper/
    └── verifier/ 

## 🚀 Getting Started

### Prerequisites

Before you begin, ensure you have:

- ✅ **Docker Engine** installed
- ✅ **OpenTofu** (or Terraform) installed
- ✅ **Python 3** (for helper scripts used by Test #2)


### Build + Provision

From repo root:

```bash
cd infra/tofu
tofu init
tofu apply -auto-approve
```

This starts the docker network and containers (hub, flower client/server components).

### Results

```bash 
docker run --rm -v vfp-runs:/runs alpine sh -c "cat /runs/local-medmnist-001/dataset_split_summary.csv"
```

| run_id | org_id | org_label | dataset | partition | num_partitions | train_count | test_count | n_classes |
|---|---|---|---|---|---|---|---|---|
| local-medmnist-001 | org_b | Org B | pneumoniamnist | 1 | 2 | 2354 | 312 | 2 |
| local-medmnist-001 | org_a | Org A | pneumoniamnist | 0 | 2 | 2354 | 312 | 2 |





