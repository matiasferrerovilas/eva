# eva

A small, dependency-free terminal CLI to run a Docker Compose homelab from one place: see what is running, follow logs, check which images have updates, and update stacks with an arrow-key menu.

It works on any Linux host with Docker, from a Raspberry Pi to a server. eva only manages the stacks you point it to: your own compose files live in a separate folder, outside this repository.

```
╭──────────────────────────────────────────────────────────────╮
│ 🏠 EVA                                                homelab │
╰──────────────────────────────────────────────────────────────╯

 Temp  ██████████░░░░░░  62.0°C
 RAM   ████████░░░░░░░░  3.8 / 7.9 GB
 Disco █████░░░░░░░░░░░  18 / 62 GB
 CPU   █░░░░░░░░░░░░░░░  load 0.27 · 4 cores · up 2d 3h

 ● 19/19 contenedores running

¿Qué querés hacer?  ↑↓ mover · Enter/Espacio elegir · q volver
 ❯ Contenedores
   Update (ver novedades, pull, recrear, prune)
   Sistema (apt, limpiar Docker)
   Configuración (idioma, ruta de contenedores)
   Salir
```

The **Containers** entry opens a submenu: list containers, list stacks, view logs, up/restart/down of a single container, and up/restart/down of a whole stack.

> The interface is available in **Spanish** and **English**. You pick one during setup (shown above in Spanish).

## Features

- **Dashboard**: CPU temperature, RAM, disk, load, and container health at a glance.
- **Containers and stacks**: list them with state, networks, and published ports. Watch mode included.
- **Logs**: pick a container from a list and follow its logs live.
- **Update with preview**: compares local image digests against the registry (no download) and shows which stacks have a new version. Then pull, recreate, and prune.
- **Up / down / restart** for a single container, or for one stack or all of them.
- **System**: `apt update/upgrade`, `full-upgrade`, `autoremove`, and Docker cleanup.
- **Arrow-key navigation** everywhere. `Esc` goes back, and the screen is cleared on every step.
- **Shell completion** for zsh (or bash if zsh is not installed), including stack and container names.
- **Self-update**: the menu header shows the version, and tells you when a newer one is available (checked at most every 6 hours). Update from **System → Update eva**.
- **Two languages**: Spanish and English, chosen at setup.
- **No dependencies**: Python standard library only.

## Requirements

- Linux, Python 3.8+ (uses `termios`, so Windows is not supported)
- Docker with the Compose plugin (`docker compose`)
- Docker Buildx (`docker buildx`), used to read remote image digests for update checks
- `sudo`, only for the `apt` actions (and for installing the command in `/usr/local/bin`, which is optional)
- Optional: `vcgencmd` (Raspberry Pi) for temperature. Falls back to `/sys/class/thermal`.

eva checks these requirements every time it starts and tells you what to fix. For example, if your user is not in the `docker` group it prints the exact `usermod` command, and if the Docker daemon is down it suggests how to start it. A missing Buildx is only a warning: everything works except the update preview. Run `eva doctor` at any time for a full report.

## Install

```bash
git clone <this-repo-url> ~/eva
~/eva/scripts/eva.py install
```

`eva install` will:

1. Ask for the interface language (`es` or `en`).
2. Ask where your stacks live (the folder that contains your compose files).
3. Ask which stacks to exclude from bulk updates (optional).
4. Save everything to `config/.env`.
5. Offer to link the command as `eva`: in `~/.local/bin` (default, no sudo) or in `/usr/local/bin` (needs sudo). If `~/.local/bin` is not in your `PATH`, it prints the line to add.
6. Offer to enable shell completion: it adds one `source <(eva completion ...)` line to `~/.zshrc` if zsh is installed, otherwise to `~/.bashrc`.

If you run `eva` before configuring it, the installer opens by itself.

## Layout

```
~/eva/                   this repository
├── scripts/eva.py       the CLI
└── config/
    ├── .env             your settings (git-ignored)
    └── .env.example     reference

/srv/stacks/             your stacks: anywhere you like, set during `eva install`
├── blog/compose.yml
└── infra/
    └── proxy/compose.yml
```

Keep your stacks out of this repository: they usually contain secrets and data. (`services/` is git-ignored here as a safety net.)

Stacks are found recursively under `containers_location`. The stack name is the name of the folder that holds the compose file. The files `compose.yaml`, `compose.yml`, `docker-compose.yaml` and `docker-compose.yml` are recognized.
Folders named `data`, `cache`, `logs`, `tmp`, `uploads`, `database`, `letsencrypt`, `model-cache` and `.git` are skipped.

## Configuration

`config/.env`:

| Key | Description |
|---|---|
| `containers_location` | Folder that holds your stacks. Required. |
| `language` | Interface language: `es` or `en`. Default `es`. |
| `excluded_stacks` | Comma-separated stack names to leave out of bulk actions (`update all`, `check all`). You can still update them by name. |

Example:

```
containers_location=/srv/stacks
language=en
excluded_stacks=db,proxy
```

Excluding is useful for stacks pinned to `:latest` where a major upgrade could break your data, like a database.

## Usage

Run `eva` for the menu, or use commands directly:

| Command | What it does |
|---|---|
| `eva` | Interactive menu |
| `eva status` | Dashboard and stack list |
| `eva containers [-a] [-w] [-i N]` | Containers with networks and ports. `-a` all, `-w` watch, `-i` interval |
| `eva stacks` | List stacks |
| `eva logs [container]` | Follow logs |
| `eva check [stack\|all]` | Show which stacks have newer images (downloads nothing) |
| `eva update [stack\|all] [--force]` | Update stacks that have news, then prune. `--force` updates all selected |
| `eva up\|down\|restart [stack\|all]` | Compose actions on a whole stack. `down` removes the stack's containers (volumes are kept) |
| `eva container up\|restart\|down [name]` | One container: `docker start` / `restart` / `stop` |
| `eva system update\|upgrade\|clean\|docker` | apt update+upgrade, full-upgrade, autoremove, Docker cleanup |
| `eva doctor` | Check requirements (Python, Docker, Compose, Buildx) and config |
| `eva install` | Configure or reconfigure (language, folder, exclusions, completion) |
| `eva completion [zsh\|bash]` | Print the completion script |
| `eva --version` | Print the version (and git commit) |
| `eva update-self` | Update eva itself with `git pull --ff-only` (needs a git clone with an upstream) |

Keys in the menu: `↑` `↓` (or `j` `k`) to move, `Enter` or `Space` to choose, `Esc` or `q` to go back.

## How update works

1. For each image in the selected stacks, eva reads the digest in the registry (`docker buildx imagetools inspect`) and compares it with the local one.
2. It shows what is new, up to date, not pulled yet, or unknown.
3. For the stacks you confirm: `docker compose pull`, then `docker compose up -d --remove-orphans` (only containers whose image changed are recreated).
4. It finishes with a Docker prune.

## Heads up

- The Docker cleanup runs `docker system prune -a --volumes -f`. It removes **unused volumes**, including those of stacks that are down at that moment. Back up first if you care about that data.
- Updating `:latest` images can jump major versions. Pin versions or use `excluded_stacks` for databases.
- `Esc` does not interrupt live logs or text prompts. Use `Ctrl+C` there.

## Contributing

Issues and pull requests are welcome. Ideas on the list: volume backups, notifications, a scheduled update with rollback, and shell access into a container.

To add a language, add a column to the `STR` table in `scripts/eva.py` and its code to `LANGS`.

## License

[MIT](LICENSE)
