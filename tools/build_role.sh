#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
if [[ "$ROLE" != "leader" && "$ROLE" != "follower" ]]; then
  echo "Usage: $0 leader|follower" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../firmware" && pwd)"
BUILD_DIR="$PROJECT_DIR/build-$ROLE"

cd "$PROJECT_DIR"
idf.py -B "$BUILD_DIR" -DBANDTOY_ROLE="$ROLE" set-target esp32s3 build

