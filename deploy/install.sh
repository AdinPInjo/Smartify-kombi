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
// Smartify Kombi: let members of "netdev" scan for and join WiFi networks
// (only the NetworkManager actions the dashboard's WiFi page needs).
var SMARTIFY_WIFI = [
  "org.freedesktop.NetworkManager.network-control",
  "org.freedesktop.NetworkManager.wifi.scan",
  "org.freedesktop.NetworkManager.enable-disable-wifi",
  "org.freedesktop.NetworkManager.settings.modify.own",
  "org.freedesktop.NetworkManager.settings.modify.system"
];
polkit.addRule(function (action, subject) {
  if (SMARTIFY_WIFI.indexOf(action.id) >= 0 && subject.isInGroup("netdev")) {
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
  RELAYS=$(ask "Relays as name:GPIO (comma separated)" "heater:25,fan:26")
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

SMARTIFY_DEFAULT_RELAYS=$RELAYS
# Sensors (temperature, GPS, water tank, doors, ...) are added in the dashboard:
# Sensors tab. Nothing to set here.

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

step "Enabling updates from the dashboard (Settings → Updates)"
DATA_DIR=$(grep -E '^SMARTIFY_DATA_DIR=' "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true)
DATA_DIR=${DATA_DIR:-data}
[[ $DATA_DIR == /* ]] || DATA_DIR="$BACKEND/$DATA_DIR"
as_user mkdir -p "$DATA_DIR/update"
for unit in smartify-update.service smartify-update.path; do
  sed -e "s|__USER__|$SERVICE_USER|g" -e "s|__DIR__|$REPO|g" -e "s|__DATA__|$DATA_DIR|g" \
    "$REPO/deploy/$unit" >"/etc/systemd/system/$unit"
done
# The updater runs as $SERVICE_USER; this is the one extra right it gets.
cat >/etc/polkit-1/rules.d/50-smartify-update.rules <<EOF
// Smartify Kombi: let the updater (user $SERVICE_USER) start, stop and restart smartify.service.
polkit.addRule(function (action, subject) {
  if (action.id == "org.freedesktop.systemd1.manage-units" && subject.user == "$SERVICE_USER") {
    var unit = action.lookup("unit");
    var verb = action.lookup("verb");
    if (unit == "smartify.service" && (verb == "start" || verb == "stop" || verb == "restart")) {
      return polkit.Result.YES;
    }
  }
});
EOF
systemctl daemon-reload
systemctl enable --now smartify-update.path >/dev/null 2>&1
ok "updates can be installed and rolled back from the dashboard"

# The first login is created in the browser, and only with this code: someone
# else on the same WiFi can't create it before you.
SETUP_CODE=""
HAS_LOGIN=$(sqlite3 "$DATA_DIR/smartify.db" "SELECT 1 FROM account LIMIT 1" 2>/dev/null || true)
ENV_PASSWORD=$(grep -E '^SMARTIFY_PASSWORD=.+' "$ENV_FILE" 2>/dev/null || true)
if [[ -z $HAS_LOGIN && -z $ENV_PASSWORD ]]; then
  CODE_FILE="$DATA_DIR/setup-code.txt"
  if [[ ! -s $CODE_FILE ]]; then
    RAW=$(LC_ALL=C tr -dc 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' </dev/urandom | head -c8 || true)
    printf '%s-%s\n' "${RAW:0:4}" "${RAW:4:4}" >"$CODE_FILE"
    chown "$SERVICE_USER": "$CODE_FILE"
    chmod 600 "$CODE_FILE"
  fi
  SETUP_CODE=$(cat "$CODE_FILE")
fi

# --- done ---------------------------------------------------------------------------------------------

HOST=$(hostname)
URL="http://$HOST.local"; [[ $PORT != 80 ]] && URL="$URL:$PORT"
echo
echo "${BOLD}${GREEN}Installed.${RESET}"
echo
echo "  1. Reboot so I2C, the serial port and the group changes take effect:"
echo "       ${BOLD}sudo reboot${RESET}"
echo "  2. Then open the dashboard: ${BOLD}$URL${RESET}"
if [[ -n $SETUP_CODE ]]; then
  echo "     The first time, it asks you to create your login with this setup code:"
  echo
  echo "         ${BOLD}${AMBER}$SETUP_CODE${RESET}"
  echo
  echo "     (Lost it? On the Pi: cat $DATA_DIR/setup-code.txt)"
else
  echo "     Sign in with your login."
fi
echo "  3. First checks: docs/install.md, section \"After the first boot\"."
echo
echo "  Logs:     journalctl -u smartify -f"
echo "  Settings: $ENV_FILE  (then: sudo systemctl restart smartify)"
