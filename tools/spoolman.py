"""
Spoolman Integration Tools
Filament spool tracking and management
"""
import json
import asyncio
from typing import Optional
import aiohttp
import config


def register_spoolman_tools(mcp):
    """Register Spoolman tools."""

    # Lazily-created, reused session (mirrors MoonrakerClient._get_session) so
    # we don't pay a fresh TCP/TLS handshake on every Spoolman call.
    _session_holder = {"session": None}
    _session_lock = asyncio.Lock()

    async def _get_spoolman_session() -> aiohttp.ClientSession:
        async with _session_lock:
            session = _session_holder["session"]
            if session is None or session.closed:
                session = aiohttp.ClientSession()
                _session_holder["session"] = session
            return session

    async def close_spoolman_session():
        """Close the shared Spoolman session, if open."""
        session = _session_holder["session"]
        if session and not session.closed:
            await session.close()

    async def spoolman_request(method: str, endpoint: str, json_data: dict = None):
        """Make request to Spoolman API."""
        if not config.SPOOLMAN_ENABLED:
            return {"error": "Spoolman not enabled. Set SPOOLMAN_ENABLED=true"}

        url = f"{config.SPOOLMAN_URL}/api/v1{endpoint}"

        try:
            session = await _get_spoolman_session()
            async with session.request(method, url, json=json_data) as response:
                if response.status == 404:
                    return {"error": f"Spoolman endpoint not found: {endpoint}"}
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            return {"error": f"Spoolman connection error: {str(e)}"}
    
    @mcp.tool()
    async def list_spools(filament_type: Optional[str] = None) -> str:
        """
        List all filament spools in Spoolman.
        
        Args:
            filament_type: Optional filter by type (e.g., 'PLA', 'ABS', 'PETG')
        """
        result = await spoolman_request("GET", "/spool")
        
        if "error" in result:
            return json.dumps(result)
        
        spools = result if isinstance(result, list) else []
        
        # Filter by type if specified
        if filament_type:
            filament_type_lower = filament_type.lower()
            spools = [s for s in spools if s.get("filament", {}).get("material", "").lower() == filament_type_lower]
        
        formatted = []
        for spool in spools:
            filament = spool.get("filament", {})
            formatted.append({
                "id": spool.get("id"),
                "name": filament.get("name"),
                "material": filament.get("material"),
                "color": filament.get("color_hex"),
                "vendor": filament.get("vendor", {}).get("name"),
                "remaining_weight_g": spool.get("remaining_weight"),
                "used_weight_g": spool.get("used_weight"),
                "first_used": spool.get("first_used"),
                "last_used": spool.get("last_used"),
            })
        
        return json.dumps({
            "count": len(formatted),
            "spools": formatted
        }, indent=2)
    
    @mcp.tool()
    async def get_spool_details(spool_id: int) -> str:
        """
        Get detailed information about a specific spool.
        
        Args:
            spool_id: The spool ID from Spoolman
        """
        result = await spoolman_request("GET", f"/spool/{spool_id}")
        
        if "error" in result:
            return json.dumps(result)
        
        spool = result
        filament = spool.get("filament", {})
        
        return json.dumps({
            "id": spool.get("id"),
            "filament": {
                "name": filament.get("name"),
                "material": filament.get("material"),
                "color": filament.get("color_hex"),
                "diameter_mm": filament.get("diameter"),
                "density_g_cm3": filament.get("density"),
                "settings": {
                    "print_temp": filament.get("settings", {}).get("print_temp"),
                    "bed_temp": filament.get("settings", {}).get("bed_temp"),
                }
            },
            "vendor": spool.get("filament", {}).get("vendor", {}).get("name"),
            "weight": {
                "initial_g": spool.get("initial_weight"),
                "remaining_g": spool.get("remaining_weight"),
                "used_g": spool.get("used_weight"),
                "remaining_percent": round(
                    spool.get("remaining_weight", 0) / spool.get("initial_weight", 1) * 100, 1
                ) if spool.get("initial_weight") else None
            },
            "price": spool.get("price"),
            "location": spool.get("location"),
            "lot_nr": spool.get("lot_nr"),
            "comment": spool.get("comment"),
            "first_used": spool.get("first_used"),
            "last_used": spool.get("last_used"),
        }, indent=2)
    
    @mcp.tool()
    async def get_active_spool() -> str:
        """Get the currently active spool (if set via Moonraker-Spoolman integration)."""
        from moonraker import get_client

        client = get_client()

        # Spoolman is a Moonraker *component*, not a Klipper printer object, so
        # query it via the dedicated endpoint rather than query_printer_objects.
        result = await client.get_spool_id()

        if "error" in result:
            # Spoolman component may not be configured in Moonraker
            return json.dumps({
                "message": "Spoolman integration not configured in Moonraker",
                "hint": "Add [spoolman] section to moonraker.conf"
            })

        spool_id = result.get("result", {}).get("spool_id")

        if not spool_id:
            return json.dumps({"active_spool": None, "message": "No spool currently active"})

        # Fetch full spool details from Spoolman itself now that we have the ID
        spool = await spoolman_request("GET", f"/spool/{spool_id}")

        if "error" in spool:
            return json.dumps({"spool_id": spool_id, "error": spool["error"]})

        filament = spool.get("filament", {})

        return json.dumps({
            "spool_id": spool_id,
            "filament_name": filament.get("name"),
            "material": filament.get("material"),
            "color": filament.get("color_hex"),
            "remaining_weight_g": spool.get("remaining_weight"),
            "used_weight_g": spool.get("used_weight"),
        }, indent=2)
    
    @mcp.tool()
    async def set_active_spool(spool_id: int) -> str:
        """
        Set the active spool for tracking filament usage.
        
        Args:
            spool_id: The spool ID to set as active
        """
        from moonraker import get_client
        
        client = get_client()
        result = await client.run_gcode(f"SET_ACTIVE_SPOOL ID={spool_id}")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "active_spool_id": spool_id
        })
    
    @mcp.tool()
    async def clear_active_spool() -> str:
        """Clear the currently active spool."""
        from moonraker import get_client
        
        client = get_client()
        result = await client.run_gcode("CLEAR_ACTIVE_SPOOL")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "message": "Active spool cleared"
        })
    
    @mcp.tool()
    async def get_filament_vendors() -> str:
        """List all filament vendors in Spoolman."""
        result = await spoolman_request("GET", "/vendor")
        
        if "error" in result:
            return json.dumps(result)
        
        vendors = result if isinstance(result, list) else []
        
        formatted = []
        for vendor in vendors:
            formatted.append({
                "id": vendor.get("id"),
                "name": vendor.get("name"),
                "comment": vendor.get("comment"),
            })
        
        return json.dumps({
            "count": len(formatted),
            "vendors": formatted
        }, indent=2)
    
    @mcp.tool()
    async def get_low_filament_spools(threshold_grams: int = 100) -> str:
        """
        Get spools that are running low on filament.
        
        Args:
            threshold_grams: Warn if remaining weight is below this (default: 100g)
        """
        result = await spoolman_request("GET", "/spool")
        
        if "error" in result:
            return json.dumps(result)
        
        spools = result if isinstance(result, list) else []
        
        low_spools = []
        for spool in spools:
            remaining = spool.get("remaining_weight", 0)
            if remaining < threshold_grams and remaining > 0:  # Exclude empty/archived
                filament = spool.get("filament", {})
                low_spools.append({
                    "id": spool.get("id"),
                    "name": filament.get("name"),
                    "material": filament.get("material"),
                    "color": filament.get("color_hex"),
                    "remaining_g": remaining,
                    "location": spool.get("location"),
                })
        
        # Sort by remaining weight
        low_spools.sort(key=lambda x: x.get("remaining_g", 0))
        
        return json.dumps({
            "threshold_grams": threshold_grams,
            "low_spools_count": len(low_spools),
            "spools": low_spools
        }, indent=2)
    
    @mcp.tool()
    async def get_filament_usage_by_material() -> str:
        """Get total filament usage grouped by material type."""
        result = await spoolman_request("GET", "/spool")
        
        if "error" in result:
            return json.dumps(result)
        
        spools = result if isinstance(result, list) else []
        
        usage_by_material = {}
        
        for spool in spools:
            filament = spool.get("filament", {})
            material = filament.get("material", "Unknown")
            used = spool.get("used_weight", 0) or 0
            
            if material not in usage_by_material:
                usage_by_material[material] = {
                    "total_used_g": 0,
                    "spool_count": 0
                }
            
            usage_by_material[material]["total_used_g"] += used
            usage_by_material[material]["spool_count"] += 1
        
        # Format and sort by usage
        formatted = []
        for material, data in usage_by_material.items():
            formatted.append({
                "material": material,
                "total_used_g": round(data["total_used_g"], 1),
                "total_used_kg": round(data["total_used_g"] / 1000, 2),
                "spool_count": data["spool_count"]
            })
        
        formatted.sort(key=lambda x: x["total_used_g"], reverse=True)
        
        return json.dumps({
            "usage_by_material": formatted
        }, indent=2)
