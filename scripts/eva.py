#!/usr/bin/env python3
"""eva - homelab CLI (interactive menu + subcommands). No third-party deps."""

import io
import json
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

VERSION = "0.1.0"
BASE = Path(__file__).resolve().parent.parent  # clone root: <BASE>/scripts/eva.py
CONFIG_DIR = BASE / "config"
ENV_FILE = CONFIG_DIR / ".env"
ENV_KEY = "containers_location"
ROOT = None  # set by load_config()
CANCELLED = False  # set by pick() when the user backs out (Esc / Ctrl+C)
ASSUME_YES = False  # --yes: skip confirmations (required when there is no terminal)
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
    "live.total": ("Total: CPU {cpu} · RAM {mem}", "Total: CPU {cpu} · RAM {mem}"),
    "confirm.no": ("No, cancelar", "No, cancel"),
    "confirm.yes": ("Sí, continuar", "Yes, continue"),
    "confirm.needs_yes": ("Esta acción necesita confirmación. Ejecutala en una terminal interactiva o agregá --yes.",
                          "This action needs confirmation. Run it in an interactive terminal or add --yes."),
    "confirm.down": ("¿Bajar {n} stack(s)? Se detienen y eliminan sus contenedores (los volúmenes se conservan)",
                     "Stop {n} stack(s)? Their containers are stopped and removed (volumes are kept)"),
    "confirm.down_all": ("¿Bajar TODOS los stacks ({n})? Esto apaga todo el homelab, incluido el acceso externo",
                         "Stop ALL stacks ({n})? This shuts down the whole homelab, including remote access"),
    "clean.title": ("🧹 Limpiar Docker", "🧹 Clean up Docker"),
    "clean.df": ("Uso actual de Docker:", "Current Docker usage:"),
    "clean.sec.dangling": ("Imágenes viejas sin etiqueta: {n}", "Old untagged images: {n}"),
    "clean.sec.unused": ("Imágenes sin uso: {n}", "Unused images: {n}"),
    "clean.sec.stopped": ("Contenedores detenidos: {n}", "Stopped containers: {n}"),
    "clean.sec.volumes": ("Volúmenes sin uso: {n}", "Unused volumes: {n}"),
    "clean.safe": ("Segura: imágenes viejas sin etiqueta y caché de build",
                   "Safe: old untagged images and build cache"),
    "clean.all": ("Completa: además imágenes sin uso, contenedores detenidos y redes sin uso",
                  "Full: also unused images, stopped containers and unused networks"),
    "clean.volumes": ("Completa + volúmenes sin uso (puede borrar datos de stacks que estén caídos)",
                      "Full + unused volumes (may delete the data of stacks that are down)"),
    "clean.all_confirm": ("¿Ejecutar la limpieza completa? Elimina contenedores detenidos e imágenes sin uso",
                          "Run the full cleanup? It removes stopped containers and unused images"),
    "clean.volumes_confirm": ("¿Borrar {n} volumen(es) sin uso? No se puede deshacer",
                              "Delete {n} unused volume(s)? This cannot be undone"),
    "clean.done": ("Limpieza terminada", "Cleanup finished"),
    "logs.reconnect": ("El contenedor se reinició o cortó el stream; reconectando...",
                       "The container restarted or the stream dropped; reconnecting..."),
    "logs.stopped": ("{name} está en estado '{status}'. Fin de los logs.",
                     "{name} is '{status}'. End of logs."),
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
    "menu.containers": ("Contenedores", "Containers"),
    "menu.ctaction": ("Up / Restart / Down de un contenedor", "Up / Restart / Down of a container"),
    "menu.stackaction": ("Up / Restart / Down de un stack", "Up / Restart / Down of a stack"),
    "ct.action": ("⚙️  Acción sobre el contenedor", "⚙️  Container action"),
    "ct.pick": ("{action}: ¿qué contenedor?", "{action}: which container?"),
    "ct.notfound": ("Contenedor '{name}' no encontrado", "Container '{name}' not found"),
    "ct.ok": ("{name}: {action} OK", "{name}: {action} OK"),
    "d.container": ("Up, restart o down de un contenedor", "Up, restart or down a container"),
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
                            contenedores con CPU, RAM, redes y puertos. -a todos, -w en vivo
  eva stacks [-w] [-i N]    stacks con CPU y RAM (-w en vivo)
  eva status                temperatura, RAM, disco, salud y stacks
  eva logs [contenedor]     seguir logs
  eva check [stack|all]     ver qué stacks tienen imagen nueva (sin descargar)
  eva update [stack|all] [--force]
                            actualiza solo los que tienen novedades + prune
  eva up|down|restart [stack|all]   (down pide confirmación; --yes la omite)
  eva container up|restart|down [nombre]
                            start / restart / stop de un contenedor
  eva system update|upgrade|clean|docker
                            apt update+upgrade / full-upgrade / autoremove / limpiar Docker
  eva prune [--all|--volumes]  limpieza de Docker: segura por defecto; --all y --volumes piden confirmación
  eva doctor                diagnóstico de requisitos (Docker, Compose, Buildx, config)
  eva update-self           actualizar eva desde git (git pull --ff-only)
  eva --version             versión de eva
  eva completion [zsh|bash] imprime el script de autocompletado
