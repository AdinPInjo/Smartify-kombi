#!/usr/bin/env bash
# Smartify Kombi installer for Raspberry Pi OS (Bookworm or newer), Lite or Desktop.
#
#   git clone https://github.com/AdinPInjo/Smartify-kombi.git ~/smartify-kombi
#   cd ~/smartify-kombi && sudo ./deploy/install.sh
#
# Safe to run again: it updates what is there and keeps your backend/.env.
# Options:
#   --yes            accept all defaults, ask nothing
#   --password PASS  set the dashboard password now (otherwise the dashboard asks
#                    for it the first time you open it)
#   --port N         dashboard port (default 80: http://<hostname>.local)
#   --no-dashboard   skip installing the web dashboard (API only)

set -euo pipefail

# --- helpers -------------------------------------------------------------------------

BOLD=$'\e[1m'; DIM=$'\e[2m'; AMBER=$'\e[33m'; GREEN=$'\e[32m'; RED=$'\e[31m'; RESET=$'\e[0m'
step() { echo; echo "${BOLD}${AMBER}▸ $*${RESET}"; }
info() { echo "  $*"; }
ok()   { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${AMBER}!${RESET} $*"; }
die()  { echo "${RED}✗ $*${RESET}" >&2; exit 1; }

ask() { # ask "Question" default -> echoes answer
  local question=$1 default=${2:-} answer
  if [[ $YES == 1 ]]; then echo "$default"; return; fi
  read -r -p "  $question ${DIM}[$default]${RESET} " answer </dev/tty || true
  echo "${answer:-$default}"
}

# --- arguments ---------------------------------------------------------------------------

YES=0; PASSWORD=""; PORT=80; DASHBOARD=1
while [[ $# -gt 0 ]]; do
  case $1 in
    --yes|-y) YES=1 ;;
    --password) PASSWORD=$2; shift ;;
    --port) PORT=$2; shift ;;
    --no-dashboard) DASHBOARD=0 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "Unknown option $1 (see --help)" ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo ./deploy/install.sh"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-}"
[[ -n $SERVICE_USER && $SERVICE_USER != root ]] || die "Run as your normal user with sudo, not as root (the service runs as that user)."
[[ -f $REPO/backend/pyproject.toml ]] || die "Run this from the cloned smartify-kombi folder."
BACKEND="$REPO/backend"
ENV_FILE="$BACKEND/.env"
as_user() { sudo -u "$SERVICE_USER" -H "$@"; }

echo "${BOLD}Smartify Kombi installer${RESET}"
info "Folder:  $REPO"
info "User:    $SERVICE_USER"
if [[ -r /proc/device-tree/model ]]; then info "Board:   $(tr -d '\0' </proc/device-tree/model)"; fi
. /etc/os-release
info "System:  $PRETTY_NAME ($(uname -m))"
if [[ ${VERSION_CODENAME:-} != bookworm && ${VERSION_CODENAME:-} != trixie ]]; then
  warn "Tested on Raspberry Pi OS Bookworm/Trixie. Continuing anyway."
fi

# --- 1. packages ---------------------------------------------------------------------------

step "Installing system packages (a few minutes on a Pi 3)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  git python3 python3-venv python3-dev build-essential \
  i2c-tools raspi-utils bluez network-manager sqlite3 curl ca-certificates >/dev/null
ok "packages installed"

# --- 2. interfaces -------------------------------------------------------------------------

step "Enabling I2C (ADS1115) and the serial port (GPS)"
if command -v raspi-config >/dev/null; then
  raspi-config nonint do_i2c 0          # enable I2C
  raspi-config nonint do_serial_cons 1  # no login console on the serial port…
  raspi-config nonint do_serial_hw 0    # …but keep the serial hardware on for the GPS
  ok "I2C and UART enabled (takes effect after a reboot)"
else
  warn "raspi-config not found: enable I2C and the serial port by hand (see docs/install.md)"
fi
systemctl enable --now bluetooth >/dev/null 2>&1 || warn "could not enable Bluetooth"
# Raspberry Pi OS often ships with Bluetooth soft-blocked; Victron devices need it on.
command -v rfkill >/dev/null && rfkill unblock bluetooth >/dev/null 2>&1 || true

step "Giving $SERVICE_USER access to GPIO, I2C, serial, Bluetooth and WiFi"
for group in gpio i2c dialout bluetooth netdev; do
  getent group "$group" >/dev/null && usermod -aG "$group" "$SERVICE_USER"
done
# NetworkManager: let the netdev group switch WiFi networks from the dashboard.
install -d /etc/polkit-1/rules.d
cat >/etc/polkit-1/rules.d/50-smartify-networkmanager.rules <<'EOF'
// Smartify Kombi: allow members of "netdev" to manage WiFi via NetworkManager.
polkit.addRule(function (action, subject) {
  if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 && subject.isInGroup("netdev")) {
    return polkit.Result.YES;
  }
});
EOF
ok "groups and permissions set"

