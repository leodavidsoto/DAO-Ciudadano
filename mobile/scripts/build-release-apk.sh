#!/usr/bin/env bash
# Backwards-compatible entry point. It no longer mutates Git state, installs
# floating dependencies or copies artifacts to a user-specific directory.
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
exec "$SCRIPT_DIR/build-release-android.sh" "$@"
