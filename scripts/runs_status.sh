#!/bin/sh
# What the detached runs are doing and how they ended (scripts/detach.py).
#   scripts/runs_status.sh [<label>] [--json]
exec python3 "$(dirname "$0")/detach.py" status "$@"
