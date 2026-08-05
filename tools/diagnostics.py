"""
Diagnostics Tools
Error log parsing, config validation, and troubleshooting
"""
import json
import re
from typing import Optional
import config
from moonraker import get_client


def register_diagnostics_tools(mcp):
    """Register diagnostics tools."""
    
    @mcp.tool()
    async def parse_klippy_log(lines: int = 200) -> str:
        """
        Parse klippy.log for errors, warnings, and important messages.
        
        Args:
            lines: Number of recent lines to analyze (default: 200)
        """
        client = get_client()
        session = await client._get_session()
        
        url = f"{client.base_url}/server/files/logs/klippy.log"
        
        try:
            async with session.get(url) as response:
                if response.status == 404:
                    return json.dumps({"error": "klippy.log not found"})
                response.raise_for_status()
                content = await response.text()
                
                # Get last N lines
                all_lines = content.split('\n')
                recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                
                errors = []
                warnings = []
                shutdowns = []
                tmc_errors = []
                mcu_issues = []

                # Track the real starting line number explicitly rather than
                # back-computing it from len(all_lines) - lines, which goes negative
                # when the file is shorter than the requested `lines` count.
                start_line = (len(all_lines) - lines + 1) if len(all_lines) > lines else 1

                for i, line in enumerate(recent_lines):
                    line_lower = line.lower()
                    line_number = start_line + i

                    # Checks are independent (not elif) so a line matching multiple
                    # categories (e.g. both "error" and "shutdown") is counted under
                    # every category it actually matches, not just the first.
                    if 'error' in line_lower or 'exception' in line_lower:
                        errors.append({"line": line_number, "text": line.strip()})

                    if 'warning' in line_lower or 'warn' in line_lower:
                        warnings.append({"line": line_number, "text": line.strip()})

                    if 'shutdown' in line_lower:
                        shutdowns.append({"line": line_number, "text": line.strip()})

                    if 'tmc' in line_lower and ('fault' in line_lower or 'error' in line_lower or 'overtemp' in line_lower):
                        tmc_errors.append({"line": line_number, "text": line.strip()})

                    if 'mcu' in line_lower and ('timeout' in line_lower or 'disconnect' in line_lower or 'lost' in line_lower):
                        mcu_issues.append({"line": line_number, "text": line.strip()})
                
                return json.dumps({
                    "analyzed_lines": len(recent_lines),
                    "summary": {
                        "errors": len(errors),
                        "warnings": len(warnings),
                        "shutdowns": len(shutdowns),
                        "tmc_errors": len(tmc_errors),
                        "mcu_issues": len(mcu_issues),
                    },
                    "errors": errors[-10:] if errors else [],  # Last 10
                    "warnings": warnings[-5:] if warnings else [],  # Last 5
                    "shutdowns": shutdowns[-3:] if shutdowns else [],  # Last 3
                    "tmc_errors": tmc_errors[-5:] if tmc_errors else [],
                    "mcu_issues": mcu_issues[-5:] if mcu_issues else [],
                }, indent=2)
                
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def get_recent_errors(count: int = 10) -> str:
        """
        Get the most recent errors from klippy.log with context.
        
        Args:
            count: Number of errors to return (default: 10)
        """
        client = get_client()
        session = await client._get_session()
        
        url = f"{client.base_url}/server/files/logs/klippy.log"
        
        try:
            async with session.get(url) as response:
                if response.status == 404:
                    return json.dumps({"error": "klippy.log not found"})
                response.raise_for_status()
                content = await response.text()
                
                lines = content.split('\n')
                
                errors_with_context = []
                
                for i, line in enumerate(lines):
                    if 'error' in line.lower() or 'exception' in line.lower():
                        # Get context: 2 lines before and 2 after
                        start = max(0, i - 2)
                        end = min(len(lines), i + 3)
                        context = lines[start:end]
                        
                        errors_with_context.append({
                            "line_number": i + 1,
                            "error": line.strip(),
                            "context": [l.strip() for l in context]
                        })
                
                # Return last N errors
                recent_errors = errors_with_context[-count:] if errors_with_context else []
                
                return json.dumps({
                    "total_errors_found": len(errors_with_context),
                    "showing": len(recent_errors),
                    "errors": recent_errors
                }, indent=2)
                
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def check_common_issues() -> str:
        """
        Check for common configuration issues and problems.
        Analyzes printer state and recent logs for known issues.
        """
        client = get_client()
        issues = []
        warnings = []
        
        # Check printer status
        status_result = await client.get_printer_status()
        if "error" in status_result:
            issues.append({
                "category": "connection",
                "severity": "critical",
                "message": "Cannot connect to Klipper",
                "suggestion": "Check if Klipper service is running"
            })
            return json.dumps({"issues": issues, "warnings": warnings})
        
        status = status_result.get("result", {}).get("status", {})
        
        # Check print state
        print_stats = status.get("print_stats", {})
        if print_stats.get("state") == "error":
            issues.append({
                "category": "print",
                "severity": "high",
                "message": f"Printer in error state: {print_stats.get('message', 'unknown')}",
                "suggestion": "Check klippy.log for details and restart Klipper"
            })
        
        # Check temperatures
        extruder = status.get("extruder", {})
        if extruder.get("temperature", 0) > 50 and extruder.get("target", 0) == 0:
            warnings.append({
                "category": "temperature",
                "message": "Extruder is hot but target is 0",
                "suggestion": "Extruder may still be cooling down from previous print"
            })
        
        bed = status.get("heater_bed", {})
        if bed.get("temperature", 0) > 50 and bed.get("target", 0) == 0:
            warnings.append({
                "category": "temperature",
                "message": "Bed is hot but target is 0",
                "suggestion": "Bed may still be cooling down"
            })
        
        # Check homing
        toolhead = status.get("toolhead", {})
        homed = toolhead.get("homed_axes", "")
        if homed != "xyz":
            warnings.append({
                "category": "homing",
                "message": f"Not all axes homed (current: {homed or 'none'})",
                "suggestion": "Run G28 to home all axes before printing"
            })
        
        # Check for idle timeout
        idle = status.get("idle_timeout", {})
        if idle.get("state") == "Printing" and print_stats.get("state") != "printing":
            warnings.append({
                "category": "state",
                "message": "Idle timeout thinks printer is printing but print_stats disagrees",
                "suggestion": "State may be out of sync - consider FIRMWARE_RESTART"
            })
        
        return json.dumps({
            "issues_found": len(issues),
            "warnings_found": len(warnings),
            "issues": issues,
            "warnings": warnings,
            "status": "healthy" if not issues else "needs_attention"
        }, indent=2)
    
    @mcp.tool()
    async def get_mcu_status() -> str:
        """
        Get MCU (microcontroller) status including timing and connection info.
        """
        client = get_client()
        
        result = await client.query_printer_objects({
            "mcu": ["mcu_version", "mcu_build_versions", "mcu_constants", "last_stats"],
            "toolhead": ["max_velocity", "max_accel", "square_corner_velocity"]
        })
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        status = result.get("result", {}).get("status", {})
        
        mcu = status.get("mcu", {})
        toolhead = status.get("toolhead", {})
        
        return json.dumps({
            "mcu": {
                "version": mcu.get("mcu_version"),
                "build_versions": mcu.get("mcu_build_versions"),
                "last_stats": mcu.get("last_stats"),
            },
            "motion": {
                "max_velocity": toolhead.get("max_velocity"),
                "max_accel": toolhead.get("max_accel"),
                "square_corner_velocity": toolhead.get("square_corner_velocity"),
            }
        }, indent=2)
    
    @mcp.tool()
    async def get_gcode_history(count: int = 50) -> str:
        """
        Get recent G-code commands and responses.
        
        Args:
            count: Number of recent commands to return (default: 50)
        """
        client = get_client()
        result = await client.get_gcode_store(count=count)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        gcode_store = result.get("result", {}).get("gcode_store", [])
        
        commands = []
        for entry in gcode_store[-count:]:
            commands.append({
                "message": entry.get("message"),
                "time": entry.get("time"),
                "type": entry.get("type"),
            })
        
        return json.dumps({
            "count": len(commands),
            "commands": commands
        }, indent=2)
    
    @mcp.tool()
    async def diagnose_problem(symptom: str) -> str:
        """
        Get troubleshooting suggestions based on a symptom description.
        
        Args:
            symptom: Description of the problem (e.g., 'layer shifts', 'nozzle clog', 'bed adhesion')
        """
        symptom_lower = symptom.lower()
        
        troubleshooting = {
            "layer shift": {
                "possible_causes": [
                    "Belts too loose",
                    "Stepper motor overheating (TMC overtemp)",
                    "Acceleration too high",
                    "Nozzle hitting print",
                    "Grub screws loose on pulleys"
                ],
                "suggestions": [
                    "Check belt tension",
                    "Check TMC driver temps (run parse_klippy_log)",
                    "Reduce max_accel in printer.cfg",
                    "Check for Z-hop in slicer",
                    "Tighten grub screws on motor pulleys"
                ],
                "gcode_commands": ["M569 (check TMC)", "SET_VELOCITY_LIMIT ACCEL=3000"]
            },
            "adhesion": {
                "possible_causes": [
                    "Bed not level",
                    "Z offset too high",
                    "Bed not clean",
                    "Bed temp too low",
                    "First layer speed too fast"
                ],
                "suggestions": [
                    "Run bed mesh calibration",
                    "Adjust Z offset (negative = closer)",
                    "Clean bed with IPA",
                    "Increase bed temp by 5-10°C",
                    "Reduce first layer speed to 20mm/s"
                ]
            },
            "clog": {
                "possible_causes": [
                    "Heat creep",
                    "Partial clog from debris",
                    "Wet filament",
                    "Gap between nozzle and heatbreak",
                    "Retraction too high"
                ],
                "suggestions": [
                    "Check hotend fan is working",
                    "Do cold pull to clear partial clog",
                    "Dry filament (4h at 50-60°C)",
                    "Re-seat nozzle hot-tightened",
                    "Reduce retraction distance"
                ]
            },
            "stringing": {
                "possible_causes": [
                    "Retraction too low",
                    "Temperature too high",
                    "Wet filament",
                    "Travel speed too slow"
                ],
                "suggestions": [
                    "Increase retraction distance/speed",
                    "Lower hotend temp by 5-10°C",
                    "Dry filament",
                    "Increase travel speed"
                ]
            },
            "underextrusion": {
                "possible_causes": [
                    "Partial clog",
                    "Extruder tension too low",
                    "Incorrect e-steps",
                    "Filament grinding",
                    "PTFE tube gap"
                ],
                "suggestions": [
                    "Check for clog (cold pull)",
                    "Increase extruder gear tension",
                    "Calibrate e-steps",
                    "Check extruder gear for worn teeth",
                    "Check PTFE tube seating"
                ]
            }
        }
        
        # Find matching symptom
        matched = None
        for key in troubleshooting:
            if key in symptom_lower:
                matched = troubleshooting[key]
                matched["symptom"] = key
                break
        
        if matched:
            return json.dumps(matched, indent=2)
        else:
            return json.dumps({
                "message": f"No specific troubleshooting found for '{symptom}'",
                "available_topics": list(troubleshooting.keys()),
                "suggestion": "Try describing the symptom differently or check klippy.log for errors"
            }, indent=2)

    @mcp.tool()
    async def get_log_files() -> str:
        """
        List all log files with their sizes and ages.
        Fetched via Moonraker's file API (root=logs) on the printer's host machine -
        the printer's logs live there, not on the local filesystem of this MCP server.
        """
        from datetime import datetime

        client = get_client()
        result = await client.list_files(root="logs")

        if "error" in result:
            return json.dumps({"error": result["error"]})

        files = result.get("result", [])

        log_files = []
        total_size = 0

        for entry in files:
            size = entry.get("size", 0)
            total_size += size
            modified_ts = entry.get("modified")
            mtime = datetime.fromtimestamp(modified_ts) if modified_ts else None

            log_files.append({
                "name": entry.get("path"),
                "size_bytes": size,
                "size_mb": round(size / (1024 * 1024), 2),
                "modified": mtime.strftime("%Y-%m-%d %H:%M:%S") if mtime else None,
                "age_days": (datetime.now() - mtime).days if mtime else None
            })

        log_files.sort(key=lambda f: f["name"] or "")

        return json.dumps({
            "logs_root": "logs (via Moonraker /server/files/list)",
            "total_files": len(log_files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "files": log_files
        }, indent=2)

    @mcp.tool()
    async def clear_old_logs(days_to_keep: int = 7, dry_run: bool = True) -> str:
        """
        Clear log files older than specified days, via Moonraker's file API.

        Args:
            days_to_keep: Keep logs from the last N days (default: 7)
            dry_run: If True, only show what would be deleted without actually deleting (default: True)
        """
        from datetime import datetime, timedelta

        client = get_client()
        result = await client.list_files(root="logs")

        if "error" in result:
            return json.dumps({"error": result["error"]})

        files = result.get("result", [])
        cutoff = datetime.now() - timedelta(days=days_to_keep)

        to_delete = []
        kept = []
        total_freed = 0

        # Protected files that should never be deleted (current active logs)
        protected = ["klippy.log", "moonraker.log", "crowsnest.log",
                     "KlipperScreen.log", "octoeverywhere.log"]

        for entry in files:
            filename = entry.get("path", "")
            size = entry.get("size", 0)
            size_mb = size / (1024 * 1024)
            modified_ts = entry.get("modified")
            mtime = datetime.fromtimestamp(modified_ts) if modified_ts else datetime.now()

            # Keep protected (current) log files
            if filename in protected:
                kept.append({"name": filename, "reason": "active log", "size_mb": round(size_mb, 2)})
                continue

            # Check if older than cutoff
            if mtime < cutoff:
                entry_result = {
                    "name": filename,
                    "size_mb": round(size_mb, 2),
                    "modified": mtime.strftime("%Y-%m-%d %H:%M:%S")
                }
                to_delete.append(entry_result)
                total_freed += size

                if not dry_run:
                    del_result = await client.delete_file(f"logs/{filename}")
                    if "error" in del_result:
                        entry_result["error"] = del_result["error"]
            else:
                kept.append({"name": filename, "reason": "within retention", "size_mb": round(size_mb, 2)})

        return json.dumps({
            "dry_run": dry_run,
            "days_to_keep": days_to_keep,
            "cutoff_date": cutoff.strftime("%Y-%m-%d"),
            "files_to_delete": len(to_delete),
            "space_freed_mb": round(total_freed / (1024 * 1024), 2),
            "deleted": to_delete,
            "kept": kept,
            "message": "Dry run - no files deleted. Set dry_run=false to delete." if dry_run else f"Deleted {len(to_delete)} files"
        }, indent=2)

    @mcp.tool()
    async def truncate_log(log_name: str = "klippy") -> str:
        """
        Rotate a log file via Moonraker's safe log rollover API
        (POST /server/logs/rollover) instead of destructively truncating it in place.
        A local truncate races with Klipper's/Moonraker's own open file handle - writes
        after the truncate land past the new EOF, producing a NUL-padded corrupted file.
        Rollover instead renames/archives the current log and starts a fresh one.

        Args:
            log_name: Log to rotate - 'klippy' or 'moonraker' (default: klippy).
                Only these two applications support rollover via Moonraker.
        """
        app_map = {
            "klippy": "klipper",
            "klipper": "klipper",
            "moonraker": "moonraker",
        }

        application = app_map.get(log_name.lower())
        if not application:
            return json.dumps({
                "error": f"Unknown log: {log_name}",
                "available_logs": ["klippy", "moonraker"],
                "note": "Moonraker's rollover API only supports 'klipper' and 'moonraker' logs."
            })

        client = get_client()
        result = await client.rollover_logs(application)

        if "error" in result:
            return json.dumps({"error": result["error"]})

        payload = result.get("result", {})
        rolled_over = payload.get("rolled_over", [])
        failed = payload.get("failed", {})

        return json.dumps({
            "status": "success" if application in rolled_over else "failed",
            "application": application,
            "rolled_over": rolled_over,
            "failed": failed,
            "message": f"{application} log rolled over via Moonraker. The prior log was archived and a fresh log file is now in use."
        }, indent=2)

    @mcp.tool()
    async def get_log_summary() -> str:
        """
        Get a summary of recent log activity - errors, warnings, and events.
        Scans the trailing portion of klippy.log and moonraker.log via Moonraker's file
        API. This is a "last N lines" scan, not a real time window - klippy.log/
        moonraker.log lines don't carry a machine-parseable timestamp this tool filters
        on, so the reported period describes lines scanned rather than elapsed time.
        """
        from datetime import datetime

        client = get_client()
        session = await client._get_session()

        summary = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "period": "last 5000 lines of klippy.log / last 2000 lines of moonraker.log",
            "klippy": {"errors": 0, "warnings": 0, "shutdowns": 0},
            "moonraker": {"errors": 0, "warnings": 0, "requests": 0},
            "recent_events": []
        }

        # Parse klippy.log via Moonraker's file content API
        try:
            klippy_url = f"{client.base_url}/server/files/logs/klippy.log"
            async with session.get(klippy_url) as response:
                if response.status == 200:
                    content = await response.text()
                    lines = content.split('\n')[-5000:]

                    for line in lines:
                        line_lower = line.lower()
                        # Independent checks (not elif) so a line matching multiple
                        # categories is counted under every category it matches.
                        if 'error' in line_lower:
                            summary["klippy"]["errors"] += 1
                        if 'warning' in line_lower or 'warn' in line_lower:
                            summary["klippy"]["warnings"] += 1
                        if 'shutdown' in line_lower:
                            summary["klippy"]["shutdowns"] += 1
                            summary["recent_events"].append({
                                "source": "klippy",
                                "type": "shutdown",
                                "message": line.strip()[:200]
                            })
                elif response.status != 404:
                    summary["klippy"]["error"] = f"HTTP {response.status}"
        except Exception as e:
            summary["klippy"]["error"] = str(e)

        # Parse moonraker.log via Moonraker's file content API
        try:
            moonraker_url = f"{client.base_url}/server/files/logs/moonraker.log"
            async with session.get(moonraker_url) as response:
                if response.status == 200:
                    content = await response.text()
                    lines = content.split('\n')[-2000:]

                    for line in lines:
                        line_lower = line.lower()
                        if 'error' in line_lower:
                            summary["moonraker"]["errors"] += 1
                        if 'warning' in line_lower:
                            summary["moonraker"]["warnings"] += 1
                        if 'request' in line_lower:
                            summary["moonraker"]["requests"] += 1
                elif response.status != 404:
                    summary["moonraker"]["error"] = f"HTTP {response.status}"
        except Exception as e:
            summary["moonraker"]["error"] = str(e)

        return json.dumps(summary, indent=2)
