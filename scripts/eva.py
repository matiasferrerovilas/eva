#!/usr/bin/env python3
"""eva - homelab CLI (interactive menu + subcommands). No third-party deps."""

import json
import os
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VERSION = "0.1.0"
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
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")

# ── ANSI ─────────────────────────────────────────────────────
R, B, D = "\033[0m", "\033[1m", "\033[2m"
RED, GREEN, YELLOW, BLUE, CYAN, WHITE = (
    "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m", "\033[97m",
)
if not sys.stdout.isatty():
    R = B = D = RED = GREEN = YELLOW = BLUE = CYAN = WHITE = ""

# ── i18n ─────────────────────────────────────────────────────
# id -> (español, english). Add a language by adding a column and a LANGS entry.
LANGS = ("es", "en")
STR = {
    "inst.title": ("🛠️  Configuración", "🛠️  Setup"),
    "inst.lang": ("Idioma / Language", "Idioma / Language"),
    "inst.path": ("Carpeta donde están tus contenedores (archivos compose) [{cur}]",
                  "Folder that holds your containers (compose files) [{cur}]"),
    "inst.notexist": ("{path} no existe. ¿Crearla? [y/N]", "{path} does not exist. Create it? [y/N]"),
    "inst.cancel": ("Configuración cancelada", "Setup cancelled"),
    "inst.found": ("{n} stack(s) encontrados", "{n} stack(s) found"),
    "inst.exclude": ("Stacks a excluir del update/check masivo, separados por coma [{cur}] ('-' para vaciar)",
                     "Stacks to exclude from bulk update/check, comma-separated [{cur}] ('-' to clear)"),
    "inst.none": ("ninguno", "none"),
    "inst.symlink": ("¿Instalar el comando 'eva' en {target}? (sudo) [Y/n]",
                     "Install the 'eva' command in {target}? (sudo) [Y/n]"),
    "inst.symlink_ok": ("Comando 'eva' instalado", "'eva' command installed"),
    "inst.symlink_fail": ("No se pudo crear el symlink", "Could not create the symlink"),
    "inst.comp": ("¿Activar el autocompletado de {shell} en {rc}? [Y/n]",
                  "Enable {shell} completion in {rc}? [Y/n]"),
    "inst.comp_ok": ("Autocompletado activado. Abre una terminal nueva o ejecuta: source {rc}",
                     "Completion enabled. Open a new terminal or run: source {rc}"),
    "inst.comp_have": ("Autocompletado ya activo en {rc}", "Completion already enabled in {rc}"),
    "notconf": ("eva no está configurado (falta {key} en {path})",
                "eva is not configured ({key} is missing in {path})"),
    "enter_cont": ("Enter para continuar...", "Press Enter to continue..."),
    "inst.bin": ("¿Dónde instalar el comando 'eva'?\n  1) ~/.local/bin (sin sudo)\n  2) /usr/local/bin (con sudo)\n  3) No instalar\nElige [1]:",
                 "Where to install the 'eva' command?\n  1) ~/.local/bin (no sudo)\n  2) /usr/local/bin (with sudo)\n  3) Do not install\nChoose [1]:"),
    "inst.path_warn": ("{dir} no está en tu PATH. Agrega esto a tu archivo rc: export PATH=\"$HOME/.local/bin:$PATH\"",
                       "{dir} is not in your PATH. Add this to your shell rc file: export PATH=\"$HOME/.local/bin:$PATH\""),
    "inst.exists": ("{target} ya existe y no es un symlink; no lo toco.",
                    "{target} already exists and is not a symlink; leaving it alone."),
    "self.title": ("⬆️  Actualizar eva", "⬆️  Update eva"),
    "self.notgit": ("eva no está instalado desde un clon de git, no puede actualizarse solo.",
                    "eva was not installed from a git clone, so it cannot update itself."),
    "self.noup": ("La rama actual no tiene upstream configurado.", "The current branch has no upstream configured."),
    "self.fetching": ("Buscando cambios...", "Looking for changes..."),
    "self.latest": ("Ya tienes la última versión ({v})", "You already have the latest version ({v})"),
    "self.pulling": ("Hay {n} commit(s) nuevos. Actualizando...", "{n} new commit(s). Updating..."),
    "self.done": ("Actualizado: {old} → {new}", "Updated: {old} → {new}"),
    "self.fail": ("git no pudo actualizar:\n{out}", "git could not update:\n{out}"),
    "sys.eva": ("Actualizar eva", "Update eva"),
    "self.avail": ("Hay una versión nueva de eva ({n} commit(s)). Actualízala en Sistema → Actualizar eva",
                   "A new version of eva is available ({n} commit(s)). Update it in System → Update eva"),
    "self.restart": ("Vuelve a ejecutar eva para usar la nueva versión", "Run eva again to use the new version"),
    "d.update_self": ("Actualizar eva desde git", "Update eva from git"),
    "d.version": ("Versión de eva", "eva version"),
    "pf.nodocker": ("Docker no encontrado. Instálalo: https://docs.docker.com/engine/install/",
                    "Docker not found. Install it: https://docs.docker.com/engine/install/"),
    "pf.perm": ("Sin permisos sobre Docker. Ejecuta: sudo usermod -aG docker $USER (y vuelve a iniciar sesión)",
                "No permission to use Docker. Run: sudo usermod -aG docker $USER (then log out and back in)"),
    "pf.daemon": ("No se pudo conectar al daemon de Docker. ¿Está corriendo? Prueba: sudo systemctl start docker",
                  "Cannot reach the Docker daemon. Is it running? Try: sudo systemctl start docker"),
    "pf.compose": ("Falta el plugin Docker Compose (docker compose). Guía: https://docs.docker.com/compose/install/linux/",
                   "The Docker Compose plugin (docker compose) is missing. Guide: https://docs.docker.com/compose/install/linux/"),
    "pf.buildx": ("Falta docker buildx: el chequeo de novedades no podrá comparar imágenes.",
                  "docker buildx is missing: the update check will not be able to compare images."),
    "doctor.title": ("🩺 Diagnóstico", "🩺 Diagnostics"),
    "doctor.cfg_bad": ("Falta configurar eva. Ejecuta: eva install", "eva is not configured. Run: eva install"),
    "doctor.good": ("Todo en orden", "All good"),
    "doctor.bad": ("Hay problemas que resolver", "There are problems to fix"),
    "d.doctor": ("Diagnóstico de requisitos", "Check requirements"),
    "pick.hint": ("↑↓ mover · Enter/Espacio elegir · q volver",
                  "↑↓ move · Enter/Space select · q back"),
    "ask.choose": ("Elige", "Choose"),
    "back": ("volver", "back"),
    "invalid": ("Opción inválida", "Invalid option"),
    "ps.title": ("🐳 Contenedores", "🐳 Containers"),
    "ps.none": ("No hay contenedores", "No containers"),
    "col.container": ("CONTENEDOR", "CONTAINER"),
    "col.state": ("ESTADO", "STATE"),
    "col.netports": ("REDES / PUERTOS", "NETWORKS / PORTS"),
    "esc_back": ("Esc para volver", "Esc to go back"),
    "sys.title": ("🖥️  Sistema", "🖥️  System"),
    "sys.docker": ("Limpiar Docker", "Clean up Docker"),
    "sys.invalid": ("Acción '{a}' inválida: {opts}", "Invalid action '{a}': {opts}"),
    "logs.pick": ("📜 ¿Logs de qué contenedor?", "📜 Logs of which container?"),
    "logs.follow": ("Siguiendo logs de {name} — Ctrl+C para volver",
                    "Following logs of {name} — Ctrl+C to go back"),
    "pull.fail": ("{name}: pull falló\n{out}", "{name}: pull failed\n{out}"),
    "up.fail": ("{name}: up falló\n{out}", "{name}: up failed\n{out}"),
    "upd.new": ("{name}: imagen nueva, contenedor recreado", "{name}: new image, container recreated"),
    "upd.same": ("{name}: sin cambios", "{name}: no changes"),
    "st.new": ("⬆ nueva versión", "⬆ new version"),
    "st.ok": ("✔ al día", "✔ up to date"),
    "st.missing": ("⬇ sin descargar", "⬇ not pulled"),
    "st.unknown": ("? sin info remota", "? no remote info"),
    "all_stacks": ("Todos los stacks", "All stacks"),
    "all": ("Todos", "All"),
    "excl_tag": ("(excluido de 'todos')", "(excluded from 'all')"),
    "notfound": ("Stack '{name}' no encontrado", "Stack '{name}' not found"),
    "check.pick": ("🔎 ¿Qué stacks chequear?", "🔎 Which stacks to check?"),
    "check.title": ("🔎 Novedades", "🔎 Updates"),
    "n_stacks": ("{n} stack(s)", "{n} stack(s)"),
    "skipped": ("Excluidos por config: {names}", "Excluded by config: {names}"),
    "querying": ("Consultando registries...", "Querying registries..."),
    "with_news": ("{n} stack(s) con novedades", "{n} stack(s) with updates"),
    "uptodate": ("Todo al día", "Everything is up to date"),
    "upd.pick": ("🔄 ¿Qué actualizar?", "🔄 What to update?"),
    "upd.title": ("🔄 Update", "🔄 Update"),
    "searching": ("Buscando novedades...", "Looking for updates..."),
    "nothing": ("Todo al día, no hay nada que actualizar", "Everything is up to date, nothing to update"),
    "pend.title": ("{n} stack(s) con novedades", "{n} stack(s) with updates"),
    "pend.only": ("Actualizar solo los que tienen novedades ({names})", "Update only those with news ({names})"),
    "pend.force": ("Forzar los {n} seleccionados", "Force all {n} selected"),
    "with_errors": ("Con errores: {names}", "With errors: {names}"),
    "all_updated": ("Todo actualizado", "Everything updated"),
    "compose.pick": ("⚙️  {action}: ¿qué stack?", "⚙️  {action}: which stack?"),
    "compose.action": ("⚙️  Acción", "⚙️  Action"),
    "dash.disk": ("Disco", "Disk"),
    "dash.cpu": ("load {load} · {cpus} núcleos · activo {up}", "load {load} · {cpus} cores · up {up}"),
    "dash.running": ("{up}/{total} contenedores running", "{up}/{total} containers running"),
    "dash.more": ("… y {n} más", "… and {n} more"),
    "status.title": ("📊 Estado", "📊 Status"),
    "menu.ps": ("Listar contenedores", "List containers"),
    "menu.stacks": ("Listar stacks", "List stacks"),
    "menu.logs": ("Ver logs", "View logs"),
    "menu.update": ("Update (ver novedades, pull, recrear, prune)", "Update (check news, pull, recreate, prune)"),
    "menu.compose": ("Up / Down / Restart", "Up / Down / Restart"),
    "menu.system": ("Sistema (apt, limpiar Docker)", "System (apt, clean up Docker)"),
    "menu.config": ("Configuración (idioma, ruta de contenedores)", "Setup (language, containers folder)"),
    "menu.exit": ("Salir", "Exit"),
    "menu.question": ("¿Qué quieres hacer?", "What do you want to do?"),
    "menu.back": ("Esc / Enter para volver al menú", "Esc / Enter to go back to the menu"),
    "d.containers": ("Contenedores (redes, puertos)", "Containers (networks, ports)"),
    "d.stacks": ("Listar stacks", "List stacks"),
    "d.logs": ("Seguir logs de un contenedor", "Follow container logs"),
    "d.update": ("Actualizar stacks con novedades", "Update stacks that have news"),
    "d.check": ("Ver qué stacks tienen imagen nueva", "Show which stacks have newer images"),
    "d.up": ("Levantar stacks", "Start stacks"),
    "d.down": ("Bajar stacks", "Stop stacks"),
    "d.restart": ("Reiniciar stacks", "Restart stacks"),
    "d.system": ("apt y limpieza de Docker", "apt and Docker cleanup"),
    "d.status": ("Temperatura, RAM, disco, salud y stacks", "Temperature, RAM, disk, health and stacks"),
    "d.install": ("Configurar eva", "Configure eva"),
    "d.prune": ("Docker system prune", "Docker system prune"),
    "usage": (
        """eva — homelab CLI

  eva                       menú interactivo
  eva install               configurar idioma, ruta de contenedores y autocompletado
  eva containers [-a] [-w] [-i N]
                            contenedores (redes, puertos). -a todos, -w watch
  eva stacks                listar stacks
  eva status                temperatura, RAM, disco, salud y stacks
  eva logs [contenedor]     seguir logs
  eva check [stack|all]     ver qué stacks tienen imagen nueva (sin descargar)
  eva update [stack|all] [--force]
                            actualiza solo los que tienen novedades + prune
  eva up|down|restart [stack|all]
  eva system update|upgrade|clean|docker
                            apt update+upgrade / full-upgrade / autoremove / limpiar Docker
  eva prune                 docker system prune -a --volumes -f
  eva doctor                diagnóstico de requisitos (Docker, Compose, Buildx, config)
  eva update-self           actualizar eva desde git (git pull --ff-only)
  eva --version             versión de eva
  eva completion [zsh|bash] imprime el script de autocompletado
""",
        """eva — homelab CLI

  eva                       interactive menu
  eva install               configure language, containers folder and completion
  eva containers [-a] [-w] [-i N]
                            containers (networks, ports). -a all, -w watch
  eva stacks                list stacks
  eva status                temperature, RAM, disk, health and stacks
  eva logs [container]      follow logs
  eva check [stack|all]     show which stacks have newer images (downloads nothing)
  eva update [stack|all] [--force]
                            update only stacks that have news + prune
  eva up|down|restart [stack|all]
  eva system update|upgrade|clean|docker
                            apt update+upgrade / full-upgrade / autoremove / Docker cleanup
  eva prune                 docker system prune -a --volumes -f
  eva doctor                check requirements (Docker, Compose, Buildx, config)
  eva update-self           update eva from git (git pull --ff-only)
  eva --version             print eva's version
  eva completion [zsh|bash] print the shell completion script
""",
    ),
}
LANG = "es"


