"""
Klipper MCP Server - Main Entry Point
Compatible with Python 3.9+ (CB1/Raspberry Pi)
Run with: python server.py
"""
import asyncio
import copy
import inspect
import json
import os
import re
import sys
import traceback
from datetime import datetime
from aiohttp import web
from typing import Any, Callable, Dict, get_type_hints, get_origin, get_args
import html

import config
from moonraker import init_client, close_client, get_client
from tools.security import verify_pin


# ============================================================
# HTML Rendering Utilities (for fetch_webpage compatibility)
# ============================================================

def escape(text: Any) -> str:
    """HTML escape any value."""
    return html.escape(str(text)) if text is not None else ""


def render_json_as_html(data: Any, title: str = "MCP Response", depth: int = 0) -> str:
    """Recursively render any JSON data as formatted HTML."""
    if isinstance(data, dict):
        items = []
        for key, value in data.items():
            rendered_value = render_json_value(value, depth + 1)
            items.append(f'<dt><strong>{escape(key)}</strong></dt><dd>{rendered_value}</dd>')
        return f'<dl style="margin-left:{depth*20}px;">{"".join(items)}</dl>'
    elif isinstance(data, list):
        if not data:
            return '<em>(empty list)</em>'
        items = [f'<li>{render_json_value(item, depth + 1)}</li>' for item in data]
        return f'<ul style="margin-left:{depth*20}px;">{"".join(items)}</ul>'
    else:
        return escape(data)


def render_json_value(value: Any, depth: int = 0) -> str:
    """Render a single JSON value as HTML."""
    if value is None:
        return '<em>null</em>'
    elif isinstance(value, bool):
        color = "green" if value else "red"
        return f'<span style="color:{color};">{str(value).lower()}</span>'
    elif isinstance(value, (int, float)):
        return f'<code>{value}</code>'
    elif isinstance(value, str):
        return escape(value)
    elif isinstance(value, (dict, list)):
        return render_json_as_html(value, depth=depth)
    else:
        return escape(value)


