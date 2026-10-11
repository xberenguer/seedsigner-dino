#!/bin/bash
set -euo pipefail
test "$(uname -m)" = x86_64
exec python3 scripts/container_build.py "$@"