def t(key, **kw):
    entry = STR.get(key)
    text = entry[LANGS.index(LANG)] if entry else key
    return text.format(**kw) if kw else text


# ── output helpers ───────────────────────────────────────────
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


def ok(msg): print(f"{GREEN}✔{R} {msg}")
def warn(msg): print(f"{YELLOW}!{R} {msg}")
def err(msg): print(f"{RED}✘{R} {msg}")
def info(msg): print(f"{BLUE}•{R} {msg}")


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


def load_language():
    global LANG
    lang = read_env().get("language", "es")
    LANG = lang if lang in LANGS else "es"


def load_config():
    global ROOT
    load_language()
    value = read_env().get(ENV_KEY)
    if value and Path(value).expanduser().is_dir():
        ROOT = Path(value).expanduser()
        return True
    return False


load_language()


def excluded_stacks():
    """Stack names skipped by bulk update/check ('all'), from config `excluded_stacks`."""
    raw = read_env().get("excluded_stacks", "")
    return {n.strip() for n in raw.split(",") if n.strip()}


# ── shell completion ─────────────────────────────────────────
ZSH_COMPLETION = r"""#compdef eva
(( $+functions[compdef] )) || { autoload -Uz compinit && compinit }
_eva() {
  local -a cmds
  cmds=(
@CMDS@
  )
  if (( CURRENT == 2 )); then
    _describe 'eva' cmds
    return
  fi
  case $words[2] in
    containers|ps) compadd -- -a -w -i ;;
    system) compadd -- update upgrade clean docker ;;
    update) compadd -- all --force ${(f)"$(eva _complete stacks 2>/dev/null)"} ;;
    check|up|down|restart) compadd -- all ${(f)"$(eva _complete stacks 2>/dev/null)"} ;;
    logs) compadd -- ${(f)"$(eva _complete containers 2>/dev/null)"} ;;
  esac
}
compdef _eva eva
"""

