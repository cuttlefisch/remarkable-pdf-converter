#!/usr/bin/env bash
# Dev convenience wrapper — runs r2pdf via the project venv.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/.venv/bin/r2pdf" "$@"
