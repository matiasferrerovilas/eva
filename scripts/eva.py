#!/usr/bin/env python3
"""eva - homelab CLI (interactive menu + subcommands). No third-party deps."""

import json
import os
import shutil
import select
import subprocess
from concurrent.futures import ThreadPoolExecutor
import sys
import termios
import time
import tty
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # clone root: <BASE>/scripts/eva.py
CONFIG_DIR = BASE / "config"
ENV_FILE = CONFIG_DIR / ".env"
ENV_KEY = "containers_location"
ROOT = None  # set by load_config()
CANCELLED = False  # set by pick() when the user backs out (Esc / Ctrl+C)
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


def clear():
    if sys.stdout.isatty():
        print("\033[2J\033[3J\033[H", end="", flush=True)


# ── config ───────────────────────────────────────────────────
def read_env():
    env = {}
    if ENV_FILE.exists():
        for ln in ENV_FILE.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip("\"'")
    return env


def write_env(key, value):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith(f"{key}=")]
    ENV_FILE.write_text("\n".join(lines + [f"{key}={value}"]) + "\n")


def load_config():
    global ROOT
    value = read_env().get(ENV_KEY)
    if value and Path(value).expanduser().is_dir():
        ROOT = Path(value).expanduser()
        return True
    return False


def cmd_install():
    global ROOT
    banner("🛠️  Configuración", "eva")
    current = read_env().get(ENV_KEY) or str(BASE / "services")
    info(f"Config: {ENV_FILE}")
    try:
        raw = input(f"\n{CYAN}❯{R} Ruta donde están tus contenedores (compose.yml) [{current}]: ").strip()
        path = Path(raw or current).expanduser().resolve()
        if not path.is_dir():
            if input(f"{path} no existe. ¿Crearla? [y/N]: ").strip().lower() != "y":
                warn("Configuración cancelada")
                return False
            path.mkdir(parents=True)
        write_env(ENV_KEY, str(path))
        ROOT = path
        ok(f"{ENV_KEY}={path}")
        ok(f"{len(find_stacks())} stack(s) encontrados")
        cur_ex = read_env().get("excluded_stacks", "")
        raw = input(f"\n{CYAN}❯{R} Stacks a excluir del update/check masivo, separados por coma "
                    f"[{cur_ex or 'ninguno'}] ('-' para vaciar): ").strip()
        if raw:
            write_env("excluded_stacks", "" if raw == "-" else raw)
            ok(f"excluded_stacks={read_env().get('excluded_stacks', '')}")
        me = Path(__file__).resolve()
        target = Path("/usr/local/bin/eva")
        if not (target.is_symlink() and target.resolve() == me):
            if input(f"\n¿Instalar el comando 'eva' en {target}? (sudo) [Y/n]: ").strip().lower() != "n":
                r = subprocess.run(["sudo", "ln", "-sf", str(me), str(target)])
                ok("Comando 'eva' instalado") if r.returncode == 0 else err("No se pudo crear el symlink")
        return True
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def ok(msg): print(f"{GREEN}✔{R} {msg}")
def warn(msg): print(f"{YELLOW}!{R} {msg}")
def err(msg): print(f"{RED}✘{R} {msg}")
def info(msg): print(f"{BLUE}•{R} {msg}")


