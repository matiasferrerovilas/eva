#!/usr/bin/env bash

set -euo pipefail

ROOT="/opt/homelab"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

find_compose() {
    find "$ROOT" \
        \( \
            -name ".git" -o \
            -name "data" -o \
            -name "letsencrypt" -o \
            -name "uploads" -o \
            -name "upload" -o \
            -name "database" -o \
            -name "model-cache" -o \
            -name "cache" -o \
            -name "logs" -o \
            -name "tmp" \
        \) -prune \
        -o -type f -name "compose.yml" -print | sort
}

find_service() {
    find_compose | grep "/$1/compose.yml$" || true
}

run_all() {
    local cmd="$1"

    while IFS= read -r compose; do
        local dir
        dir=$(dirname "$compose")

        info "$(basename "$dir")"

        (
            cd "$dir"
            docker compose $cmd
        )

        echo
    done < <(find_compose)
}

run_one() {
    local service="$1"
    local cmd="$2"

    local compose
    compose=$(find_service "$service")

    if [[ -z "$compose" ]]; then
        error "Servicio '$service' no encontrado."
        exit 1
    fi

    info "$service"

    (
        cd "$(dirname "$compose")"
        docker compose $cmd
    )
}

logs() {
    local service="$1"
    shift

    local compose
    compose=$(find_service "$service")

    if [[ -z "$compose" ]]; then
        error "Servicio '$service' no encontrado."
        exit 1
    fi

    (
        cd "$(dirname "$compose")"
        docker compose logs "$@"
    )
}

image_ids_for() {
    # Requiere estar parado en la carpeta del compose. Imprime "imagen<TAB>id" por línea.
    local img
    while IFS= read -r img; do
        [[ -z "$img" ]] && continue
        local id
        id=$(docker image inspect "$img" --format '{{.Id}}' 2>/dev/null || echo "missing")
        printf '%s\t%s\n' "$img" "$id"
    done < <(docker compose config --images 2>/dev/null)
}

smart_update_dir() {
    local dir="$1"
    local name
    name=$(basename "$dir")

    (
        cd "$dir"

        local before after
        before=$(image_ids_for)

        docker compose pull --quiet 2>/dev/null || docker compose pull >/dev/null

        after=$(image_ids_for)

        if [[ "$before" == "$after" ]]; then
            info "$name sin cambios"
        else
            docker compose up -d
            success "$name actualizado (imagen nueva)"
        fi
    )
}

smart_update_all() {
    while IFS= read -r compose; do
        smart_update_dir "$(dirname "$compose")"
    done < <(find_compose)
}

smart_update_one() {
    local service="$1"

    local compose
    compose=$(find_service "$service")

    if [[ -z "$compose" ]]; then
        error "Servicio '$service' no encontrado."
        exit 1
    fi

    smart_update_dir "$(dirname "$compose")"
}

status() {
    local py="$SCRIPT_DIR/homelab.py"

    if [[ ! -f "$py" ]]; then
        error "No se encontró $py"
        exit 1
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        error "python3 no está instalado."
        exit 1
    fi

    python3 "$py"
}

usage() {
local self
self="$(basename "${BASH_SOURCE[0]}")"
cat <<EOF

Homelab CLI

Uso:

  $self up [servicio]
  $self down [servicio]
  $self restart [servicio]
  $self pull [servicio]
  $self update [servicio]
  $self status
  $self logs <servicio> [-f]

Ejemplos:

  $self up
  $self up identity
  $self update
  $self update movements
  $self status
  $self logs identity
  $self logs identity -f

EOF
}

case "${1:-}" in

up)
    [[ $# -eq 2 ]] && run_one "$2" "up -d" || run_all "up -d"
    ;;

down)
    [[ $# -eq 2 ]] && run_one "$2" "down" || run_all "down"
    ;;

restart)
    [[ $# -eq 2 ]] && run_one "$2" "restart" || run_all "restart"
    ;;

pull)
    [[ $# -eq 2 ]] && run_one "$2" "pull" || run_all "pull"
    ;;

update)
    [[ $# -eq 2 ]] && smart_update_one "$2" || smart_update_all
    ;;

status)
    status
    ;;

logs)
    [[ $# -lt 2 ]] && { usage; exit 1; }
    shift
    logs "$@"
    ;;

-h|--help|help)
    usage
    ;;

*)
    usage
    exit 1
    ;;

esac
