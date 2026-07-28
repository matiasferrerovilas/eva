#!/usr/bin/env python3

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

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def find_stacks():
    return sorted(ROOT.rglob("compose.yml"))


def stack_images(compose_file: Path):
    result = run(["docker", "compose", "-f", str(compose_file), "config", "--images"])

    if result.returncode != 0:
        return []

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def image_ids(images):
    ids = {}

    for image in images:
        result = run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
        ids[image] = result.stdout.strip() if result.returncode == 0 else None

    return ids


def update_stack(compose_file: Path):
    images = stack_images(compose_file)

    if not images:
        return False, "sin imágenes resueltas"

    before = image_ids(images)

    pull = run(["docker", "compose", "-f", str(compose_file), "pull"])
    if pull.returncode != 0:
        return False, (pull.stdout + pull.stderr).strip()

    after = image_ids(images)

    changed = any(before[img] != after[img] for img in images)

    if not changed:
        return False, None

    up = run(["docker", "compose", "-f", str(compose_file), "up", "-d"])

    if up.returncode != 0:
        return False, (up.stdout + up.stderr).strip()

    return True, None


def main():
    print()
    print(c(BOLD, WHITE) + "🔄 Homelab Update" + RESET)
    print(c(DIM) + "─" * 60 + RESET)

    stacks = find_stacks()
    updated = 0

    for compose in stacks:
        name = compose.relative_to(ROOT).parent
        print(f"{c(DIM)}⋯ {name}{RESET} chequeando imagen...", end="\r")

        changed, error = update_stack(compose)

        if error:
            print(f"{c(RED)}✘ {name}{RESET} error: {error}")
        elif changed:
            print(f"{c(GREEN)}✔ {name}{RESET} imagen nueva, contenedor recreado")
            updated += 1
        else:
            print(f"{c(DIM)}· {name}{RESET} sin cambios")

    print(c(DIM) + "─" * 60 + RESET)
    print(f"Stacks actualizados: {updated}/{len(stacks)}")
    print()


if __name__ == "__main__":
    main()
