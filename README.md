# Klipper MCP Server

A Model Context Protocol (MCP) server for controlling Klipper 3D printers via Moonraker API. Enables AI assistants like Claude to control your 3D printer through VS Code or any MCP-compatible client.

## Overview

This server exposes **100+ tools** for complete printer management, from basic operations to advanced diagnostics and toolchanger control. Perfect for Voron, RatRig, or any Klipper-based printer.

## Features

### 🖨️ Core Printer Control
| Tool | Description |
|------|-------------|
| `get_printer_status` | Full status including temps, position, state |
| `run_gcode` | Execute any G-code command |
| `start_print` | Start a print job |
| `pause_print` / `resume_print` | Print flow control |
| `cancel_print` | Cancel current print |
| `home_axes` | Home X/Y/Z or all axes |
| `emergency_stop` | Immediate halt |
| `restart_klipper` | Firmware restart |
| `quad_gantry_level` | Run QGL procedure |
| `set_heater_temperature` | Set hotend/bed temps |

### 🔧 StealthChanger / Toolchanger Support
| Tool | Description |
|------|-------------|
| `get_active_tool` | Current tool status |
| `select_tool` | Pick up tool (T0-T5) |
| `drop_tool` | Return tool to dock |
| `initialize_toolchanger` | Run init sequence |
| `get_tool_offsets` | Tool offset values |
| `start_tool_alignment` | Alignment workflow |
| `test_dock_undock` | Test docking operations |
| `disable_crash_detection` | Disable during testing |

### ⚡ TMC Stepper Driver Control
| Tool | Description |
|------|-------------|
| `get_tmc_status` | Driver status, currents, temps |
| `set_tmc_current` | Adjust run/hold current |
| `dump_tmc_registers` | Register diagnostics |
| `get_tmc_field` / `set_tmc_field` | Direct register access |
| `get_autotune_status` | TMC Autotune configuration |
| `list_tmc_steppers` | All TMC-equipped steppers |

### 💡 LED Effects (klipper-led_effect)
| Tool | Description |
|------|-------------|
| `list_led_effects` | Available effects |
| `set_led_effect` | Activate an effect |
| `stop_led_effect` / `stop_all_effects` | Stop effects |
| `set_led_color` | Direct RGB/RGBW control |
| `list_led_scenes` | Preset scenes |
| `activate_led_scene` | Apply scene preset |

### 📁 File Operations
| Tool | Description |
|------|-------------|
| `list_gcode_files` | Browse G-code files |
| `get_file_metadata` | Slicer settings, thumbnails |
| `read_gcode_file` | Read file contents |
| `upload_gcode_file` | Upload new files |
| `delete_gcode_file` | Remove files |
| `search_in_file` | Search file contents |
| `list_config_files` | Klipper config files |
| `read_config_file` | Read printer.cfg etc. |

### 📷 Camera & Timelapse
| Tool | Description |
|------|-------------|
| `get_camera_snapshot` | Capture current frame |
| `get_camera_stream_url` | MJPEG stream URL |
| `get_timelapse_settings` | Current timelapse config |
| `set_timelapse_enabled` | Enable/disable timelapse |
| `capture_timelapse_frame` | Manual frame capture |
| `render_timelapse` | Trigger video render |
| `configure_timelapse` | Adjust settings |

### 📊 Print Statistics
| Tool | Description |
|------|-------------|
| `get_print_history` | Past prints with filtering |
| `get_print_stats` | Cumulative statistics |
| `get_filament_usage_by_material` | Usage breakdown |
| `get_recent_prints` | Last N prints summary |
| `get_average_print_stats` | Average metrics |
| `export_printer_data` | Export all data to JSON |

### 🔍 Diagnostics & Troubleshooting
| Tool | Description |
|------|-------------|
| `parse_klippy_log` | Analyze log for issues |
| `get_recent_errors` | Recent errors with context |
| `get_log_summary` | Log overview |
| `check_common_issues` | Config problem detection |
| `get_mcu_status` | MCU info and timing |
| `get_gcode_history` | Recent G-code commands |
| `get_troubleshooting_guide` | Problem-specific help |
| `analyze_print_failure` | Failure diagnosis |
| `check_config_issues` | Configuration validation |
| `get_system_performance` | CPU, memory, disk stats |

