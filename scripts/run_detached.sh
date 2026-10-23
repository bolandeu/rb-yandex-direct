#!/bin/sh
# Start a long command detached from this session: it survives an interrupted
# agent turn and a closed terminal. Usage and file layout: scripts/detach.py.
#   scripts/run_detached.sh tests uv run pytest
#   scripts/runs_status.sh tests
exec python3 "$(dirname "$0")/detach.py" start "$@"
