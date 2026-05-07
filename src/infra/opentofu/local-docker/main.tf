 terraform {
  required_version = ">= 1.6.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

# ------------------------------------------------------------
# OpenHealth / VFP local Docker MVP
#
# Docker is the runtime.
# OpenTofu is the deployment authority.
#
# Services:
# - vfp-governance-gatekeeper: pass-through governance placeholder
# - vfp-core-hub: FastAPI orchestrator / coordination service
# - vfp-core-flower-server: Flower aggregation backend
# - vfp-core-flower-client-* : organisation-side FL clients
#
# FCaC is not implemented here.
# vfp-governance is placeholder only.
# ------------------------------------------------------------

locals {
  repo_root = abspath("${path.module}/../../..")

  run_id = "local-medmnist-001"

  dataset        = "medmnist"
  dataset_subset = "pneumoniamnist"

  flower_rounds = 5

  orgs = {
    org_a = {
      label     = "Org A"
      partition = "0"
      enabled   = true
    }

    org_b = {
      label     = "Org B"
      partition = "1"
      enabled   = true
    }

    # Reserved for later scale-out / dropout tests.
    org_c = {
      label     = "Org C"
      partition = "2"
      enabled   = false
    }
  }

  enabled_orgs = {
    for k, v in local.orgs : k => v if v.enabled
  }
}

# ------------------------------------------------------------
# Local Docker substrate
# ------------------------------------------------------------

resource "docker_network" "vfp" {
  name = "vfp-local-net"
}

resource "docker_volume" "runs" {
  name = "vfp-runs"
}

# ------------------------------------------------------------
# vfp-governance: gatekeeper placeholder
# ------------------------------------------------------------

resource "docker_image" "gatekeeper" {
  name = "vfp-governance-gatekeeper:local"

  build {
    context = "${local.repo_root}/vfp-governance/gatekeeper"
  }
}

resource "docker_container" "gatekeeper" {
  name  = "vfp-governance-gatekeeper"
  image = docker_image.gatekeeper.image_id

  networks_advanced {
    name = docker_network.vfp.name
  }

  ports {
    internal = 8080
    external = 8081
  }

  volumes {
    volume_name    = docker_volume.runs.name
    container_path = "/app/runs"
  }

  env = [
    "RUN_ID=${local.run_id}",
    "RUNS_DIR=/app/runs",
    "GOVERNANCE_MODE=pass_through"
  ]
}

# ------------------------------------------------------------
# vfp-core: hub / orchestrator
# ------------------------------------------------------------

resource "docker_image" "hub" {
  name = "vfp-core-hub:local"

  build {
    context = "${local.repo_root}/vfp-core/hub"
  }
}

resource "docker_container" "hub" {
  name  = "vfp-core-hub"
  image = docker_image.hub.image_id

  networks_advanced {
    name = docker_network.vfp.name
  }

  ports {
    internal = 8080
    external = 8080
  }

  volumes {
    volume_name    = docker_volume.runs.name
    container_path = "/app/runs"
  }

  env = [
    "RUN_ID=${local.run_id}",
    "RUNS_DIR=/app/runs",
    "DATASET=${local.dataset}",
    "DATASET_SUBSET=${local.dataset_subset}",
    "FLOWER_ROUNDS=${local.flower_rounds}",
    "MIN_CLIENTS=${length(local.enabled_orgs)}",
    "ORGS_JSON=${jsonencode(local.enabled_orgs)}",
    "FLOWER_BACKEND_URL=vfp-core-flower-server:8080",
    "GOVERNANCE_URL=http://vfp-governance-gatekeeper:8080/admission/check",
    "GOVERNANCE_MODE=pass_through",
    "FCAC_ENABLED=false"
  ]

  depends_on = [
    docker_container.gatekeeper
  ]
}

# ------------------------------------------------------------
# vfp-core: Flower server / aggregation backend
# ------------------------------------------------------------

resource "docker_image" "flower_server" {
  name = "vfp-core-flower-server:local"

  build {
    context = "${local.repo_root}/vfp-core/services/fl-server"
  }
}

resource "docker_container" "flower_server" {
  name     = "vfp-core-flower-server"
  image    = docker_image.flower_server.image_id
  

  networks_advanced {
    name = docker_network.vfp.name
  }

  ports {
    internal = 8080
    external = 9090
  }

  volumes {
    volume_name    = docker_volume.runs.name
    container_path = "/app/runs"
  }

  env = [
    "RUN_ID=${local.run_id}",
    "RUNS_DIR=/app/runs",
    "FLOWER_ROUNDS=${local.flower_rounds}",
    "MIN_CLIENTS=${length(local.enabled_orgs)}",
    "SERVER_ADDRESS=0.0.0.0:8080",
    "GOVERNANCE_URL=http://vfp-governance-gatekeeper:8080/admission/check"
  ]

  depends_on = [docker_container.gatekeeper, docker_container.hub]
  must_run = true
  restart = "unless-stopped"
}

# ------------------------------------------------------------
# vfp-core: Flower clients / organisation nodes
# ------------------------------------------------------------

resource "docker_image" "flower_client" {
  name = "vfp-core-flower-client:local"

  build {
    context = "${local.repo_root}/vfp-core/services/fl-client"
  }
}

resource "docker_container" "flower_client" {
  for_each = local.enabled_orgs

  name     = "vfp-core-flower-client-${each.key}"
  image    = docker_image.flower_client.image_id
   

  networks_advanced {
    name = docker_network.vfp.name
  }

  volumes {
    volume_name    = docker_volume.runs.name
    container_path = "/app/runs"
  }

  env = [
    "RUN_ID=${local.run_id}",
    "CLIENT_START_DELAY_SECONDS=8",
    "RUNS_DIR=/app/runs",
    "ORG_ID=${each.key}",
    "ORG_LABEL=${each.value.label}",
    "DATA_PARTITION=${each.value.partition}",
    "NUM_PARTITIONS=${length(local.enabled_orgs)}",
    "MEDMNIST_DATASET=${local.dataset_subset}",
    "FLOWER_SERVER_URL=vfp-core-flower-server:8080",
    "GOVERNANCE_URL=http://vfp-governance-gatekeeper:8080/admission/check"
  ]

  depends_on = [docker_container.flower_server]
  must_run = true
  restart  = "no"
}

# ------------------------------------------------------------
# Outputs
# ------------------------------------------------------------

output "run_id" {
  value = local.run_id
}

output "repo_root" {
  value = local.repo_root
}

output "docker_network" {
  value = docker_network.vfp.name
}

output "runs_volume" {
  value = docker_volume.runs.name
}

output "hub_url" {
  value = "http://localhost:8080"
}

output "gatekeeper_url" {
  value = "http://localhost:8081"
}

output "flower_server_url" {
  value = "localhost:9090"
}

output "enabled_organisations" {
  value = keys(local.enabled_orgs)
}