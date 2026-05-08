# Open Health / VFP Federated Computing MVP

This repository provides a minimal, open, reproducible baseline scaffold for **Federated Computing infrastructure** in the Open Health / VFP context.

The MVP is intentionally small. Its purpose is to demonstrate a local federated execution path using Docker services managed by OpenTofu, with a real biomedical educational dataset and a clear evidence trail.

## Purpose

The project provides a reference scaffold for:

- Federated Computing infrastructure education;
- reproducible federated-learning experiments;
- Open Health MVP development;
- future AWS/OpenTofu deployment;
- future FCaC-style governance extensions.

The MVP is **not** a production Open Health platform.

## Architectural split

The repository separates the working federated infrastructure from future governance work.

| Module | Role in this MVP | Status |
|---|---|---|
| `vfp-core` | Runs the federated infrastructure and FL workload | Implemented by the MVP |
| `vfp-governance` | Provides a placeholder admission/governance seam | Pass-through only |
| `infra/opentofu/local-docker` | Provisions local Docker services using OpenTofu | First deployment target |
| `infra/opentofu/aws` | Future AWS/OpenTofu deployment target | Planned |
| `datasets/medmnist` | Dataset preparation and partitioning | Planned |
| `experiments/medmnist-baseline` | Reproducible baseline experiment configuration | Planned |
| `runs/` | Run artefacts: metrics, events, configs, outputs | Generated at runtime |

## What this MVP implements

### Milestone 1 — Local OpenTofu/Docker FL baseline
Milestone 1 proves that the MVP can execute a reproducible federated-learning experiment over a biomedical educational dataset and generate inspectable evidence artefacts.

Limitations of Milestone 1:

- clients start according to container startup order;
- experiment activation is not yet controlled by the hub;
- the frontend is not yet implemented;
- vfp-governance is pass-through only;
- FCaC is not implemented.

Milestone 2 addresses the startup-order limitation by introducing hub-controlled experiment activation.
The first milestone is a local OpenTofu-managed Docker deployment with:

- local OpenTofu-managed Docker deployment;
- Flower/FedAvg execution;
- two simulated organisations: `org_a` and `org_b`;
- MedMNIST/PneumoniaMNIST as the biomedical educational dataset;
- dataset partitioning across the two organisations;
- local training on each client;
- aggregation by the Flower server;
- metrics generation;
- event logging;
- dataset split summary generation;
- run artefacts stored under `runs/<run_id>/`.

The local MVP uses OpenTofu with the `kreuzwerker/docker` provider to provision Docker services. This establishes the same infrastructure-as-code workflow that can later be extended to AWS.

## What this MVP does not implement

This MVP does **not** implement:

- FCaC;
- cryptographic admission control;
- signed capability tokens;
- proof-of-possession;
- healthcare consent workflows;
- production governance-as-code;
- differential privacy;
- secure aggregation;
- homomorphic encryption;
- trusted execution environments;
- EHR/FHIR/DICOM integration;
- production UX;
- clinical validation.

`vfp-governance` is included only as an explicit future extension point.

## Governance placeholder

In the MVP, `vfp-governance` operates in pass-through mode.

Example response:

```json
{
  "decision": "ALLOW",
  "mode": "pass_through",
  "reason": "vfp-governance placeholder: FCaC verification not enabled"
}
```

### Milestone 2: hub-controlled experiment activation
This Milestone removes startup timing assumptions from the local MVP.

OpenTofu still provisions the local Docker substrate and starts the services, but the experiment lifecycle is now controlled by the `vfp-core` hub.

Runtime flow:

```
tofu apply
  ├── starts vfp-governance-gatekeeper
  ├── starts vfp-core-hub
  ├── starts vfp-core-flower-server
  └── starts vfp-core-flower-client-org_a / org_b

clients
  ├── register with the hub
  └── wait for experiment activation

user / CLI / future frontend
  └── POST /experiments/{run_id}/start

hub
  └── sets experiment status to running

clients
  └── connect to Flower server and run the FL experiment
```