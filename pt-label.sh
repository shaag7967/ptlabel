#!/bin/sh
# Startet PT-Label unter Linux. Beim ersten Start wird die Python-Umgebung eingerichtet.
# Voraussetzung (Debian/Ubuntu): sudo apt install python3-venv python3-tk
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv-linux/bin/python ]; then
    echo "Richte Python-Umgebung ein ..."
    python3 -m venv .venv-linux && .venv-linux/bin/python -m pip install -r requirements.txt || exit 1
fi
exec .venv-linux/bin/python -m ptlabel "$@"