# --- 3. Python backend -----------------------------------------------------------------------

step "Installing the Smartify backend (Python)"
if [[ ! -x $BACKEND/.venv/bin/python ]]; then
  as_user python3 -m venv "$BACKEND/.venv"
fi
as_user "$BACKEND/.venv/bin/pip" install -q --upgrade pip
as_user "$BACKEND/.venv/bin/pip" install -q -e "${BACKEND}[pi]"
ok "backend installed in backend/.venv"

# --- 4. settings ---------------------------------------------------------------------------------

step "Settings (backend/.env)"
if [[ -f $ENV_FILE ]]; then
  ok "keeping your existing backend/.env"
else
  if [[ -n $PASSWORD && ${#PASSWORD} -lt 8 ]]; then die "--password needs at least 8 characters"; fi
  SENSORS=$(ask "DHT22 sensors as name:GPIO (comma separated)" "inside:4,outside:17")
  RELAYS=$(ask "Relays as name:GPIO (comma separated)" "heater:25,fan:26")
  GPS=$(ask "GPS module connected? (true/false)" "true")
  umask 077
  cat >"$ENV_FILE" <<EOF
# Smartify Kombi settings. All options: .env.example in the project folder.
# After changing anything: sudo systemctl restart smartify
SMARTIFY_HARDWARE=pi
SMARTIFY_PORT=$PORT
SMARTIFY_FRONTEND_DIR=$REPO/frontend/dist

# The dashboard login is created in the browser on first start (stored hashed).
# Only set these to skip that, e.g. for scripted installs.
SMARTIFY_USERNAME=admin
SMARTIFY_PASSWORD=$PASSWORD

SMARTIFY_DHT22_SENSORS=$SENSORS
SMARTIFY_DEFAULT_RELAYS=$RELAYS
SMARTIFY_GPS_ENABLED=$GPS

# Victron over Bluetooth: name|MAC|key, see docs/victron.md
# SMARTIFY_VICTRON_DEVICES=

# Remote dashboard, see cloud/README.md
# SMARTIFY_CLOUD_URL=
# SMARTIFY_CLOUD_TOKEN=
EOF
  umask 022
  chown "$SERVICE_USER": "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "written (only $SERVICE_USER can read it)"
fi

# --- 5. dashboard -----------------------------------------------------------------------------------

if [[ $DASHBOARD == 1 ]]; then
  step "Installing the web dashboard"
  DIST="$REPO/frontend/dist"
  if [[ -f $DIST/index.html ]]; then
    ok "already built (frontend/dist)"
  else
    # 1) a prebuilt dashboard from the project's latest GitHub release
    URL="https://github.com/AdinPInjo/Smartify-kombi/releases/latest/download/dashboard.tar.gz"
    if as_user curl -fsSL --max-time 60 "$URL" -o /tmp/smartify-dashboard.tar.gz 2>/dev/null; then
      as_user mkdir -p "$DIST"
      as_user tar -xzf /tmp/smartify-dashboard.tar.gz -C "$DIST"
      rm -f /tmp/smartify-dashboard.tar.gz
      ok "downloaded the prebuilt dashboard"
    else
      # 2) build it here (slow on a Pi 3: about 5 minutes)
      warn "no prebuilt dashboard available, building it on the Pi (about 5 minutes)"
      apt-get install -y -qq nodejs npm >/dev/null
      (cd "$REPO/frontend" && as_user npm ci --no-audit --no-fund --loglevel=error && as_user npm run build)
      ok "dashboard built"
    fi
  fi
fi

# --- 6. service ---------------------------------------------------------------------------------------

step "Installing the systemd service"
sed -e "s|__USER__|$SERVICE_USER|g" -e "s|__DIR__|$REPO|g" "$REPO/deploy/smartify.service" \
  >/etc/systemd/system/smartify.service
systemctl daemon-reload
systemctl enable smartify >/dev/null 2>&1
ok "smartify.service enabled (starts on every boot)"

# --- done ---------------------------------------------------------------------------------------------

HOST=$(hostname)
URL="http://$HOST.local"; [[ $PORT != 80 ]] && URL="$URL:$PORT"
echo
echo "${BOLD}${GREEN}Installed.${RESET}"
echo
echo "  1. Reboot so I2C, the serial port and the group changes take effect:"
echo "       ${BOLD}sudo reboot${RESET}"
echo "  2. Then open the dashboard: ${BOLD}$URL${RESET}"
echo "     The first time, it asks you to create your login."
echo "  3. First checks: docs/install.md, section \"After the first boot\"."
echo
echo "  Logs:     journalctl -u smartify -f"
echo "  Settings: $ENV_FILE  (then: sudo systemctl restart smartify)"