BASH_COMPLETION = r"""_eva() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "@NAMES@" -- "$cur") )
    return
  fi
  case "${COMP_WORDS[1]}" in
    containers|ps) COMPREPLY=( $(compgen -W "-a -w -i" -- "$cur") ) ;;
    system) COMPREPLY=( $(compgen -W "update upgrade clean docker" -- "$cur") ) ;;
    update) COMPREPLY=( $(compgen -W "all --force $(eva _complete stacks 2>/dev/null)" -- "$cur") ) ;;
    check|up|down|restart) COMPREPLY=( $(compgen -W "all $(eva _complete stacks 2>/dev/null)" -- "$cur") ) ;;
    logs) COMPREPLY=( $(compgen -W "$(eva _complete containers 2>/dev/null)" -- "$cur") ) ;;
  esac
}
complete -F _eva eva
"""

COMP_COMMANDS = [
    ("containers", "d.containers"), ("stacks", "d.stacks"), ("status", "d.status"),
    ("logs", "d.logs"), ("check", "d.check"), ("update", "d.update"),
    ("up", "d.up"), ("down", "d.down"), ("restart", "d.restart"),
    ("system", "d.system"), ("prune", "d.prune"), ("install", "d.install"),
    ("doctor", "d.doctor"), ("update-self", "d.update_self"), ("version", "d.version"),
]


