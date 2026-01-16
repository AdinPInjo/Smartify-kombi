#!/bin/bash
# Installation script for Smartify Remote Sync

set -e

echo "🚐 Smartify Remote Sync Installation"
echo "====================================="
echo ""

# Detect the actual user (not root even if using sudo)
if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
elif [ -n "$LOGNAME" ]; then
    ACTUAL_USER="$LOGNAME"
else
    ACTUAL_USER="$(logname 2>/dev/null || whoami)"
fi

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "⚠️  Running as root with SUDO."
    echo "   Service will run as user: $ACTUAL_USER"
    echo ""
else
    echo "ℹ️  Running as user: $ACTUAL_USER"
    echo "   This script will use sudo when needed."
    echo ""
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMARTIFY_DIR="$(dirname "$SCRIPT_DIR")"

echo "📁 Directories:"
echo "   Smartify: $SMARTIFY_DIR"
echo "   Deploy:   $SCRIPT_DIR"
echo "   User:     $ACTUAL_USER"
echo ""

# Create required directories
echo "📁 Creating directories..."
sudo mkdir -p /var/log/smartify
sudo mkdir -p /var/lib/smartify
sudo mkdir -p /etc/smartify

# Set permissions
sudo chown $ACTUAL_USER:$ACTUAL_USER /var/log/smartify
sudo chown $ACTUAL_USER:$ACTUAL_USER /var/lib/smartify
sudo chown $ACTUAL_USER:$ACTUAL_USER /etc/smartify

echo "   ✓ Directories created with proper permissions for $ACTUAL_USER"
echo ""

# Create default desired_state.json if it doesn't exist
if [ ! -f /etc/smartify/desired_state.json ]; then
    echo "📝 Creating default desired_state.json..."
    cat > /etc/smartify/desired_state.json <<EOF
{
  "version": 0,
  "desired_state": {}
}
EOF
    sudo chown $ACTUAL_USER:$ACTUAL_USER /etc/smartify/desired_state.json
    echo "   ✓ Created /etc/smartify/desired_state.json"
else
    echo "📝 desired_state.json already exists, skipping"
fi
echo ""

# Copy systemd service file and substitute user/paths
echo "⚙️  Installing systemd service..."

# Create temporary service file with substitutions
TEMP_SERVICE=$(mktemp)
sed "s|__USER__|$ACTUAL_USER|g" "$SCRIPT_DIR/smartify-remote-sync.service" > "$TEMP_SERVICE"
sed -i "s|__WORKING_DIR__|$SMARTIFY_DIR|g" "$TEMP_SERVICE"

# Install service
sudo cp "$TEMP_SERVICE" /etc/systemd/system/smartify-remote-sync.service
rm "$TEMP_SERVICE"

# Reload systemd
sudo systemctl daemon-reload

echo "   ✓ Service installed for user: $ACTUAL_USER"
echo ""

# Enable service
echo "🔄 Enabling service (will start on boot)..."
sudo systemctl enable smartify-remote-sync
echo "   ✓ Service enabled"
echo ""

# Ask if user wants to start now
read -p "Start service now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "▶️  Starting service..."
    sudo systemctl start smartify-remote-sync
    sleep 2
    
    # Show status
    echo ""
    echo "📊 Service status:"
    sudo systemctl status smartify-remote-sync --no-pager -l || true
    echo ""
    
    echo "✅ Service started!"
else
    echo "⏸️  Service not started. Start manually with:"
    echo "   sudo systemctl start smartify-remote-sync"
fi

echo ""
echo "====================================="
echo "✅ Installation complete!"
echo ""
echo "📂 Important files:"
echo "   Telemetry:      /var/log/smartify/telemetry_outbox.jsonl"
echo "   Settings:       /etc/smartify/desired_state.json"
echo "   ACK State:      /var/log/smartify/ack_state.json"
echo "   Applied Ver:    /var/lib/smartify/applied_version.txt"
echo "   Last GPS:       /var/lib/smartify/last_gps.json"
echo ""
echo "📚 Useful commands:"
echo "   Check status:   sudo systemctl status smartify-remote-sync"
echo "   View logs:      tail -f /var/log/smartify/remote_sync.log"
echo "   View telemetry: tail -f /var/log/smartify/telemetry_outbox.jsonl"
echo "   Restart:        sudo systemctl restart smartify-remote-sync"
echo "   Stop:           sudo systemctl stop smartify-remote-sync"
echo ""
echo "🔧 To update settings:"
echo "   Edit /etc/smartify/desired_state.json and increment the version"
echo "   The runner will detect and apply changes within 15 seconds"
echo ""
echo "🚀 Your device is now running in local mode!"
