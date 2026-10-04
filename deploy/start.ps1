$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# Docker Desktop on this machine has a BuildKit/Bake header issue; the
# classic builder is stable for this small deployment.
$env:DOCKER_BUILDKIT = "0"
$env:COMPOSE_DOCKER_CLI_BUILD = "0"
# Compose v5 may invoke Bake even when the legacy builder variables are set.
# Disable it explicitly to avoid Docker Desktop's shared-session-key error.
$env:COMPOSE_BAKE = "false"

docker compose -p club-platform up --build -d
docker compose -p club-platform ps
