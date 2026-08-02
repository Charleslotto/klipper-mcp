"""
StealthChanger Toolchanger Tools
Tool selection, calibration, crash detection, offset management
"""
import json
import config
from moonraker import get_client


def register_toolchanger_tools(mcp):
    """Register StealthChanger toolchanger tools."""
    
    @mcp.tool()
    async def select_tool(tool_number: int) -> str:
        """
        Select/activate a tool (T0, T1, T2, etc).
        REQUIRES: System must be ARMED.
        
        Args:
            tool_number: Tool number to select (0, 1, 2, 3, etc.)
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED. Tool changes require ARMED=true."})
        
        if tool_number < 0 or tool_number >= config.TOOL_COUNT:
            return json.dumps({"error": f"Invalid tool {tool_number}. Valid: 0-{config.TOOL_COUNT-1}"})
        
        client = get_client()
        result = await client.run_gcode(f"T{tool_number}")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        tool_name = config.TOOL_NAMES.get(tool_number, f"T{tool_number}")
        return json.dumps({"success": True, "active_tool": tool_number, "name": tool_name})
    
    @mcp.tool()
    async def get_active_tool() -> str:
        """Get the currently active tool on the StealthChanger."""
        client = get_client()
        
        # Query toolchanger status
        result = await client.query_printer_objects({
            "toolchanger": ["tool_current", "tool_numbers"],
            "tool_probe": ["last_query"]
        })
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        status = result.get("result", {}).get("status", {})
        toolchanger = status.get("toolchanger", {})
        
        current = toolchanger.get("tool_current", -1)
        if current == -1:
            return json.dumps({"active_tool": None, "message": "No tool currently loaded"})
        
        return json.dumps({
            "active_tool": current,
            "name": config.TOOL_NAMES.get(current, f"T{current}"),
            "available_tools": toolchanger.get("tool_numbers", list(range(config.TOOL_COUNT)))
        })
    
    @mcp.tool()
    async def initialize_toolchanger() -> str:
        """
        Initialize the toolchanger system.
        Run this after startup or if tool detection is inconsistent.
        REQUIRES: System must be ARMED.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.run_gcode("INITIALIZE_TOOLCHANGER")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "message": "Toolchanger initialized"})
    
    @mcp.tool()
    async def get_tool_offsets() -> str:
        """Get configured offsets for all tools (gcode_x/y/z_offset and tool_probe offsets)."""
        client = get_client()
        
        # Query all tool objects
        objects = {}
        for i in range(config.TOOL_COUNT):
            tool_name = f"tool T{i}"
            objects[tool_name] = ["gcode_x_offset", "gcode_y_offset", "gcode_z_offset"]
            objects[f"tool_probe T{i}"] = ["x_offset", "y_offset", "z_offset"]
        
        result = await client.query_printer_objects(objects)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        status = result.get("result", {}).get("status", {})
        
        offsets = {}
        for i in range(config.TOOL_COUNT):
            tool_key = f"tool T{i}"
            probe_key = f"tool_probe T{i}"
            
            tool_data = status.get(tool_key, {})
            probe_data = status.get(probe_key, {})
            
            offsets[f"T{i}"] = {
                "gcode_offset": {
                    "x": tool_data.get("gcode_x_offset", 0),
                    "y": tool_data.get("gcode_y_offset", 0),
                    "z": tool_data.get("gcode_z_offset", 0),
                },
                "probe_offset": {
                    "x": probe_data.get("x_offset", 0),
                    "y": probe_data.get("y_offset", 0),
                    "z": probe_data.get("z_offset", 0),
                }
            }
        
        return json.dumps(offsets, indent=2)
    
    @mcp.tool()
    async def tool_align_start(tool_number: int) -> str:
        """
        Start tool alignment procedure - positions toolhead 100mm from dock.
        REQUIRES: System must be ARMED.
        
        Args:
            tool_number: Tool to align (0, 1, 2, etc.)
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        if tool_number < 0 or tool_number >= config.TOOL_COUNT:
            return json.dumps({"error": f"Invalid tool {tool_number}"})
        
        client = get_client()
        result = await client.run_gcode(f"Tool_Align_Start T={tool_number}")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "message": f"Tool {tool_number} alignment started. Toolhead positioned near dock.",
            "next_step": "Use 'tool_align_test' to test docking/undocking procedure"
        })
    
    @mcp.tool()
    async def tool_align_test() -> str:
        """
        Test the docking/undocking procedure for current tool alignment.
        Run after 'tool_align_start'.
        REQUIRES: System must be ARMED.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.run_gcode("Tool_Align_Test")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "message": "Docking/undocking test executed. Observe the movement and adjust dock position if needed.",
            "next_step": "Run 'tool_align_done' when satisfied or 'tool_align_test' to retry"
        })
    
    @mcp.tool()
    async def tool_align_done() -> str:
        """
        Complete tool alignment and move toolhead away from dock.
        REQUIRES: System must be ARMED.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.run_gcode("Tool_Align_Done")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "message": "Tool alignment complete. Toolhead moved away from dock."})
    
    @mcp.tool()
    async def start_crash_detection() -> str:
        """
        Enable tool crash detection during printing.
        Monitors for unexpected tool detachment.
        REQUIRES: System must be ARMED.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.run_gcode("START_TOOL_CRASH_DETECTION")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "crash_detection": "enabled"})
    
    @mcp.tool()
    async def stop_crash_detection() -> str:
        """
        Disable tool crash detection.
        REQUIRES: System must be ARMED.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})

        client = get_client()
        result = await client.run_gcode("STOP_TOOL_CRASH_DETECTION")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "crash_detection": "disabled"})
    
    @mcp.tool()
    async def dropoff_tool() -> str:
        """
        Drop off the currently loaded tool to its dock.
        REQUIRES: System must be ARMED.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.run_gcode("TOOL_DROPOFF")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "message": "Tool dropped off at dock"})
    
    @mcp.tool()
    async def pickup_tool(tool_number: int) -> str:
        """
        Pick up a specific tool from its dock.
        REQUIRES: System must be ARMED.
        
        Args:
            tool_number: Tool to pick up (0, 1, 2, etc.)
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        if tool_number < 0 or tool_number >= config.TOOL_COUNT:
            return json.dumps({"error": f"Invalid tool {tool_number}"})
        
        client = get_client()
        result = await client.run_gcode(f"TOOL_PICKUP T={tool_number}")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "picked_up": tool_number})
    
    @mcp.tool()
    async def set_tool_temperature(tool_number: int, target: float) -> str:
        """
        Set temperature for a specific tool's extruder.
        REQUIRES: System must be ARMED.
        
        Args:
            tool_number: Tool number (0, 1, 2, etc.)
            target: Target temperature in Celsius
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        if tool_number < 0 or tool_number >= config.TOOL_COUNT:
            return json.dumps({"error": f"Invalid tool {tool_number}"})
        
        if target < 0 or target > 350:
            return json.dumps({"error": f"Invalid temperature {target}"})
        
        client = get_client()
        # M104's T parameter targets an extruder index, which this toolchanger's
        # config defines 1:1 with tool_number (tool 0 -> extruder, tool 1 ->
        # extruder1, etc.), matching the extruder{N} naming used elsewhere
        # (see tools/printer.py get_temperatures).
        result = await client.run_gcode(f"M104 T{tool_number} S{target}")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "tool": tool_number, "target": target})
    
    @mcp.tool()
    async def get_dock_positions() -> str:
        """Get configured dock positions for all tools."""
        # Note: This reads from config - actual implementation would parse printer.cfg
        # For now, return a message about checking config
        
        return json.dumps({
            "message": "Dock positions are configured in your tool config files (T0.cfg, T1.cfg, etc.)",
            "key_parameters": [
                "params_park_x - X position of dock",
                "params_park_y - Y position of dock", 
                "params_park_z - Z position for docking",
                "params_close_y - Y position to approach dock",
                "params_safe_y - Safe Y position when tool is loaded"
            ],
            "hint": "Use 'read_file' tool to read your tool config files for exact values"
        })
    
    @mcp.tool()
    async def quad_gantry_level() -> str:
        """
        Run Quad Gantry Level (QGL) procedure.
        REQUIRES: System must be ARMED and homed.
        """
        if not config.ARMED:
            return json.dumps({"error": "System not ARMED."})
        
        client = get_client()
        result = await client.run_gcode("QUAD_GANTRY_LEVEL")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "message": "Quad Gantry Level complete"})
