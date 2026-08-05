"""
Core Printer Control Tools
Basic printer operations: status, temps, G-code, emergency stop
"""
import json
from typing import Optional
import config
from moonraker import get_client
from tools.security import verify_pin


def register_printer_tools(mcp):
    """Register printer control tools."""
    
    @mcp.tool()
    async def get_printer_status() -> str:
        """
        Get comprehensive Voron printer status including temperatures, 
        position, print state, and progress.
        """
        client = get_client()
        result = await client.get_printer_status()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        status = result.get("result", {}).get("status", {})
        
        # Format into readable structure
        formatted = {
            "printer": config.PRINTER_NAME,
            "state": status.get("print_stats", {}).get("state", "unknown"),
            "temperatures": {
                "bed": {
                    "current": status.get("heater_bed", {}).get("temperature"),
                    "target": status.get("heater_bed", {}).get("target"),
                },
                "extruder": {
                    "current": status.get("extruder", {}).get("temperature"),
                    "target": status.get("extruder", {}).get("target"),
                },
            },
            "position": status.get("toolhead", {}).get("position"),
            "homed_axes": status.get("toolhead", {}).get("homed_axes"),
            "print": {
                "filename": status.get("print_stats", {}).get("filename"),
                "progress": status.get("virtual_sdcard", {}).get("progress"),
                "duration": status.get("print_stats", {}).get("print_duration"),
                "filament_used": status.get("print_stats", {}).get("filament_used"),
            },
            "speed": {
                "factor": status.get("gcode_move", {}).get("speed_factor"),
                "current": status.get("gcode_move", {}).get("speed"),
            },
            "fan_speed": status.get("fan", {}).get("speed"),
        }
        
        return json.dumps(formatted, indent=2)
    
    @mcp.tool()
    async def get_temperatures() -> str:
        """Get current temperatures for all heaters (bed, extruder(s)). Does not query chamber sensors."""
        client = get_client()
        
        objects = {
            "heater_bed": ["temperature", "target", "power"],
            "extruder": ["temperature", "target", "power"],
        }
        
        # Try to get additional heaters
        for i in range(1, config.TOOL_COUNT):
            objects[f"extruder{i}"] = ["temperature", "target", "power"]
        
        result = await client.query_printer_objects(objects)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        status = result.get("result", {}).get("status", {})
        temps = {}
        
        for heater, data in status.items():
            if data:  # Only include heaters that exist
                temp = data.get("temperature")
                target = data.get("target")
                power = data.get("power")
                temps[heater] = {
                    "current": round(temp, 1) if temp is not None else None,
                    "target": round(target, 1) if target is not None else None,
                    "power": round(power * 100, 1) if power is not None else None,
                }
        
        return json.dumps({"temperatures": temps})
    
    @mcp.tool()
    async def set_temperature(heater: str, target: float) -> str:
        """
        Set target temperature for a heater.
        
        Args:
            heater: Heater name - 'extruder', 'extruder1', 'heater_bed', etc.
            target: Target temperature in Celsius
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED. Set ARMED=true to enable temperature control."})

        if target < 0:
            return json.dumps({"error": f"Invalid temperature {target}. Must be >= 0°C"})

        client = get_client()

        # Prefer the heater's real configured max_temp (from Klipper's
        # configfile.settings) over a hardcoded ceiling that's really tuned
        # for hotends. A bed's real max_temp is usually far lower
        # (~120-130°C), and letting a bed target through a hotend-sized
        # ceiling only lets it fail later as a hard Klipper max_temp shutdown.
        max_temp = 350  # fallback ceiling, used if lookup fails or heater isn't found
        settings_result = await client.query_printer_objects({"configfile": ["settings"]})
        if "error" not in settings_result:
            heater_settings = (
                settings_result.get("result", {})
                .get("status", {})
                .get("configfile", {})
                .get("settings", {})
                .get(heater.lower(), {})
            )
            configured_max = heater_settings.get("max_temp")
            if isinstance(configured_max, (int, float)):
                max_temp = configured_max

        if target > max_temp:
            return json.dumps({"error": f"Invalid temperature {target}. Must be 0-{max_temp}°C for '{heater}'"})

        result = await client.set_heater_temperature(heater, target)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "heater": heater, "target": target})
    
    @mcp.tool()
    async def run_gcode(gcode: str) -> str:
        """
        Execute G-code command(s) on the printer.
        REQUIRES: System must be ARMED for safety.
        
        Args:
            gcode: G-code command(s) to execute. Multiple commands can be separated by newlines.
        
        Examples:
            - "G28" - Home all axes
            - "G1 X100 Y100 F3000" - Move to position
            - "M104 S200" - Set extruder temp
        """
        if not config.ARMED:
            return json.dumps({
                "error": "System not ARMED. Set ARMED=true environment variable to enable G-code execution.",
                "hint": "This is a safety feature to prevent accidental commands."
            })
        
        client = get_client()
        result = await client.run_gcode(gcode)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "executed": gcode})
    
    @mcp.tool()
    async def emergency_stop(pin: str) -> str:
        """
        EMERGENCY STOP - Immediately halt the printer.
        REQUIRES: Correct admin PIN for safety.
        
        Args:
            pin: Admin PIN to authorize emergency stop
        """
        if not verify_pin(pin, config.ADMIN_PIN):
            return json.dumps({"error": "Invalid PIN. Emergency stop not executed."})
        
        client = get_client()
        result = await client.emergency_stop()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "message": "EMERGENCY STOP executed!"})
    
    @mcp.tool()
    async def home_printer(axes: str = "XYZ") -> str:
        """
        Home printer axes.
        REQUIRES: System must be ARMED.
        
        Args:
            axes: Axes to home - 'X', 'Y', 'Z', 'XY', 'XYZ', etc. Default: 'XYZ'
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        axes = axes.upper()
        valid_axes = set("XYZ")
        if not all(a in valid_axes for a in axes):
            return json.dumps({"error": f"Invalid axes '{axes}'. Use X, Y, Z or combinations."})
        
        gcode = f"G28 {' '.join(axes)}"
        client = get_client()
        result = await client.run_gcode(gcode)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "homed": list(axes)})
    
    @mcp.tool()
    async def start_print(filename: str) -> str:
        """
        Start printing a G-code file.
        REQUIRES: System must be ARMED.
        
        Args:
            filename: Name of the G-code file to print
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.start_print(filename)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "printing": filename})
    
    @mcp.tool()
    async def pause_print() -> str:
        """Pause the current print job. REQUIRES: System must be ARMED."""
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})

        client = get_client()
        result = await client.pause_print()

        if "error" in result:
            return json.dumps({"error": result["error"]})

        return json.dumps({"success": True, "state": "paused"})

    @mcp.tool()
    async def resume_print() -> str:
        """Resume a paused print job. REQUIRES: System must be ARMED."""
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})

        client = get_client()
        result = await client.resume_print()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "state": "resumed"})
    
    @mcp.tool()
    async def cancel_print() -> str:
        """
        Cancel the current print job.
        REQUIRES: System must be ARMED.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.cancel_print()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "state": "cancelled"})
    
    @mcp.tool()
    async def restart_klipper() -> str:
        """
        Restart Klipper firmware.
        REQUIRES: System must be ARMED.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.restart_firmware()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "message": "Firmware restart initiated"})
    
    @mcp.tool()
    async def get_server_info() -> str:
        """Get Moonraker server information including version, plugins, and connection status."""
        client = get_client()
        result = await client.get_server_info()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps(result.get("result", {}), indent=2)
