"""
Klipper MCP Server Configuration
Copy this file to config.py and customize for your printer.

  cp config.example.py config.py
  nano config.py
"""
import os

# Base directories (derived from environment, never hardcoded)
_HOME = os.path.expanduser("~")
_MCP_DIR = os.path.dirname(os.path.abspath(__file__))

# =============================================================================
# MOONRAKER CONNECTION
# =============================================================================
# URL to your Moonraker instance (usually localhost if running on same machine)
MOONRAKER_URL = os.getenv("MOONRAKER_URL", "http://localhost:7125")

# Timeout (seconds) for requests to Moonraker. Some operations (homing, bed mesh
# calibration, quad gantry level, tool changes, plugin updates) legitimately take
# longer than a typical HTTP request timeout.
MOONRAKER_TIMEOUT_SECONDS = int(os.getenv("MOONRAKER_TIMEOUT_SECONDS", "120"))

# Display name for your printer
PRINTER_NAME = "Voron"

# =============================================================================
# MCP SERVER SETTINGS
# =============================================================================
# Host: 0.0.0.0 = listen on all interfaces (required for remote access)
#       127.0.0.1 = localhost only
MCP_HOST = "0.0.0.0"
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

# =============================================================================
# SECURITY - IMPORTANT: Change these values!
# =============================================================================
# API key for authenticating MCP clients
# Generate a strong random key: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
API_KEY = os.getenv("API_KEY", "CHANGE-ME-TO-A-SECURE-KEY")

# Armed mode - when False, dangerous commands (gcode, temp changes) are blocked
# Set to True once you've verified everything works
ARMED = os.getenv("ARMED", "false").lower() == "true"

# Admin PIN for destructive operations (delete files, restore config, reboot)
ADMIN_PIN = os.getenv("ADMIN_PIN", "123456")

# =============================================================================
# FILE PATHS
# Derived from $HOME by default; override with env vars for custom setups
# =============================================================================
PRINTER_DATA_PATH = os.getenv("PRINTER_DATA_PATH", os.path.join(_HOME, "printer_data"))
CONFIG_PATH = f"{PRINTER_DATA_PATH}/config"
GCODES_PATH = f"{PRINTER_DATA_PATH}/gcodes"
LOGS_PATH = f"{PRINTER_DATA_PATH}/logs"
BACKUP_PATH = f"{PRINTER_DATA_PATH}/backups"

# Security: Only allow file operations in these directories
ALLOWED_PATHS = [
    CONFIG_PATH,
    GCODES_PATH,
    LOGS_PATH,
    BACKUP_PATH,
]

# =============================================================================
# CAMERA SETTINGS
# =============================================================================
# Crowsnest/mjpg-streamer URLs
CAMERA_SNAPSHOT_URL = os.getenv("CAMERA_SNAPSHOT_URL", "http://localhost/webcam/?action=snapshot")
CAMERA_STREAM_URL = os.getenv("CAMERA_STREAM_URL", "http://localhost/webcam/?action=stream")

# =============================================================================
# SPOOLMAN SETTINGS (optional filament tracking)
# https://github.com/Donkie/Spoolman
# =============================================================================
SPOOLMAN_ENABLED = os.getenv("SPOOLMAN_ENABLED", "false").lower() == "true"
SPOOLMAN_URL = os.getenv("SPOOLMAN_URL", "http://localhost:7912")

# =============================================================================
# NOTIFICATION SETTINGS (all optional)
# =============================================================================
# ntfy.sh - free, self-hostable push notifications
NTFY_ENABLED = os.getenv("NTFY_ENABLED", "false").lower() == "true"
NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.sh")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "voron-printer")

# Discord webhook
DISCORD_ENABLED = os.getenv("DISCORD_ENABLED", "false").lower() == "true"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Slack webhook
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Pushover
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN", "")

# Text-to-Speech (plays on CB1/Pi speaker if available)
TTS_ENABLED = os.getenv("TTS_ENABLED", "false").lower() == "true"
TTS_RATE = int(os.getenv("TTS_RATE", "150"))
TTS_VOLUME = float(os.getenv("TTS_VOLUME", "0.8"))

# =============================================================================
# TOOLCHANGER / STEALTHCHANGER SETTINGS
# =============================================================================
# Number of tools configured (T0, T1, T2, etc.)
TOOL_COUNT = int(os.getenv("TOOL_COUNT", "1"))

# Tool display names (optional)
TOOL_NAMES = {
    0: "T0",
    1: "T1",
    2: "T2",
    3: "T3",
}

# =============================================================================
# MAINTENANCE TRACKING
# =============================================================================
# Path to store maintenance data
MAINTENANCE_DATA_FILE = os.getenv("MAINTENANCE_DATA_FILE", os.path.join(_MCP_DIR, "data", "maintenance.json"))
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", os.path.join(_MCP_DIR, "data", "audit.log"))

# Maintenance intervals (in print hours)
MAINTENANCE_INTERVALS = {
    "nozzle_change": 500,
    "belt_tension": 200,
    "lubrication": 100,
    "pom_nut_check": 300,
    "filter_change": 200,
    "hotend_clean": 50,
}

# =============================================================================
# LED SCENES
# =============================================================================
LED_SCENES_FILE = os.getenv("LED_SCENES_FILE", os.path.join(_MCP_DIR, "scenes", "led_scenes.json"))

# Aliases for backward compatibility
MAINTENANCE_LOG_PATH = MAINTENANCE_DATA_FILE
AUDIT_LOG_PATH = AUDIT_LOG_FILE
