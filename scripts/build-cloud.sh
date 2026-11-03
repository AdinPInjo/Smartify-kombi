#!/usr/bin/env bash
# Build the remote dashboard package: the PHP API plus the dashboard, ready to
# upload to any PHP + MySQL hosting. Output: dist/smartify-cloud.zip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist/smartify-cloud"

echo "Building the dashboard…"
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)

rm -rf "$OUT" "$ROOT/dist/smartify-cloud.zip"
mkdir -p "$OUT"
cp -r "$ROOT/cloud/." "$OUT/"
rm -f "$OUT/dev-router.php" "$OUT/private/config.php" "$OUT"/private/*.sqlite*
cp -r "$ROOT/frontend/dist/." "$OUT/"

(cd "$ROOT/dist" && zip -qr smartify-cloud.zip smartify-cloud)
echo "Done: dist/smartify-cloud.zip"
echo "Upload the contents of smartify-cloud/ to your hosting, then open install.php."
