"""
LED Effects Tools
Control klipper-led_effect animations and pre-defined scenes
"""
import json
import os
from typing import Optional
import config
from moonraker import get_client
from tools.security import sanitize_gcode_param


# Pre-defined LED scenes for common printer states
DEFAULT_SCENES = {
    "idle": {
        "description": "Calm breathing effect when printer is idle",
        "effects": [
            {"effect": "panel_idle", "action": "start"}
        ]
    },
    "heating": {
        "description": "Orange/red pulsing while heating",
        "effects": [
            {"effect": "heating", "action": "start", "replace": True}
        ]
    },
    "printing": {
        "description": "Steady illumination during printing",
        "effects": [
            {"effect": "printing", "action": "start", "replace": True}
        ]
    },
    "tool_change": {
        "description": "Flash effect during tool changes",
        "effects": [
            {"effect": "tool_change", "action": "start"}
        ]
    },
    "complete": {
        "description": "Green celebration when print completes",
        "effects": [
            {"effect": "print_complete", "action": "start", "replace": True}
        ]
    },
    "error": {
        "description": "Red flashing on error",
        "effects": [
            {"effect": "critical_error", "action": "start", "replace": True}
        ]
    },
    "off": {
        "description": "Turn off all LED effects",
        "effects": []
    }
}


