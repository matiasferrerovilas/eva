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
    local -a cmd=("$@")
    local -a failed=()

    while IFS= read -r compose; do
        local dir name
        dir=$(dirname "$compose")
        name=$(basename "$dir")

        info "$name"

        if ! (cd "$dir" && docker compose "${cmd[@]}"); then
            error "$name falló"
            failed+=("$name")
        fi

        echo
    done < <(find_compose)

    if [[ ${#failed[@]} -gt 0 ]]; then
        warning "Stacks con errores: ${failed[*]}"
        return 1
    fi
}

run_one() {
    local service="$1"
    shift
    local -a cmd=("$@")

    local compose
    compose=$(find_service "$service")

    if [[ -z "$compose" ]]; then
        error "Servicio '$service' no encontrado."
        exit 1
    fi

    info "$service"

    (cd "$(dirname "$compose")" && docker compose "${cmd[@]}")
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
    local -a failed=()

    while IFS= read -r compose; do
        local dir
        dir=$(dirname "$compose")

        if ! smart_update_dir "$dir"; then
            error "$(basename "$dir") falló"
            failed+=("$(basename "$dir")")
        fi
    done < <(find_compose)

    if [[ ${#failed[@]} -gt 0 ]]; then
        warning "Stacks con errores: ${failed[*]}"
        return 1
    fi
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

docker_prune() {
    echo "🐳 Cleaning Docker..."
    docker system prune -a --volumes -f
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
  $self prune

Ejemplos:

  $self up
  $self up identity
  $self update
  $self update movements
  $self status
  $self logs identity
  $self logs identity -f
  $self prune

EOF
}

case "${1:-}" in

up)
    if [[ $# -eq 2 ]]; then run_one "$2" up -d; else run_all up -d; fi
    ;;

down)
    if [[ $# -eq 2 ]]; then run_one "$2" down; else run_all down; fi
    ;;

restart)
    if [[ $# -eq 2 ]]; then run_one "$2" restart; else run_all restart; fi
    ;;

pull)
    if [[ $# -eq 2 ]]; then run_one "$2" pull; else run_all pull; fi
    ;;

update)
    rc=0
    if [[ $# -eq 2 ]]; then
        smart_update_one "$2" || rc=$?
    else
        smart_update_all || rc=$?
    fi
    docker_prune
    exit "$rc"
    ;;

status)
    status
    ;;

prune)
    docker_prune
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
