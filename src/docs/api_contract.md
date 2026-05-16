# API Contract
This document defines the current API contract for the OpenHealth / VFP MVP.The API is exposed by:

```
vfp-core-hub
```
Local URL:

```
http://localhost:8082
```

Internal Docker URL:

```
http://vfp-core-hub:8080
```

## Scope

The hub API manages experiment metadata, client registration, experiment status, activation, metrics access, and event access.

The hub does not implement FCaC.

The governance layer is currently represented by:

```
vfp-governance-gatekeeper
```

which runs in pass-through mode.


## Milestone 3 frontend contract

Milestone 3 adds a lightweight static frontend served by:

```
vfp-core-frontend
```

Local URL:

http://localhost:3000

The frontend is an evidence dashboard for the local MVP. It does not implement a production OpenHealth user interface.

The frontend uses nginx to proxy API calls to the hub:

/frontend browser → /api/... → vfp-core-hub:8080

Therefore, the frontend calls the hub API through paths such as:

/api/status
/api/experiments/{run_id}
/api/experiments/{run_id}/status
/api/experiments/{run_id}/metrics
/api/experiments/{run_id}/events
/api/experiments/{run_id}/start

These are proxied internally to:

/status
/experiments/{run_id}
/experiments/{run_id}/status
/experiments/{run_id}/metrics
/experiments/{run_id}/events
/experiments/{run_id}/start
Frontend lifecycle behavior

The Milestone 3 frontend supports the current one-run lifecycle:

waiting → running → completed

The START button calls:

POST /api/experiments/{run_id}/start

The dashboard auto-polls the hub API to update:

experiment status;
registered clients;
round progress;
metrics table;
event timeline;
configuration;
evidence summary.

Manual refresh is not part of the Milestone 3 contract. The dashboard uses automatic polling.

Frontend limitations

The Milestone 3 frontend does not provide:

reset/new-run capability;
full experiment parameter editing;
graph rendering for accuracy/loss;
Grafana or Prometheus integration;
authentication;
production UI behavior.

Reusable experiment lifecycle, editable parameters, and richer observability are deferred to a later milestone.

## Status

### `GET /health`

Returns hub health.

Example:

```
curl http://localhost:8082/health | jq
```

Example response:

```
{  "status": "ok",  "component": "vfp-core/hub",  "run_id": "local-medmnist-001",  "fcac_enabled": false}
```

### `GET /status`

Returns global hub status and current default experiment settings.

Example:

```
curl http://localhost:8082/status | jq
```

----------

## Client registration

### `POST /clients/register`

Registers a Flower client with the hub.

This endpoint is normally called by the Flower client container at startup.

Example request:

```
{  "run_id": "local-medmnist-001",  "org_id": "org_a",  "org_label": "Org A",  "data_partition": 0,  "metadata": {    "dataset": "pneumoniamnist",    "num_partitions": 2  }}
```

Example response:

```
{  "status": "registered",  "client": {    "org_id": "org_a",    "org_label": "Org A",    "data_partition": 0  },  "experiment": {    "run_id": "local-medmnist-001",    "status": "waiting",    "registered_clients": ["org_a", "org_b"],    "registered_client_count": 2,    "min_clients": 2,    "can_start": true  }}
```

----------

## Experiment configuration

### `POST /experiments`

Creates or updates an experiment configuration.

This endpoint is intended for the future frontend "New Experiment" form.

Example request:

```
{  "run_id": "local-medmnist-001",  "dataset": "medmnist",  "dataset_subset": "pneumoniamnist",  "rounds": 10,  "min_clients": 2,  "local_epochs": 1,  "batch_size": 32,  "learning_rate": 0.001,  "selected_orgs": ["org_a", "org_b"],  "split_strategy": "iid_modulo",  "governance_mode": "pass_through",  "fcac_enabled": false}
```

Expected behavior:

-   writes `experiment_config.json`;
-   initializes or updates experiment state;
-   writes an `experiment_configured` event;
-   does not start the experiment.

Example response:

```
{  "status": "configured",  "run_id": "local-medmnist-001",  "experiment": {    "run_id": "local-medmnist-001",    "dataset": "medmnist",    "dataset_subset": "pneumoniamnist",    "rounds": 10,    "min_clients": 2,    "selected_orgs": ["org_a", "org_b"],    "status": "waiting"  }}
```

