# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-15

### Added
- Menú interactivo con navegación por flechas (`Esc` vuelve un nivel) y subcomandos equivalentes
  para usar en scripts.
- Panel de estado: temperatura, RAM, disco, carga y salud de los contenedores.
- Contenedores y stacks: listado con estado, redes y puertos (modo watch), logs en vivo y
  up/restart/down por contenedor, por stack o para todos.
- Update con vista previa: compara el digest de cada imagen contra el registry (`docker buildx
  imagetools inspect`) sin descargar, y actualiza solo los stacks con novedades. `excluded_stacks`
  deja fuera de las acciones masivas a los stacks que lo necesiten.
- Menú Sistema: `apt update/upgrade`, `full-upgrade`, `autoremove` y limpieza de Docker.
- `eva install`: idioma (español/inglés), carpeta de stacks, instalación del comando
  (`~/.local/bin` sin sudo o `/usr/local/bin`) y autocompletado de zsh, con bash como alternativa.
- `eva doctor` y verificación de requisitos al arrancar (Docker, permisos, Compose, Buildx).
- `eva update-self` y aviso de versión nueva en el menú.
- Detección de `compose.yaml`, `compose.yml`, `docker-compose.yaml` y `docker-compose.yml`.
