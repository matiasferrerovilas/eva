#!/usr/bin/env python3
"""eva - homelab CLI (interactive menu + subcommands). No third-party deps."""

import json
import os
import shutil
import select
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

ROOT = Path("/opt/homelab")
PRUNE_DIRS = {
    ".git", "data", "letsencrypt", "uploads", "upload", "database",
    "model-cache", "cache", "logs", "tmp",
}

# ── ANSI ─────────────────────────────────────────────────────
R, B, D = "\033[0m", "\033[1m", "\033[2m"
RED, GREEN, YELLOW, BLUE, CYAN, WHITE = (
    "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m", "\033[97m",
)
if not sys.stdout.isatty():
    R = B = D = RED = GREEN = YELLOW = BLUE = CYAN = WHITE = ""


def width():
    return min(shutil.get_terminal_size((90, 24)).columns, 90)


def line(ch="─"):
    return f"{D}{ch * width()}{R}"


def banner(title, subtitle=""):
    w = width()
    print()
    print(f"{CYAN}╭{'─' * (w - 2)}╮{R}")
    print(f"{CYAN}│{R} {B}{WHITE}{title}{R}{' ' * max(0, w - 3 - len(title) - len(subtitle))}{D}{subtitle}{R} {CYAN}│{R}")
    print(f"{CYAN}╰{'─' * (w - 2)}╯{R}")


def ok(msg): print(f"{GREEN}✔{R} {msg}")
def warn(msg): print(f"{YELLOW}!{R} {msg}")
def err(msg): print(f"{RED}✘{R} {msg}")
def info(msg): print(f"{BLUE}•{R} {msg}")


# ── docker helpers ───────────────────────────────────────────
def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def find_stacks():
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        if "compose.yml" in filenames:
            found.append(Path(dirpath) / "compose.yml")
    return sorted(found)


def find_stack(name):
    for s in find_stacks():
        if s.parent.name == name:
            return s
    return None


def containers():
    """All containers: dicts with name, status, state, stack, image."""
    res = run(["docker", "ps", "-a", "--format", "{{json .}}"])
    out = []
    for ln in res.stdout.splitlines():
        if not ln.strip():
            continue
        o = json.loads(ln)
        labels = dict(
            kv.split("=", 1) for kv in o.get("Labels", "").split(",") if "=" in kv
        )
        out.append({
            "name": o["Names"],
            "status": o["Status"],
            "state": o["State"],
            "image": o["Image"],
            "ports": o.get("Ports", ""),
            "networks": o.get("Networks", ""),
            "stack": labels.get("com.docker.compose.project", "-"),
        })
    return sorted(out, key=lambda c: (c["stack"], c["name"]))


def dot(c):
    st, status = c["state"], c["status"].lower()
    if st == "running" and "unhealthy" not in status and "restarting" not in status:
        return f"{GREEN}●{R}"
    if st in ("running", "restarting"):
        return f"{YELLOW}●{R}"
    return f"{RED}●{R}"