### 🌡️ Temperature & Bed Mesh
| Tool | Description |
|------|-------------|
| `get_temperatures` | All heater temperatures |
| `get_temperature_history` | Historical temp data |
| `analyze_temperature_data` | Anomaly detection |
| `set_temperature_alert` | Threshold alerts |
| `run_bed_mesh_calibrate` | Run bed mesh |
| `get_bed_mesh_profiles` | List saved meshes |
| `load_bed_mesh` | Load a mesh profile |
| `save_bed_mesh` | Save current mesh |
| `clear_bed_mesh` | Remove active mesh |

### 🧵 Spoolman Integration
| Tool | Description |
|------|-------------|
| `list_spools` | All tracked spools |
| `get_active_spool` | Currently loaded spool |
| `set_active_spool` | Set spool for tool |
| `get_spool_details` | Full spool info |
| `check_low_filament` | Low filament warnings |
| `get_filament_usage_by_material` | Material statistics |
| `list_vendors` | Filament vendors |
| `list_filaments` | Filament database |

### 🔔 Notifications
| Tool | Description |
|------|-------------|
| `send_notification` | Multi-channel notify |
| `send_discord_notification` | Discord webhook |
| `send_slack_notification` | Slack webhook |
| `send_pushover_notification` | Pushover push |
| `announce_tts` | Text-to-speech |
| `test_notifications` | Test all channels |
| `get_notification_settings` | Current config |

### 💾 Backup & Maintenance
| Tool | Description |
|------|-------------|
| `backup_config` | Backup all configs |
| `list_backups` | Available backups |
| `restore_config` | Restore from backup |
| `check_maintenance_due` | Maintenance alerts |
| `log_maintenance` | Record maintenance |
| `get_maintenance_history` | Maintenance log |
| `get_audit_log` | Security audit trail |
| `export_printer_data` | Full data export |

### 📝 G-code Analysis
| Tool | Description |
|------|-------------|
| `analyze_gcode_file` | Full file analysis |
| `validate_gcode` | Check for issues |
| `extract_gcode_comments` | Slicer comments |
| `get_gcode_moves` | Movement statistics |
| `extract_layer` | Get specific layer |
| `compare_gcode_files` | Diff two files |

### 🖥️ System Management
| Tool | Description |
|------|-------------|
| `get_system_info` | CPU, memory, disk, temp |
| `get_network_info` | IP addresses, WiFi |
| `check_updates` | Available updates |
| `update_component` | Update Klipper/Moonraker |
| `refresh_update_status` | Check repos |
| `get_service_status` | Service states |
| `restart_service` | Restart services |
| `reboot_system` | System reboot |
| `shutdown_system` | System shutdown |
| `get_moonraker_config` | Moonraker info |
| `get_printer_objects` | Available Klipper objects |

## Installation

### Prerequisites
- Klipper + Moonraker running on your printer
- Python 3.9+ on your CB1/Raspberry Pi
- Network access between VS Code and printer
- VS Code with GitHub Copilot (for Claude integration)

### Quick Start (5 minutes)

```bash
# 1. SSH into your printer
ssh <user>@192.168.x.x  # e.g. biqu@ for BTT CB1, pi@ for Raspberry Pi

# 2. Clone the repository
cd ~
git clone https://github.com/Charleslotto/klipper-mcp.git
cd klipper-mcp

# 3. Create config from template
cp config.example.py config.py

# 4. Generate a secure API key and edit config
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
nano config.py  # Paste the API key and adjust settings

# 5. Run the installer
chmod +x install.sh
./install.sh

# 6. Start the service
sudo systemctl start klipper-mcp
sudo systemctl enable klipper-mcp  # Auto-start on boot
```

### Verify Installation

```bash
# Check service is running
sudo systemctl status klipper-mcp

# Test the API (replace with your API key)
curl -H "X-API-Key: your-api-key" http://localhost:8000/health

# View logs
journalctl -u klipper-mcp -f
```

### Configuration

Copy `config.example.py` to `config.py` and customize:

```bash
nano ~/klipper-mcp/config.py
```

**Required settings:**
| Setting | Description | Example |
|---------|-------------|---------|
| `API_KEY` | Secure authentication key | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `MOONRAKER_URL` | Your Moonraker address | `http://localhost:7125` |
| `PRINTER_NAME` | Display name | `Voron 2.4` |

**Security settings:**
| Setting | Description | Default |
|---------|-------------|---------|
| `ARMED` | Enable dangerous operations | `false` |
| `ADMIN_PIN` | PIN for destructive ops | `123456` |

**Optional integrations:**
| Setting | Description |
|---------|-------------|
| `SPOOLMAN_ENABLED` | Enable Spoolman filament tracking |
| `TOOL_COUNT` | Number of toolchanger tools |
| `DISCORD_WEBHOOK_URL` | Discord notifications |

