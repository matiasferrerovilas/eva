# eva

A small, dependency-free terminal CLI to run a Docker Compose homelab from one place: see what is running, follow logs, check which images have updates, and update stacks with an arrow-key menu.

Built on a Raspberry Pi 5, but it works on any Linux host with Docker.

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
 ❯ Listar contenedores
   Listar stacks
   Ver logs
   Update (ver novedades, pull, recrear, prune)
   Up / Down / Restart
   Sistema (apt, limpiar Docker)
   Configuración (ruta de contenedores)
   Salir
```

> The interface text is currently in Spanish. Translations are welcome.

## Features

- **Dashboard**: CPU temperature, RAM, disk, load, and container health at a glance.
- **Containers and stacks**: list them with state, networks, and published ports. Watch mode included.
- **Logs**: pick a container from a list and follow its logs live.
- **Update with preview**: compares local image digests against the registry (no download) and shows which stacks have a new version. Then pull, recreate, and prune.
- **Up / down / restart** for one stack or all of them.
- **System**: `apt update/upgrade`, `full-upgrade`, `autoremove`, and Docker cleanup.
- **Arrow-key navigation** everywhere. `Esc` goes back, and the screen is cleared on every step.
- **No dependencies**: Python standard library only.

## Requirements

- Linux, Python 3.8+
- Docker with the Compose plugin (`docker compose`)
- Docker Buildx (`docker buildx`), used to read remote image digests for update checks
- `sudo`, only for the `apt` actions and for installing the `eva` command
- Optional: `vcgencmd` (Raspberry Pi) for temperature. Falls back to `/sys/class/thermal`.

## Install

```bash
git clone https://github.com/matiasferrerovilas/homelab.git /opt/homelab
/opt/homelab/scripts/eva.py install
```

`eva install` will:

1. Ask where your stacks live (the folder that contains your `compose.yml` files).
2. Save it to `config/.env`.
3. Offer to link the command to `/usr/local/bin/eva`.

If you run `eva` before configuring it, the installer opens by itself.

## Layout

```
eva/
├── scripts/eva.py       the CLI
├── config/
│   ├── .env             your settings (git-ignored)
│   └── .env.example     reference
└── services/            your stacks, one folder each (path is configurable)
    ├── immich/compose.yml
    └── infrastructure/
        └── npm/compose.yml
```

Stacks are found recursively under `containers_location`. The stack name is the name of the folder that holds the compose file. The files `compose.yaml`, `compose.yml`, `docker-compose.yaml` and `docker-compose.yml` are recognized.
Folders named `data`, `cache`, `logs`, `tmp`, `uploads`, `database`, `letsencrypt`, `model-cache` and `.git` are skipped.

## Configuration

`config/.env`:

| Key | Description |
|---|---|
| `containers_location` | Folder that holds your stacks. Required. |
| `excluded_stacks` | Comma-separated stack names to leave out of bulk actions (`update all`, `check all`). You can still update them by name. |

Example:

```
containers_location=/opt/homelab/services
excluded_stacks=dbs,keycloak
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
| `eva up\|down\|restart [stack\|all]` | Compose actions |
| `eva system update\|upgrade\|clean\|docker` | apt update+upgrade, full-upgrade, autoremove, Docker cleanup |
| `eva install` | Configure or reconfigure |

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

Issues and pull requests are welcome. Ideas on the list: volume backups, notifications, a scheduled update with rollback, shell access into a container, shell autocompletion, and translations.

## License

No license has been chosen yet.
