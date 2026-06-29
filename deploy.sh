#!/usr/bin/env bash
# deploy.sh — sync this project to a remote server and (re)build its venv.
#
# First run on a fresh box:
#   ./deploy.sh
#
# Subsequent code-only changes:
#   ./deploy.sh
#
# After editing pyproject.toml dependencies:
#   ./deploy.sh --reinstall
#
# Verify with tests on remote:
#   ./deploy.sh --test
#
# Override target:
#   ./deploy.sh --host user@host --path /opt/foo
#   RELAY_DETECTOR_HOST=user@host ./deploy.sh

set -euo pipefail

REMOTE_HOST="${RELAY_DETECTOR_HOST:-priceai-us-edge}"
REMOTE_PATH="${RELAY_DETECTOR_PATH:-/opt/priceai-detector}"
INSTALL_EXTRAS="${RELAY_DETECTOR_INSTALL_EXTRAS:-web}"

REINSTALL=false
RUN_TESTS=false
DRY_RUN=false

print_usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Sync this project to a remote server, build its venv on first run,
optionally reinstall deps and run tests.

Options:
  --host HOST      ssh destination (default: $REMOTE_HOST)
  --path PATH      remote install path (default: $REMOTE_PATH)
  --reinstall      re-run \`pip install -e .[dev]\` after sync
                   (use when pyproject.toml changed)
  --test           run pytest on remote after sync
  --dry-run        rsync -n; show what would change, copy nothing
  -h, --help       show this help and exit

Environment overrides: RELAY_DETECTOR_HOST, RELAY_DETECTOR_PATH
Optional: RELAY_DETECTOR_INSTALL_EXTRAS (default: web)

Prerequisite (one-time, on fresh Ubuntu):
  ssh $REMOTE_HOST 'apt-get update && apt-get install -y python3-venv'
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)      REMOTE_HOST="$2"; shift 2 ;;
    --path)      REMOTE_PATH="$2"; shift 2 ;;
    --reinstall) REINSTALL=true;   shift ;;
    --test)      RUN_TESTS=true;   shift ;;
    --dry-run)   DRY_RUN=true;     shift ;;
    -h|--help)   print_usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; print_usage >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"

EXCLUDES=(
  --exclude='venv/'
  --exclude='.venv/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='*.pyo'
  --exclude='.git/'
  --exclude='.pytest_cache/'
  --exclude='.local/'
  --exclude='.local-data/'
  --exclude='*.egg-info/'
  --exclude='build/'
  --exclude='dist/'
  --exclude='report*.json'
  --exclude='web_data/'          # persistent web job reports on remote
  --exclude='.cache/'
  --exclude='.DS_Store'
  # .env is host-specific: local points at one relay for dev, remote points
  # at whatever you're testing right now. Never let one overwrite the other.
  --exclude='.env'
  --exclude='.env.*'            # .env.bak, .env.local, etc. — host-local
  --exclude='*.bak'             # any manual backups
  --exclude='baselines/'        # local-only output dir of bench.sh on remote
  --exclude='out/'              # ad-hoc output directory on remote
  --exclude='tmp/'              # ad-hoc tmp dir
)

RSYNC_FLAGS=(-az --delete)
$DRY_RUN && RSYNC_FLAGS+=(-n -v)

echo "→ rsync $HERE/  →  $REMOTE_HOST:$REMOTE_PATH/"
rsync "${RSYNC_FLAGS[@]}" "${EXCLUDES[@]}" "$HERE"/ "$REMOTE_HOST:$REMOTE_PATH"/

if $DRY_RUN; then
  echo "✓ dry run only, nothing changed"
  exit 0
fi

# Always lock down .env on remote — we just rsynced it.
ssh "$REMOTE_HOST" "test -f $REMOTE_PATH/.env && chmod 600 $REMOTE_PATH/.env || true"

# venv-bin/relay-detector existing means a working install is already there.
NEED_VENV=$(ssh "$REMOTE_HOST" \
  "test -x $REMOTE_PATH/venv/bin/relay-detector && echo no || echo yes")

if [[ "$NEED_VENV" == "yes" ]]; then
  echo "→ first-time venv build on remote"
  ssh "$REMOTE_HOST" "set -e; cd $REMOTE_PATH && \
    python3 -m venv venv && \
    ./venv/bin/pip install --quiet --upgrade pip && \
    ./venv/bin/pip install --quiet -e '.[$INSTALL_EXTRAS]'"
elif $REINSTALL; then
  echo "→ reinstalling deps on remote"
  ssh "$REMOTE_HOST" "cd $REMOTE_PATH && ./venv/bin/pip install --quiet -e '.[$INSTALL_EXTRAS]'"
fi

if $RUN_TESTS; then
  echo "→ running pytest on remote"
  if ! ssh "$REMOTE_HOST" "cd $REMOTE_PATH && ./venv/bin/pytest tests/"; then
    echo "✗ tests failed on remote" >&2
    exit 1
  fi
fi

echo "✓ deployed to $REMOTE_HOST:$REMOTE_PATH"
echo "  try:  ssh $REMOTE_HOST 'cd $REMOTE_PATH && ./venv/bin/relay-detector detect --mode quick'"