# ── docker helpers ───────────────────────────────────────────
def run(cmd, cwd=None, timeout=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")


def find_stacks():
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        name = next((n for n in COMPOSE_NAMES if n in filenames), None)
        if name:
            found.append(Path(dirpath) / name)
    return sorted(found)


def excluded_stacks():
    """Stack names skipped by bulk update/check ('all'), from config `excluded_stacks`."""
    raw = read_env().get("excluded_stacks", "")
    return {n.strip() for n in raw.split(",") if n.strip()}


SKIPPED = []  # names left out of the last bulk selection, for display


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
    global CANCELLED
    CANCELLED = False
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
                clear()
                return entries[cur][0]
            elif key == "esc":
                CANCELLED = True
                clear()
                return None
            print(f"\033[{len(entries)}A", end="")
    except KeyboardInterrupt:
        CANCELLED = True
        clear()
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print("\033[?25h", end="")


def wait_key(timeout=None):
    """Block until Enter/Space/Esc/q (cbreak). Returns True if a key was pressed,
    False on timeout or non-TTY. Used for 'back to menu' pauses and watch mode."""
    if not sys.stdin.isatty():
        return False
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        if not select.select([fd], [], [], timeout)[0]:
            return False
        return read_key() in ("enter", "esc")
    except KeyboardInterrupt:
        return True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


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
            print(f"{D}Esc para volver{R}", flush=True)
            if wait_key(interval):
                break
    except KeyboardInterrupt:
        pass
    clear()


def cmd_system(action=None):
    cmds = {
        "update": ("apt update + upgrade", "sudo apt update && sudo apt upgrade -y"),
        "upgrade": ("apt full-upgrade", "sudo apt full-upgrade -y"),
        "clean": ("autoremove + autoclean", "sudo apt autoremove -y && sudo apt autoclean"),
        "docker": ("Limpiar Docker", None),
    }
    if action is None:
        keys = list(cmds)
        sel = pick("🖥️  Sistema", [
            cmds[k][0] if k == "docker" else f"{k}  {D}{cmds[k][0]}{R}" for k in keys])
        if sel is None:
            return
        action = keys[sel]
    if action not in cmds:
        err(f"Acción '{action}' inválida: {', '.join(cmds)}")
        return
    if action == "docker":
        return docker_prune()
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


def stack_images_of(compose):
    cfg = run(["docker", "compose", "config", "--images"], cwd=str(compose.parent))
    return sorted({i.strip() for i in cfg.stdout.splitlines() if i.strip()})


def image_state(img):
    """'new' | 'ok' | 'missing' (not pulled yet) | 'unknown' (no remote digest)."""
    r = run(["docker", "image", "inspect", img, "--format", "{{json .RepoDigests}}"])
    if r.returncode != 0:
        return "missing"
    local = {d.split("@")[1] for d in json.loads(r.stdout or "[]") if "@" in d}
    remote = run(["docker", "buildx", "imagetools", "inspect", img,
                  "--format", "{{.Manifest.Digest}}"], timeout=30)
    digest = remote.stdout.strip()
    if remote.returncode != 0 or not digest.startswith("sha256:"):
        return "unknown"
    return "ok" if digest in local else "new"


def check_updates(targets):
    """Compare local vs registry digests, in parallel. -> {stack: [(image, state)]}"""
    pairs = [(t, img) for t in targets for img in stack_images_of(t)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        states = list(pool.map(lambda p: image_state(p[1]), pairs))
    result = {t: [] for t in targets}
    for (t, img), st in zip(pairs, states):
        result[t].append((img, st))
    return result


def render_check(result):
    labels = {"new": (YELLOW, "⬆ nueva versión"), "ok": (GREEN, "✔ al día"),
              "missing": (YELLOW, "⬇ sin descargar"), "unknown": (D, "? sin info remota")}
    nw = max((len(t.parent.name) for t in result), default=5)
    for t, imgs in result.items():
        print(f" {B}{t.parent.name.ljust(nw)}{R}")
        for img, st in imgs:
            col, txt = labels[st]
            print(f"   {col}{txt.ljust(18)}{R} {D}{img.split('@')[0]}{R}")


def pending_stacks(result):
    return [t for t, imgs in result.items() if any(s in ("new", "missing") for _, s in imgs)]


def resolve_targets(name, title, stacks):
    """Pick stack(s) interactively (name None), or by name/'all'. None = cancelled/not found."""
    global SKIPPED
    SKIPPED = []
    ex = excluded_stacks()

    def bulk():
        global SKIPPED
        SKIPPED = [s.parent.name for s in stacks if s.parent.name in ex]
        return [s for s in stacks if s.parent.name not in ex]

    if name is None:
        tag = "  (excluido de 'todos')"
        labels = [f"{s.parent.name}  {D}{s.parent.relative_to(ROOT)}"
                  f"{tag if s.parent.name in ex else ''}{R}" for s in stacks]
        sel = pick(title, labels, extra=[("a", f"{B}Todos los stacks{R}")])
        if sel is None:
            return None
        return bulk() if sel == "a" else [stacks[sel]]
    if name == "all":
        return bulk()
    s = find_stack(name)
    if not s:
        err(f"Stack '{name}' no encontrado")
        return None
    return [s]


def cmd_check(name=None):
    targets = resolve_targets(name, "🔎 ¿Qué stacks chequear?", find_stacks())
    if not targets:
        return
    banner("🔎 Novedades", f"{len(targets)} stack(s)")
    if SKIPPED:
        info(f"Excluidos por config: {', '.join(SKIPPED)}")
    info("Consultando registries...")
    result = check_updates(targets)
    print()
    render_check(result)
    n = len(pending_stacks(result))
    print(line())
    (warn if n else ok)(f"{n} stack(s) con novedades" if n else "Todo al día")


def cmd_update(name=None, force=False):
    targets = resolve_targets(name, "🔄 ¿Qué actualizar?", find_stacks())
    if not targets:
        return
    banner("🔄 Update", f"{len(targets)} stack(s)")
    if SKIPPED:
        info(f"Excluidos por config: {', '.join(SKIPPED)}")
    info("Buscando novedades...")
    result = check_updates(targets)
    print()
    render_check(result)
    pend = pending_stacks(result)
    print(line())
    chosen = targets if force else pend
    if name is None and sys.stdin.isatty() and not force:
        if not pend:
            ok("Todo al día, no hay nada que actualizar")
            return
        sel = pick(f"{len(pend)} stack(s) con novedades", [
            f"Actualizar solo los que tienen novedades ({', '.join(t.parent.name for t in pend)})",
            f"Forzar los {len(targets)} seleccionados"])
        if sel is None:
            return
        chosen = pend if sel == 0 else targets
    elif not chosen:
        ok("Todo al día, no hay nada que actualizar")
        return
    banner("🔄 Update", f"{len(chosen)} stack(s)")
    failed = [t.parent.name for t in chosen if not update_stack(t)]
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


# ── dashboard (system stats + container health) ──────────────
def bar(pct, warn_at=60, crit_at=80, size=16):
    pct = max(0.0, min(100.0, pct))
    col = GREEN if pct < warn_at else YELLOW if pct < crit_at else RED
    fill = round(size * pct / 100)
    return f"{col}{'█' * fill}{D}{'░' * (size - fill)}{R}"


def cpu_temp():
    r = run(["vcgencmd", "measure_temp"]) if shutil.which("vcgencmd") else None
    if r and r.returncode == 0 and "=" in r.stdout:
        return float(r.stdout.split("=")[1].split("'")[0])
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (OSError, ValueError):
        return None


def mem_info():
    try:
        m = {k: int(v.split()[0]) for k, v in (
            ln.split(":", 1) for ln in Path("/proc/meminfo").read_text().splitlines())}
        return (m["MemTotal"] - m["MemAvailable"]) / 1048576, m["MemTotal"] / 1048576
    except (OSError, KeyError, ValueError):
        return None


def uptime_str():
    try:
        s = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError):
        return "?"
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return f"{d}d {h}h" if d else f"{h}h {m}m"


def dashboard():
    rows = []
    t = cpu_temp()
    if t is not None:  # Pi throttles ~80°C
        rows.append(("Temp", bar(t, 60, 75), f"{t:.1f}°C"))
    mem = mem_info()
    if mem:
        rows.append(("RAM", bar(mem[0] / mem[1] * 100), f"{mem[0]:.1f} / {mem[1]:.1f} GB"))
    du = shutil.disk_usage("/")
    rows.append(("Disco", bar(du.used / du.total * 100, 70, 90), f"{du.used / 1e9:.0f} / {du.total / 1e9:.0f} GB"))
    load, cpus = os.getloadavg()[0], os.cpu_count() or 1
    rows.append(("CPU", bar(load / cpus * 100), f"load {load:.2f} · {cpus} cores · up {uptime_str()}"))
    print()
    for label, b, val in rows:
        print(f" {B}{label.ljust(6)}{R}{b}  {val}")
    cts = containers()
    up = sum(1 for c in cts if c["state"] == "running")
    bad = [c for c in cts if dot(c) != f"{GREEN}●{R}"]
    col = GREEN if not bad else YELLOW
    print(f"\n {col}●{R} {B}{up}/{len(cts)}{R} contenedores running")
    for c in bad[:5]:
        print(f"   {RED}✘{R} {c['name']}  {D}{c['status']}{R}")
    if len(bad) > 5:
        print(f"   {D}… y {len(bad) - 5} más{R}")


def cmd_status():
    banner("📊 Estado", "homelab")
    dashboard()
    print()
    cmd_stacks()


# ── menu ─────────────────────────────────────────────────────
MENU = [
    ("1", "Listar contenedores", lambda: cmd_ps(show_all=True)),
    ("2", "Listar stacks", cmd_stacks),
    ("3", "Ver logs", cmd_logs),
    ("4", "Update (ver novedades, pull, recrear, prune)", cmd_update),
    ("5", "Up / Down / Restart", None),
    ("6", "Sistema (apt, limpiar Docker)", cmd_system),
    ("7", "Configuración (ruta de contenedores)", cmd_install),
    ("0", "Salir", None),
]


def menu():
    try:
        _menu_loop()
    finally:
        clear()


def _menu_loop():
    while True:
        clear()
        banner("🏠 EVA", "homelab")
        dashboard()
        print()
        sel = pick("¿Qué querés hacer?", [label for _, label, _ in MENU])
        if sel is None or MENU[sel][0] == "0":
            return
        key, _, fn = MENU[sel]
        if key == "5":
            act = pick("⚙️  Acción", ["up", "down", "restart"])
            if act is None:
                continue
            cmd_compose(["up", "down", "restart"][act])
        else:
            fn()
        if key != "3" and not CANCELLED:
            print(f"\n{D}Esc / Enter para volver al menú{R}", flush=True)
            while not wait_key() and sys.stdin.isatty():
                pass


USAGE = """eva — homelab CLI

  eva                       menú interactivo
  eva install               configurar la ruta de contenedores (config/.env)
  eva containers [-a] [-w] [-i N]
                            contenedores (redes, puertos). -a todos, -w watch
  eva stacks                listar stacks
  eva system update|upgrade|clean|docker
                            apt update+upgrade / full-upgrade / autoremove
  eva logs [contenedor]     seguir logs
  eva status                temperatura, RAM, disco, salud y stacks
  eva check [stack|all]     ver qué stacks tienen imagen nueva (sin descargar)
  eva update [stack|all] [--force]
                            actualiza solo los que tienen novedades + prune
  eva up|down|restart [stack|all]
  eva prune                 docker system prune -a --volumes -f
"""


def main(argv):
    if argv and argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv and argv[0] == "install":
        return 0 if cmd_install() else 1
    if not load_config():
        warn(f"eva no está configurado (falta {ENV_KEY} en {ENV_FILE})")
        if not cmd_install():
            return 1
        input(f"\n{D}Enter para continuar...{R}")
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
        "stacks": cmd_stacks, "status": cmd_status,
        "check": lambda: cmd_check(arg),
        "logs": lambda: cmd_logs(arg),
        "update": lambda: cmd_update(arg if arg != "--force" else None, "--force" in flags),
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