""",
        """eva — homelab CLI

  eva                       interactive menu
  eva install               configure language, containers folder and completion
  eva containers [-a] [-w] [-i N]
                            containers with CPU, RAM, networks and ports. -a all, -w live
  eva stacks [-w] [-i N]    stacks with CPU and RAM (-w live)
  eva status                temperature, RAM, disk, health and stacks
  eva logs [container]      follow logs
  eva check [stack|all]     show which stacks have newer images (downloads nothing)
  eva update [stack|all] [--force]
                            update only stacks that have news + prune
  eva up|down|restart [stack|all]   (down asks for confirmation; --yes skips it)
  eva container up|restart|down [name]
                            start / restart / stop one container
  eva system update|upgrade|clean|docker
                            apt update+upgrade / full-upgrade / autoremove / Docker cleanup
  eva prune [--all|--volumes]  Docker cleanup: safe by default; --all and --volumes ask for confirmation
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
    stacks) compadd -- -w -i ;;
    prune) compadd -- --all --volumes --yes ;;
    system) compadd -- update upgrade clean docker ;;
    update) compadd -- all --force ${(f)"$(eva _complete stacks 2>/dev/null)"} ;;
    check|up|restart) compadd -- all ${(f)"$(eva _complete stacks 2>/dev/null)"} ;;
    down) compadd -- all --yes ${(f)"$(eva _complete stacks 2>/dev/null)"} ;;
    logs) compadd -- ${(f)"$(eva _complete containers 2>/dev/null)"} ;;
    container)
      if (( CURRENT == 3 )); then compadd -- up restart down
      elif (( CURRENT == 4 )); then compadd -- ${(f)"$(eva _complete containers 2>/dev/null)"}
      fi ;;
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
    stacks) COMPREPLY=( $(compgen -W "-w -i" -- "$cur") ) ;;
    prune) COMPREPLY=( $(compgen -W "--all --volumes --yes" -- "$cur") ) ;;
    system) COMPREPLY=( $(compgen -W "update upgrade clean docker" -- "$cur") ) ;;
    update) COMPREPLY=( $(compgen -W "all --force $(eva _complete stacks 2>/dev/null)" -- "$cur") ) ;;
    check|up|restart) COMPREPLY=( $(compgen -W "all $(eva _complete stacks 2>/dev/null)" -- "$cur") ) ;;
    down) COMPREPLY=( $(compgen -W "all --yes $(eva _complete stacks 2>/dev/null)" -- "$cur") ) ;;
    logs) COMPREPLY=( $(compgen -W "$(eva _complete containers 2>/dev/null)" -- "$cur") ) ;;
    container)
      if [[ $COMP_CWORD -eq 2 ]]; then COMPREPLY=( $(compgen -W "up restart down" -- "$cur") )
      elif [[ $COMP_CWORD -eq 3 ]]; then COMPREPLY=( $(compgen -W "$(eva _complete containers 2>/dev/null)" -- "$cur") )
      fi ;;
  esac
}
complete -F _eva eva
"""

COMP_COMMANDS = [
    ("containers", "d.containers"), ("stacks", "d.stacks"), ("status", "d.status"),
    ("logs", "d.logs"), ("check", "d.check"), ("update", "d.update"),
    ("up", "d.up"), ("down", "d.down"), ("restart", "d.restart"), ("container", "d.container"),
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


@contextmanager
def cbreak_mode():
    """cbreak + hidden cursor for a live view; restores the terminal on exit."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    print("\033[?25l", end="", flush=True)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print("\033[?25h", end="", flush=True)


def poll_key(timeout):
    """Key pressed within `timeout` seconds (terminal in cbreak mode), else None."""
    fd = sys.stdin.fileno()
    if select.select([fd], [], [], timeout)[0]:
        return read_key()
    return None


def capture(render):
    """Run a printing function and return what it printed."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        render()
    return buf.getvalue()


def show_live(frame, interval=None):
    """Print frame() once, or refresh it every `interval` seconds until Esc/Enter.
    The next frame is built before drawing, so the screen never flickers blank."""
    if interval is None or not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(frame(), end="")
        return
    first = True
    try:
        with cbreak_mode():
            while True:
                started = time.time()
                text = frame()  # docker stats takes ~2s itself, so count it as part of the interval
                prefix = "\033[2J\033[H" if first else "\033[H"
                print(prefix + text.replace("\n", "\033[K\n") + "\033[J", end="", flush=True)
                first = False
                if poll_key(max(0.2, interval - (time.time() - started))) in ("esc", "enter"):
                    break
    except KeyboardInterrupt:
        pass
    clear()


def confirm(title, lines=(), danger=False):
    """Ask before a destructive action. 'No' and Esc cancel; with no terminal it needs --yes."""
    if ASSUME_YES:
        return True
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        err(t("confirm.needs_yes"))
        return False
    for ln in lines:
        print(ln)
    shown = f"{RED}{title}{R}" if danger else title
    return pick(shown, [t("confirm.no"), t("confirm.yes")]) == 1


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


SIZE_UNITS = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
              "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}


def parse_size(text):
    """'245.3MiB' -> bytes. Unknown or empty text -> 0."""
    m = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", text or "")
    return float(m.group(1)) * SIZE_UNITS.get(m.group(2).lower(), 1) if m else 0.0


def human(nbytes):
    for unit in ("B", "KiB", "MiB"):
        if nbytes < 1024:
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (nbytes, unit)
        nbytes /= 1024
    return "%.2f GiB" % nbytes


def percent(text):
    try:
        return float(str(text).strip().rstrip("%"))
    except ValueError:
        return 0.0


def container_stats():
    """{name: {cpu, mem, mem_pct}} for running containers (one docker sample, ~1-2s)."""
    r = run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=25)
    out = {}
    for ln in r.stdout.splitlines():
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        out[o.get("Name", "")] = {
            "cpu": percent(o.get("CPUPerc")),
            "mem": parse_size(str(o.get("MemUsage", "")).split("/")[0]),
            "mem_pct": percent(o.get("MemPerc")),
        }
    return out


def level_color(value, warn_at, crit_at):
    return GREEN if value < warn_at else YELLOW if value < crit_at else RED


def cpu_cell(s):
    """CPU% as docker reports it: 100 = one full core."""
    return f"{level_color(s['cpu'], 60, 120)}{s['cpu']:5.1f}%{R}" if s else f"{D}    —{R}"


def mem_cell(s):
    return f"{level_color(s['mem_pct'], 60, 85)}{human(s['mem']).rjust(9)}{R}" if s else f"{D}        —{R}"


def totals_line(stats, names):
    mine = [stats[n] for n in names if n in stats]
    cpu, mem = sum(s["cpu"] for s in mine), sum(s["mem"] for s in mine)
    return f"{B}{t('live.total', cpu='%.1f%%' % cpu, mem=human(mem))}{R}"


def render_ps(cts, stats, hint=""):
    up = sum(1 for c in cts if c["state"] == "running")
    banner(t("ps.title"), f"{up}/{len(cts)} running{hint}")
    if not cts:
        warn(t("ps.none"))
        return
    nw = max(len(c["name"]) for c in cts)
    sw = max(len(c["stack"]) for c in cts)
    head = (f"{t('col.container').ljust(nw)}  {'STACK'.ljust(sw)}  {t('col.state').ljust(22)}  "
            f"{'CPU'.rjust(6)}  {'RAM'.rjust(9)}  {t('col.netports')}")
    print(f"   {B}{head}{R}")
    print(line())
    for c in cts:
        nets = ",".join(n for n in c["networks"].split(",") if n) or "—"
        s = stats.get(c["name"])
        print(f" {dot(c)} {c['name'].ljust(nw)}  {D}{c['stack'].ljust(sw)}{R}  "
              f"{c['status'][:22].ljust(22)}  {cpu_cell(s)}  {mem_cell(s)}  "
              f"{BLUE}{nets}{R}  {fmt_ports(c['ports'])}")
    print(line())
    print(totals_line(stats, [c["name"] for c in cts]))


def cmd_ps(show_all=False, watch=False, interval=3):
    hint = f" · ↻ {interval}s" if watch else ""

    def frame():
        cts = [c for c in containers() if show_all or c["state"] == "running"]
        text = capture(lambda: render_ps(cts, container_stats(), hint))
        return text + (f"{D}{t('esc_back')}{R}\n" if watch else "")
    show_live(frame, interval if watch else None)


CLEAN_COMMANDS = {
    # safe: only what an update leaves behind. all: anything unused. volumes: also unused volumes.
    "safe": [["docker", "image", "prune", "-f"], ["docker", "builder", "prune", "-f"]],
    "all": [["docker", "system", "prune", "-a", "-f"]],
    "volumes": [["docker", "system", "prune", "-a", "--volumes", "-f"]],
}


def docker_prune(level="safe"):
    for cmd in CLEAN_COMMANDS[level]:
        print(f"\n{D}🧹 {' '.join(cmd)}{R}")
        r = run(cmd)
        tail = (r.stdout.strip().splitlines() or [""])[-1]
        ok(tail) if r.returncode == 0 else err(r.stderr.strip())


def cleanup_preview():
    """What each cleanup level would remove. Read-only."""
    stopped = run(["docker", "ps", "-a", "--filter", "status=exited", "--filter", "status=created",
                   "--format", "{{.Names}}"]).stdout.split()
    volumes = run(["docker", "volume", "ls", "-q", "-f", "dangling=true"]).stdout.split()
    ids = run(["docker", "ps", "-aq"]).stdout.split()
    used = set(run(["docker", "inspect", "--format", "{{.Image}}"] + ids).stdout.split()) if ids else set()
    dangling, unused = [], []
    listing = run(["docker", "image", "ls", "-a", "--no-trunc",
                   "--format", "{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.Size}}"]).stdout
    for ln in listing.splitlines():
        parts = ln.split("\t")
        if len(parts) != 3 or parts[0] in used:
            continue
        (dangling if parts[1] == "<none>:<none>" else unused).append("%s (%s)" % (parts[1], parts[2]))
    return {"stopped": stopped, "volumes": volumes, "dangling": dangling, "unused": unused,
            "df": run(["docker", "system", "df"]).stdout.rstrip()}


def print_preview(p):
    print(f"\n{B}{t('clean.df')}{R}\n{D}{p['df']}{R}")
    for key, names, col in (("dangling", p["dangling"], YELLOW), ("unused", p["unused"], YELLOW),
                            ("stopped", p["stopped"], YELLOW), ("volumes", p["volumes"], RED)):
        print(f"\n{col}•{R} {t('clean.sec.' + key, n=len(names))}")
        for name in names[:8]:
            print(f"    {D}{name}{R}")
        if len(names) > 8:
            print(f"    {D}{t('dash.more', n=len(names) - 8)}{R}")


def cmd_cleanup(level=None):
    """Interactive cleanup: preview, then choose how far to go. Flags (--all, --volumes) skip the
    menu but still ask for confirmation. The default level is the safe one."""
    interactive = level is None and sys.stdin.isatty() and sys.stdout.isatty()
    level = level or "safe"
    banner(t("clean.title"), "docker")
    if interactive or level != "safe":
        preview = cleanup_preview()
        if interactive:
            print_preview(preview)
            keys = ["safe", "all", "volumes"]
            sel = pick(t("clean.title"), [t("clean." + k) for k in keys])
            if sel is None:
                return
            level = keys[sel]
    if level == "all" and not confirm(t("clean.all_confirm"), []):
        return
    if level == "volumes" and not confirm(
            t("clean.volumes_confirm", n=len(preview["volumes"])),
            [f"  {RED}{v}{R}" for v in preview["volumes"][:15]], danger=True):
        return
    docker_prune(level)
    ok(t("clean.done"))


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
        return cmd_cleanup()
    if action == "eva":
        return cmd_update_self()
    print(f"\n{B}{cmds[action][0]}{R}")
    try:
        subprocess.run(cmds[action][1], shell=True)  # constant strings only
    except KeyboardInterrupt:
        pass


def stack_usage(mine, stats):
    """Summed CPU/RAM of a stack's running containers, or None if none is running."""
    used = [stats[c["name"]] for c in mine if c["name"] in stats]
    if not used:
        return None
    return {"cpu": sum(s["cpu"] for s in used), "mem": sum(s["mem"] for s in used),
            "mem_pct": sum(s["mem_pct"] for s in used)}


def render_stacks(stacks, cts, stats, hint=""):
    banner("📦 Stacks", f"{len(stacks)} compose{hint}")
    nw = max((len(s.parent.name) for s in stacks), default=5)
    print(f"   {B}{'STACK'.ljust(nw)}  {'     '}  {'CPU'.rjust(6)}  {'RAM'.rjust(9)}  PATH{R}")
    print(line())
    for s in stacks:
        name = s.parent.name
        mine = [c for c in cts if c["stack"] == name]
        run_n = sum(1 for c in mine if c["state"] == "running")
        if mine and run_n == len(mine):
            col = GREEN if all(dot(c) == f"{GREEN}●{R}" for c in mine) else YELLOW
        else:
            col = YELLOW if run_n else RED
        rel = s.parent.relative_to(ROOT)
        usage = stack_usage(mine, stats)
        print(f" {col}●{R} {name.ljust(nw)}  {f'{run_n}/{len(mine)}'.ljust(5)}  "
              f"{cpu_cell(usage)}  {mem_cell(usage)}  {D}{rel}{R}")
    print(line())
    print(totals_line(stats, [c["name"] for c in cts]))


def cmd_stacks(watch=False, interval=3):
    hint = f" · ↻ {interval}s" if watch else ""

    def frame():
        text = capture(lambda: render_stacks(find_stacks(), containers(), container_stats(), hint))
        return text + (f"{D}{t('esc_back')}{R}\n" if watch else "")
    show_live(frame, interval if watch else None)


def cmd_logs(name=None):
    menu_flow = name is None  # picked from the menu: keep the screen until a key is pressed
    cts = containers()
    if name is None:
        labels = [f"{dot(c)} {c['name']}  {D}({c['stack']}){R}" for c in cts]
        idx = pick(t("logs.pick"), labels)
        if idx is None:
            return
        name = cts[idx]["name"]
    print(f"\n{D}{t('logs.follow', name=name)}{R}\n")
    since = None
    status = "?"
    try:
        # `docker logs -f` ends whenever the container stops or restarts, so reconnect
        # while it is running/restarting (e.g. a crash loop) instead of leaving the screen.
        while True:
            when = ["--since", str(since)] if since else ["--tail", "100"]
            subprocess.run(["docker", "logs", "-f", *when, name])
            since = int(time.time())
            state = run(["docker", "inspect", name, "--format", "{{.State.Status}}"]).stdout.strip()
            status = state or "removed"
            if state not in ("running", "restarting"):
                break
            print(f"{D}↻ {t('logs.reconnect')}{R}", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        return
    print(f"\n{YELLOW}■{R} {t('logs.stopped', name=name, status=status)}")
    if menu_flow:
        pause()


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


CONTAINER_VERBS = {"up": "start", "restart": "restart", "down": "stop"}


def cmd_container(action=None, name=None):
    """up/restart/down of ONE container (docker start / restart / stop)."""
    if action is None:
        keys = list(CONTAINER_VERBS)
        sel = pick(t("ct.action"), [f"{k}  {D}(docker {CONTAINER_VERBS[k]}){R}" for k in keys])
        if sel is None:
            return
        action = keys[sel]
    if action not in CONTAINER_VERBS:
        err(t("sys.invalid", a=action, opts=", ".join(CONTAINER_VERBS)))
        return
    cts = containers()
    if name is None:
        idx = pick(t("ct.pick", action=action), [
            f"{dot(c)} {c['name']}  {D}({c['stack']}) · {c['status']}{R}" for c in cts])
        if idx is None:
            return
        name = cts[idx]["name"]
    elif name not in [c["name"] for c in cts]:
        err(t("ct.notfound", name=name))
        return
    r = run(["docker", CONTAINER_VERBS[action], name], timeout=120)
    if r.returncode == 0:
        ok(t("ct.ok", name=name, action=action))
    else:
        err(f"{name}: {r.stderr.strip()}")


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
    if action == "down":
        every = len(targets) == len(stacks) and len(targets) > 1
        cts = containers()
        lines = [f"  {tg.parent.name}  {D}({sum(1 for c in cts if c['stack'] == tg.parent.name)} "
                 f"containers){R}" for tg in targets]
        title = t("confirm.down_all" if every else "confirm.down", n=len(targets))
        if not confirm(title, lines, danger=every):
            return
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
def pause():
    print(f"\n{D}{t('menu.back')}{R}", flush=True)
    while not wait_key() and sys.stdin.isatty():
        pass


def cmd_stack_action():
    act = pick(t("compose.action"), ["up", "restart", "down"])
    if act is not None:
        cmd_compose(["up", "restart", "down"][act])


def live_ps():
    cmd_ps(show_all=True, watch=True)


def live_stacks():
    cmd_stacks(watch=True)


CONTAINERS_MENU = [
    ("menu.ps", live_ps),
    ("menu.stacks", live_stacks),
    ("menu.logs", cmd_logs),
    ("menu.ctaction", cmd_container),
    ("menu.stackaction", cmd_stack_action),
]


def containers_menu():
    while True:
        clear()
        banner(t("menu.containers"), "eva")
        sel = pick(t("menu.question"), [t(label) for label, _ in CONTAINERS_MENU])
        if sel is None:
            return
        label, fn = CONTAINERS_MENU[sel]
        fn()
        if not CANCELLED and fn not in (cmd_logs, live_ps, live_stacks):  # these end on their own key
            pause()


MENU = [
    ("1", "menu.containers", containers_menu),
    ("2", "menu.update", cmd_update),
    ("3", "menu.system", cmd_system),
    ("4", "menu.config", cmd_install),
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
            t(label) + (f" {YELLOW}⬆{R}" if behind and key == "3" else "") for key, label, _ in MENU])
        if sel is None or MENU[sel][0] == "0":
            return
        key, _, fn = MENU[sel]
        fn()
        if key != "1" and not CANCELLED:  # containers_menu pauses by itself
            pause()


def usage():
    return t("usage")


def main(argv):
    global ASSUME_YES
    ASSUME_YES = any(a in ("--yes", "-y") for a in argv)
    argv = [a for a in argv if a not in ("--yes", "-y")]
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
        "stacks": lambda: cmd_stacks("-w" in flags, interval), "status": cmd_status,
        "check": lambda: cmd_check(arg),
        "logs": lambda: cmd_logs(arg),
        "update": lambda: cmd_update(arg if arg != "--force" else None, "--force" in flags),
        "prune": lambda: cmd_cleanup("volumes" if "--volumes" in flags else "all" if "--all" in flags else "safe"),
        "docker-prune": lambda: cmd_cleanup("volumes" if "--volumes" in flags else "all" if "--all" in flags else "safe"),
        "container": lambda: cmd_container(arg, rest[1] if len(rest) > 1 else None),
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
