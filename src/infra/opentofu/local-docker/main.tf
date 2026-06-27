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
# - vfp-governance-gatekeeper: FLICS-compatible admission verifier
# - vfp-governance-verifier-proxy: local mTLS edge for verifier checks
# - vfp-core-issuer-* / holder-signer / redis: FLICS governance support
# - vfp-core-hub: FastAPI orchestrator / coordination service
# - vfp-core-flower-server: Flower aggregation backend
# - vfp-core-flower-client-* : organisation-side FL clients
#
# FCaC is disabled by default for backwards-compatible local MVP runs.
# ------------------------------------------------------------

locals {
  repo_root = abspath("${path.module}/../../..")

  run_id = "local-medmnist-001"

  dataset        = "medmnist"
  dataset_subset = "pneumoniamnist"

  flower_rounds = 10

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

resource "docker_volume" "issuer_registry_org_a" {
  name = "vfp-issuer-registry-org-a"
}

resource "docker_volume" "issuer_registry_org_b" {
  name = "vfp-issuer-registry-org-b"
}

# ------------------------------------------------------------
# vfp-governance: FLICS governance substrate
# ------------------------------------------------------------

resource "docker_image" "redis" {
  name         = "redis:7-alpine"
  keep_locally = true
}

resource "docker_container" "redis" {
  name  = "vfp-governance-redis"
  image = docker_image.redis.name

  networks_advanced {
    name    = docker_network.vfp.name
    aliases = ["redis"]
  }

  must_run = true
  restart  = "unless-stopped"
}

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
    name    = docker_network.vfp.name
    aliases = ["verifier-app"]
  }

  ports {
    internal = 9000
    external = 8081
    ip       = "127.0.0.1"
  }

  volumes {
    volume_name    = docker_volume.runs.name
    container_path = "/app/runs"
  }

  volumes {
    host_path      = "${local.repo_root}/vfp-governance/verifier/state"
    container_path = "/app/state"
  }

  volumes {
    host_path      = "${local.repo_root}/vfp-governance/verifier/certs"
    container_path = "/app/verifier/certs"
    read_only      = true
  }

  env = [
    "RUN_ID=${local.run_id}",
    "RUNS_DIR=/app/runs",
    "GOVERNANCE_MODE=strict",
    "FCAC_ENABLED=true",
    "FCAC_STATE_DIR=/app/state",
    "FCAC_CERTS_DIR=/app/verifier/certs",
    "REDIS_URL=redis://vfp-governance-redis:6379/0",
    "FCAC_ENVELOPE_CHANNEL=fcac:envelopes:created",
    "REQUIRE_MTLS_HEADERS=true",
    "ISS=http://vfp-governance-gatekeeper:9000",
    "AUD=svc:openhealth-vfp-local"
  ]

  depends_on = [docker_container.redis]
  must_run   = true
  restart    = "unless-stopped"
}

resource "docker_image" "verifier_proxy" {
  name = "vfp-governance-verifier-proxy:local"

  build {
    context = "${local.repo_root}/vfp-governance/verifier/nginx"
  }
}

resource "docker_container" "verifier_proxy" {
  name  = "vfp-governance-verifier-proxy"
  image = docker_image.verifier_proxy.image_id

  networks_advanced {
    name    = docker_network.vfp.name
    aliases = ["verifier.local"]
  }

  ports {
    internal = 8443
    external = 8443
    ip       = "127.0.0.1"
  }

  volumes {
    host_path      = "${local.repo_root}/vfp-governance/verifier/certs"
    container_path = "/etc/nginx/certs"
    read_only      = true
  }

  depends_on = [docker_container.gatekeeper]
  must_run   = true
  restart    = "unless-stopped"
}

resource "docker_image" "holder_signer" {
  name = "vfp-governance-holder-signer:local"

  build {
    context = "${local.repo_root}/vfp-governance/signer"
  }
}

