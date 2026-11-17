#!/bin/sh
# Instala campus-usc en Mac o Linux. En la app Terminal:
#   curl -LsSf https://raw.githubusercontent.com/PabloPC05/campus-usc/main/instalar.sh | sh
# Te explica qué se instala, te pregunta y lo instala. Para no preguntar: … | sh -s -- --si
set -eu
REPO="https://raw.githubusercontent.com/PabloPC05/campus-usc/main"

if ! command -v uv >/dev/null 2>&1; then
  echo "Instalando uv, el programa que instala campus (solo la primera vez)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM
curl -LsSf "$REPO/instalar.py" -o "$tmp/instalar.py"

# The menu asks questions: read the answers from the terminal, not from the curl pipe.
if (exec </dev/tty) 2>/dev/null; then
  uv run --quiet --python 3.12 "$tmp/instalar.py" "$@" </dev/tty
else
  uv run --quiet --python 3.12 "$tmp/instalar.py" "$@"
fi
