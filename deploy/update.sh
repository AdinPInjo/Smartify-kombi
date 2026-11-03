#!/usr/bin/env bash
# Update Smartify Kombi to the latest version and restart it.
#
#   cd ~/smartify-kombi && sudo ./deploy/update.sh
#
# Your settings (backend/.env) and data (backend/data) are kept. Database
# changes are applied automatically when the service starts.

set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo ./deploy/update.sh" >&2; exit 1; }
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:?run with sudo from your normal user}"
as_user() { sudo -u "$USER_NAME" -H "$@"; }

echo "▸ Backing up the database"
if [[ -f $REPO/backend/data/smartify.db ]]; then
  as_user mkdir -p "$REPO/backend/data/backups"
  as_user sqlite3 "$REPO/backend/data/smartify.db" ".backup '$REPO/backend/data/backups/before-update-$(date +%F-%H%M).db'"
fi

echo "▸ Downloading the new version"
OLD=$(as_user git -C "$REPO" rev-parse HEAD)
as_user git -C "$REPO" pull --ff-only
NEW=$(as_user git -C "$REPO" rev-parse HEAD)
if [[ $OLD == "$NEW" ]]; then
  echo "  Already up to date."
fi

echo "▸ Updating the backend"
as_user "$REPO/backend/.venv/bin/pip" install -q -e "${REPO}/backend[pi]"

echo "▸ Updating the dashboard"
rm -rf "$REPO/frontend/dist"
# Re-run the installer's dashboard and service steps (keeps .env).
"$REPO/deploy/install.sh" --yes --password unused >/dev/null

echo "▸ Restarting"
systemctl restart smartify
sleep 3
systemctl --no-pager --lines=5 status smartify || true
echo "Done."
