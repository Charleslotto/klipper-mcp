"""
Temperature and Bed Mesh Tools
Temperature history, anomaly detection, and bed mesh management
"""
import json
from typing import Optional, List
import config
from moonraker import get_client
from tools.security import sanitize_gcode_param


def register_temperature_tools(mcp):
    """Register temperature and bed mesh tools."""
    
    @mcp.tool()
    async def get_temperature_history() -> str:
        """
        Get temperature history for all heaters.
        Returns recent temperature samples useful for graphing or analysis.
        """
        client = get_client()
        result = await client.get_temperature_store()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        data = result.get("result", {})
        
        # Format temperature data
        formatted = {}
        for heater, values in data.items():
            if isinstance(values, dict) and "temperatures" in values:
                temps = values.get("temperatures", [])
                targets = values.get("targets", [])
                
                formatted[heater] = {
                    "current": temps[-1] if temps else None,
                    "target": targets[-1] if targets else None,
                    "min": round(min(temps), 1) if temps else None,
                    "max": round(max(temps), 1) if temps else None,
                    "samples": len(temps),
                    "recent_temps": temps[-20:] if temps else [],  # Last 20 samples
                }
        
        return json.dumps(formatted, indent=2)
    
    @mcp.tool()
    async def detect_temperature_anomalies() -> str:
        """
        Analyze temperature data for anomalies.
        Checks for thermal runaway conditions, heating failures, or unusual patterns.
        """
        client = get_client()
        
        # Get current status and temperature history
        status_result = await client.get_printer_status()
        temp_result = await client.get_temperature_store()
        
        if "error" in status_result:
            return json.dumps({"error": status_result["error"]})
        
        status = status_result.get("result", {}).get("status", {})
        temp_store = temp_result.get("result", {})
        
        anomalies = []
        
        # Check extruder
        extruder = status.get("extruder", {})
        extruder_temp = extruder.get("temperature", 0)
        extruder_target = extruder.get("target", 0)
        
        if extruder_target > 0:
            # Check if heating
            if extruder_temp < extruder_target - 50:
                # Check temperature history for heating progress
                extruder_history = temp_store.get("extruder", {}).get("temperatures", [])
                if len(extruder_history) > 10:
                    recent = extruder_history[-10:]
                    if max(recent) - min(recent) < 2:  # Not increasing
                        anomalies.append({
                            "heater": "extruder",
                            "type": "heating_failure",
                            "severity": "high",
                            "message": f"Extruder not heating - stuck at {extruder_temp}°C, target {extruder_target}°C",
                            "suggestion": "Check heater cartridge and thermistor connections"
                        })
            
            # Check for overshoot
            if extruder_temp > extruder_target + 15:
                anomalies.append({
                    "heater": "extruder",
                    "type": "overshoot",
                    "severity": "medium",
                    "message": f"Extruder overshooting - {extruder_temp}°C vs target {extruder_target}°C",
                    "suggestion": "PID tuning may be needed"
                })
        
        # Check bed
        bed = status.get("heater_bed", {})
        bed_temp = bed.get("temperature", 0)
        bed_target = bed.get("target", 0)
        
        if bed_target > 0:
            if bed_temp < bed_target - 30:
                bed_history = temp_store.get("heater_bed", {}).get("temperatures", [])
                if len(bed_history) > 20:
                    recent = bed_history[-20:]
                    if max(recent) - min(recent) < 2:
                        anomalies.append({
                            "heater": "heater_bed",
                            "type": "heating_failure",
                            "severity": "high",
                            "message": f"Bed not heating - stuck at {bed_temp}°C, target {bed_target}°C",
                            "suggestion": "Check bed heater and thermistor"
                        })
        
        # Check for unusually high temperatures with no target
        if extruder_temp > 50 and extruder_target == 0:
            anomalies.append({
                "heater": "extruder",
                "type": "unexpected_heat",
                "severity": "low",
                "message": f"Extruder at {extruder_temp}°C with no target set",
                "suggestion": "May be residual heat from previous print"
            })
        
        return json.dumps({
            "anomalies_found": len(anomalies),
            "anomalies": anomalies,
            "current_state": {
                "extruder": {"temp": extruder_temp, "target": extruder_target},
                "bed": {"temp": bed_temp, "target": bed_target}
            }
        }, indent=2)
    
    @mcp.tool()
    async def get_bed_mesh() -> str:
        """
        Get current bed mesh data.
        Returns the probed matrix and mesh parameters.
        """
        client = get_client()
        result = await client.get_bed_mesh()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        status = result.get("result", {}).get("status", {})
        mesh = status.get("bed_mesh", {})
        
        if not mesh:
            return json.dumps({
                "error": "No bed mesh data available",
                "suggestion": "Run BED_MESH_CALIBRATE to create a mesh"
            })
        
        probed_matrix = mesh.get("probed_matrix", [])
        
        # Calculate mesh statistics
        if probed_matrix:
            flat = [val for row in probed_matrix for val in row]
            mesh_stats = {
                "min": round(min(flat), 4),
                "max": round(max(flat), 4),
                "range": round(max(flat) - min(flat), 4),
                "average": round(sum(flat) / len(flat), 4),
            }
        else:
            mesh_stats = None
        
        return json.dumps({
            "profile_name": mesh.get("profile_name"),
            "mesh_min": mesh.get("mesh_min"),
            "mesh_max": mesh.get("mesh_max"),
            "probed_matrix": probed_matrix,
            "statistics": mesh_stats,
        }, indent=2)
    
    @mcp.tool()
    async def get_bed_mesh_profiles() -> str:
        """List all saved bed mesh profiles."""
        client = get_client()
        result = await client.get_bed_mesh()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        status = result.get("result", {}).get("status", {})
        mesh = status.get("bed_mesh", {})
        
        profiles = mesh.get("profiles", {})
        current = mesh.get("profile_name", "")
        
        profile_list = []
        for name, data in profiles.items():
            profile_list.append({
                "name": name,
                "active": name == current,
                "mesh_params": data.get("mesh_params", {}) if isinstance(data, dict) else {}
            })
        
        return json.dumps({
            "current_profile": current,
            "profiles": profile_list,
            "count": len(profile_list)
        }, indent=2)
    
    @mcp.tool()
    async def load_bed_mesh_profile(profile_name: str) -> str:
        """
        Load a saved bed mesh profile.
        REQUIRES: System must be ARMED.

        Args:
            profile_name: Name of the profile to load
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})

        try:
            profile_name = sanitize_gcode_param(profile_name, "profile_name")
        except ValueError as e:
            return json.dumps({"error": str(e)})

        client = get_client()
        result = await client.load_bed_mesh(profile_name)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "loaded_profile": profile_name
        })
    
    @mcp.tool()
    async def calibrate_bed_mesh() -> str:
        """
        Run bed mesh calibration.
        REQUIRES: System must be ARMED and printer homed.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.run_gcode("BED_MESH_CALIBRATE")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "message": "Bed mesh calibration started. This may take a few minutes."
        })
    
    @mcp.tool()
    async def save_bed_mesh_profile(profile_name: str) -> str:
        """
        Save current bed mesh to a named profile.
        REQUIRES: System must be ARMED. Refuses to run SAVE_CONFIG while a
        print is active or paused, since SAVE_CONFIG rewrites printer.cfg and
        triggers a full Klipper restart (which would abort the print and
        commit any other pending config changes with no way to undo).

        Args:
            profile_name: Name for the saved profile
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})

        try:
            profile_name = sanitize_gcode_param(profile_name, "profile_name")
        except ValueError as e:
            return json.dumps({"error": str(e)})

        client = get_client()
        result = await client.run_gcode(f"BED_MESH_PROFILE SAVE={profile_name}")

        if "error" in result:
            return json.dumps({"error": result["error"]})

        # SAVE_CONFIG restarts Klipper, which would abort an in-progress print.
        # Refuse to run it if a print is currently printing or paused.
        status_result = await client.query_printer_objects({"print_stats": ["state"]})
        if "error" in status_result:
            return json.dumps({
                "error": f"Bed mesh profile saved, but could not verify print state before "
                         f"SAVE_CONFIG: {status_result['error']}. Config was NOT saved.",
                "saved_profile": profile_name,
                "config_saved": False,
            })

        print_state = status_result.get("result", {}).get("status", {}).get("print_stats", {}).get("state")
        if print_state in ("printing", "paused"):
            return json.dumps({
                "error": f"Refusing to run SAVE_CONFIG while a print is {print_state}. "
                         "SAVE_CONFIG triggers a full Klipper restart and would abort the print. "
                         "Wait until the print finishes, then save the config separately.",
                "saved_profile": profile_name,
                "config_saved": False,
            })

        save_config_result = await client.run_gcode("SAVE_CONFIG")
        if "error" in save_config_result:
            return json.dumps({
                "error": f"Bed mesh profile saved, but SAVE_CONFIG failed: {save_config_result['error']}",
                "saved_profile": profile_name,
                "config_saved": False,
            })

        return json.dumps({
            "success": True,
            "saved_profile": profile_name,
            "config_saved": True,
            "message": "Profile saved and config updated"
        })
    
    @mcp.tool()
    async def clear_bed_mesh() -> str:
        """Clear the currently loaded bed mesh. REQUIRES: System must be ARMED."""
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})

        client = get_client()
        result = await client.run_gcode("BED_MESH_CLEAR")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "message": "Bed mesh cleared"
        })
    
    @mcp.tool()
    async def get_heater_pid_params(heater: str = "extruder") -> str:
        """
        Get current PID parameters for a heater.
        
        Args:
            heater: Heater name - 'extruder' or 'heater_bed'
        """
        client = get_client()

        # Confirm the heater actually exists before trusting all-null fields as
        # "PID params really are zero" vs. "heater not found / no PID data".
        objects_result = await client.get('/printer/objects/list')
        if "error" in objects_result:
            return json.dumps({"error": objects_result["error"]})
        all_objects = objects_result.get('result', {}).get('objects', [])
        if heater not in all_objects:
            return json.dumps({
                "error": f"Heater '{heater}' not found on printer.",
                "available_heaters": [o for o in all_objects if o.startswith("extruder") or o.startswith("heater_")],
            })

        result = await client.query_printer_objects({
            heater: ["control", "pid_kp", "pid_ki", "pid_kd"]
        })

        if "error" in result:
            return json.dumps({"error": result["error"]})

        status = result.get("result", {}).get("status", {})
        heater_data = status.get(heater, {})
        
        return json.dumps({
            "heater": heater,
            "control": heater_data.get("control"),
            "pid_kp": heater_data.get("pid_kp"),
            "pid_ki": heater_data.get("pid_ki"),
            "pid_kd": heater_data.get("pid_kd"),
        }, indent=2)
