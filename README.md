<div align="center">

# eva

**La consola de tu homelab: contenedores, logs y actualizaciones desde un menú.**
Mirá qué está corriendo, seguí logs, enterate de qué imágenes tienen novedades y actualizá tus stacks de Docker Compose con las flechas del teclado.

[![CI](https://github.com/matiasferrerovilas/eva/actions/workflows/ci.yml/badge.svg)](https://github.com/matiasferrerovilas/eva/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776ab?logo=python&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker%20Compose-2496ed?logo=docker&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-host-fcc624?logo=linux&logoColor=black)
![Dependencias](https://img.shields.io/badge/dependencias-0-4d4d4d)

<img src="docs/architecture.svg" alt="Arquitectura de eva: terminal, eva, Docker, registry, stacks, config/.env y sistema, dentro de un host Linux" width="900" />

</div>

---

## Qué hace

| Área | Para qué sirve |
| --- | --- |
| **Estado de un vistazo** | Temperatura, RAM, disco, carga y cuántos contenedores están sanos, con barras que cambian de color. |
| **Contenedores y stacks** | Listá contenedores y stacks con su estado, **CPU y RAM en vivo**, redes y puertos. Desde el menú se refrescan solos hasta que apretás `Esc`. |
| **Logs** | Elegí un contenedor de la lista y seguí sus logs en vivo. |
| **Update con vista previa** | Compara el digest de cada imagen contra el registry **sin descargar nada**, te muestra qué stacks tienen novedades y recién ahí hace `pull` y recrea. |
| **Up / restart / down** | Sobre un solo contenedor, sobre un stack o sobre todos. |
| **Sistema** | `apt update/upgrade`, limpieza de paquetes y limpieza de Docker **con vista previa** de lo que se borraría, desde el mismo menú. |
| **Sin sorpresas** | Lo destructivo (bajar stacks, limpiar volúmenes) muestra qué va a pasar y pide confirmación. |
| **Comodidades** | Navegación con flechas (`Esc` vuelve un nivel), autocompletado de zsh/bash, español e inglés, y `eva update-self` para actualizarse solo. |

eva solo administra los stacks que le indiques: tus `compose.yml` viven en una carpeta aparte, fuera de este repositorio.

---

## Tutorial: instalarlo en tu máquina

### Requisitos

- **Linux** y **Python 3.8+** (usa `termios`, así que Windows no está soportado).
- **Docker** con el plugin Compose (`docker compose`).
- **Docker Buildx**, para comparar imágenes contra el registry. Si falta, todo funciona menos la vista previa del update.
- `sudo`, solo para las acciones de `apt` (y para instalar el comando en `/usr/local/bin`, que es opcional).
- Opcional: `vcgencmd` (Raspberry Pi) para la temperatura; si no está, usa `/sys/class/thermal`.

eva revisa estos requisitos cada vez que arranca y te dice qué arreglar. Por ejemplo, si tu usuario no está en el grupo `docker`, imprime el `usermod` exacto.

### Pasos

```bash
# 1. Clonar
git clone https://github.com/matiasferrerovilas/eva.git ~/eva
cd ~/eva

# 2. Configurar (idioma, carpeta de stacks, comando y autocompletado)
./scripts/eva.py install
```

`eva install` te pregunta, en orden:

1. El idioma de la interfaz (`es` o `en`).
2. La carpeta donde están tus stacks, la que contiene tus `compose.yml`.
3. Qué stacks excluir de los updates masivos (opcional).
4. Dónde instalar el comando `eva`: `~/.local/bin` (por defecto, sin sudo) o `/usr/local/bin` (con sudo).
5. Si querés activar el autocompletado: agrega una línea a tu `~/.zshrc` si tenés zsh, o a `~/.bashrc` si no.

Todo queda guardado en `config/.env`. Si ejecutás `eva` sin configurar, el instalador se abre solo.

### Probalo

```bash
eva doctor    # verifica Docker, Compose, Buildx y tu configuración
eva status    # estado de la máquina y de tus stacks
eva           # el menú interactivo
```

### Configuración

`config/.env`:

| Clave | Descripción |
| --- | --- |
| `containers_location` | Carpeta que contiene tus stacks. Obligatoria. |
| `language` | Idioma de la interfaz: `es` o `en`. Por defecto `es`. |
| `excluded_stacks` | Nombres de stacks, separados por coma, que quedan fuera de las acciones masivas (`update all`, `check all`). Igual podés actualizarlos por nombre. |

```
containers_location=/srv/stacks
language=es
excluded_stacks=db,proxy
```

Excluir sirve para stacks fijados a `:latest` donde un salto de versión mayor podría romper tus datos, como una base de datos.

---

## Tutorial: usarlo

Abrí `eva` y movete con las flechas. `Enter` o `Espacio` elige, `Esc` vuelve un nivel y, en el menú principal, sale.

```
EVA
├── Contenedores
│   ├── Listar contenedores
│   ├── Listar stacks
│   ├── Ver logs
│   ├── Up / Restart / Down de un contenedor
│   └── Up / Restart / Down de un stack
├── Update
├── Sistema
├── Configuración
└── Salir
```

También funciona sin menú, ideal para scripts:

```bash
# Contenedores con redes y puertos, refrescando cada 5 segundos
eva containers -w -i 5

# Logs de un contenedor
eva logs mi-contenedor

# ¿Qué stacks tienen imágenes nuevas? (no descarga nada)
eva check all

# Actualizar un stack, o todos los que tengan novedades
eva update mi-stack
eva update all
```

---

## Comandos útiles

| Comando | Qué hace |
| --- | --- |
| `eva` | Abre el menú interactivo. |
| `eva status` | Temperatura, RAM, disco, salud y lista de stacks. |
| `eva containers [-a] [-w] [-i N]` | Contenedores con CPU, RAM, redes y puertos. `-a` todos, `-w` en vivo, `-i` intervalo. |
| `eva stacks [-w] [-i N]` | Lista los stacks con su CPU y RAM. `-w` en vivo. |
| `eva logs [contenedor]` | Sigue los logs de un contenedor. |
| `eva check [stack\|all]` | Muestra qué stacks tienen una imagen más nueva, sin descargar. |
| `eva update [stack\|all] [--force]` | Actualiza los stacks con novedades y limpia Docker. `--force` actualiza todos los elegidos. |
| `eva up\|down\|restart [stack\|all]` | Acciones de Compose sobre un stack. `down` elimina sus contenedores (los volúmenes se conservan) y **pide confirmación**. |
| `eva container up\|restart\|down [nombre]` | Un solo contenedor: `docker start`, `restart` o `stop`. |
| `eva system update\|upgrade\|clean\|docker` | `apt update`+`upgrade`, `full-upgrade`, `autoremove` o limpieza de Docker (con vista previa). |
| `eva prune [--all\|--volumes]` | Limpieza de Docker. Por defecto es la **segura**; `--all` y `--volumes` piden confirmación. |
| `--yes` | En cualquier comando: omite las confirmaciones (obligatorio si no hay terminal, por ejemplo en scripts). |
| `eva doctor` | Diagnóstico de requisitos y configuración. |
| `eva install` | Configura o reconfigura eva. |
| `eva update-self` | Se actualiza con `git pull --ff-only` (necesita un clon de git con upstream). |
| `eva completion [zsh\|bash]` | Imprime el script de autocompletado. |
| `eva --version` | Muestra la versión y el commit. |

---

## Cómo está armado

El diagrama de arriba resume el flujo: eva lee `config/.env`, llama a `docker` y `docker compose` sobre las carpetas de tus stacks, consulta el registry con `buildx` para saber si hay imágenes nuevas, y usa `apt` y `/proc` para la parte de sistema.

- **Stack:** un solo archivo, `scripts/eva.py`, con la biblioteca estándar de Python. Sin dependencias.
- **Detección de stacks:** busca recursivamente bajo `containers_location` los archivos `compose.yaml`, `compose.yml`, `docker-compose.yaml` y `docker-compose.yml`. El nombre del stack es el de la carpeta que contiene el archivo. Se saltea `data`, `cache`, `logs`, `tmp`, `uploads`, `database`, `letsencrypt`, `model-cache` y `.git`.
- **Textos:** una tabla `STR` con cada mensaje en español e inglés.

```
eva/
├── scripts/eva.py      # el CLI
├── config/
│   ├── .env            # tu configuración (ignorada por git)
│   └── .env.example    # referencia
├── docs/               # diagrama de arquitectura
├── CHANGELOG.md
└── LICENSE
```

Tus stacks van **fuera** de este repo, por ejemplo en `/srv/stacks`: suelen tener secretos y datos. Como red de seguridad, `services/` y `stacks/` están en el `.gitignore`.

### Cómo funciona el update

1. Por cada imagen de los stacks elegidos, eva lee el digest en el registry (`docker buildx imagetools inspect`) y lo compara con el local.
2. Te muestra qué está nuevo, al día, sin descargar o sin información.
3. Para los stacks que confirmes: `docker compose pull` y `docker compose up -d --remove-orphans` (solo se recrean los contenedores cuya imagen cambió).
4. Termina borrando las imágenes viejas sin etiqueta que el pull dejó atrás (nunca toca volúmenes ni contenedores).

## Ojo con

- La limpieza de Docker tiene tres niveles y te muestra de antemano qué se borraría: **segura** (imágenes viejas sin etiqueta y caché de build), **completa** (además imágenes sin uso, contenedores detenidos y redes sin uso) y **completa + volúmenes**. Este último elimina los volúmenes sin uso, incluidos los de los stacks que estén caídos en ese momento: hacé backup antes si te importan esos datos.
- Actualizar imágenes `:latest` puede saltar de versión mayor. Fijá versiones o usá `excluded_stacks` para las bases de datos.
- `Esc` no interrumpe los logs en vivo ni los prompts de texto: ahí usá `Ctrl+C`.
- Si movés la carpeta de un stack, recrealo desde la ruta nueva (`docker compose up -d --force-recreate`): los contenedores existentes siguen apuntando a la ruta vieja.

## Contribuir

- Los issues y pull requests son bienvenidos.
- Commits con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) (`feat:`, `fix:`, `docs:`...).
- Cada cambio se anota en el [CHANGELOG](CHANGELOG.md).
- Para publicar una versión: subí `VERSION` en `scripts/eva.py` y agregá su sección `## [x.y.z]` al CHANGELOG. Al llegar a `main`, el CI crea el tag y el release de GitHub con esas notas.
- Los tests no necesitan Docker: `python3 -m unittest discover -s tests`. El CI los corre en Python 3.8 a 3.13 y pasa `ruff`.
- Para agregar un idioma, sumá una columna a la tabla `STR` de `scripts/eva.py` y su código a `LANGS`.
- En la lista de ideas: backup de volúmenes, notificaciones, update programado con rollback y shell dentro de un contenedor.

## Licencia

MIT — ver [LICENSE](LICENSE).