def load_scenes() -> dict:
    """Load LED scenes from config file or return defaults."""
    try:
        if os.path.exists(config.LED_SCENES_FILE):
            with open(config.LED_SCENES_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return DEFAULT_SCENES


def register_led_tools(mcp):
    """Register LED effects tools."""
    
    @mcp.tool()
    async def set_led_effect(
        effect: str,
        fadetime: float = 0.0,
        replace: bool = False,
        restart: bool = False
    ) -> str:
        """
        Start an LED effect.
        
        Args:
            effect: Name of the LED effect to start (as defined in printer.cfg)
            fadetime: Time in seconds to fade in the effect (default: 0)
            replace: If True, stop other effects on the same LEDs (default: False)
            restart: If True, restart effect from beginning (default: False)
        
        Examples:
            - set_led_effect("panel_idle")
            - set_led_effect("heating", fadetime=1.0, replace=True)
        """
        if not config.ARMED:
            return json.dumps({
                "error": "System not ARMED. Set ARMED=true environment variable to enable G-code execution.",
                "hint": "This is a safety feature to prevent accidental commands."
            })

        try:
            effect = sanitize_gcode_param(effect, "effect")
        except ValueError as e:
            return json.dumps({"error": str(e)})

        client = get_client()

        cmd = f"SET_LED_EFFECT EFFECT={effect}"
        if fadetime > 0:
            cmd += f" FADETIME={fadetime}"
        if replace:
            cmd += " REPLACE=1"
        if restart:
            cmd += " RESTART=1"
        
        result = await client.run_gcode(cmd)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "effect": effect,
            "fadetime": fadetime,
            "replace": replace,
            "restart": restart
        })
    
    @mcp.tool()
    async def stop_led_effect(effect: str, fadetime: float = 0.0) -> str:
        """
        Stop a specific LED effect.
        
        Args:
            effect: Name of the LED effect to stop
            fadetime: Time in seconds to fade out (default: 0)
        """
        if not config.ARMED:
            return json.dumps({
                "error": "System not ARMED. Set ARMED=true environment variable to enable G-code execution.",
                "hint": "This is a safety feature to prevent accidental commands."
            })

        try:
            effect = sanitize_gcode_param(effect, "effect")
        except ValueError as e:
            return json.dumps({"error": str(e)})

        client = get_client()

        cmd = f"SET_LED_EFFECT EFFECT={effect} STOP=1"
        if fadetime > 0:
            cmd += f" FADETIME={fadetime}"
        
        result = await client.run_gcode(cmd)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({"success": True, "stopped": effect, "fadetime": fadetime})
    
    @mcp.tool()
    async def stop_all_led_effects(
        leds: Optional[str] = None,
        fadetime: float = 0.0
    ) -> str:
        """
        Stop all LED effects, optionally filtered by LED chain.
        
        Args:
            leds: Optional LED chain to stop (e.g., "neopixel:panel_ring"). If None, stops all.
            fadetime: Time in seconds to fade out (default: 0)
        """
        if not config.ARMED:
            return json.dumps({
                "error": "System not ARMED. Set ARMED=true environment variable to enable G-code execution.",
                "hint": "This is a safety feature to prevent accidental commands."
            })

        try:
            leds = sanitize_gcode_param(leds, "leds")
        except ValueError as e:
            return json.dumps({"error": str(e)})

        client = get_client()

        cmd = "STOP_LED_EFFECTS"
        if leds:
            cmd += f' LEDS="{leds}"'
        if fadetime > 0:
            cmd += f" FADETIME={fadetime}"
        
        result = await client.run_gcode(cmd)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "stopped": leds if leds else "all",
            "fadetime": fadetime
        })
    
    @mcp.tool()
    async def set_led_scene(scene: str) -> str:
        """
        Activate a pre-defined LED scene.
        
        Args:
            scene: Scene name - 'idle', 'heating', 'printing', 'tool_change', 
                   'complete', 'error', or 'off'
        
        Scenes are pre-configured LED combinations for common printer states.
        """
        scenes = load_scenes()
        
        if scene not in scenes:
            return json.dumps({
                "error": f"Unknown scene '{scene}'",
                "available_scenes": list(scenes.keys())
            })
        
        scene_config = scenes[scene]
        client = get_client()
        
        # First stop all effects if scene is 'off' or has replace
        if scene == "off":
            await client.run_gcode("STOP_LED_EFFECTS FADETIME=0.5")
            return json.dumps({"success": True, "scene": "off", "message": "All effects stopped"})
        
        # Apply each effect in the scene
        results = []
        for effect_cmd in scene_config.get("effects", []):
            effect_name = effect_cmd.get("effect")
            action = effect_cmd.get("action", "start")
            
            if action == "start":
                cmd = f"SET_LED_EFFECT EFFECT={effect_name}"
                if effect_cmd.get("replace"):
                    cmd += " REPLACE=1"
                if effect_cmd.get("fadetime"):
                    cmd += f" FADETIME={effect_cmd['fadetime']}"
            else:
                cmd = f"SET_LED_EFFECT EFFECT={effect_name} STOP=1"
            
            result = await client.run_gcode(cmd)
            results.append({"effect": effect_name, "action": action, "result": "ok" if "error" not in result else result["error"]})
        
        return json.dumps({
            "success": True,
            "scene": scene,
            "description": scene_config.get("description", ""),
            "effects_applied": results
        })
    
    @mcp.tool()
    async def list_led_scenes() -> str:
        """List all available pre-defined LED scenes."""
        scenes = load_scenes()
        
        # Ensure scenes is a dict
        if not isinstance(scenes, dict):
            return json.dumps({
                "error": "Invalid scenes configuration",
                "hint": "LED scenes file should contain a JSON object, not an array",
                "default_scenes": list(DEFAULT_SCENES.keys())
            }, indent=2)
        
        scene_list = []
        for name, scene_config in scenes.items():
            # Handle case where scene_config might not be a dict
            if isinstance(scene_config, dict):
                scene_list.append({
                    "name": name,
                    "description": scene_config.get("description", ""),
                    "effects_count": len(scene_config.get("effects", []))
                })
            else:
                scene_list.append({
                    "name": name,
                    "description": "(invalid config)",
                    "effects_count": 0
                })
        
        return json.dumps({"scenes": scene_list}, indent=2)
    
    @mcp.tool()
    async def set_led_direct(
        led_chain: str,
        red: float = 0.0,
        green: float = 0.0,
        blue: float = 0.0,
        white: float = 0.0,
        index: Optional[int] = None
    ) -> str:
        """
        Set LED color directly (bypassing effects).
        
        Args:
            led_chain: LED chain name (e.g., "neopixel:panel_ring")
            red: Red value 0.0-1.0
            green: Green value 0.0-1.0
            blue: Blue value 0.0-1.0
            white: White value 0.0-1.0 (for RGBW LEDs)
            index: Optional specific LED index to set
        """
        if not config.ARMED:
            return json.dumps({
                "error": "System not ARMED. Set ARMED=true environment variable to enable G-code execution.",
                "hint": "This is a safety feature to prevent accidental commands."
            })

        try:
            led_chain = sanitize_gcode_param(led_chain, "led_chain")
        except ValueError as e:
            return json.dumps({"error": str(e)})

        client = get_client()

        # Validate color values
        for color, name in [(red, "red"), (green, "green"), (blue, "blue"), (white, "white")]:
            if not 0.0 <= color <= 1.0:
                return json.dumps({"error": f"{name} must be between 0.0 and 1.0"})

        # Parse chain name
        parts = led_chain.split(":")
        if len(parts) != 2:
            return json.dumps({"error": "led_chain format should be 'type:name' e.g., 'neopixel:panel_ring'"})
        
        led_name = parts[1]
        
        cmd = f"SET_LED LED={led_name} RED={red} GREEN={green} BLUE={blue}"
        if white > 0:
            cmd += f" WHITE={white}"
        if index is not None:
            cmd += f" INDEX={index}"
        cmd += " TRANSMIT=1"
        
        result = await client.run_gcode(cmd)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        return json.dumps({
            "success": True,
            "led": led_chain,
            "color": {"red": red, "green": green, "blue": blue, "white": white},
            "index": index
        })
    
    @mcp.tool()
    async def list_led_effects() -> str:
        """
        List LED effects that are likely configured.
        Note: This provides common effect names - actual effects depend on your printer.cfg
        """
        # Common effects that users typically configure with klipper-led_effect
        common_effects = [
            {"name": "panel_idle", "description": "Idle breathing animation"},
            {"name": "heating", "description": "Heater warming animation"},
            {"name": "printing", "description": "Active printing illumination"},
            {"name": "tool_change", "description": "Tool change flash"},
            {"name": "print_complete", "description": "Print complete celebration"},
            {"name": "critical_error", "description": "Error strobe"},
            {"name": "homing", "description": "Homing feedback"},
            {"name": "bed_heating", "description": "Bed heating progress"},
            {"name": "nozzle_heating", "description": "Nozzle heating progress"},
        ]
        
        return json.dumps({
            "message": "Common LED effects - actual effects depend on your printer.cfg [led_effect] sections",
            "common_effects": common_effects,
            "hint": "Use 'read_file' to check your printer.cfg or led_effects.cfg for actual configured effects"
        }, indent=2)
