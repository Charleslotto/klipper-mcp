"""
System Management Tools
Software updates, service control, system monitoring

NOTE: This MCP server runs on the user's local machine, but Klipper/Moonraker run on a
separate remote host (config.MOONRAKER_URL). Every tool in this module that reports on
or controls "the system" must describe/act on that remote host via Moonraker's
/machine/* API - never via local psutil/subprocess/os calls, which would instead
report on or control the machine running this MCP server.
"""
import json
from typing import Optional
import config
from moonraker import get_client


def register_system_tools(mcp):
    """Register system management tools."""

    @mcp.tool()
    async def get_system_info() -> str:
        """
        Get information about the machine that Klipper/Moonraker actually run on -
        CPU, memory, uptime, and distribution info - via Moonraker's
        /machine/system_info and /machine/proc_stats endpoints. This is the
        printer's host machine, not the local machine running this MCP server.
        """
        client = get_client()

        sys_result = await client.get_machine_system_info()
        if "error" in sys_result:
            return json.dumps({"error": sys_result["error"]})

        system_info = sys_result.get("result", {}).get("system_info", {})
        cpu_info = system_info.get("cpu_info", {})
        distribution = system_info.get("distribution", {})

        # Hostname isn't part of system_info; fetch it from printer.info instead.
        hostname = None
        printer_info = await client.get_printer_info()
        if "error" not in printer_info:
            hostname = printer_info.get("result", {}).get("hostname")

        info = {
            "hostname": hostname,
            "distribution": distribution.get("name"),
            "codename": distribution.get("codename"),
            "architecture": cpu_info.get("processor"),
            "cpu_model": cpu_info.get("model") or cpu_info.get("cpu_desc"),
            "cpu_count": cpu_info.get("cpu_count"),
        }

        proc_result = await client.get_machine_proc_stats()
        if "error" not in proc_result:
            proc = proc_result.get("result", {})

            system_memory = proc.get("system_memory") or {}
            total_kb = system_memory.get("total")
            available_kb = system_memory.get("available")
            used_kb = system_memory.get("used")
            if total_kb:
                info["memory"] = {
                    "total_mb": round(total_kb / 1024, 1),
                    "available_mb": round(available_kb / 1024, 1) if available_kb is not None else None,
                    "used_mb": round(used_kb / 1024, 1) if used_kb is not None else None,
                    "percent_used": round(used_kb / total_kb * 100, 1) if used_kb is not None and total_kb else None,
                }

            system_cpu_usage = proc.get("system_cpu_usage") or {}
            if "cpu" in system_cpu_usage:
                info["cpu_usage_percent"] = system_cpu_usage.get("cpu")

            uptime_seconds = proc.get("system_uptime")
            if uptime_seconds:
                uptime_seconds = int(uptime_seconds)
                days = uptime_seconds // 86400
                hours = (uptime_seconds % 86400) // 3600
                minutes = (uptime_seconds % 3600) // 60
                info["uptime"] = {
                    "seconds": uptime_seconds,
                    "formatted": f"{days}d {hours}h {minutes}m"
                }

            cpu_temp = proc.get("cpu_temp")
            if cpu_temp is not None:
                info["cpu_temp_c"] = round(cpu_temp, 1)

            throttled_state = proc.get("throttled_state")
            if throttled_state and throttled_state.get("flags"):
                info["throttled_state"] = throttled_state

        info["note"] = (
            "Disk usage and load average have no equivalent in Moonraker's /machine API "
            "and are omitted rather than fabricated. This reflects the printer's host "
            "machine, not the local machine running klipper-mcp."
        )

        return json.dumps(info, indent=2)

    @mcp.tool()
    async def get_network_info() -> str:
        """
        Get network information for the machine Klipper/Moonraker run on - IP addresses
        and bandwidth per interface - via Moonraker's /machine/system_info and
        /machine/proc_stats endpoints, not local network introspection.
        """
        client = get_client()

        sys_result = await client.get_machine_system_info()
        if "error" in sys_result:
            return json.dumps({"error": sys_result["error"]})

        system_info = sys_result.get("result", {}).get("system_info", {})
        network = system_info.get("network", {})

        interfaces = {}
        for name, iface in network.items():
            addrs = [a.get("address") for a in iface.get("ip_addresses", [])]
            interfaces[name] = {
                "mac_address": iface.get("mac_address"),
                "ip_addresses": addrs,
            }

        proc_result = await client.get_machine_proc_stats()
        if "error" not in proc_result:
            proc_network = proc_result.get("result", {}).get("network", {})
            for name, stats in proc_network.items():
                entry = interfaces.setdefault(name, {})
                entry["rx_bytes"] = stats.get("rx_bytes")
                entry["tx_bytes"] = stats.get("tx_bytes")
                entry["bandwidth_bytes_per_sec"] = stats.get("bandwidth")

        info = {
            "interfaces": interfaces,
            "note": "WiFi signal strength has no equivalent in Moonraker's /machine API and is omitted.",
        }

        return json.dumps(info, indent=2)

    @mcp.tool()
    async def check_updates() -> str:
        """
        Check for available software updates for Klipper, Moonraker, and system.
        Uses Moonraker's update manager API.
        """
        client = get_client()
        session = await client._get_session()
        
        try:
            # Get update status from Moonraker
            url = f"{client.base_url}/machine/update/status"
            async with session.get(url, params={"refresh": "false"}) as response:
                if response.status != 200:
                    return json.dumps({"error": f"Failed to get update status: {response.status}"})
                
                data = await response.json()
                result = data.get("result", {})
                
                updates = {
                    "busy": result.get("busy", False),
                    "components": {}
                }
                
                version_info = result.get("version_info", {})
                for component, info in version_info.items():
                    comp_data = {
                        "version": info.get("version", "unknown"),
                        "remote_version": info.get("remote_version", "unknown"),
                        "is_valid": info.get("is_valid", False),
                        "is_dirty": info.get("is_dirty", False),
                    }
                    
                    # Check if update available
                    current = info.get("version", "")
                    remote = info.get("remote_version", "")
                    if current and remote and current != remote:
                        comp_data["update_available"] = True
                    else:
                        comp_data["update_available"] = False
                    
                    # Add commit info if available
                    if "commits_behind" in info:
                        comp_data["commits_behind"] = info["commits_behind"]
                    
                    updates["components"][component] = comp_data
                
                # Summary
                updates_available = [k for k, v in updates["components"].items() if v.get("update_available")]
                updates["summary"] = {
                    "updates_available": len(updates_available),
                    "components_with_updates": updates_available
                }
                
                return json.dumps(updates, indent=2)
                
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def update_component(component: str) -> str:
        """
        Update a specific software component (klipper, moonraker, etc.) via Moonraker's
        current update manager API (POST /machine/update/upgrade). The old per-component
        endpoints (/machine/update/full, /client, /system, /klipper, /moonraker) are
        deprecated and are no longer used here.

        Args:
            component: Component to update - e.g. 'klipper', 'moonraker', 'mainsail',
                'fluidd', 'system', or 'all'. Valid names are discovered dynamically from
                Moonraker's update status.
        """
        client = get_client()

        # Discover valid component names dynamically from Moonraker's update status
        # (its version_info keys), instead of a hardcoded list that can drift out of sync
        # with what's actually configured.
        status_result = await client.get("/machine/update/status", params={"refresh": "false"})
        if "error" not in status_result:
            valid_components = list(status_result.get("result", {}).get("version_info", {}).keys())
        else:
            valid_components = ['klipper', 'moonraker', 'mainsail', 'fluidd', 'klipperscreen', 'system']

        if component.lower() == 'all':
            # Omitting "name" upgrades all registered software.
            result = await client.post("/machine/update/upgrade")
            if "error" in result:
                return json.dumps({"error": f"Failed to start full update: {result['error']}"})
            return json.dumps({
                "status": "started",
                "message": "Full system update started. This may take several minutes.",
                "note": "Services will restart automatically. Monitor via Moonraker logs."
            }, indent=2)

        if valid_components and component.lower() not in [c.lower() for c in valid_components]:
            return json.dumps({
                "error": f"Unknown component: {component}",
                "valid_components": valid_components + ['all']
            })

        result = await client.update_upgrade(component.lower())
        if "error" in result:
            return json.dumps({"error": f"Failed to update {component}: {result['error']}"})

        return json.dumps({
            "status": "started",
            "component": component,
            "message": f"Update for {component} started. Check Moonraker logs for progress.",
            "note": "Service may restart automatically."
        }, indent=2)

    @mcp.tool()
    async def refresh_update_status() -> str:
        """
        Refresh the update status by checking remote repositories.
        Uses Moonraker's POST /machine/update/refresh, which (unlike the deprecated
        GET /machine/update/status?refresh=true) doesn't silently no-op while still
        reporting success when an update/print is in progress or a refresh happened
        within the last 60 seconds.
        """
        client = get_client()
        result = await client.update_refresh(name=None)

        if "error" in result:
            return json.dumps({"error": f"Failed to refresh: {result['error']}"})

        return json.dumps({
            "status": "refreshed",
            "message": "Update status refreshed. Use check_updates to see results."
        }, indent=2)

    @mcp.tool()
    async def get_service_status(service: str = "all") -> str:
        """
        Get the status of printer-related services on the machine Moonraker runs on.
        Uses Moonraker's /machine/system_info (service_state), not local systemctl -
        there's no dedicated services-list endpoint, but system_info reports
        active_state/sub_state for every service Moonraker monitors.

        Args:
            service: Service name or 'all' for all services (default: all)
        """
        client = get_client()
        result = await client.get_machine_system_info()

        if "error" in result:
            return json.dumps({"error": result["error"]})

        system_info = result.get("result", {}).get("system_info", {})
        service_state = system_info.get("service_state", {})
        available_services = system_info.get("available_services", [])

        if service.lower() != "all":
            matches = {s: v for s, v in service_state.items() if s.lower() == service.lower()}
            if not matches:
                return json.dumps({
                    "error": f"Service '{service}' not found",
                    "available_services": available_services
                })
            service_state = matches

        results = {}
        for svc, state in service_state.items():
            results[svc] = {
                "active_state": state.get("active_state", "unknown"),
                "sub_state": state.get("sub_state", "unknown"),
            }

        return json.dumps(results, indent=2)

    @mcp.tool()
    async def restart_service(service: str) -> str:
        """
        Restart a printer-related service via Moonraker's machine API
        (POST /machine/services/restart) rather than local `sudo systemctl`, since the
        service actually runs on the printer's host machine, not the local machine
        running this MCP server.

        Args:
            service: Service to restart - 'klipper', 'moonraker', 'KlipperScreen', 'crowsnest'
        """
        allowed_services = ['klipper', 'moonraker', 'KlipperScreen', 'crowsnest', 'klipper-mcp']

        if service not in allowed_services:
            return json.dumps({
                "error": f"Service '{service}' not allowed",
                "allowed_services": allowed_services
            })

        client = get_client()
        result = await client.machine_service_action(service, "restart")

        if "error" in result:
            return json.dumps({
                "error": f"Failed to restart {service}",
                "details": result["error"]
            })

        return json.dumps({
            "status": "restarted",
            "service": service,
            "message": f"{service} restart requested via Moonraker"
        }, indent=2)

    @mcp.tool()
    async def reboot_system() -> str:
        """
        Reboot the machine Klipper/Moonraker run on, via Moonraker's /machine/reboot
        endpoint. This happens immediately - Moonraker's reboot endpoint takes no delay
        parameter, so no delay is offered here.
        """
        if not config.ARMED:
            return json.dumps({
                "error": "System reboot requires ARMED=True in config",
                "armed": False
            })

        client = get_client()
        result = await client.reboot_system()

        if "error" in result:
            return json.dumps({"error": result["error"]})

        return json.dumps({
            "status": "rebooting",
            "message": "Reboot requested immediately via Moonraker (no delay is supported).",
            "warning": "All services will be unavailable until the machine comes back up"
        }, indent=2)

    @mcp.tool()
    async def shutdown_system() -> str:
        """
        Shutdown the machine Klipper/Moonraker run on, via Moonraker's /machine/shutdown
        endpoint. This happens immediately - Moonraker's shutdown endpoint takes no delay
        parameter, so no delay is offered here.
        """
        if not config.ARMED:
            return json.dumps({
                "error": "System shutdown requires ARMED=True in config",
                "armed": False
            })

        client = get_client()
        result = await client.shutdown_system()

        if "error" in result:
            return json.dumps({"error": result["error"]})

        return json.dumps({
            "status": "shutting down",
            "message": "Shutdown requested immediately via Moonraker (no delay is supported).",
            "warning": "You will need physical access to power on again"
        }, indent=2)

    @mcp.tool()
    async def get_moonraker_config() -> str:
        """
        Get the current Moonraker configuration including enabled components.
        """
        client = get_client()
        session = await client._get_session()
        
        try:
            url = f"{client.base_url}/server/info"
            async with session.get(url) as response:
                if response.status != 200:
                    return json.dumps({"error": f"Failed to get server info: {response.status}"})
                
                data = await response.json()
                result = data.get("result", {})
                
                return json.dumps({
                    "klippy_connected": result.get("klippy_connected"),
                    "klippy_state": result.get("klippy_state"),
                    "components": result.get("components", []),
                    "failed_components": result.get("failed_components", []),
                    "registered_directories": result.get("registered_directories", []),
                    "warnings": result.get("warnings", []),
                    "moonraker_version": result.get("moonraker_version"),
                    "api_version": result.get("api_version"),
                    "api_version_string": result.get("api_version_string")
                }, indent=2)
                
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_printer_objects() -> str:
        """
        List all available printer objects that can be queried.
        Useful for discovering what data is available from Klipper.
        """
        client = get_client()
        session = await client._get_session()
        
        try:
            url = f"{client.base_url}/printer/objects/list"
            async with session.get(url) as response:
                if response.status != 200:
                    return json.dumps({"error": f"Failed to get objects: {response.status}"})
                
                data = await response.json()
                objects = data.get("result", {}).get("objects", [])
                
                # Categorize objects
                categories = {
                    "heaters": [],
                    "fans": [],
                    "steppers": [],
                    "sensors": [],
                    "leds": [],
                    "tools": [],
                    "system": [],
                    "other": []
                }
                
                for obj in sorted(objects):
                    obj_lower = obj.lower()
                    if 'heater' in obj_lower or 'extruder' in obj_lower:
                        categories["heaters"].append(obj)
                    elif 'fan' in obj_lower:
                        categories["fans"].append(obj)
                    elif 'stepper' in obj_lower or 'tmc' in obj_lower:
                        categories["steppers"].append(obj)
                    elif 'sensor' in obj_lower or 'probe' in obj_lower:
                        categories["sensors"].append(obj)
                    elif 'led' in obj_lower or 'neopixel' in obj_lower:
                        categories["leds"].append(obj)
                    elif obj.startswith('tool') or obj.startswith('T'):
                        categories["tools"].append(obj)
                    elif obj in ['mcu', 'webhooks', 'print_stats', 'toolhead', 'gcode_move', 'motion_report']:
                        categories["system"].append(obj)
                    else:
                        categories["other"].append(obj)
                
                return json.dumps({
                    "total_objects": len(objects),
                    "categories": categories
                }, indent=2)
                
        except Exception as e:
            return json.dumps({"error": str(e)})
