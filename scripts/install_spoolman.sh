#!/bin/bash
# Spoolman Installation Script for CB1/Raspberry Pi

set -e

SPOOLMAN_DIR="${SPOOLMAN_INSTALL_DIR:-$HOME/spoolman}"
SPOOLMAN_VERSION="0.19.3"

echo "=== Installing Spoolman v${SPOOLMAN_VERSION} ==="

# Install dependencies
echo "Installing dependencies..."
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv

# Create directory
echo "Creating Spoolman directory..."
rm -rf "${SPOOLMAN_DIR}"
mkdir -p "${SPOOLMAN_DIR}"
cd "${SPOOLMAN_DIR}"

# Download latest release
echo "Downloading Spoolman..."
DOWNLOAD_URL="https://github.com/Donkie/Spoolman/releases/download/v${SPOOLMAN_VERSION}/spoolman.tar.gz"
curl -sL "${DOWNLOAD_URL}" | tar xz

# Create virtual environment and install dependencies
echo "Setting up Python environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

# Create .env file
echo "Creating configuration..."
cat > .env << 'EOF'
# Spoolman Configuration
SPOOLMAN_DB_TYPE=sqlite
SPOOLMAN_HOST=0.0.0.0
SPOOLMAN_PORT=7912
SPOOLMAN_LOGGING_LEVEL=info
EOF

# Create systemd service
echo "Creating systemd service..."
sudo tee /etc/systemd/system/spoolman.service > /dev/null << EOF
[Unit]
Description=Spoolman - Filament Spool Manager
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=${SPOOLMAN_DIR}
ExecStart=${SPOOLMAN_DIR}/.venv/bin/uvicorn spoolman.main:app --host 0.0.0.0 --port 7912
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
echo "Starting Spoolman service..."
sudo systemctl daemon-reload
sudo systemctl enable spoolman
sudo systemctl start spoolman

# Wait and check status
sleep 3
sudo systemctl status spoolman --no-pager

echo ""
echo "=== Spoolman Installation Complete ==="
echo "Web UI: http://$(hostname -I | awk '{print $1}'):7912"
echo ""
echo "Next steps:"
echo "1. Add to Moonraker config:"
echo "   [spoolman]"
echo "   server: http://localhost:7912"
echo ""
echo "2. Enable in Klipper MCP:"
echo "   Set SPOOLMAN_ENABLED=true"
