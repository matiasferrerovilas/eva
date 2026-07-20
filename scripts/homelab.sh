#!/usr/bin/env bash

set -euo pipefail

ROOT="/opt/homelab"

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
    find "$ROOT" -type f -name "compose.yml" | sort
}

find_service() {
    find "$ROOT" -type f -path "*/$1/compose.yml"
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

    cd "$(dirname "$compose")"

    docker compose logs "$@"
}

usage() {
    cat <<EOF

Homelab CLI

Uso:

  homelab.sh up [servicio]
  homelab.sh down [servicio]
  homelab.sh restart [servicio]
  homelab.sh pull [servicio]
  homelab.sh update [servicio]
  homelab.sh status
  homelab.sh logs <servicio> [-f]

Ejemplos:

  ./homelab.sh up
  ./homelab.sh up identity
  ./homelab.sh update
  ./homelab.sh update movements
  ./homelab.sh logs identity
  ./homelab.sh logs identity -f

EOF
}

case "${1:-}" in

up)
    if [[ $# -eq 2 ]]; then
        run_one "$2" "up -d"
    else
        run_all "up -d"
    fi
    ;;

down)
    if [[ $# -eq 2 ]]; then
        run_one "$2" "down"
    else
        run_all "down"
    fi
    ;;

restart)
    if [[ $# -eq 2 ]]; then
        run_one "$2" "restart"
    else
        run_all "restart"
    fi
    ;;

pull)
    if [[ $# -eq 2 ]]; then
        run_one "$2" "pull"
    else
        run_all "pull"
    fi
    ;;

update)
    if [[ $# -eq 2 ]]; then
        run_one "$2" "pull"
        run_one "$2" "up -d"
    else
        run_all "pull"
        run_all "up -d"
    fi
    ;;

status)
    run_all "ps"
    ;;

logs)
    if [[ $# -lt 2 ]]; then
        usage
        exit 1
    fi

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
