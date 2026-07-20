#!/usr/bin/env python3

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path("/opt/homelab")

# ─────────────────────────────────────────────────────────────
# ANSI
# ─────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
WHITE = "\033[97m"


def c(*codes):
    return "".join(codes)


# ─────────────────────────────────────────────────────────────

def term_width():
    return shutil.get_terminal_size((100, 24)).columns


def find_stacks():
    return sorted(ROOT.rglob("compose.yml"))

def compose_ps(compose_file: Path):
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(compose_file),
                "ps",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        output = result.stdout.strip()

        if not output:
            return []

        lines = output.splitlines()
        containers = []

        for line in lines:
            line = line.strip()

            if not line:
                continue

            obj = json.loads(line)

            if isinstance(obj, list):
                containers.extend(obj)

            elif isinstance(obj, dict):
                containers.append(obj)

        return containers

    except subprocess.CalledProcessError:
        return []

def analyse_stack(compose):
    containers = compose_ps(compose)

    total = len(containers)

    running = 0
    healthy = True

    for ct in containers:

        state = ct.get("State", "").lower()

        if state == "running":
            running += 1

        health = ct.get("Health")

        if health and health.lower() != "healthy":
            healthy = False

    if total == 0:
        status = "Stopped"
        icon = "🔴"
        color = RED

    elif running == total:

        status = "Running"

        if healthy:
            icon = "🟢"
            color = GREEN
        else:
            icon = "🟡"
            color = YELLOW

    else:
        icon = "🟡"
        color = YELLOW
        status = f"{running}/{total}"

    return {
        "name": compose.parent.name,
        "icon": icon,
        "color": color,
        "status": status,
        "running": running,
        "total": total,
    }


def render(rows):

    tw = min(term_width(), 90)

    sep = c(DIM) + "─" * tw + RESET

    print()

    print(c(BOLD, WHITE) + "🏠 Homelab Status" + RESET)
    print(sep)

    print(
        f"{'STACK':<20}"
        f"{'STATUS':<15}"
        f"{'CONTAINERS'}"
    )

    print(sep)

    total_stacks = len(rows)
    total_running = 0
    total_containers = 0

    for row in rows:

        total_running += row["running"]
        total_containers += row["total"]

        status = f"{row['icon']} {row['status']}"

        print(
            f"{row['name']:<20}"
            f"{status:<15}"
            f"{row['running']}/{row['total']}"
        )

    print(sep)

    print(f"Stacks      : {total_stacks}")
    print(f"Containers  : {total_containers}")
    print(f"Running     : {total_running}")

    print()


def main():

    rows = []

    for compose in find_stacks():
        rows.append(analyse_stack(compose))

    render(rows)


if __name__ == "__main__":
    main()
