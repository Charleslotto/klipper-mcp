#!/bin/bash
# Klipper MCP Server Installation Script for CB1
# Run this script on your CB1 to install the MCP server
# Compatible with Python 3.9+

set -e

echo "=========================================="
echo "Klipper MCP Server Installer"
echo "=========================================="

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python version: $PYTHON_VERSION"

# Configuration
INSTALL_DIR="${KLIPPER_MCP_DIR:-$HOME/klipper-mcp}"
VENV_DIR="$INSTALL_DIR/venv"
SERVICE_NAME="klipper-mcp"
CURRENT_USER="$(whoami)"

echo "Installing as user: $CURRENT_USER"
echo "Install directory: $INSTALL_DIR"

# Create installation directory
echo "Creating installation directory..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/backups"
mkdir -p "$INSTALL_DIR/scenes"
mkdir -p "$INSTALL_DIR/tools"

# Copy files (assumes files are in current directory)
echo "Copying files..."
cp -r ./*.py "$INSTALL_DIR/" 2>/dev/null || true
cp -r ./tools/*.py "$INSTALL_DIR/tools/" 2>/dev/null || true
cp -r ./data/* "$INSTALL_DIR/data/" 2>/dev/null || true
cp -r ./scenes/* "$INSTALL_DIR/scenes/" 2>/dev/null || true
cp requirements.txt "$INSTALL_DIR/" 2>/dev/null || true
cp klipper-mcp.service "$INSTALL_DIR/" 2>/dev/null || true

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"

# Activate venv and install dependencies
echo "Installing dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$INSTALL_DIR/requirements.txt"

# Create config from template if needed
if [ ! -f "$INSTALL_DIR/config.py" ]; then
    echo "Creating default config.py..."
    # The config.py should already be copied, but create if missing
    cp "$INSTALL_DIR/config.example.py" "$INSTALL_DIR/config.py"
fi

# Generate systemd service file for current user/paths
echo "Generating systemd service file..."
cat > "$INSTALL_DIR/klipper-mcp.service" << SVCEOF
[Unit]
Description=Klipper MCP Server
After=network.target moonraker.service
Wants=moonraker.service

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$VENV_DIR/bin/python server.py
Restart=always
RestartSec=10

# Logging
StandardOutput=append:/var/log/klipper-mcp.log
StandardError=append:/var/log/klipper-mcp.log

[Install]
WantedBy=multi-user.target
SVCEOF

# Install systemd service
echo "Installing systemd service..."
sudo cp "$INSTALL_DIR/klipper-mcp.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

# Create log file
sudo touch /var/log/klipper-mcp.log
sudo chown "$CURRENT_USER:$CURRENT_USER" /var/log/klipper-mcp.log

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit the configuration file:"
echo "   nano $INSTALL_DIR/config.py"
echo ""
echo "2. Set ARMED=True when ready to enable dangerous commands"
echo ""
echo "3. Start the service:"
echo "   sudo systemctl start $SERVICE_NAME"
echo ""
echo "4. Check service status:"
echo "   sudo systemctl status $SERVICE_NAME"
echo ""
echo "5. View logs:"
echo "   tail -f /var/log/klipper-mcp.log"
echo ""
echo "MCP server will be available at:"
echo "   http://$(hostname -I | awk '{print $1}'):${MCP_PORT:-8000}/mcp"
echo ""