resource "docker_container" "holder_signer" {
  name  = "vfp-governance-holder-signer"
  image = docker_image.holder_signer.image_id

  networks_advanced {
    name    = docker_network.vfp.name
    aliases = ["holder-signer"]
  }

  volumes {
    host_path      = "${local.repo_root}/vfp-governance/verifier/vault/holder_keys"
    container_path = "/vault/holder_keys"
    read_only      = true
  }

  env = [
    "HOLDER_KEYS_DIR=/vault/holder_keys"
  ]

  must_run = true
  restart  = "unless-stopped"
}

resource "docker_image" "issuer" {
  name = "vfp-core-issuer:local"

  build {
    context = "${local.repo_root}/vfp-core/issuers"
  }
}

resource "docker_container" "issuer_org_a" {
  name  = "vfp-core-issuer-org-a"
  image = docker_image.issuer.image_id

  networks_advanced {
    name    = docker_network.vfp.name
    aliases = ["issuer-hospitala"]
  }

  volumes {
    volume_name    = docker_volume.issuer_registry_org_a.name
    container_path = "/vault/registry"
  }

  volumes {
    host_path      = "${local.repo_root}/vfp-governance/verifier/certs"
    container_path = "/run/certs"
    read_only      = true
  }

  env = [
    "ORG=org://HospitalA",
    "VERIFIER_URL=https://verifier.local:8443",
    "CA_CRT=/run/certs/ca.crt",
    "VERIFY_TLS=1",
    "ADMIN_CRT=/run/certs/HospitalA-admin.crt",
    "ADMIN_KEY=/run/certs/HospitalA-admin.key",
    "REGISTRY_DIR=/vault/registry",
    "CAP_PROFILE_PATH=/app/config/cap_profiles.json"
  ]

  depends_on = [docker_container.verifier_proxy]
  must_run   = true
  restart    = "unless-stopped"
}

resource "docker_container" "issuer_org_b" {
  name  = "vfp-core-issuer-org-b"
  image = docker_image.issuer.image_id

  networks_advanced {
    name    = docker_network.vfp.name
    aliases = ["issuer-hospitalb"]
  }

  volumes {
    volume_name    = docker_volume.issuer_registry_org_b.name
    container_path = "/vault/registry"
  }

  volumes {
    host_path      = "${local.repo_root}/vfp-governance/verifier/certs"
    container_path = "/run/certs"
    read_only      = true
  }

  env = [
    "ORG=org://HospitalB",
    "VERIFIER_URL=https://verifier.local:8443",
    "CA_CRT=/run/certs/ca.crt",
    "VERIFY_TLS=1",
    "ADMIN_CRT=/run/certs/HospitalB-admin.crt",
    "ADMIN_KEY=/run/certs/HospitalB-admin.key",
    "REGISTRY_DIR=/vault/registry",
    "CAP_PROFILE_PATH=/app/config/cap_profiles.json"
  ]

  depends_on = [docker_container.verifier_proxy]
  must_run   = true
  restart    = "unless-stopped"
}

resource "docker_image" "issuer_proxy" {
  name = "vfp-core-issuer-proxy:local"

  build {
    context = "${local.repo_root}/vfp-core/issuers/nginx"
  }
}