def completion_script(shell):
    if shell == "zsh":
        cmds = "\n".join(f"    '{name}:{t(desc)}'" for name, desc in COMP_COMMANDS)
        return ZSH_COMPLETION.replace("@CMDS@", cmds)
    return BASH_COMPLETION.replace("@NAMES@", " ".join(n for n, _ in COMP_COMMANDS))


def install_completion():
    """zsh if installed, otherwise bash. Appends one `source` line to the rc file."""
    shell = "zsh" if shutil.which("zsh") else "bash"
    rc = Path.home() / (".zshrc" if shell == "zsh" else ".bashrc")
    if rc.exists() and "eva completion" in rc.read_text():
        info(t("inst.comp_have", rc=rc))
        return
    if input(t("inst.comp", shell=shell, rc=rc) + " ").strip().lower() == "n":
        return
    with rc.open("a") as f:
        f.write(f"\n# eva completion\nsource <(eva completion {shell})\n")
    ok(t("inst.comp_ok", rc=rc))


def install_command():
    """Link this script as `eva` into ~/.local/bin (no sudo) or /usr/local/bin (sudo)."""
    me = Path(__file__).resolve()
    found = shutil.which("eva")
    if found and Path(found).resolve() == me:
        return
    choice = input("\n" + t("inst.bin") + " ").strip() or "1"
    if choice == "1":
        d = Path.home() / ".local" / "bin"
        d.mkdir(parents=True, exist_ok=True)
        target = d / "eva"
        if target.exists() and not target.is_symlink():
            err(t("inst.exists", target=target))
            return
        if target.is_symlink():
            target.unlink()
        target.symlink_to(me)
        ok(t("inst.symlink_ok"))
        if str(d) not in os.environ.get("PATH", "").split(":"):
            warn(t("inst.path_warn", dir=d))
    elif choice == "2":
        r = subprocess.run(["sudo", "ln", "-sf", str(me), "/usr/local/bin/eva"])
        ok(t("inst.symlink_ok")) if r.returncode == 0 else err(t("inst.symlink_fail"))