---

## Setting Up VS Code MCP Client

### Method 1: User Settings (Recommended)

Add to your VS Code `settings.json` (`Ctrl+Shift+P` → "Preferences: Open User Settings (JSON)"):

```json
{
  "mcp": {
    "servers": {
      "voron": {
        "type": "http",
        "url": "http://192.168.x.x:8000/mcp",
        "headers": {
          "X-API-Key": "your-api-key-here"
        }
      }
    }
  }
}
```

### Method 2: Workspace Config

Create `.vscode/mcp.json` in your project:

```json
{
  "mcpServers": {
    "voron": {
      "type": "http", 
      "url": "http://192.168.x.x:8000/mcp",
      "headers": {
        "X-API-Key": "your-api-key-here"
      }
    }
  }
}
```

### Method 3: Multiple Printers

Configure multiple printers in settings.json:

```json
{
  "mcp": {
    "servers": {
      "voron-2.4": {
        "type": "http",
        "url": "http://192.168.1.100:8000/mcp",
        "headers": { "X-API-Key": "key-for-voron" }
      },
      "voron-0.2": {
        "type": "http",
        "url": "http://192.168.1.101:8000/mcp",
        "headers": { "X-API-Key": "key-for-v0" }
      }
    }
  }
}
```

### Verify Connection

1. Open VS Code with Copilot
2. Open the Copilot Chat panel
3. Type: `@voron what's your status?`
4. Claude should respond with your printer's status

**Troubleshooting:**
- Ensure the CB1/Pi IP address is reachable: `ping 192.168.x.x`
- Check firewall allows port 8000: `sudo ufw allow 8000`
- Verify API key matches exactly in VS Code and config.py
- Check service is running: `sudo systemctl status klipper-mcp`

---

## Security

### ARMED Flag
Dangerous operations (G-code execution, temperature changes) require `ARMED=True` in config.

### Admin PIN
Destructive operations (file deletion, config restore, system reboot) require the admin PIN.

### API Key
All requests must include a valid `X-API-Key` header matching your config.

### Audit Log
All operations are logged to `data/audit.log` for security review.

## Configuration Reference

```python
# config.py

# Moonraker connection
MOONRAKER_URL = "http://localhost:7125"
PRINTER_NAME = "Voron"

# MCP Server
MCP_HOST = "0.0.0.0"
MCP_PORT = 8000
MCP_TRANSPORT = "http"  # or "stdio" for local use

# Security
API_KEY = "your-secret-key"        # Required for all API calls
ARMED = False                       # Set True to enable dangerous ops
ADMIN_PIN = "1234"                  # For destructive operations

# Camera
CAMERA_SNAPSHOT_URL = "http://localhost/webcam/?action=snapshot"
CAMERA_STREAM_URL = "http://localhost/webcam/?action=stream"

# Spoolman (optional)
SPOOLMAN_ENABLED = True
SPOOLMAN_URL = "http://localhost:7912"

# Notifications (optional)
DISCORD_WEBHOOK_URL = ""
SLACK_WEBHOOK_URL = ""
PUSHOVER_USER_KEY = ""
PUSHOVER_API_TOKEN = ""

# Text-to-Speech (optional)
TTS_ENABLED = False
TTS_RATE = 150
TTS_VOLUME = 1.0

# Maintenance intervals (print hours)
MAINTENANCE_INTERVALS = {
    "nozzle": 200,
    "belts": 500,
    "linear_rails": 1000,
    "filters": 100
}

# StealthChanger / Toolchanger
TOOL_COUNT = 4  # Number of tools (T0-T3)
```

## Usage Examples

### Basic Commands
```
"What's my printer's current status?"
"Set the bed to 60°C and hotend to 210°C"
"Start printing benchy.gcode"
"Pick up T1" / "Drop the current tool"
```

---

### 🧵 Bulk Import Filament Database into Spoolman

**User:** "I want to bulk import filaments into Spoolman from the community database"

**Claude:** I'll fetch the external filament database and import everything for you...

**Result:**
- Fetched 6,957 filaments from SpoolmanDB community database
- Created 53 vendors (Polymaker, eSun, Bambu Lab, Prusament, Hatchbox, etc.)
- Imported 5,223 filaments with full specifications:
  - Material types: PLA (2,466), PETG (943), ASA (526), ABS (467), TPU (312)...
  - Includes density, diameters, temp ranges, colors
- All searchable in Spoolman UI

---

### 🔍 System Health Check After Heavy Operation

