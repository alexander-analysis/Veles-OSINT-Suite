#!/usr/bin/env bash
# Build the frontend, pack the project (with backend/.env) and install it on a
# Pi in userspace via deployment/userspace/install.sh.
#
#   bash deployment/push-to-pi.sh nyxia@10.251.102.130 [-i ~/.ssh/key] [--port 8090] [--skip-build]
#
# The remote side needs Python 3.11+ and (optionally) cloudflared in ~/.local/bin.
set -euo pipefail

TARGET="${1:?usage: push-to-pi.sh user@host [-i key] [--port N] [--skip-build]}"
shift
SSH_OPTS=()
PORT=8090
BUILD=1
while [ $# -gt 0 ]; do
    case "$1" in
        -i) SSH_OPTS+=(-i "$2"); shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --skip-build) BUILD=0; shift ;;
        *) echo "unknown option $1" >&2; exit 1 ;;
    esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [ "$BUILD" = 1 ]; then
    echo "=== building frontend ==="
    (cd frontend && npm run build >/dev/null)
fi
[ -d frontend/dist ] || { echo "frontend/dist missing - run without --skip-build" >&2; exit 1; }
[ -f backend/.env ] || { echo "backend/.env missing - copy .env.example and add keys" >&2; exit 1; }

ARCHIVE="$(mktemp -t veles-XXXXXX).tar.gz"
echo "=== packing $ARCHIVE ==="
tar -czf "$ARCHIVE" \
    --exclude='backend/venv' --exclude='backend/logs' --exclude='backend/reports' --exclude='backend/*.db*' \
    --exclude='backend/settings.local.yaml' --exclude='__pycache__' --exclude='.pytest_cache' \
    --exclude='frontend/node_modules' --exclude='frontend/src' --exclude='.git' \
    backend frontend/dist frontend/package.json deployment docs README.md LICENSE

echo "=== uploading to $TARGET ==="
scp -q "${SSH_OPTS[@]}" "$ARCHIVE" "$TARGET:/tmp/veles.tar.gz"
rm -f "$ARCHIVE"

echo "=== installing (this takes a few minutes the first time) ==="
ssh "${SSH_OPTS[@]}" "$TARGET" "mkdir -p ~/veles && tar -xzf /tmp/veles.tar.gz -C ~/veles && rm /tmp/veles.tar.gz && PORT=$PORT bash ~/veles/deployment/userspace/install.sh"