def git(*args, timeout=60):
    # never block on a credential/passphrase prompt
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0",
           "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes"}
    return run(["git", "-C", str(BASE), *args], timeout=timeout, env=env)


UPDATE_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "eva" / "update.json"


def save_update_cache(behind):
    try:
        UPDATE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_CACHE.write_text(json.dumps({"t": time.time(), "behind": behind}))
    except OSError:
        pass


def update_status(max_age=6 * 3600):
    """Commits behind upstream, or None if unknown / not a git clone.
    Cached for `max_age` seconds so starting eva stays fast."""
    try:
        data = json.loads(UPDATE_CACHE.read_text())
    except (OSError, ValueError):
        data = {}
    if "behind" in data and time.time() - data.get("t", 0) < max_age:
        return data["behind"]
    behind = None
    if (shutil.which("git") and git("rev-parse", "--abbrev-ref", "@{u}", timeout=5).returncode == 0):
        if git("fetch", "--quiet", timeout=5).returncode != 0:
            return data.get("behind")  # offline: keep the last known value, retry next launch
        count = git("rev-list", "--count", "HEAD..@{u}", timeout=5).stdout.strip()
        behind = int(count) if count.isdigit() else None
    save_update_cache(behind)
    return behind


def version_string():
    r = git("rev-parse", "--short", "HEAD", timeout=5) if shutil.which("git") else None
    commit = r.stdout.strip() if r and r.returncode == 0 else ""
    return f"{VERSION} ({commit})" if commit else VERSION


def cmd_update_self():
    banner(t("self.title"), f"eva {VERSION}")
    if not shutil.which("git") or git("rev-parse", "--is-inside-work-tree", timeout=5).returncode != 0:
        err(t("self.notgit"))
        return 1
    if git("rev-parse", "--abbrev-ref", "@{u}", timeout=5).returncode != 0:
        err(t("self.noup"))
        return 1
    info(t("self.fetching"))
    fetch = git("fetch", "--quiet")
    if fetch.returncode != 0:
        err(t("self.fail", out=(fetch.stdout + fetch.stderr).strip()))
        return 1
    behind = int(git("rev-list", "--count", "HEAD..@{u}", timeout=5).stdout.strip() or 0)
    if behind == 0:
        ok(t("self.latest", v=version_string()))
        save_update_cache(0)
        return 0
    old = version_string()
    info(t("self.pulling", n=behind))
    pull = git("pull", "--ff-only")
    if pull.returncode != 0:
        err(t("self.fail", out=(pull.stdout + pull.stderr).strip()))
        return 1
    ok(t("self.done", old=old, new=version_string()))
    info(t("self.restart"))
    save_update_cache(0)
    return 0