**User:** "How is the Voron's load now that Spoolman has all that data?"

**Claude:** Let me check the system status...

```
┌──────────────────────────────────────┐
│ System Load After Spoolman Import    │
├─────────────┬────────────┬───────────┤
│ CPU Load    │ 1.32       │ 🟢 Normal │
│ Memory      │ 60% used   │ 🟢 OK     │
│ Disk        │ 38% used   │ 🟢 OK     │
│ CPU Temp    │ 45.7°C     │ 🟢 Cool   │
│ CAN Bus     │ All Active │ 🟢 OK     │
└─────────────┴────────────┴───────────┘
```

**Analysis:** Spoolman runs on a separate machine, so the 5,223 filaments don't impact Klipper. Load settled from 1.71 → 1.32 after initial indexing.

---

### 🛠️ Configuration Audit & Diagnostics

**User:** "Can you audit my Voron's configuration?"

**Claude:** I'll analyze your printer configuration and logs...

**Results:**
```
Configuration Issues Found:
⚠️  Klipper git state: dirty/invalid - uncommitted changes
⚠️  TMC Autotune: Installed but not configured for all steppers
⚠️  Hold current: Using default 50% - consider optimizing

Recommendations:
1. Run 'git stash' in Klipper directory to clean state
2. Add [autotune_tmc] sections for stepper_x, stepper_y, stepper_z
3. Set hold_current to 40% for lower idle power consumption

No Critical Errors Found ✅
CAN Bus: All 4 MCUs communicating properly
TMC Drivers: No errors, all steppers responding
```

---

### 🌡️ Temperature Anomaly Detection

**User:** "Analyze my temperature data for any issues"

**Claude:** Analyzing temperature history...

```
Temperature Analysis (Last 24 Hours)
────────────────────────────────────
Hotend (extruder):
  ✅ Stable PID tuning - variance: ±0.3°C
  ✅ No thermal runaway events
  
Bed (heater_bed):
  ⚠️ Detected 2 oscillations during warmup
  💡 Consider re-running PID_CALIBRATE BED

Chamber:
  ✅ Consistent 45°C during ABS prints
  
MCU Temperatures:
  ✅ All MCUs under 50°C
```

---

### 🔧 TMC Driver Optimization

**User:** "What are my TMC driver settings and can they be improved?"

**Claude:** Let me check your TMC configuration...

```
TMC Driver Status
─────────────────────────────────────────────────
Stepper      │ Driver   │ Run    │ Hold   │ Temp
─────────────┼──────────┼────────┼────────┼──────
stepper_x    │ TMC2209  │ 0.800A │ 0.400A │ 42°C
stepper_y    │ TMC2209  │ 0.800A │ 0.400A │ 44°C
stepper_z    │ TMC2209  │ 0.800A │ 0.600A │ 38°C
stepper_z1   │ TMC2209  │ 0.800A │ 0.600A │ 39°C
stepper_z2   │ TMC2209  │ 0.800A │ 0.600A │ 37°C
stepper_z3   │ TMC2209  │ 0.800A │ 0.600A │ 38°C
extruder     │ TMC2209  │ 0.650A │ 0.325A │ 41°C

TMC Autotune: ⚠️ Installed but needs motor configuration
Recommendation: Add motor specs to enable automatic tuning
```

---

### 📊 Print Statistics & Filament Usage

**User:** "Show me my print statistics and filament usage"

**Claude:** Here's your printing summary...

```
Lifetime Statistics
───────────────────
Total Prints:     847
Success Rate:     94.2%
Total Print Time: 1,247 hours
Total Filament:   12.4 kg

Filament by Material
────────────────────
PLA   │ ████████████████████ │ 6.2 kg (50%)
PETG  │ ████████████         │ 3.1 kg (25%)
ABS   │ ████████             │ 2.0 kg (16%)
ASA   │ ████                 │ 1.1 kg (9%)

Recent Prints (Last 7 Days)
───────────────────────────
✅ voron_panel_x4.gcode    │ 4h 23m │ PETG
✅ cable_chain.gcode       │ 2h 15m │ ABS
✅ benchy.gcode            │ 0h 42m │ PLA
❌ large_vase.gcode        │ Failed │ Layer shift @ 45%
```

---

### 🔄 Multi-Tool Print Setup

**User:** "I want to print a dual-color model, help me set up the tools"

**Claude:** Let me configure your toolchanger...

