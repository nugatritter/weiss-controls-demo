#!/bin/sh
# Baut die WEISS-Images direkt aus dem Upstream-Git-Repo (rootless).
# Nutzung: scripts/build-images.sh [--with-softioc] [env-datei]
#   env-datei: Standard ~/.config/weiss/weiss.env
#   --with-softioc: baut zusätzlich die Test-SoftIOC (dauert einige Minuten)
# Version wählen: WEISS_REF=v1.2.3 scripts/build-images.sh
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$HOME/.config/weiss/weiss.env"
WITH_SOFTIOC=0
for arg in "$@"; do
    case "$arg" in
        --with-softioc) WITH_SOFTIOC=1 ;;
        *) ENV_FILE="$arg" ;;
    esac
done
REF="${WEISS_REF:-main}"
REPO="https://github.com/weiss-controls/weiss.git#$REF"
GIT_TIMEOUT="${WEISS_GIT_TIMEOUT_SECONDS:-180}"

if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

# Die VITE_*-Werte werden beim Frontend-Build fest eingebacken.
podman build --target prod \
    --build-arg "VITE_DEMO_MODE=${DEMO_MODE:-false}" \
    --build-arg "VITE_AUTH_IDENTITY_PROVIDER=${AUTH_IDENTITY_PROVIDER:-oauth}" \
    -t localhost/weiss:latest "$REPO"
podman build -t localhost/weiss-epicsws:latest "$REPO:backend/epicsWS"
podman build -t localhost/weiss-api-upstream:latest "$REPO:backend/api"
podman build \
    --build-arg "BASE_IMAGE=localhost/weiss-api-upstream:latest" \
    --build-arg "WEISS_GIT_TIMEOUT_SECONDS=$GIT_TIMEOUT" \
    -f "$ROOT/overrides/weiss-api-timeout.Containerfile" \
    -t localhost/weiss-api:latest "$ROOT"

if [ "$WITH_SOFTIOC" = 1 ]; then
    podman build -t localhost/weiss-softioc:latest "$ROOT/softioc"
fi