If this endpoint is not yet implemented in the current code, the equivalent behavior is currently provided by `/experiments/initialise`.

----------

## Experiment status

### `GET /experiments/{run_id}/status`

Returns current experiment readiness and lifecycle state.

Example:

```
curl http://localhost:8082/experiments/local-medmnist-001/status | jq
```

Example response before START:

```
{  "run_id": "local-medmnist-001",  "status": "waiting",  "flower_server_ready": true,  "registered_clients": ["org_a", "org_b"],  "registered_client_count": 2,  "min_clients": 2,  "can_start": true,  "fcac_enabled": false,  "governance_mode": "pass_through"}
```

Example response after START:

```
{  "run_id": "local-medmnist-001",  "status": "running",  "flower_server_ready": true,  "registered_clients": ["org_a", "org_b"],  "registered_client_count": 2,  "min_clients": 2,  "can_start": false,  "fcac_enabled": false,  "governance_mode": "pass_through"}
```

----------

## Experiment activation

### `POST /experiments/{run_id}/start`

Activates the experiment.

This endpoint simulates the future frontend START button.

Example:

```
curl -X POST http://localhost:8082/experiments/local-medmnist-001/start | jq
```

Expected behavior:

-   checks that the Flower server is ready;
-   checks that enough clients are registered;
-   calls the pass-through gatekeeper;
-   sets experiment status to `running`;
-   writes an `experiment_started` event;
-   clients detect activation and connect to Flower.

Example response:

```
{  "run_id": "local-medmnist-001",  "status": "running",  "message": "Experiment activated",  "experiment": {    "run_id": "local-medmnist-001",    "status": "running",    "registered_clients": ["org_a", "org_b"],    "registered_client_count": 2,    "min_clients": 2  }}
```

### `POST /experiments/{run_id}/stop`

Stops or disables the experiment lifecycle state.

Example:

```
curl -X POST http://localhost:8082/experiments/local-medmnist-001/stop | jq
```

Current behavior:

-   sets experiment status to `stopped`;
-   writes an `experiment_stopped` event.

This does not yet terminate Docker containers. Container lifecycle remains managed by OpenTofu in the local MVP.

----------

## Experiment metadata

### `GET /experiments/{run_id}`

Returns experiment configuration and participant metadata.

Example:

```
curl http://localhost:8082/experiments/local-medmnist-001 | jq
```

Expected response includes:

-   `experiment_config`;
-   `participants`.

----------

## Experiment metrics

### `GET /experiments/{run_id}/metrics`

Returns parsed metrics from:

```
runs/<run_id>/metrics.csv
```

Example:

```
curl http://localhost:8082/experiments/local-medmnist-001/metrics | jq
```

Metrics may include:

-   round;
-   fit client count;
-   fit failure count;
-   evaluation client count;
-   evaluation failure count;
-   loss;
-   accuracy;
-   train loss;
-   train accuracy.

----------

## Experiment events

### `GET /experiments/{run_id}/events`

Returns recent lifecycle and admission events from:

```
runs/<run_id>/events.jsonl
```

Example:

```
curl "http://localhost:8082/experiments/local-medmnist-001/events?limit=50" | jq
```

Events may include:

-   `hub_starting`;
-   `experiment_initialised`;
-   `client_registered`;
-   `experiment_started`;
-   `admission_check`;
-   `client_activation_received`;
-   `fit_started`;
-   `fit_completed`;
-   `round_fit_aggregated`;
-   `round_evaluate_aggregated`;
-   `server_completed`.

----------

## Governance API

The gatekeeper is exposed locally at:

```
http://localhost:8081
```

### `GET /health`

```
curl http://localhost:8081/health | jq
```

### `POST /admission/check`

Example request:

```
{  "participant_id": "org_a",  "action": "join_experiment",  "resource": "medmnist-baseline",  "experiment_id": "local-medmnist-001",  "metadata": {    "dataset": "pneumoniamnist"  }}
```

Example response:

```
{  "decision": "ALLOW",  "mode": "pass_through",  "reason": "vfp-governance placeholder: FCaC verification not enabled"}
```

## Current limitations

The current API does not provide:

-   authentication;
-   authorization;
-   real policy enforcement;
-   FCaC verification;
-   token validation;
-   proof-of-possession;
-   consent workflows;
-   production orchestration;
-   Docker lifecycle management;
-   multi-run isolation.

The API is a minimal control-plane contract for the educational MVP.