def html_page(title: str, body: str, subtitle: str = None) -> str:
    """Wrap content in a complete HTML page with styling."""
    subtitle_html = f'<p style="color:#666;">{escape(subtitle)}</p>' if subtitle else ''
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)} - Klipper MCP</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
               max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; border-bottom: 2px solid #007acc; padding-bottom: 10px; }}
        h2 {{ color: #007acc; margin-top: 30px; }}
        h3 {{ color: #555; }}
        section {{ background: white; padding: 20px; margin: 20px 0; border-radius: 8px; 
                  box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        dl {{ display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; }}
        dt {{ font-weight: bold; color: #333; }}
        dd {{ margin: 0; color: #666; }}
        code {{ background: #e8e8e8; padding: 2px 6px; border-radius: 3px; font-family: monospace; }}
        pre {{ background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 5px; 
               overflow-x: auto; font-size: 13px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background: #007acc; color: white; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        .status-ok {{ color: green; font-weight: bold; }}
        .status-error {{ color: red; font-weight: bold; }}
        .temp {{ font-size: 1.2em; }}
        .tool-card {{ border: 1px solid #ddd; padding: 10px; margin: 5px 0; border-radius: 5px; }}
        .tool-name {{ font-weight: bold; color: #007acc; }}
        .timestamp {{ color: #999; font-size: 0.9em; }}
        a {{ color: #007acc; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .nav {{ background: #007acc; padding: 10px; border-radius: 5px; margin-bottom: 20px; }}
        .nav a {{ color: white; margin-right: 15px; }}
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/">Home</a>
        <a href="/status.html">Status</a>
        <a href="/tools.html">Tools</a>
        <a href="/health.html">Health</a>
        <a href="/config.html">Config Files</a>
    </nav>
    <h1>{escape(title)}</h1>
    {subtitle_html}
    {body}
    <footer style="margin-top:40px; padding-top:20px; border-top:1px solid #ddd; color:#999;">
        <p class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <p>Klipper MCP Server v1.0.0 | Printer: {escape(config.PRINTER_NAME)}</p>
    </footer>
</body>
</html>'''


def error_html(title: str, error: str) -> str:
    """Render an error page."""
    return html_page(title, f'''
        <section>
            <h2 class="status-error">Error</h2>
            <p>{escape(error)}</p>
        </section>
    ''')


# ============================================================
# Authentication
# ============================================================

def check_api_key(request: web.Request) -> bool:
    """Check the X-API-Key header against config.API_KEY. No key configured = auth disabled (dev mode)."""
    expected = getattr(config, "API_KEY", None)
    if not expected:
        return True
    provided = request.headers.get("X-API-Key")
    return verify_pin(provided, expected)


# Tool registry
TOOLS: Dict[str, Dict[str, Any]] = {}

def get_tool_description(tool_info):
    """Extract the first meaningful line from a tool's docstring."""
    doc = tool_info.get("description", "") or ""
    # Strip leading/trailing whitespace and split by lines
    lines = doc.strip().split('\n')
    # Find the first non-empty line
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped
    return "No description available"


_ARGS_HEADER_RE = re.compile(r'^\s*Args:\s*$')
_ARG_LINE_RE = re.compile(r'^\s+(\w+)\s*:\s*(.*)$')


def parse_docstring_args(doc: str) -> Dict[str, str]:
    """
    Parse a Google-style 'Args:' section out of a docstring into {param_name: description}.
    Best-effort: if no Args section is found, or its format doesn't match, returns {}.
    """
    try:
        if not doc:
            return {}
        lines = doc.split('\n')
        args = {}
        in_args = False
        for line in lines:
            if not in_args:
                if _ARGS_HEADER_RE.match(line):
                    in_args = True
                continue
            if not line.strip():
                break
            match = _ARG_LINE_RE.match(line)
            if not match:
                break
            args[match.group(1)] = match.group(2).strip()
        return args
    except Exception:
        return {}


_PIN_KEY_RE = re.compile(r'^pin$|_pin$', re.IGNORECASE)


def _redact_pins(value):
    """Recursively redact any dict key (case-insensitive) equal to 'pin' or ending in '_pin'."""
    if isinstance(value, dict):
        redacted = {}
        for key, val in value.items():
            if isinstance(key, str) and _PIN_KEY_RE.search(key.lower()):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = _redact_pins(val)
        return redacted
    elif isinstance(value, list):
        return [_redact_pins(item) for item in value]
    else:
        return value


def audit_log(action: str, details: dict = None):
    """Write to audit log for security tracking."""
    log_path = config.AUDIT_LOG_FILE
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    safe_details = _redact_pins(copy.deepcopy(details)) if details else {}

    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "details": safe_details
    }

    try:
        with open(log_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        print(f"Failed to write audit log: {e}", file=sys.stderr)


# ============================================================
# Import and register all tools from tool modules
# ============================================================

def register_all_tools():
    """Import and register all tool modules."""
    from tools import register_all_tools as _register
    
    # Create a mock MCP object that captures tool registrations
    class MockMCP:
        def tool(self):
            def decorator(func):
                tool_name = func.__name__
                TOOLS[tool_name] = {
                    "function": func,
                    "description": func.__doc__ or "",
                    "name": tool_name
                }
                return func
            return decorator
    
    mock_mcp = MockMCP()
    _register(mock_mcp)
    
    print(f"✓ Registered {len(TOOLS)} tools", file=sys.stderr)


# ============================================================
# HTTP API Handlers
# ============================================================

async def handle_list_tools(request: web.Request) -> web.Response:
    """List all available tools."""
    tools_list = []
    for name, tool_info in TOOLS.items():
        tools_list.append({
            "name": name,
            "description": get_tool_description(tool_info)
        })
    
    return web.json_response({
        "tools": tools_list,
        "count": len(tools_list)
    })


async def handle_call_tool(request: web.Request) -> web.Response:
    """Call a specific tool."""
    if not check_api_key(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    tool_name = data.get("tool") or data.get("name")
    arguments = data.get("arguments", {}) or data.get("params", {})
    
    if not tool_name:
        return web.json_response({"error": "Missing 'tool' field"}, status=400)
    
    if tool_name not in TOOLS:
        return web.json_response({
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(TOOLS.keys())
        }, status=404)
    
    tool_info = TOOLS[tool_name]
    func = tool_info["function"]
    
    # Log the call
    audit_log("tool_call", {"tool": tool_name, "arguments": arguments})
    
    try:
        # Call the tool function
        if asyncio.iscoroutinefunction(func):
            result = await func(**arguments)
        else:
            result = func(**arguments)
        
        if isinstance(result, str):
            try:
                parsed_result = json.loads(result)
            except (ValueError, TypeError):
                parsed_result = result
        else:
            parsed_result = result

        if isinstance(parsed_result, dict) and parsed_result.get("__mcp_image__"):
            parsed_result = dict(parsed_result)
            data_len = len(parsed_result.get("data", "") or "")
            parsed_result["data"] = f"<{data_len} bytes of base64 image data omitted from JSON response>"

        return web.json_response({
            "tool": tool_name,
            "result": parsed_result
        })

    except TypeError as e:
        return web.json_response({
            "error": f"Invalid arguments: {str(e)}",
            "tool": tool_name
        }, status=400)
    
    except Exception as e:
        traceback.print_exc()
        return web.json_response({
            "error": str(e),
            "tool": tool_name
        }, status=500)


async def handle_server_info(request: web.Request) -> web.Response:
    """Get server information."""
    return web.json_response({
        "name": "klipper-mcp",
        "version": "1.0.0",
        "printer": config.PRINTER_NAME,
        "moonraker_url": config.MOONRAKER_URL,
        "armed": config.ARMED,
        "tools_count": len(TOOLS),
        "features": {
            "stealthchanger": True,
            "led_effects": True,
            "spoolman": config.SPOOLMAN_ENABLED,
            "tts": config.TTS_ENABLED,
        }
    })


async def handle_printer_status(request: web.Request) -> web.Response:
    """Quick printer status endpoint."""
    try:
        client = get_client()
        result = await client.get_printer_status()
        
        if "error" in result:
            return web.json_response({"error": result["error"]}, status=500)
        
        status = result.get("result", {}).get("status", {})
        print_stats = status.get("print_stats", {})
        extruder = status.get("extruder", {})
        bed = status.get("heater_bed", {})

        return web.json_response({
            "state": print_stats.get("state"),
            "filename": print_stats.get("filename"),
            "progress": status.get("virtual_sdcard", {}).get("progress", 0),
            "temperatures": {
                "extruder": {
                    "current": extruder.get("temperature"),
                    "target": extruder.get("target")
                },
                "bed": {
                    "current": bed.get("temperature"),
                    "target": bed.get("target")
                }
            }
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    try:
        client = get_client()
        result = await client.get_printer_status()
        moonraker_ok = "error" not in result
    except:
        moonraker_ok = False
    
    return web.json_response({
        "status": "ok" if moonraker_ok else "degraded",
        "moonraker_connected": moonraker_ok,
        "timestamp": datetime.now().isoformat()
    })


# ============================================================
# HTML Endpoint Handlers (for fetch_webpage compatibility)
# ============================================================

async def handle_server_info_html(request: web.Request) -> web.Response:
    """Server info in HTML format."""
    body = f'''
    <section>
        <h2>Server Information</h2>
        <dl>
            <dt>Server Name</dt><dd>klipper-mcp</dd>
            <dt>Version</dt><dd>1.0.0</dd>
            <dt>Printer</dt><dd>{escape(config.PRINTER_NAME)}</dd>
            <dt>Moonraker URL</dt><dd><code>{escape(config.MOONRAKER_URL)}</code></dd>
            <dt>Armed Mode</dt><dd><span class="{"status-ok" if config.ARMED else "status-error"}">{config.ARMED}</span></dd>
            <dt>Tools Available</dt><dd>{len(TOOLS)}</dd>
        </dl>
    </section>
    <section>
        <h2>Features</h2>
        <dl>
            <dt>StealthChanger</dt><dd><span class="status-ok">Enabled</span></dd>
            <dt>LED Effects</dt><dd><span class="status-ok">Enabled</span></dd>
            <dt>Spoolman</dt><dd><span class="{"status-ok" if config.SPOOLMAN_ENABLED else "status-error"}">{config.SPOOLMAN_ENABLED}</span></dd>
            <dt>TTS Notifications</dt><dd><span class="{"status-ok" if config.TTS_ENABLED else "status-error"}">{config.TTS_ENABLED}</span></dd>
        </dl>
    </section>
    <section>
        <h2>Quick Links</h2>
        <ul>
            <li><a href="/status.html">Printer Status</a></li>
            <li><a href="/tools.html">Available Tools ({len(TOOLS)})</a></li>
            <li><a href="/health.html">Health Check</a></li>
            <li><a href="/shaper.html">Input Shaper Status</a></li>
            <li><a href="/config.html">Configuration Files</a></li>
        </ul>
    </section>
    '''
    return web.Response(text=html_page("Klipper MCP Server", body, f"Controlling {config.PRINTER_NAME}"), 
                       content_type='text/html')


async def handle_printer_status_html(request: web.Request) -> web.Response:
    """Printer status in HTML format."""
    try:
        client = get_client()
        result = await client.get_printer_status()
        
        if "error" in result:
            return web.Response(text=error_html("Printer Status", result["error"]), 
                               content_type='text/html', status=500)
        
        status = result.get("result", {}).get("status", {})
        print_stats = status.get("print_stats", {})
        extruder = status.get("extruder", {})
        extruder1 = status.get("extruder1", {})
        extruder2 = status.get("extruder2", {})
        bed = status.get("heater_bed", {})
        toolhead = status.get("toolhead", {})
        
        state = print_stats.get("state", "unknown")
        state_class = "status-ok" if state in ["standby", "printing", "complete"] else "status-error" if state == "error" else ""
        
        progress = status.get("virtual_sdcard", {}).get("progress", 0) or 0
        
        body = f'''
        <section>
            <h2>Print State</h2>
            <dl>
                <dt>State</dt><dd><span class="{state_class}" style="font-size:1.3em;">{escape(state).upper()}</span></dd>
                <dt>Filename</dt><dd>{escape(print_stats.get("filename")) or "<em>None</em>"}</dd>
                <dt>Progress</dt><dd>
                    <progress value="{progress * 100}" max="100" style="width:200px;"></progress>
                    {progress * 100:.1f}%
                </dd>
                <dt>Print Duration</dt><dd>{print_stats.get("print_duration", 0):.0f}s</dd>
            </dl>
        </section>
        
        <section>
            <h2>Temperatures</h2>
            <table>
                <tr><th>Heater</th><th>Current</th><th>Target</th><th>Power</th></tr>
                <tr>
                    <td><strong>T0 (Extruder)</strong></td>
                    <td class="temp">{extruder.get("temperature", 0):.1f}°C</td>
                    <td>{extruder.get("target", 0):.0f}°C</td>
                    <td>{(extruder.get("power", 0) or 0) * 100:.0f}%</td>
                </tr>
                <tr>
                    <td><strong>T1 (Extruder1)</strong></td>
                    <td class="temp">{extruder1.get("temperature", 0):.1f}°C</td>
                    <td>{extruder1.get("target", 0):.0f}°C</td>
                    <td>{(extruder1.get("power", 0) or 0) * 100:.0f}%</td>
                </tr>
                <tr>
                    <td><strong>T2 (Extruder2)</strong></td>
                    <td class="temp">{extruder2.get("temperature", 0):.1f}°C</td>
                    <td>{extruder2.get("target", 0):.0f}°C</td>
                    <td>{(extruder2.get("power", 0) or 0) * 100:.0f}%</td>
                </tr>
                <tr>
                    <td><strong>Bed</strong></td>
                    <td class="temp">{bed.get("temperature", 0):.1f}°C</td>
                    <td>{bed.get("target", 0):.0f}°C</td>
                    <td>{(bed.get("power", 0) or 0) * 100:.0f}%</td>
                </tr>
            </table>
        </section>
        
        <section>
            <h2>Toolhead</h2>
            <dl>
                <dt>Position</dt><dd>X: {toolhead.get("position", [0,0,0,0])[0]:.2f}, Y: {toolhead.get("position", [0,0,0,0])[1]:.2f}, Z: {toolhead.get("position", [0,0,0,0])[2]:.2f}</dd>
                <dt>Homed Axes</dt><dd><code>{toolhead.get("homed_axes", "none")}</code></dd>
                <dt>Max Velocity</dt><dd>{toolhead.get("max_velocity", 0)} mm/s</dd>
                <dt>Max Accel</dt><dd>{toolhead.get("max_accel", 0)} mm/s²</dd>
            </dl>
        </section>
        '''
        
        return web.Response(text=html_page("Printer Status", body, f"{config.PRINTER_NAME}"), 
                           content_type='text/html')
    except Exception as e:
        return web.Response(text=error_html("Printer Status", str(e)), 
                           content_type='text/html', status=500)


async def handle_list_tools_html(request: web.Request) -> web.Response:
    """List all tools in HTML format."""
    # Group tools by category
    categories = {}
    for name, tool_info in sorted(TOOLS.items()):
        # Determine category from tool name prefix
        if name.startswith("get_"):
            cat = "Query/Read"
        elif name.startswith("set_"):
            cat = "Configuration"
        elif name.startswith("list_"):
            cat = "Listing"
        elif any(name.startswith(p) for p in ["start_", "stop_", "pause_", "resume_", "cancel_"]):
            cat = "Control"
        elif any(x in name for x in ["tool", "pickup", "dropoff"]):
            cat = "Toolchanger"
        elif any(x in name for x in ["led", "light"]):
            cat = "LED Effects"
        elif any(x in name for x in ["temperature", "temp", "heater", "pid"]):
            cat = "Temperature"
        elif any(x in name for x in ["mesh", "bed", "level", "calibrat"]):
            cat = "Bed & Calibration"
        elif any(x in name for x in ["file", "gcode"]):
            cat = "Files & G-code"
        elif any(x in name for x in ["camera", "timelapse", "snapshot"]):
            cat = "Camera"
        elif any(x in name for x in ["spool", "filament"]):
            cat = "Spoolman"
        elif any(x in name for x in ["notify", "announce", "tts"]):
            cat = "Notifications"
        elif any(x in name for x in ["backup", "maintenance", "audit", "log"]):
            cat = "Maintenance"
        elif any(x in name for x in ["diagnose", "error", "issue", "mcu"]):
            cat = "Diagnostics"
        else:
            cat = "Other"
        
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((name, tool_info))
    
    body = f'<section><h2>Total Tools: {len(TOOLS)}</h2></section>'
    
    for cat in sorted(categories.keys()):
        tools = categories[cat]
        tools_html = ""
        for name, tool_info in tools:
            desc = get_tool_description(tool_info)
            tools_html += f'''
            <div class="tool-card">
                <span class="tool-name">{escape(name)}</span>
                <p style="margin:5px 0 0 0; color:#666;">{escape(desc)}</p>
                <small><a href="/call/{name}.html">Try it →</a></small>
            </div>
            '''
        
        body += f'''
        <section>
            <h2>{escape(cat)} ({len(tools)})</h2>
            {tools_html}
        </section>
        '''
    
    return web.Response(text=html_page("Available Tools", body, f"{len(TOOLS)} tools registered"), 
                       content_type='text/html')


async def handle_health_html(request: web.Request) -> web.Response:
    """Health check in HTML format."""
    try:
        client = get_client()
        result = await client.get_printer_status()
        moonraker_ok = "error" not in result
    except Exception as e:
        moonraker_ok = False
        error_msg = str(e)
    else:
        error_msg = None
    
    status_class = "status-ok" if moonraker_ok else "status-error"
    status_text = "OK" if moonraker_ok else "DEGRADED"
    
    body = f'''
    <section>
        <h2>System Health</h2>
        <dl>
            <dt>Overall Status</dt>
            <dd><span class="{status_class}" style="font-size:1.5em;">{status_text}</span></dd>
            <dt>Moonraker Connected</dt>
            <dd><span class="{status_class}">{moonraker_ok}</span></dd>
            <dt>MCP Server</dt>
            <dd><span class="status-ok">Running</span></dd>
            <dt>Tools Loaded</dt>
            <dd>{len(TOOLS)}</dd>
        </dl>
        {f'<p class="status-error">Error: {escape(error_msg)}</p>' if error_msg else ''}
    </section>
    '''
    
    return web.Response(text=html_page("Health Check", body), content_type='text/html')


async def handle_call_tool_html(request: web.Request) -> web.Response:
    """
    Show a form for a tool (GET, never executes) or execute it (POST, requires API key).
    """
    tool_name = request.match_info.get('tool_name', '').replace('.html', '')

    if not tool_name:
        return web.Response(text=error_html("Tool Call", "No tool specified"),
                           content_type='text/html', status=400)

    if tool_name not in TOOLS:
        body = f'''
        <section>
            <h2 class="status-error">Unknown Tool: {escape(tool_name)}</h2>
            <p>This tool does not exist. <a href="/tools.html">View available tools</a></p>
        </section>
        '''
        return web.Response(text=html_page("Tool Not Found", body),
                           content_type='text/html', status=404)

    tool_info = TOOLS[tool_name]
    func = tool_info["function"]

    if request.method == "GET":
        # GET never executes the tool - just show a pre-fillable form. Any query params
        # present are used only to pre-fill input values, not to trigger execution.
        query_args = dict(request.query)
        desc = tool_info["description"] or "No description available."
        prefill_fields = "".join(
            f'<p><label>{escape(key)}: <input type="text" name="{escape(key)}" value="{escape(value)}"></label></p>'
            for key, value in query_args.items()
        )
        body = f'''
        <section>
            <h2>Tool: {escape(tool_name)}</h2>
            <p>{escape(desc)}</p>
            <form method="POST" action="/call/{escape(tool_name)}.html">
                {prefill_fields}
                <p><em>Add form fields to call with arguments, or click below to call without arguments:</em></p>
                <button type="submit" style="padding:10px 20px; font-size:1.1em; cursor:pointer;">
                    Run {escape(tool_name)}
                </button>
            </form>
        </section>
        '''
        return web.Response(text=html_page(f"Tool: {tool_name}", body), content_type='text/html')

    # POST: this executes the tool - requires a valid API key.
    if not check_api_key(request):
        return web.Response(text=error_html(f"Tool: {tool_name}", "Unauthorized: missing or invalid X-API-Key header"),
                           content_type='text/html', status=401)

    form = await request.post()
    arguments = dict(form)

    audit_log("tool_call_html", {"tool": tool_name, "arguments": arguments})

    try:
        if asyncio.iscoroutinefunction(func):
            result = await func(**arguments)
        else:
            result = func(**arguments)

        # Parse JSON if string
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except:
                pass

        # Image convention: render inline as an <img>, and don't dump the base64 blob into the raw JSON view.
        if isinstance(result, dict) and result.get("__mcp_image__"):
            mime_type = result.get("mime_type", "image/jpeg")
            data = result.get("data", "") or ""
            result_html = f'<img src="data:{escape(mime_type)};base64,{data}" style="max-width:100%;">'
            raw_json_display = f"<{len(data)} bytes of base64 image data omitted from HTML response>"
        else:
            # Render result
            if isinstance(result, (dict, list)):
                result_html = render_json_as_html(result)
            else:
                result_html = f'<pre>{escape(str(result))}</pre>'
            raw_json_display = json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)

        body = f'''
        <section>
            <h2>Tool: {escape(tool_name)}</h2>
            <p><strong>Arguments:</strong> {escape(json.dumps(arguments)) if arguments else "<em>None</em>"}</p>
        </section>
        <section>
            <h2>Result</h2>
            {result_html}
        </section>
        <section>
            <h3>Raw JSON</h3>
            <pre>{escape(raw_json_display)}</pre>
        </section>
        '''

        return web.Response(text=html_page(f"Result: {tool_name}", body), content_type='text/html')

    except TypeError as e:
        return web.Response(text=error_html(f"Tool: {tool_name}", f"Invalid arguments: {e}"),
                           content_type='text/html', status=400)
    except Exception as e:
        traceback.print_exc()
        return web.Response(text=error_html(f"Tool: {tool_name}", str(e)),
                           content_type='text/html', status=500)


async def handle_input_shaper_html(request: web.Request) -> web.Response:
    """Display input shaper settings for all toolheads."""
    import re
    
    try:
        client = get_client()
        
        # Query current active input_shaper settings from Klipper
        result = await client.query_printer_objects({
            "input_shaper": None  # Get all attributes
        })
        
        active_shaper = {}
        if "result" in result:
            status = result.get("result", {}).get("status", {})
            active_shaper = status.get("input_shaper", {})
        
        # Read per-tool input shaper params from config files
        tool_shapers = []
        for i in range(config.TOOL_COUNT):
            tool_name = config.TOOL_NAMES.get(i, f"T{i}")
            filepath = f"Toolheads/T{i}.cfg"
            
            try:
                session = await client._get_session()
                url = f"{client.base_url}/server/files/config/{filepath}"
                
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.text()
                        
                        # Parse input shaper params from config
                        freq_x = re.search(r'params_input_shaper_freq_x:\s*([\d.]+)', content)
                        freq_y = re.search(r'params_input_shaper_freq_y:\s*([\d.]+)', content)
                        type_x = re.search(r'params_input_shaper_type_x:\s*(\w+)', content)
                        type_y = re.search(r'params_input_shaper_type_y:\s*(\w+)', content)
                        
                        tool_shapers.append({
                            "tool": tool_name,
                            "freq_x": float(freq_x.group(1)) if freq_x else None,
                            "freq_y": float(freq_y.group(1)) if freq_y else None,
                            "type_x": type_x.group(1) if type_x else "mzv",
                            "type_y": type_y.group(1) if type_y else "mzv",
                        })
                    else:
                        tool_shapers.append({
                            "tool": tool_name,
                            "error": f"Config file not found: {filepath}"
                        })
            except Exception as e:
                tool_shapers.append({
                    "tool": tool_name,
                    "error": str(e)
                })
        
        # Build HTML
        active_freq_x = active_shaper.get("shaper_freq_x", 0)
        active_freq_y = active_shaper.get("shaper_freq_y", 0)
        active_type_x = active_shaper.get("shaper_type_x", "unknown")
        active_type_y = active_shaper.get("shaper_type_y", "unknown")
        smoothing = active_shaper.get("smoothing", 0)
        
        body = f'''
        <section>
            <h2>Active Input Shaper</h2>
            <p>Currently applied shaper settings (changes on tool change):</p>
            <table>
                <tr><th>Axis</th><th>Type</th><th>Frequency (Hz)</th></tr>
                <tr>
                    <td><strong>X</strong></td>
                    <td><code>{escape(active_type_x)}</code></td>
                    <td>{active_freq_x:.1f} Hz</td>
                </tr>
                <tr>
                    <td><strong>Y</strong></td>
                    <td><code>{escape(active_type_y)}</code></td>
                    <td>{active_freq_y:.1f} Hz</td>
                </tr>
            </table>
            <dl>
                <dt>Smoothing</dt><dd>{smoothing:.4f}</dd>
            </dl>
        </section>
        
        <section>
            <h2>Per-Tool Shaper Configuration</h2>
            <p>Values stored in each toolhead's config file (applied on tool change):</p>
            <table>
                <tr><th>Tool</th><th>Freq X (Hz)</th><th>Freq Y (Hz)</th><th>Type X</th><th>Type Y</th><th>Config</th></tr>
        '''
        
        for ts in tool_shapers:
            if "error" in ts:
                body += f'''
                <tr>
                    <td><strong>{escape(ts["tool"])}</strong></td>
                    <td colspan="4" style="color:#d32f2f;">Error: {escape(ts["error"])}</td>
                    <td>-</td>
                </tr>
                '''
            else:
                freq_x_str = f'{ts["freq_x"]:.1f}' if ts["freq_x"] else '<em>not set</em>'
                freq_y_str = f'{ts["freq_y"]:.1f}' if ts["freq_y"] else '<em>not set</em>'
                config_link = f'<a href="/config/Toolheads/{ts["tool"]}.cfg.html">View</a>'
                body += f'''
                <tr>
                    <td><strong>{escape(ts["tool"])}</strong></td>
                    <td>{freq_x_str}</td>
                    <td>{freq_y_str}</td>
                    <td><code>{escape(ts["type_x"])}</code></td>
                    <td><code>{escape(ts["type_y"])}</code></td>
                    <td>{config_link}</td>
                </tr>
                '''
        
        body += '''
            </table>
        </section>
        
        <section>
            <h2>Calibration</h2>
            <p>To calibrate input shaper for each tool:</p>
            <ol>
                <li>Select tool: <code>T0</code> / <code>T1</code> / <code>T2</code></li>
                <li>Run: <code>SHAPER_CALIBRATE</code></li>
                <li>Update the tool's config file with the recommended values</li>
                <li>Repeat for each tool</li>
            </ol>
            <p><a href="/call/run_gcode.html?script=GET_INPUT_SHAPER">Check current shaper via G-code →</a></p>
        </section>
        '''
        
        return web.Response(text=html_page("Input Shaper Status", body, f"{config.PRINTER_NAME}"), 
                           content_type='text/html')
    except Exception as e:
        traceback.print_exc()
        return web.Response(text=error_html("Input Shaper Status", str(e)), 
                           content_type='text/html', status=500)


async def handle_config_files_html(request: web.Request) -> web.Response:
    """List and link to config files."""
    try:
        client = get_client()
        result = await client.get_directory("config")
        
        if "error" in result:
            return web.Response(text=error_html("Config Files", result["error"]), 
                               content_type='text/html', status=500)
        
        data = result.get("result", {})
        files = data.get("files", [])
        cfg_files = [f for f in files if f.get("filename", "").endswith(".cfg")]
        
        rows = ""
        for f in sorted(cfg_files, key=lambda x: x.get("filename", "")):
            filename = f.get("filename", "")
            size = f.get("size", 0)
            modified = f.get("modified", 0)
            mod_date = datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M") if modified else "Unknown"
            rows += f'''
            <tr>
                <td><a href="/config/{escape(filename)}.html">{escape(filename)}</a></td>
                <td>{size:,} bytes</td>
                <td>{mod_date}</td>
            </tr>
            '''
        
        body = f'''
        <section>
            <h2>Configuration Files ({len(cfg_files)})</h2>
            <table>
                <tr><th>File</th><th>Size</th><th>Modified</th></tr>
                {rows}
            </table>
        </section>
        '''
        
        return web.Response(text=html_page("Configuration Files", body), content_type='text/html')
    except Exception as e:
        return web.Response(text=error_html("Config Files", str(e)), 
                           content_type='text/html', status=500)


async def handle_config_file_html(request: web.Request) -> web.Response:
    """Display a config file."""
    filepath = request.match_info.get('filepath', '').replace('.html', '')
    
    if not filepath:
        return web.Response(text=error_html("Config File", "No file specified"), 
                           content_type='text/html', status=400)
    
    try:
        client = get_client()
        # Use direct file download like the filesystem tool does
        session = await client._get_session()
        url = f"{client.base_url}/server/files/config/{filepath}"
        
        async with session.get(url) as response:
            if response.status == 404:
                return web.Response(text=error_html("Config File", f"File not found: {filepath}"), 
                                   content_type='text/html', status=404)
            response.raise_for_status()
            content = await response.text()
        
        body = f'''
        <section>
            <h2>{escape(filepath)}</h2>
            <p><a href="/config.html">← Back to file list</a></p>
            <pre style="white-space:pre-wrap; word-wrap:break-word;">{escape(content)}</pre>
        </section>
        '''
        
        return web.Response(text=html_page(f"Config: {filepath}", body), content_type='text/html')
    except Exception as e:
        return web.Response(text=error_html("Config File", str(e)), 
                           content_type='text/html', status=500)


# ============================================================
# MCP Protocol Handler (JSON-RPC style)
# ============================================================

async def handle_mcp(request: web.Request) -> web.Response:
    """
    Handle MCP protocol requests (JSON-RPC style).
    This allows VS Code MCP clients to communicate with the server.
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error"},
            "id": None
        }, status=400)

    method = data.get("method", "")
    params = data.get("params", {})
    request_id = data.get("id")

    if not check_api_key(request):
        return web.json_response({
            "jsonrpc": "2.0",
            "error": {"code": -32001, "message": "Unauthorized"},
            "id": request_id
        }, status=401)

    # JSON-RPC notifications (no "id") get no response at all per spec - not an error.
    if request_id is None and (method.startswith("notifications/") or method == "notifications/initialized"):
        return web.Response(status=204)

    result = None
    error = None

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "klipper-mcp",
                    "version": "1.0.0"
                },
                "capabilities": {
                    "tools": {"listChanged": False}
                }
            }
        
        elif method == "tools/list":
            tools_list = []
            type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
            for name, tool_info in TOOLS.items():
                func = tool_info["function"]
                sig = inspect.signature(func)
                try:
                    hints = get_type_hints(func)
                except Exception:
                    hints = {}
                arg_docs = parse_docstring_args(tool_info.get("description", "") or "")
                properties = {}
                required = []
                for param_name, param in sig.parameters.items():
                    hint = hints.get(param_name)
                    # Unwrap Optional[X] (i.e. Union[X, None]) to X before the type_map lookup.
                    if get_origin(hint) is not None and type(None) in get_args(hint):
                        non_none = [a for a in get_args(hint) if a is not type(None)]
                        if len(non_none) == 1:
                            hint = non_none[0]
                    json_type = type_map.get(hint, "string")
                    prop = {"type": json_type}
                    if param_name in arg_docs:
                        prop["description"] = arg_docs[param_name]
                    properties[param_name] = prop
                    if param.default is inspect.Parameter.empty:
                        required.append(param_name)
                input_schema = {"type": "object", "properties": properties, "additionalProperties": False}
                if required:
                    input_schema["required"] = required
                tools_list.append({
                    "name": name,
                    "description": get_tool_description(tool_info),
                    "inputSchema": input_schema
                })
            result = {"tools": tools_list}
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if tool_name not in TOOLS:
                error = {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            else:
                tool_info = TOOLS[tool_name]
                func = tool_info["function"]
                
                audit_log("tool_call", {"tool": tool_name, "arguments": arguments})
                
                if asyncio.iscoroutinefunction(func):
                    tool_result = await func(**arguments)
                else:
                    tool_result = func(**arguments)
                
                # Parse JSON string result if needed
                if isinstance(tool_result, str):
                    try:
                        tool_result = json.loads(tool_result)
                    except:
                        pass

                # Convention: a tool may return {"__mcp_image__": True, "data": <base64>, "mime_type": ...}
                # to hand back binary image content instead of a giant base64 text blob.
                if isinstance(tool_result, dict) and tool_result.get("__mcp_image__"):
                    result = {
                        "content": [{
                            "type": "image",
                            "data": tool_result["data"],
                            "mimeType": tool_result.get("mime_type", "image/jpeg")
                        }]
                    }
                else:
                    result = {
                        "content": [{
                            "type": "text",
                            "text": json.dumps(tool_result, indent=2) if isinstance(tool_result, (dict, list)) else str(tool_result)
                        }]
                    }
        
        elif method == "ping":
            result = {}
        
        else:
            error = {"code": -32601, "message": f"Method not found: {method}"}
    
    except Exception as e:
        traceback.print_exc()
        error = {"code": -32603, "message": str(e)}
    
    response = {"jsonrpc": "2.0", "id": request_id}
    if error:
        response["error"] = error
    else:
        response["result"] = result
    
    return web.json_response(response)


# ============================================================
# Main Application
# ============================================================

async def on_startup(app):
    """Called when the server starts."""
    print("Initializing Moonraker client...", file=sys.stderr)
    init_client()
    
    print("Registering tools...", file=sys.stderr)
    register_all_tools()
    
    audit_log("server_start", {
        "printer": config.PRINTER_NAME,
        "moonraker_url": config.MOONRAKER_URL
    })


async def on_cleanup(app):
    """Called when the server stops."""
    await close_client()
    audit_log("server_stop")
    print("Server stopped.", file=sys.stderr)


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    
    # JSON API routes
    app.router.add_get("/", handle_server_info)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_printer_status)
    app.router.add_get("/tools", handle_list_tools)
    app.router.add_post("/tools/call", handle_call_tool)
    app.router.add_post("/mcp", handle_mcp)  # MCP protocol endpoint
    
    # HTML routes (for fetch_webpage/browser compatibility)
    app.router.add_get("/index.html", handle_server_info_html)
    app.router.add_get("/status.html", handle_printer_status_html)
    app.router.add_get("/tools.html", handle_list_tools_html)
    app.router.add_get("/health.html", handle_health_html)
    app.router.add_get("/shaper.html", handle_input_shaper_html)
    app.router.add_get("/config.html", handle_config_files_html)
    app.router.add_get("/config/{filepath:.+}.html", handle_config_file_html)
    app.router.add_get("/call/{tool_name}.html", handle_call_tool_html)
    app.router.add_post("/call/{tool_name}.html", handle_call_tool_html)
    
    # Lifecycle hooks
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app


def main():
    """Main entry point."""
    print("=" * 50, file=sys.stderr)
    print("Klipper MCP Server v1.0.0", file=sys.stderr)
    print(f"Printer: {config.PRINTER_NAME}", file=sys.stderr)
    print(f"Moonraker: {config.MOONRAKER_URL}", file=sys.stderr)
    print(f"ARMED: {config.ARMED}", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    
    app = create_app()
    
    print(f"Starting server on {config.MCP_HOST}:{config.MCP_PORT}", file=sys.stderr)
    print(f"JSON API: http://{config.MCP_HOST}:{config.MCP_PORT}/", file=sys.stderr)
    print(f"HTML UI:  http://{config.MCP_HOST}:{config.MCP_PORT}/index.html", file=sys.stderr)
    print(f"MCP:      http://{config.MCP_HOST}:{config.MCP_PORT}/mcp", file=sys.stderr)
    
    web.run_app(
        app,
        host=config.MCP_HOST,
        port=config.MCP_PORT,
        print=lambda x: print(x, file=sys.stderr)
    )


if __name__ == "__main__":
    main()