# ── prompts ──────────────────────────────────────────────────
def ask(prompt="Elegí"):
    try:
        return input(f"\n{CYAN}❯{R} {prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"


def read_key():
    """Read one key; terminal must already be in cbreak mode (see pick)."""
    fd = sys.stdin.fileno()
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        if select.select([fd], [], [], 0.05)[0]:
            seq = os.read(fd, 2)
            return {b"[A": "up", b"[B": "down"}.get(seq, "")
        return "esc"
    if ch in (b"\r", b"\n", b" "):
        return "enter"
    return {b"k": "up", b"j": "down", b"q": "esc"}.get(ch, "")


def pick(title, items, extra=None):
    """Arrow-key picker. Returns index, an extra key, or None (cancel)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return pick_numbered(title, items, extra)
    entries = [(k, lbl) for k, lbl in extra or []] + [(i, lbl) for i, lbl in enumerate(items)]
    cur = 0
    print(f"\n{B}{title}{R}  {D}↑↓ mover · Enter/Espacio elegir · q volver{R}")
    print(line())
    print("\033[?25l", end="")  # hide cursor
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        while True:
            for n, (_, lbl) in enumerate(entries):
                if n == cur:
                    print(f"\033[2K {CYAN}❯ {B}{lbl}{R}")
                else:
                    print(f"\033[2K   {lbl}")
            key = read_key()
            if key == "up":
                cur = (cur - 1) % len(entries)
            elif key == "down":
                cur = (cur + 1) % len(entries)
            elif key == "enter":
                return entries[cur][0]
            elif key == "esc":
                return None
            print(f"\033[{len(entries)}A", end="")
    except KeyboardInterrupt:
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print("\033[?25h", end="")


def pick_numbered(title, items, extra=None):
    """Fallback when stdin is not a TTY."""
    print(f"\n{B}{title}{R}")
    print(line())
    for key, label in extra or []:
        print(f" {CYAN}{key:>3}{R}  {label}")
    for i, label in enumerate(items, 1):
        print(f" {CYAN}{i:>3}{R}  {label}")
    print(f" {D}  q  volver{R}")
    ans = ask()
    if ans.lower() in ("q", ""):
        return None
    for key, _ in extra or []:
        if ans == key:
            return key
    if ans.isdigit() and 1 <= int(ans) <= len(items):
        return int(ans) - 1
    warn("Opción inválida")
    return None


# ── actions ──────────────────────────────────────────────────
def fmt_ports(ports):
    out = []
    for p in (x.strip() for x in ports.split(",") if x.strip()):
        if "->" in p:
            host, cont = p.split("->")
            out.append(f"{CYAN}{host.split(':')[-1]}{R}→{cont}")
    return "  ".join(dict.fromkeys(out)) or f"{D}—{R}"


def render_ps(show_all, hint=""):
    cts = [c for c in containers() if show_all or c["state"] == "running"]
    up = sum(1 for c in cts if c["state"] == "running")
    banner("🐳 Contenedores", f"{up}/{len(cts)} running{hint}")
    if not cts:
        warn("No hay contenedores")
        return
    nw = max(len(c["name"]) for c in cts)
    sw = max(len(c["stack"]) for c in cts)
    print(f"   {B}{'CONTENEDOR'.ljust(nw)}  {'STACK'.ljust(sw)}  {'ESTADO'.ljust(26)}  REDES / PUERTOS{R}")
    print(line())
    for c in cts:
        nets = ",".join(n for n in c["networks"].split(",") if n) or "—"
        print(f" {dot(c)} {c['name'].ljust(nw)}  {D}{c['stack'].ljust(sw)}{R}  "
              f"{c['status'][:26].ljust(26)}  {BLUE}{nets}{R}  {fmt_ports(c['ports'])}")
    print(line())


def cmd_ps(show_all=False, watch=False, interval=3):
    if not watch:
        return render_ps(show_all)
    try:
        while True:
            print("\033[2J\033[H", end="")
            render_ps(show_all, f" · ↻ {interval}s")
            print(f"{D}Ctrl+C para salir{R}", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


def cmd_system(action=None):
    cmds = {
        "update": ("apt update + upgrade", "sudo apt update && sudo apt upgrade -y"),
        "upgrade": ("apt full-upgrade", "sudo apt full-upgrade -y"),
        "clean": ("autoremove + autoclean", "sudo apt autoremove -y && sudo apt autoclean"),
    }
    if action is None:
        keys = list(cmds)
        sel = pick("🖥️  Sistema (apt)", [f"{k}  {D}{cmds[k][0]}{R}" for k in keys])
        if sel is None:
            return
        action = keys[sel]
    if action not in cmds:
        err(f"Acción '{action}' inválida: {', '.join(cmds)}")
        return
    print(f"\n{B}{cmds[action][0]}{R}")
    try:
        subprocess.run(cmds[action][1], shell=True)
    except KeyboardInterrupt:
        pass


def cmd_stacks():
    stacks = find_stacks()
    banner("📦 Stacks", f"{len(stacks)} compose")
    cts = containers()
    nw = max(len(s.parent.name) for s in stacks)
    for s in stacks:
        name = s.parent.name
        mine = [c for c in cts if c["stack"] == name]
        run_n = sum(1 for c in mine if c["state"] == "running")
        if mine and run_n == len(mine):
            col = GREEN if all(dot(c) == f"{GREEN}●{R}" for c in mine) else YELLOW
        else:
            col = YELLOW if run_n else RED
        rel = s.parent.relative_to(ROOT)
        print(f" {col}●{R} {name.ljust(nw)}  {run_n}/{len(mine)}  {D}{rel}{R}")


def cmd_logs(name=None):
    cts = containers()
    if name is None:
        labels = [f"{dot(c)} {c['name']}  {D}({c['stack']}){R}" for c in cts]
        idx = pick("📜 ¿Logs de qué contenedor?", labels)
        if idx is None:
            return
        name = cts[idx]["name"]
    print(f"\n{D}Siguiendo logs de {name} — Ctrl+C para volver{R}\n")
    try:
        subprocess.run(["docker", "logs", "-f", "--tail", "100", name])
    except KeyboardInterrupt:
        pass
    print()


def image_ids(images):
    ids = {}
    for img in images:
        r = run(["docker", "image", "inspect", img, "--format", "{{.Id}}"])
        ids[img] = r.stdout.strip() if r.returncode == 0 else None
    return ids


def update_stack(compose):
    name = compose.parent.name
    cwd = str(compose.parent)
    cfg = run(["docker", "compose", "config", "--images"], cwd=cwd)
    images = [i.strip() for i in cfg.stdout.splitlines() if i.strip()]
    before = image_ids(images)

    print(f"{D}⋯ {name}: pull...{R}")
    pull = run(["docker", "compose", "pull"], cwd=cwd)
    if pull.returncode != 0:
        err(f"{name}: pull falló\n{(pull.stdout + pull.stderr).strip()}")
        return False
    changed = before != image_ids(images)

    up = run(["docker", "compose", "up", "-d", "--remove-orphans"], cwd=cwd)
    if up.returncode != 0:
        err(f"{name}: up falló\n{(up.stdout + up.stderr).strip()}")
        return False
    if changed:
        ok(f"{B}{name}{R}: imagen nueva, contenedor recreado")
    else:
        info(f"{name}: sin cambios")
    return True


def docker_prune():
    print(f"\n{D}🧹 docker system prune -a --volumes -f{R}")
    r = run(["docker", "system", "prune", "-a", "--volumes", "-f"])
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    ok(tail) if r.returncode == 0 else err(r.stderr.strip())


def cmd_update(name=None):
    stacks = find_stacks()
    if name is None:
        labels = [f"{s.parent.name}  {D}{s.parent.relative_to(ROOT)}{R}" for s in stacks]
        sel = pick("🔄 ¿Qué actualizar?", labels, extra=[("a", f"{B}Todos los stacks{R}")])
        if sel is None:
            return
        targets = stacks if sel == "a" else [stacks[sel]]
    elif name == "all":
        targets = stacks
    else:
        s = find_stack(name)
        if not s:
            err(f"Stack '{name}' no encontrado")
            return
        targets = [s]

    banner("🔄 Update", f"{len(targets)} stack(s)")
    failed = [t.parent.name for t in targets if not update_stack(t)]
    docker_prune()
    print(line())
    if failed:
        warn(f"Con errores: {', '.join(failed)}")
    else:
        ok("Todo actualizado")


def cmd_compose(action, name=None):
    stacks = find_stacks()
    if name is None:
        labels = [s.parent.name for s in stacks]
        sel = pick(f"⚙️  {action}: ¿qué stack?", labels, extra=[("a", f"{B}Todos{R}")])
        if sel is None:
            return
        targets = stacks if sel == "a" else [stacks[sel]]
    elif name == "all":
        targets = stacks
    else:
        s = find_stack(name)
        if not s:
            err(f"Stack '{name}' no encontrado")
            return
        targets = [s]
    args = {"up": ["up", "-d"], "down": ["down"], "restart": ["restart"]}[action]
    for t in targets:
        r = run(["docker", "compose", *args], cwd=str(t.parent))
        ok(f"{t.parent.name}: {action}") if r.returncode == 0 else err(
            f"{t.parent.name}: {r.stderr.strip()}")


# ── menu ─────────────────────────────────────────────────────
MENU = [
    ("1", "Listar contenedores", lambda: cmd_ps(show_all=True)),
    ("2", "Listar stacks", cmd_stacks),
    ("3", "Ver logs", cmd_logs),
    ("4", "Update (pull + recrear + prune)", cmd_update),
    ("5", "Up / Down / Restart", None),
    ("6", "Docker prune", docker_prune),
    ("7", "Sistema (apt update / upgrade / clean)", cmd_system),
]


def menu():
    while True:
        banner("🏠 EVA", "homelab")
        sel = pick("¿Qué querés hacer?", [label for _, label, _ in MENU])
        if sel is None:
            print(f"{D}Chau 👋{R}\n")
            return
        key, _, fn = MENU[sel]
        if key == "5":
            act = pick("⚙️  Acción", ["up", "down", "restart"])
            if act is None:
                continue
            cmd_compose(["up", "down", "restart"][act])
        else:
            fn()
        if key != "3":
            ask("Enter para volver al menú")


USAGE = """eva — homelab CLI

  eva                       menú interactivo
  eva containers [-a] [-w] [-i N]
                            contenedores (redes, puertos). -a todos, -w watch
  eva stacks                listar stacks
  eva system update|upgrade|clean
                            apt update+upgrade / full-upgrade / autoremove
  eva logs [contenedor]     seguir logs
  eva update [stack|all]    pull + recrear + prune
  eva up|down|restart [stack|all]
  eva prune                 docker system prune -a --volumes -f
"""


def main(argv):
    if not argv:
        return menu()
    c, rest = argv[0], argv[1:]
    arg = rest[0] if rest else None
    flags = set(rest)
    interval = int(rest[rest.index("-i") + 1]) if "-i" in rest else 3
    table = {
        "containers": lambda: cmd_ps("-a" in flags, "-w" in flags, interval),
        "ps": lambda: cmd_ps("-a" in flags, "-w" in flags, interval),
        "system": lambda: cmd_system(arg),
        "upgrade": lambda: cmd_system("upgrade"), "clean": lambda: cmd_system("clean"),
        "stacks": cmd_stacks, "status": cmd_stacks,
        "logs": lambda: cmd_logs(arg), "update": lambda: cmd_update(arg),
        "prune": docker_prune, "docker-prune": docker_prune,
        "up": lambda: cmd_compose("up", arg),
        "down": lambda: cmd_compose("down", arg),
        "restart": lambda: cmd_compose("restart", arg),
    }
    if c in table:
        table[c]()
    else:
        print(USAGE)
        return 0 if c in ("-h", "--help", "help") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
