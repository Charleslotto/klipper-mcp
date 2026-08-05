"""
Backup and Maintenance Tools
Configuration backup, restore, and maintenance tracking
"""
import json
import os
from datetime import datetime
from typing import Optional
import config
from moonraker import get_client
from tools.security import verify_pin
from tools.filesystem import upload_to_moonraker


def register_backup_tools(mcp):
    """Register backup and maintenance tools."""
    
    def load_maintenance_log() -> dict:
        """Load maintenance log from JSON file."""
        if os.path.exists(config.MAINTENANCE_LOG_PATH):
            try:
                with open(config.MAINTENANCE_LOG_PATH, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            "printer": config.PRINTER_NAME,
            "created": datetime.now().isoformat(),
            "maintenance_records": [],
            "component_hours": {}
        }
    
    def save_maintenance_log(data: dict):
        """Save maintenance log to JSON file."""
        os.makedirs(os.path.dirname(config.MAINTENANCE_LOG_PATH), exist_ok=True)
        with open(config.MAINTENANCE_LOG_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    
    @mcp.tool()
    async def backup_config(backup_name: Optional[str] = None) -> str:
        """
        Create a backup of all Klipper configuration files.
        
        Args:
            backup_name: Optional name for the backup (default: timestamp)
        """
        client = get_client()
        
        # List config files
        result = await client.list_files("config")
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        files = result.get("result", [])
        
        # Create backup directory name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = backup_name or f"backup_{timestamp}"

        backed_up_files = []
        failed_files = []

        # Copy each config file to backup
        session = await client._get_session()

        for file_info in files:
            filename = file_info.get("path", file_info.get("filename", ""))
            if filename.endswith(('.cfg', '.conf')):
                # Read file content
                url = f"{client.base_url}/server/files/config/{filename}"
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            content = await response.text()

                            # Save to backup location (os.makedirs handles nested
                            # paths like "Toolheads/T0.cfg" so subdirectories
                            # under config are preserved, not silently dropped)
                            backup_path = os.path.join(config.BACKUP_PATH, backup_name, filename)
                            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                            with open(backup_path, 'w') as f:
                                f.write(content)

                            backed_up_files.append(filename)
                        else:
                            failed_files.append({
                                "filename": filename,
                                "error": f"HTTP {response.status} fetching file"
                            })
                except Exception as e:
                    failed_files.append({"filename": filename, "error": str(e)})

        return json.dumps({
            "success": len(failed_files) == 0,
            "backup_name": backup_name,
            "backup_path": os.path.join(config.BACKUP_PATH, backup_name),
            "files_backed_up": backed_up_files,
            "file_count": len(backed_up_files),
            "failed_files": failed_files if failed_files else None,
            "failed_count": len(failed_files)
        }, indent=2)
    
    @mcp.tool()
    async def list_backups() -> str:
        """List all available configuration backups."""
        if not os.path.exists(config.BACKUP_PATH):
            return json.dumps({"backups": [], "message": "No backups found"})
        
        backups = []
        for item in os.listdir(config.BACKUP_PATH):
            item_path = os.path.join(config.BACKUP_PATH, item)
            if os.path.isdir(item_path):
                files = [f for f in os.listdir(item_path) if f.endswith(('.cfg', '.conf'))]
                stat = os.stat(item_path)
                backups.append({
                    "name": item,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "file_count": len(files),
                    "files": files
                })
        
        # Sort by creation time, newest first
        backups.sort(key=lambda x: x["created"], reverse=True)
        
        return json.dumps({
            "backup_count": len(backups),
            "backups": backups
        }, indent=2)
    
    @mcp.tool()
    async def restore_config(backup_name: str, admin_pin: str) -> str:
        """
        Restore configuration from a backup.
        REQUIRES: Admin PIN for destructive operations.
        
        Args:
            backup_name: Name of the backup to restore
            admin_pin: Admin PIN for authorization
        """
        if not verify_pin(admin_pin, config.ADMIN_PIN):
            return json.dumps({"error": "Invalid admin PIN"})

        backup_path = os.path.join(config.BACKUP_PATH, backup_name)

        if not os.path.exists(backup_path):
            return json.dumps({"error": f"Backup '{backup_name}' not found"})

        client = get_client()

        restored_files = []
        errors = []

        # Walk recursively so nested config files (e.g. "Toolheads/T0.cfg")
        # backed up by backup_config are actually restored, not silently
        # skipped the way a top-level os.listdir() would skip them.
        for dirpath, _dirnames, filenames in os.walk(backup_path):
            rel_dir = os.path.relpath(dirpath, backup_path)
            for filename in filenames:
                if not filename.endswith(('.cfg', '.conf')):
                    continue
                relative_path = filename if rel_dir == "." else os.path.join(rel_dir, filename)
                # Normalize to forward slashes for Moonraker's path field
                relative_path = relative_path.replace(os.sep, "/")
                file_path = os.path.join(dirpath, filename)
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()

                    # Upload via Moonraker, preserving the original subdirectory
                    # (same root+path fix as tools/filesystem.py's write_file).
                    result = await upload_to_moonraker(client, "config", relative_path, content)

                    if "error" in result:
                        errors.append({"file": relative_path, "error": result["error"]})
                    else:
                        restored_files.append(relative_path)
                except Exception as e:
                    errors.append({"file": relative_path, "error": str(e)})

        return json.dumps({
            "success": len(errors) == 0,
            "backup_restored": backup_name,
            "files_restored": restored_files,
            "errors": errors if errors else None,
            "note": "Run FIRMWARE_RESTART to apply changes"
        }, indent=2)
    
    @mcp.tool()
    async def log_maintenance(
        component: str,
        action: str,
        notes: Optional[str] = None
    ) -> str:
        """
        Log a maintenance action.
        
        Args:
            component: Component name (e.g., 'nozzle', 'belts', 'filters', 'lubrication')
            action: Action performed (e.g., 'replaced', 'cleaned', 'tensioned', 'lubricated')
            notes: Optional additional notes
        """
        log = load_maintenance_log()
        
        # Get current print hours
        client = get_client()
        totals = await client.get_print_totals()
        total_hours = totals.get("result", {}).get("job_totals", {}).get("total_print_time", 0) / 3600
        
        record = {
            "timestamp": datetime.now().isoformat(),
            "component": component,
            "action": action,
            "notes": notes,
            "print_hours_at_maintenance": round(total_hours, 1)
        }
        
        log["maintenance_records"].append(record)
        
        # Update component hours
        log["component_hours"][component] = round(total_hours, 1)
        
        save_maintenance_log(log)
        
        return json.dumps({
            "success": True,
            "recorded": record
        }, indent=2)
    
    @mcp.tool()
    async def get_maintenance_history(component: Optional[str] = None) -> str:
        """
        Get maintenance history.
        
        Args:
            component: Optional filter by component name
        """
        log = load_maintenance_log()
        records = log.get("maintenance_records", [])
        
        if component:
            records = [r for r in records if r.get("component") == component]
        
        # Sort by timestamp, newest first
        records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return json.dumps({
            "printer": log.get("printer"),
            "total_records": len(records),
            "records": records[:50]  # Last 50
        }, indent=2)
    
    @mcp.tool()
    async def check_maintenance_due() -> str:
        """
        Check which components are due for maintenance based on print hours.
        Uses configured intervals from config.MAINTENANCE_INTERVALS.
        """
        log = load_maintenance_log()
        
        # Get current print hours
        client = get_client()
        totals = await client.get_print_totals()
        current_hours = totals.get("result", {}).get("job_totals", {}).get("total_print_time", 0) / 3600
        
        due_maintenance = []
        upcoming_maintenance = []
        
        for component, interval in config.MAINTENANCE_INTERVALS.items():
            last_maintenance_hours = log.get("component_hours", {}).get(component, 0)
            hours_since = current_hours - last_maintenance_hours
            hours_until = interval - hours_since
            
            status = {
                "component": component,
                "interval_hours": interval,
                "last_maintained_at_hours": round(last_maintenance_hours, 1),
                "current_hours": round(current_hours, 1),
                "hours_since_maintenance": round(hours_since, 1),
                "hours_until_due": round(hours_until, 1)
            }
            
            if hours_until <= 0:
                status["status"] = "OVERDUE"
                due_maintenance.append(status)
            elif hours_until <= interval * 0.1:  # Within 10% of interval
                status["status"] = "DUE_SOON"
                upcoming_maintenance.append(status)
        
        return json.dumps({
            "current_print_hours": round(current_hours, 1),
            "overdue_count": len(due_maintenance),
            "due_soon_count": len(upcoming_maintenance),
            "overdue": due_maintenance,
            "due_soon": upcoming_maintenance,
            "configured_intervals": config.MAINTENANCE_INTERVALS
        }, indent=2)
    
    @mcp.tool()
    async def get_audit_log(lines: int = 100) -> str:
        """
        Get recent entries from the MCP audit log.
        Shows commands executed through MCP for security review.
        
        Args:
            lines: Number of recent entries to return
        """
        if not os.path.exists(config.AUDIT_LOG_PATH):
            return json.dumps({"entries": [], "message": "No audit log found"})
        
        try:
            with open(config.AUDIT_LOG_PATH, 'r') as f:
                all_lines = f.readlines()
        except Exception as e:
            return json.dumps({"error": str(e)})
        
        entries = []
        for line in all_lines[-lines:]:
            try:
                entry = json.loads(line.strip())
                entries.append(entry)
            except:
                entries.append({"raw": line.strip()})
        
        return json.dumps({
            "total_entries": len(all_lines),
            "showing": len(entries),
            "entries": entries
        }, indent=2)
    
    @mcp.tool()
    async def export_printer_data() -> str:
        """
        Export comprehensive printer data for analysis or backup.
        Includes print history, maintenance log, and current state.
        """
        client = get_client()
        
        # Gather data
        status = await client.get_printer_status()
        totals = await client.get_print_totals()
        history = await client.get_print_history(limit=100)
        
        maintenance_log = load_maintenance_log()
        
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "printer_name": config.PRINTER_NAME,
            "current_status": status.get("result", {}).get("status", {}),
            "print_totals": totals.get("result", {}).get("job_totals", {}),
            "recent_history": history.get("result", {}).get("jobs", []),
            "maintenance_log": maintenance_log,
        }
        
        # Save export
        export_path = os.path.join(
            config.BACKUP_PATH, 
            f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        
        with open(export_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        return json.dumps({
            "success": True,
            "export_path": export_path,
            "data_included": [
                "current_status",
                "print_totals",
                "recent_history (100 jobs)",
                "maintenance_log"
            ]
        }, indent=2)