def cmd_install():
    global ROOT, LANG
    banner(t("inst.title"), "eva")
    info(f"Config: {ENV_FILE}")
    try:
        raw = input(f"\n{CYAN}❯{R} {t('inst.lang')} [es/en] ({LANG}): ").strip().lower()
        if raw in LANGS:
            write_env("language", raw)
            LANG = raw
        elif not read_env().get("language"):
            write_env("language", LANG)
        ok(f"language={LANG}")
        current = read_env().get(ENV_KEY) or str(BASE / "services")
        raw = input(f"\n{CYAN}❯{R} {t('inst.path', cur=current)}: ").strip()
        path = Path(raw or current).expanduser().resolve()
        if not path.is_dir():
            if input(t("inst.notexist", path=path) + ": ").strip().lower() != "y":
                warn(t("inst.cancel"))
                return False
            path.mkdir(parents=True)
        write_env(ENV_KEY, str(path))
        ROOT = path
        ok(f"{ENV_KEY}={path}")
        ok(t("inst.found", n=len(find_stacks())))
        cur_ex = read_env().get("excluded_stacks", "")
        raw = input(f"\n{CYAN}❯{R} {t('inst.exclude', cur=cur_ex or t('inst.none'))}: ").strip()
        if raw:
            write_env("excluded_stacks", "" if raw == "-" else raw)
            ok(f"excluded_stacks={read_env().get('excluded_stacks', '')}")
        install_command()
        print()
        install_completion()
        return True
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ── docker helpers ───────────────────────────────────────────
def run(cmd, cwd=None, timeout=None, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def preflight():
    """Check Docker prerequisites. -> [(name, 'ok'|'warn'|'err', detail)]"""
    if not shutil.which("docker"):
        return [("Docker", "err", t("pf.nodocker"))]
    cmds = [["docker", "info", "--format", "{{.ServerVersion}}"],
            ["docker", "compose", "version", "--short"],
            ["docker", "buildx", "version"]]
    with ThreadPoolExecutor(max_workers=3) as pool:
        daemon, compose, buildx = pool.map(lambda c: run(c, timeout=15), cmds)
    if daemon.returncode == 0:
        docker_item = ("Docker", "ok", daemon.stdout.strip())
    else:
        msg = t("pf.perm") if "permission denied" in daemon.stderr.lower() else t("pf.daemon")
        docker_item = ("Docker", "err", msg)
    parts = buildx.stdout.split()
    return [
        docker_item,
        ("Compose", "ok" if compose.returncode == 0 else "err",
         compose.stdout.strip() if compose.returncode == 0 else t("pf.compose")),
        ("Buildx", "ok" if buildx.returncode == 0 else "warn",
         (parts[1] if len(parts) > 1 else "ok") if buildx.returncode == 0 else t("pf.buildx")),
    ]


def has_buildx():
    return run(["docker", "buildx", "version"], timeout=15).returncode == 0


def cmd_doctor():
    banner(t("doctor.title"), "eva")
    print()
    ok(f"Python {sys.version.split()[0]}")
    icons = {"ok": ok, "warn": warn, "err": err}
    items = preflight()
    for name, status, detail in items:
        icons[status](f"{B}{name}{R}  {detail}")
    if load_config():
        ok(f"{B}Config{R}  {ENV_KEY}={ROOT}  ·  language={LANG}")
    else:
        err(f"{B}Config{R}  {t('doctor.cfg_bad')}")
        items.append(("Config", "err", ""))
    print(line())
    bad = any(s == "err" for _, s, _ in items)
    (err if bad else ok)(t("doctor.bad") if bad else t("doctor.good"))
    return 1 if bad else 0


def find_stacks():
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        name = next((n for n in COMPOSE_NAMES if n in filenames), None)
        if name:
            found.append(Path(dirpath) / name)
    return sorted(found)


SKIPPED = []  # names left out of the last bulk selection, for display


def find_stack(name):
    for s in find_stacks():
        if s.parent.name == name:
            return s
    return None


def containers():
    """All containers: dicts with name, status, state, stack, image, ports, networks."""
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
def ask(prompt=None):
    try:
        return input(f"\n{CYAN}❯{R} {prompt or t('ask.choose')}: ").strip()
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
    print(f"\n{B}{title}{R}  {D}{t('pick.hint')}{R}")
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
    print(f" {D}  q  {t('back')}{R}")
    ans = ask()
    if ans.lower() in ("q", ""):
        return None
    for key, _ in extra or []:
        if ans == key:
            return key
    if ans.isdigit() and 1 <= int(ans) <= len(items):
        return int(ans) - 1
    warn(t("invalid"))
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
    banner(t("ps.title"), f"{up}/{len(cts)} running{hint}")
    if not cts:
        warn(t("ps.none"))
        return
    nw = max(len(c["name"]) for c in cts)
    sw = max(len(c["stack"]) for c in cts)
    head = f"{t('col.container').ljust(nw)}  {'STACK'.ljust(sw)}  {t('col.state').ljust(26)}  {t('col.netports')}"
    print(f"   {B}{head}{R}")
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
            print(f"{D}{t('esc_back')}{R}", flush=True)
            if wait_key(interval):
                break
    except KeyboardInterrupt:
        pass
    clear()


def docker_prune():
    print(f"\n{D}🧹 docker system prune -a --volumes -f{R}")
    r = run(["docker", "system", "prune", "-a", "--volumes", "-f"])
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    ok(tail) if r.returncode == 0 else err(r.stderr.strip())


def cmd_system(action=None):
    cmds = {
        "update": ("apt update + upgrade", "sudo apt update && sudo apt upgrade -y"),
        "upgrade": ("apt full-upgrade", "sudo apt full-upgrade -y"),
        "clean": ("autoremove + autoclean", "sudo apt autoremove -y && sudo apt autoclean"),
        "docker": (t("sys.docker"), None),
        "eva": (t("sys.eva"), None),
    }
    if action is None:
        keys = list(cmds)
        behind = update_status()
        sel = pick(t("sys.title"), [
            (cmds[k][0] + (f" {YELLOW}⬆{R}" if k == "eva" and behind else "")) if k in ("docker", "eva")
            else f"{k}  {D}{cmds[k][0]}{R}" for k in keys])
        if sel is None:
            return
        action = keys[sel]
    if action not in cmds:
        err(t("sys.invalid", a=action, opts=", ".join(cmds)))
        return
    if action == "docker":
        return docker_prune()
    if action == "eva":
        return cmd_update_self()
    print(f"\n{B}{cmds[action][0]}{R}")
    try:
        subprocess.run(cmds[action][1], shell=True)  # constant strings only
    except KeyboardInterrupt:
        pass


def cmd_stacks():
    stacks = find_stacks()
    banner("📦 Stacks", f"{len(stacks)} compose")
    cts = containers()
    nw = max((len(s.parent.name) for s in stacks), default=5)
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
        idx = pick(t("logs.pick"), labels)
        if idx is None:
            return
        name = cts[idx]["name"]
    print(f"\n{D}{t('logs.follow', name=name)}{R}\n")
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


def stack_images_of(compose):
    cfg = run(["docker", "compose", "config", "--images"], cwd=str(compose.parent))
    return sorted({i.strip() for i in cfg.stdout.splitlines() if i.strip()})


def update_stack(compose):
    name = compose.parent.name
    cwd = str(compose.parent)
    images = stack_images_of(compose)
    before = image_ids(images)

    print(f"{D}⋯ {name}: pull...{R}")
    pull = run(["docker", "compose", "pull"], cwd=cwd)
    if pull.returncode != 0:
        err(t("pull.fail", name=name, out=(pull.stdout + pull.stderr).strip()))
        return False
    changed = before != image_ids(images)

    up = run(["docker", "compose", "up", "-d", "--remove-orphans"], cwd=cwd)
    if up.returncode != 0:
        err(t("up.fail", name=name, out=(up.stdout + up.stderr).strip()))
        return False
    if changed:
        ok(f"{B}{t('upd.new', name=name)}{R}")
    else:
        info(t("upd.same", name=name))
    return True


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
    if not has_buildx():
        warn(t("pf.buildx"))
    pairs = [(tg, img) for tg in targets for img in stack_images_of(tg)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        states = list(pool.map(lambda p: image_state(p[1]), pairs))
    result = {tg: [] for tg in targets}
    for (tg, img), st in zip(pairs, states):
        result[tg].append((img, st))
    return result


def render_check(result):
    colors = {"new": YELLOW, "ok": GREEN, "missing": YELLOW, "unknown": D}
    nw = max((len(tg.parent.name) for tg in result), default=5)
    for tg, imgs in result.items():
        print(f" {B}{tg.parent.name.ljust(nw)}{R}")
        for img, st in imgs:
            print(f"   {colors[st]}{t('st.' + st).ljust(20)}{R} {D}{img.split('@')[0]}{R}")


def pending_stacks(result):
    return [tg for tg, imgs in result.items() if any(s in ("new", "missing") for _, s in imgs)]


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
        tag = "  " + t("excl_tag")
        labels = [f"{s.parent.name}  {D}{s.parent.relative_to(ROOT)}"
                  f"{tag if s.parent.name in ex else ''}{R}" for s in stacks]
        sel = pick(title, labels, extra=[("a", f"{B}{t('all_stacks')}{R}")])
        if sel is None:
            return None
        return bulk() if sel == "a" else [stacks[sel]]
    if name == "all":
        return bulk()
    s = find_stack(name)
    if not s:
        err(t("notfound", name=name))
        return None
    return [s]


def cmd_check(name=None):
    targets = resolve_targets(name, t("check.pick"), find_stacks())
    if not targets:
        return
    banner(t("check.title"), t("n_stacks", n=len(targets)))
    if SKIPPED:
        info(t("skipped", names=", ".join(SKIPPED)))
    info(t("querying"))
    result = check_updates(targets)
    print()
    render_check(result)
    n = len(pending_stacks(result))
    print(line())
    (warn if n else ok)(t("with_news", n=n) if n else t("uptodate"))


def cmd_update(name=None, force=False):
    targets = resolve_targets(name, t("upd.pick"), find_stacks())
    if not targets:
        return
    banner(t("upd.title"), t("n_stacks", n=len(targets)))
    if SKIPPED:
        info(t("skipped", names=", ".join(SKIPPED)))
    info(t("searching"))
    result = check_updates(targets)
    print()
    render_check(result)
    pend = pending_stacks(result)
    print(line())
    chosen = targets if force else pend
    if name is None and sys.stdin.isatty() and not force:
        if not pend:
            ok(t("nothing"))
            return
        sel = pick(t("pend.title", n=len(pend)), [
            t("pend.only", names=", ".join(tg.parent.name for tg in pend)),
            t("pend.force", n=len(targets))])
        if sel is None:
            return
        chosen = pend if sel == 0 else targets
    elif not chosen:
        ok(t("nothing"))
        return
    banner(t("upd.title"), t("n_stacks", n=len(chosen)))
    failed = [tg.parent.name for tg in chosen if not update_stack(tg)]
    docker_prune()
    print(line())
    if failed:
        warn(t("with_errors", names=", ".join(failed)))
    else:
        ok(t("all_updated"))


def cmd_compose(action, name=None):
    stacks = find_stacks()
    if name is None:
        labels = [s.parent.name for s in stacks]
        sel = pick(t("compose.pick", action=action), labels, extra=[("a", f"{B}{t('all')}{R}")])
        if sel is None:
            return
        targets = stacks if sel == "a" else [stacks[sel]]
    elif name == "all":
        targets = stacks
    else:
        s = find_stack(name)
        if not s:
            err(t("notfound", name=name))
            return
        targets = [s]
    args = {"up": ["up", "-d"], "down": ["down"], "restart": ["restart"]}[action]
    for tg in targets:
        r = run(["docker", "compose", *args], cwd=str(tg.parent))
        ok(f"{tg.parent.name}: {action}") if r.returncode == 0 else err(
            f"{tg.parent.name}: {r.stderr.strip()}")


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
    temp = cpu_temp()
    if temp is not None:  # Pi throttles ~80°C
        rows.append(("Temp", bar(temp, 60, 75), f"{temp:.1f}°C"))
    mem = mem_info()
    if mem:
        rows.append(("RAM", bar(mem[0] / mem[1] * 100), f"{mem[0]:.1f} / {mem[1]:.1f} GB"))
    du = shutil.disk_usage("/")
    rows.append((t("dash.disk"), bar(du.used / du.total * 100, 70, 90),
                 f"{du.used / 1e9:.0f} / {du.total / 1e9:.0f} GB"))
    load, cpus = os.getloadavg()[0], os.cpu_count() or 1
    rows.append(("CPU", bar(load / cpus * 100),
                 t("dash.cpu", load=f"{load:.2f}", cpus=cpus, up=uptime_str())))
    print()
    for label, b, val in rows:
        print(f" {B}{label.ljust(6)}{R}{b}  {val}")
    cts = containers()
    up = sum(1 for c in cts if c["state"] == "running")
    bad = [c for c in cts if dot(c) != f"{GREEN}●{R}"]
    col = GREEN if not bad else YELLOW
    print(f"\n {col}●{R} {t('dash.running', up=f'{B}{up}{R}', total=f'{B}{len(cts)}{R}')}")
    for c in bad[:5]:
        print(f"   {RED}✘{R} {c['name']}  {D}{c['status']}{R}")
    if len(bad) > 5:
        print(f"   {D}{t('dash.more', n=len(bad) - 5)}{R}")


def cmd_status():
    banner(t("status.title"), "homelab")
    dashboard()
    print()
    cmd_stacks()


# ── menu ─────────────────────────────────────────────────────
MENU = [
    ("1", "menu.ps", lambda: cmd_ps(show_all=True)),
    ("2", "menu.stacks", cmd_stacks),
    ("3", "menu.logs", cmd_logs),
    ("4", "menu.update", cmd_update),
    ("5", "menu.compose", None),
    ("6", "menu.system", cmd_system),
    ("7", "menu.config", cmd_install),
    ("0", "menu.exit", None),
]


def menu():
    try:
        _menu_loop()
    finally:
        clear()


def _menu_loop():
    while True:
        clear()
        banner("🏠 EVA", f"homelab · v{version_string()}")
        behind = update_status()
        if behind:
            print(f"\n {YELLOW}⬆{R} {t('self.avail', n=behind)}")
        dashboard()
        print()
        sel = pick(t("menu.question"), [
            t(label) + (f" {YELLOW}⬆{R}" if behind and key == "6" else "") for key, label, _ in MENU])
        if sel is None or MENU[sel][0] == "0":
            return
        key, _, fn = MENU[sel]
        if key == "5":
            act = pick(t("compose.action"), ["up", "down", "restart"])
            if act is None:
                continue
            cmd_compose(["up", "down", "restart"][act])
        else:
            fn()
        if key != "3" and not CANCELLED:
            print(f"\n{D}{t('menu.back')}{R}", flush=True)
            while not wait_key() and sys.stdin.isatty():
                pass


def usage():
    return t("usage")


def main(argv):
    if argv and argv[0] in ("-h", "--help", "help"):
        load_language()
        print(usage())
        return 0
    if argv and argv[0] in ("--version", "-v", "version"):
        print(f"eva {version_string()}")
        return 0
    if argv and argv[0] == "update-self":
        load_language()
        return cmd_update_self()
    if argv and argv[0] == "completion":
        load_language()
        shell = argv[1] if len(argv) > 1 else ("zsh" if shutil.which("zsh") else "bash")
        if shell not in ("zsh", "bash"):
            print(usage())
            return 1
        print(completion_script(shell))
        return 0
    if argv and argv[0] == "_complete":  # hidden: used by the completion scripts
        if load_config():
            if len(argv) > 1 and argv[1] == "stacks":
                print("\n".join(sorted({s.parent.name for s in find_stacks()})))
            elif len(argv) > 1 and argv[1] == "containers":
                print("\n".join(c["name"] for c in containers()))
        return 0
    if argv and argv[0] == "install":
        return 0 if cmd_install() else 1
    if argv and argv[0] == "doctor":
        load_language()
        return cmd_doctor()
    if not load_config():
        warn(t("notconf", key=ENV_KEY, path=ENV_FILE))
        if not cmd_install():
            return 1
        input(f"\n{D}{t('enter_cont')}{R}")
    problems = [d for _, s, d in preflight() if s == "err"]
    if problems:
        for p in problems:
            err(p)
        return 1
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
        print(usage())
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