```
Current Tool Status
───────────────────
T0 (extruder):  🔵 Active - Docked
T1 (extruder1): ⚪ Ready - Docked  
T2 (extruder2): ⚪ Ready - Docked

Setting up for dual-color print:
1. ✅ Set T0 active spool: Polymaker PLA Pro - Blue (ID: 142)
2. ✅ Set T1 active spool: Polymaker PLA Pro - White (ID: 156)
3. ✅ Verified tool offsets are calibrated
4. ✅ Both hotends at target temp (210°C)

Ready to print! The slicer should handle tool changes automatically.
```

---

### 💾 Automated Backup Before Update

**User:** "I want to update Klipper but backup my config first"

**Claude:** I'll create a backup and then check for updates...

```
Backup Created
──────────────
📁 backup_2026-01-26_143022.tar.gz
   - printer.cfg
   - moonraker.conf
   - mainsail.cfg
   - 12 include files
   Total: 847 KB

Available Updates
─────────────────
Component    │ Current     │ Available   │ Status
─────────────┼─────────────┼─────────────┼────────
Klipper      │ v0.12.0-145 │ v0.12.0-152 │ 7 commits behind
Moonraker    │ v0.8.0-401  │ v0.8.0-401  │ ✅ Up to date
Mainsail     │ v2.9.1      │ v2.10.0     │ Update available

Would you like me to proceed with updating Klipper?
```

## Optional Integrations

### Spoolman
Enable filament tracking by setting up [Spoolman](https://github.com/Donkie/Spoolman):
```bash
cd ~/klipper-mcp/scripts
chmod +x install_spoolman.sh
./install_spoolman.sh
```

Then update `config.py`:
```python
SPOOLMAN_ENABLED = True
SPOOLMAN_URL = "http://localhost:7912"
```

### TMC Autotune
For automatic TMC tuning, install [klipper_tmc_autotune](https://github.com/andrewmcgr/klipper_tmc_autotune).

### LED Effects
For animated LEDs, install [klipper-led_effect](https://github.com/julianschill/klipper-led_effect).

## Troubleshooting

### Server won't start
```bash
# Check Moonraker is running
systemctl status moonraker

# Check logs
journalctl -u klipper-mcp -f

# Verify config
python3 -c "import config; print(config.MOONRAKER_URL)"
```

### Can't connect from VS Code
- Verify CB1/Pi IP address is correct
- Check firewall allows port 8000: `sudo ufw allow 8000`
- Verify API key matches in VS Code and config.py
- Test: `curl -H "X-API-Key: your-key" http://ip:8000/health`

### Operations failing
- Check `ARMED=True` for dangerous operations
- Verify Klipper is running and ready: `systemctl status klipper`
- Check klippy.log: `tail -f ~/printer_data/logs/klippy.log`

### Spoolman not working
- Verify Spoolman is running: `systemctl status spoolman`
- Check URL in config.py matches Spoolman's address
- Test: `curl http://localhost:7912/api/v1/health`

## Project Structure

```
klipper-mcp/
├── server.py           # Main MCP server
├── moonraker.py        # Moonraker API client
├── config.py           # Configuration
├── requirements.txt    # Python dependencies
├── install.sh          # Installation script
├── klipper-mcp.service # Systemd service file
├── tools/              # MCP tool implementations
│   ├── printer.py      # Core printer control
│   ├── toolchanger.py  # Toolchanger/StealthChanger
│   ├── tmc.py          # TMC driver control
│   ├── led_effects.py  # LED animations
│   ├── filesystem.py   # File operations
│   ├── camera.py       # Camera & timelapse
│   ├── statistics.py   # Print history
│   ├── diagnostics.py  # Error analysis
│   ├── temperature.py  # Temp control & mesh
│   ├── spoolman.py     # Filament tracking
│   ├── notifications.py# Alerts & TTS
│   ├── backup.py       # Backup & maintenance
│   ├── gcode_analysis.py # G-code parsing
│   └── system.py       # System management
├── data/               # Runtime data
│   ├── audit.log       # Security log
│   └── maintenance.json# Maintenance records
├── backups/            # Config backups
├── scenes/             # LED scene presets
│   └── led_scenes.json
└── docs/               # Documentation
```

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests if applicable
4. Submit a pull request

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- [Klipper](https://www.klipper3d.org/) - 3D printer firmware
- [Moonraker](https://moonraker.readthedocs.io/) - Klipper API server
- [Model Context Protocol](https://modelcontextprotocol.io/) - AI tool protocol
- [StealthChanger](https://github.com/DraftShift/StealthChanger) - Toolchanger system
- [Spoolman](https://github.com/Donkie/Spoolman) - Filament management