resource "docker_container" "issuer_proxy" {
  name  = "vfp-core-issuer-proxy"
  image = docker_image.issuer_proxy.image_id

  networks_advanced {
    name    = docker_network.vfp.name
    aliases = ["issuer-hospitala.local", "issuer-hospitalb.local"]
  }

  ports {
    internal = 8443
    external = 9443
    ip       = "127.0.0.1"
  }

  volumes {
    host_path      = "${local.repo_root}/vfp-governance/verifier/certs"
    container_path = "/etc/nginx/certs"
    read_only      = true
  }

  depends_on = [
    docker_container.issuer_org_a,
    docker_container.issuer_org_b
  ]

  must_run = true
  restart  = "unless-stopped"
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
    external = 8082
  }

  volumes {
    volume_name    = docker_volume.runs.name
    container_path = "/app/runs"
  }

  volumes {
    host_path      = "${local.repo_root}/vfp-governance/verifier/certs"
    container_path = "/run/certs"
    read_only      = true
  }

  env = [
    "RUN_ID=${local.run_id}",
    "LOCAL_EPOCHS=1",
    "BATCH_SIZE=32",
    "LEARNING_RATE=0.001",
    "RUNS_DIR=/app/runs",
    "DATASET=${local.dataset}",
    "DATASET_SUBSET=${local.dataset_subset}",
    "FLOWER_ROUNDS=${local.flower_rounds}",
    "MIN_CLIENTS=${length(local.enabled_orgs)}",
    "ORGS_JSON=${jsonencode(local.enabled_orgs)}",
    "FLOWER_BACKEND_URL=vfp-core-flower-server:8080",
    "GOVERNANCE_URL=http://vfp-governance-gatekeeper:9000/admission/check",
    "GOVERNANCE_MODE=strict",
    "FCAC_ENABLED=true",
    "VERIFIER_URL=https://verifier.local:8443",
    "VERIFY_TLS=0",
    "HUB_CERT_CRT=/run/certs/hub.crt",
    "HUB_CERT_KEY=/run/certs/hub.key",
    "SIGNER_URL=http://holder-signer:8090",
    "FCAC_HOLDER_SUB=openhealth-hub",
    "FCAC_DPOP_NONCE=openhealth-local-nonce"
  ]

  depends_on = [
    docker_container.gatekeeper,
    docker_container.holder_signer
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
  name  = "vfp-core-flower-server"
  image = docker_image.flower_server.image_id


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
    "GOVERNANCE_URL=http://vfp-governance-gatekeeper:9000/admission/check",
    "HUB_URL=http://vfp-core-hub:8080"
  ]

  depends_on = [docker_container.gatekeeper, docker_container.hub]
  must_run   = true
  restart    = "unless-stopped"
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

  name  = "vfp-core-flower-client-${each.key}"
  image = docker_image.flower_client.image_id


  networks_advanced {
    name = docker_network.vfp.name
  }

  volumes {
    volume_name    = docker_volume.runs.name
    container_path = "/app/runs"
  }

  env = [
    "RUN_ID=${local.run_id}",
    "HUB_URL=http://vfp-core-hub:8080",
    "CLIENT_POLL_SECONDS=2",
    "RUNS_DIR=/app/runs",
    "ORG_ID=${each.key}",
    "ORG_LABEL=${each.value.label}",
    "DATA_PARTITION=${each.value.partition}",
    "NUM_PARTITIONS=${length(local.enabled_orgs)}",
    "MEDMNIST_DATASET=${local.dataset_subset}",
    "LOCAL_EPOCHS=1",
    "BATCH_SIZE=32",
    "LEARNING_RATE=0.001",
    "FLOWER_SERVER_URL=vfp-core-flower-server:8080",
    "GOVERNANCE_URL=http://vfp-governance-gatekeeper:9000/admission/check",
    "FCAC_ENABLED=true",
    "SIGNER_URL=http://holder-signer:8090",
    "FCAC_HOLDER_SUB=${each.key}",
    "FCAC_DPOP_NONCE=openhealth-local-nonce"
  ]

  depends_on = [docker_container.flower_server, docker_container.holder_signer]
  must_run   = true
  restart    = "no"
}


# ------------------------------------------------------------
# vfp-core: Frontend / organisation nodes
# ------------------------------------------------------------

resource "docker_image" "frontend" {
  name = "vfp-core-frontend:v0.3.2-react-vite"

  build {
    context = "${local.repo_root}/vfp-core/frontend"
  }
}

resource "docker_container" "frontend" {
  name  = "vfp-core-frontend"
  image = docker_image.frontend.image_id

  networks_advanced {
    name = docker_network.vfp.name
  }

  ports {
    internal = 80
    external = 3000
  }

  depends_on = [
    docker_container.hub
  ]
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
  value = "http://localhost:8082"
}

output "gatekeeper_url" {
  value = "http://localhost:8081"
}

output "verifier_mtls_url" {
  value = "https://localhost:8443"
}

output "issuer_mtls_url" {
  value = "https://localhost:9443"
}

output "flower_server_url" {
  value = "localhost:9090"
}

output "enabled_organisations" {
  value = keys(local.enabled_orgs)
}

output "frontend_url" {
  value = "http://localhost:3000"
}
