"""
Camera and Timelapse Tools
Webcam snapshots, stream URLs, and timelapse control
"""
import json
import base64
from typing import Optional
import config
from moonraker import get_client


def register_camera_tools(mcp):
    """Register camera and timelapse tools."""
    
    @mcp.tool()
    async def capture_snapshot(webcam_name: Optional[str] = None) -> dict:
        """
        Capture a snapshot from the webcam.
        Returns the image as MCP image content (not a base64 text blob).

        Args:
            webcam_name: Optional name of a specific webcam to snapshot (see
                get_camera_stream_url for configured webcam names). If omitted,
                the default configured camera is used.
        """
        client = get_client()

        image_bytes = None

        if webcam_name:
            # Multi-camera setups: look up the specific webcam's snapshot URL
            # from Moonraker's webcam list and hit it directly, since the
            # client's default get_webcam_snapshot() only knows about the
            # single configured CAMERA_SNAPSHOT_URL.
            webcam_list = await client.get_webcam_list()
            snapshot_url = None
            for cam in webcam_list.get("result", {}).get("webcams", []):
                if cam.get("name") == webcam_name:
                    snapshot_url = cam.get("snapshot_url")
                    break

            if snapshot_url is None:
                return json.dumps({
                    "error": f"Webcam not found: {webcam_name}",
                    "hint": "Use get_camera_stream_url to list configured webcam names."
                })

            session = await client._get_session()
            try:
                async with session.get(snapshot_url) as response:
                    response.raise_for_status()
                    image_bytes = await response.read()
            except Exception as e:
                return json.dumps({"error": f"Failed to capture snapshot from '{webcam_name}': {str(e)}"})
        else:
            image_bytes = await client.get_webcam_snapshot()

        if image_bytes is None:
            return json.dumps({
                "error": "Failed to capture snapshot. Check camera configuration.",
                "camera_url": config.CAMERA_SNAPSHOT_URL
            })

        # Encode as base64 and hand back via the MCP image-content convention
        # instead of embedding the blob in a JSON/text response.
        b64_image = base64.b64encode(image_bytes).decode('utf-8')

        return {
            "__mcp_image__": True,
            "data": b64_image,
            "mime_type": "image/jpeg"
        }
    
    @mcp.tool()
    async def get_camera_stream_url() -> str:
        """
        Get the MJPEG stream URL for the webcam.
        Use this URL to view the live camera feed in a browser or application.
        """
        client = get_client()
        
        # Try to get webcam list from Moonraker
        result = await client.get_webcam_list()
        
        webcams = []
        if "result" in result:
            for cam in result.get("result", {}).get("webcams", []):
                webcams.append({
                    "name": cam.get("name"),
                    "stream_url": cam.get("stream_url"),
                    "snapshot_url": cam.get("snapshot_url"),
                })
        
        return json.dumps({
            "default_stream_url": config.CAMERA_STREAM_URL,
            "default_snapshot_url": config.CAMERA_SNAPSHOT_URL,
            "configured_webcams": webcams if webcams else "No webcams configured in Moonraker"
        }, indent=2)
    
    @mcp.tool()
    async def get_timelapse_settings() -> str:
        """
        Get current timelapse settings from moonraker-timelapse plugin.
        Requires moonraker-timelapse to be installed.
        """
        client = get_client()
        result = await client.get_timelapse_settings()
        
        if "error" in result:
            return json.dumps({
                "error": result["error"],
                "hint": "moonraker-timelapse plugin may not be installed"
            })
        
        settings = result.get("result", {})
        
        return json.dumps({
            "enabled": settings.get("enabled"),
            "mode": settings.get("mode"),
            "camera": settings.get("camera"),
            "gcode_verbose": settings.get("gcode_verbose"),
            "parkhead": settings.get("parkhead"),
            "parkpos": settings.get("parkpos"),
            "park_time": settings.get("park_time"),
            "park_retract_speed": settings.get("park_retract_speed"),
            "park_extrude_speed": settings.get("park_extrude_speed"),
            "park_retract_distance": settings.get("park_retract_distance"),
            "park_extrude_distance": settings.get("park_extrude_distance"),
            "hyperlapse_cycle": settings.get("hyperlapse_cycle"),
            "autorender": settings.get("autorender"),
            "constant_rate_factor": settings.get("constant_rate_factor"),
            "output_framerate": settings.get("output_framerate"),
            "pixelformat": settings.get("pixelformat"),
            "extraoutputparams": settings.get("extraoutputparams"),
            "variable_fps": settings.get("variable_fps"),
            "targetlength": settings.get("targetlength"),
            "variable_fps_min": settings.get("variable_fps_min"),
            "variable_fps_max": settings.get("variable_fps_max"),
        }, indent=2)
    
    @mcp.tool()
    async def set_timelapse_enabled(enabled: bool) -> str:
        """
        Enable or disable timelapse recording.
        
        Args:
            enabled: True to enable timelapse, False to disable
        """
        client = get_client()
        result = await client.set_timelapse_settings({"enabled": enabled})
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "timelapse_enabled": enabled
        })
    
    @mcp.tool()
    async def configure_timelapse(
        mode: Optional[str] = None,
        autorender: Optional[bool] = None,
        output_framerate: Optional[int] = None,
        parkhead: Optional[bool] = None
    ) -> str:
        """
        Configure timelapse settings.
        
        Args:
            mode: Capture mode - 'layermacro' or 'hyperlapse'
            autorender: Automatically render timelapse when print completes
            output_framerate: Output video framerate (default: 30)
            parkhead: Park head during captures for cleaner frames
        """
        settings = {}
        
        if mode is not None:
            if mode not in ['layermacro', 'hyperlapse']:
                return json.dumps({"error": "mode must be 'layermacro' or 'hyperlapse'"})
            settings["mode"] = mode
        
        if autorender is not None:
            settings["autorender"] = autorender
        
        if output_framerate is not None:
            settings["output_framerate"] = output_framerate
        
        if parkhead is not None:
            settings["parkhead"] = parkhead
        
        if not settings:
            return json.dumps({"error": "No settings provided to update"})
        
        client = get_client()
        result = await client.set_timelapse_settings(settings)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "updated_settings": settings
        })
    
    @mcp.tool()
    async def render_timelapse() -> str:
        """
        Manually trigger timelapse rendering.
        Renders the current captured frames into a video.
        """
        client = get_client()
        result = await client.render_timelapse()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "message": "Timelapse rendering started"
        })
    
    @mcp.tool()
    async def list_timelapses() -> str:
        """List all rendered timelapse videos."""
        client = get_client()
        result = await client.list_timelapses()
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        files = result.get("result", [])
        
        timelapses = []
        for f in files:
            filename = f.get("path") or f.get("filename", "")
            if filename.endswith(('.mp4', '.webm', '.mkv')):
                timelapses.append({
                    "filename": filename,
                    "size_mb": round(f.get("size", 0) / 1024 / 1024, 2),
                    "modified": f.get("modified"),
                })
        
        # Sort by modified date, newest first
        timelapses.sort(key=lambda x: x.get("modified", 0), reverse=True)
        
        return json.dumps({"timelapses": timelapses}, indent=2)
    
    @mcp.tool()
    async def take_timelapse_frame() -> str:
        """
        Manually capture a timelapse frame.
        Useful for custom timelapse control or testing.
        """
        client = get_client()
        result = await client.run_gcode("TIMELAPSE_TAKE_FRAME")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "message": "Timelapse frame captured"
        })
