"""
Filesystem Tools
Read, write, list, upload, and delete files on the printer
"""
import asyncio
import json
import os
from typing import Optional

import aiohttp

import config
from moonraker import get_client
from tools.security import verify_pin


def is_path_allowed(path: str) -> bool:
    """Check if a local filesystem path is within one of the allowed directories."""
    abs_path = os.path.abspath(path)
    return any(abs_path.startswith(os.path.abspath(allowed)) for allowed in config.ALLOWED_PATHS)


# Moonraker file-API roots this module understands. "backups" is intentionally
# excluded here: it's a local-only directory (config.BACKUP_PATH) managed by
# tools/backup.py, not something exposed via Moonraker's /server/files API.
ROOT_ALIASES = {
    "gcode": "gcodes",
}
KNOWN_ROOTS = {"config", "gcodes", "logs", "timelapse"}
# Roots that have a corresponding local path (from config.ALLOWED_PATHS) we can
# validate resolved paths against. Roots without a local counterpart (e.g.
# "timelapse", which only exists on the Moonraker side) still get traversal
# protection, just not a local-root containment check.
ROOT_LOCAL_PATH = {
    "config": config.CONFIG_PATH,
    "gcodes": config.GCODES_PATH,
    "logs": config.LOGS_PATH,
}
DEFAULT_ROOT = "config"


def _infer_root_and_path(filepath: str, explicit_root: Optional[str] = None):
    """
    Split a caller-supplied path into a Moonraker root + path relative to that root.

    Accepts either an explicit `root` argument, or a `root/relative/path`
    convention baked into `filepath` itself (e.g. "gcodes/sub/file.gcode").
    Falls back to DEFAULT_ROOT ("config") when neither indicates a known root,
    preserving prior behavior for bare filenames like "printer.cfg" or
    "macros/custom.cfg".
    """
    filepath = filepath.lstrip("/")

    if explicit_root:
        root = ROOT_ALIASES.get(explicit_root.lower(), explicit_root.lower())
        return root, filepath

    head, sep, rest = filepath.partition("/")
    head_lower = head.lower()
    if head_lower in KNOWN_ROOTS or head_lower in ROOT_ALIASES:
        root = ROOT_ALIASES.get(head_lower, head_lower)
        return root, rest

    return DEFAULT_ROOT, filepath


def _check_path_allowed(root: str, relative_path: str) -> Optional[str]:
    """Return an error message if the resolved path escapes its allowed root, else None."""
    normalized = os.path.normpath(relative_path) if relative_path else "."
    if normalized in (".", "") or normalized.startswith("..") or os.path.isabs(normalized):
        return f"Invalid or disallowed path: {relative_path!r}"

    local_base = ROOT_LOCAL_PATH.get(root)
    if local_base is not None:
        candidate = os.path.join(local_base, normalized)
        if not is_path_allowed(candidate):
            return f"Path '{relative_path}' is outside the allowed '{root}' root"

    return None


# Per-request ceiling for plain file reads. Deliberately far below the shared
# session's MOONRAKER_TIMEOUT_SECONDS (which is sized for homing/meshing), so a
# stalled download surfaces as an error in seconds instead of hanging the caller.
FILE_READ_TIMEOUT_SECONDS = 30
FILE_READ_ATTEMPTS = 2


async def fetch_file_text(client, root: str, relative_path: str):
    """
    Download a file from Moonraker as text.

    Returns (content, error). Exactly one is None.

    Guards against two failure modes seen in practice:
      * A stale keep-alive socket from the shared ClientSession pool accepts the
        write and never answers. The session-level timeout is too generous to
        catch this, so a per-request ClientTimeout is applied here.
      * Retrying on the same poisoned pool just stalls again, so the session is
        closed between attempts to force a fresh connector.
    """
    url = f"{client.base_url}/server/files/{root}/{relative_path}"
    timeout = aiohttp.ClientTimeout(total=FILE_READ_TIMEOUT_SECONDS)
    last_error = None

    for attempt in range(1, FILE_READ_ATTEMPTS + 1):
        try:
            session = await client._get_session()
            async with session.get(url, timeout=timeout) as response:
                if response.status == 404:
                    return None, f"File not found: {root}/{relative_path}"
                response.raise_for_status()
                # Explicit encoding skips aiohttp's charset sniffing entirely and
                # keeps a stray byte from raising instead of returning content.
                return await response.text(encoding="utf-8", errors="replace"), None
        except asyncio.TimeoutError:
            last_error = (
                f"Timed out after {FILE_READ_TIMEOUT_SECONDS}s reading "
                f"{root}/{relative_path} (attempt {attempt}/{FILE_READ_ATTEMPTS})"
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < FILE_READ_ATTEMPTS:
            try:
                await client.close()
            except Exception:
                pass

    return None, last_error


async def upload_to_moonraker(client, root: str, relative_path: str, content) -> dict:
    """
    Upload file content to Moonraker via POST /server/files/upload, correctly
    setting the multipart 'root' and 'path' fields so subdirectories and
    non-config roots are honored instead of being flattened into the root
    directory. `path` carries the subdirectory only; the filename comes from
    the 'file' field's filename attribute.

    Returns the parsed Moonraker response dict (contains "error" on failure,
    per MoonrakerClient._request's status-code handling).
    """
    import aiohttp

    dirname, basename = os.path.split(relative_path)
    data = aiohttp.FormData()
    data.add_field(
        'file',
        content.encode('utf-8') if isinstance(content, str) else content,
        filename=basename,
        content_type='text/plain'
    )
    data.add_field('root', root)
    if dirname:
        data.add_field('path', dirname)

    return await client.post('/server/files/upload', data=data)


def register_filesystem_tools(mcp):
    """Register filesystem tools."""
    
    @mcp.tool()
    async def list_files(directory: str = "gcodes", recursive: bool = False) -> str:
        """
        List files in a printer directory.
        
        Args:
            directory: Directory to list - 'gcodes', 'config', 'logs', or full path
            recursive: If True, include subdirectories (default: False)
        
        Returns list of files with names, sizes, and modification dates.
        """
        client = get_client()

        # Map common names to roots (also accepts arbitrary Moonraker roots,
        # or a "root/subdir" full path, passed straight through).
        root_map = {
            "gcodes": "gcodes",
            "gcode": "gcodes",
            "config": "config",
            "logs": "logs",
        }

        directory = directory.lstrip("/")
        head, _, _ = directory.partition("/")
        root = root_map.get(directory.lower(), root_map.get(head.lower(), directory))

        # Validate against path traversal (and, for roots with a local
        # counterpart, against config.ALLOWED_PATHS).
        root_head, _, root_rest = root.partition("/")
        disallow_reason = _check_path_allowed(root_head.lower(), root_rest) if root_rest else None
        if disallow_reason:
            return json.dumps({"error": disallow_reason})

        result = await client.get_directory(root)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        data = result.get("result", {})
        
        files = []
        for item in data.get("files", []):
            files.append({
                "name": item.get("filename"),
                "size": item.get("size"),
                "modified": item.get("modified"),
            })
        
        dirs = []
        for item in data.get("dirs", []):
            dirs.append({
                "name": item.get("dirname"),
                "modified": item.get("modified"),
            })
        
        return json.dumps({
            "directory": root,
            "files": files,
            "subdirectories": dirs,
            "disk_usage": data.get("disk_usage", {})
        }, indent=2)
    
    @mcp.tool()
    async def list_gcode_files() -> str:
        """List all G-code files available for printing."""
        client = get_client()
        result = await client.list_files("gcodes")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        files = result.get("result", [])
        
        gcode_files = []
        for f in files:
            # API returns 'path' not 'filename'
            fname = f.get("path") or f.get("filename") or "unknown"
            gcode_files.append({
                "filename": fname,
                "size_mb": round(f.get("size", 0) / 1024 / 1024, 2),
                "modified": f.get("modified"),
            })
        
        # Sort by modified date, newest first
        gcode_files.sort(key=lambda x: x.get("modified", 0), reverse=True)
        
        return json.dumps({"gcode_files": gcode_files}, indent=2)
    
    @mcp.tool()
    async def read_file(
        filepath: str,
        max_lines: int = 500,
        root: Optional[str] = None,
        start_line: int = 1,
    ) -> str:
        """
        Read contents of a file from the printer.

        Args:
            filepath: Path to the file. Either a 'root/relative/path' (e.g.
                'gcodes/sub/file.gcode', 'config/printer.cfg', 'logs/klippy.log',
                'timelapse/video.mp4'), or a path relative to `root` when that
                argument is given. Bare filenames default to the 'config' root.
            max_lines: Maximum lines to return (default: 500, to avoid huge responses)
            root: Optional explicit Moonraker root ('config', 'gcodes', 'logs',
                'timelapse'). Inferred from filepath's leading segment when omitted.
            start_line: 1-indexed line to begin at (default: 1). Use with max_lines
                to page through files longer than max_lines. The response reports
                next_start_line when more content remains.

        For G-code files, use get_gcode_metadata instead for analysis.
        """
        client = get_client()

        resolved_root, relative_path = _infer_root_and_path(filepath, root)

        disallow_reason = _check_path_allowed(resolved_root, relative_path)
        if disallow_reason:
            return json.dumps({"error": disallow_reason})

        content, error = await fetch_file_text(client, resolved_root, relative_path)
        if error:
            return json.dumps({"error": error})

        lines = content.split('\n')
        total_lines = len(lines)

        begin = max(start_line, 1) - 1
        if begin >= total_lines:
            return json.dumps({
                "filepath": f"{resolved_root}/{relative_path}",
                "content": "",
                "lines": 0,
                "start_line": start_line,
                "truncated": False,
                "total_lines": total_lines,
                "note": f"start_line {start_line} is past end of file ({total_lines} lines)",
            })

        window = lines[begin:begin + max_lines]
        end = begin + len(window)
        truncated = end < total_lines

        payload = {
            "filepath": f"{resolved_root}/{relative_path}",
            "content": '\n'.join(window),
            "lines": len(window),
            "start_line": begin + 1,
            "end_line": end,
            "truncated": truncated,
            "total_lines": total_lines,
        }
        if truncated:
            payload["next_start_line"] = end + 1

        return json.dumps(payload)
    
    @mcp.tool()
    async def write_file(filepath: str, content: str, pin: str, root: Optional[str] = None) -> str:
        """
        Write content to a file on the printer.
        REQUIRES: Admin PIN for safety.

        Args:
            filepath: Path, either relative to `root` (e.g. 'macros/custom.cfg' under
                the default 'config' root) or using a 'root/relative/path' convention
                (e.g. 'gcodes/sub/file.gcode').
            content: File content to write
            pin: Admin PIN to authorize write operation
            root: Optional explicit Moonraker root ('config', 'gcodes', 'logs',
                'timelapse'). Defaults to 'config' when not inferable from filepath.

        WARNING: Be careful writing to printer.cfg - invalid config can prevent Klipper from starting.
        """
        if not verify_pin(pin, config.ADMIN_PIN):
            return json.dumps({"error": "Invalid PIN. Write operation not authorized."})

        resolved_root, relative_path = _infer_root_and_path(filepath, root)

        disallow_reason = _check_path_allowed(resolved_root, relative_path)
        if disallow_reason:
            return json.dumps({"error": disallow_reason})

        client = get_client()

        try:
            result = await upload_to_moonraker(client, resolved_root, relative_path, content)
        except Exception as e:
            return json.dumps({"error": str(e)})

        if "error" in result:
            return json.dumps({"error": result["error"]})

        return json.dumps({
            "success": True,
            "filepath": f"{resolved_root}/{relative_path}",
            "moonraker_result": result.get("result"),
            "message": "File written successfully"
        })
    
    @mcp.tool()
    async def delete_file(filepath: str, pin: str, root: Optional[str] = None) -> str:
        """
        Delete a file from the printer.
        REQUIRES: Admin PIN for safety.

        Args:
            filepath: Path to file (e.g., 'gcodes/old_print.gcode')
            pin: Admin PIN to authorize deletion
            root: Optional explicit Moonraker root ('config', 'gcodes', 'logs',
                'timelapse'). Inferred from filepath's leading segment when omitted.
        """
        if not verify_pin(pin, config.ADMIN_PIN):
            return json.dumps({"error": "Invalid PIN. Delete operation not authorized."})

        resolved_root, relative_path = _infer_root_and_path(filepath, root)

        disallow_reason = _check_path_allowed(resolved_root, relative_path)
        if disallow_reason:
            return json.dumps({"error": disallow_reason})

        client = get_client()

        result = await client.delete_file(f"{resolved_root}/{relative_path}")

        if "error" in result:
            return json.dumps({"error": result["error"]})

        return json.dumps({"success": True, "deleted": f"{resolved_root}/{relative_path}"})
    
    @mcp.tool()
    async def get_gcode_metadata(filename: str) -> str:
        """
        Get metadata for a G-code file (estimated time, filament, thumbnails, etc).
        
        Args:
            filename: G-code filename
        """
        disallow_reason = _check_path_allowed("gcodes", filename)
        if disallow_reason:
            return json.dumps({"error": disallow_reason})

        client = get_client()
        result = await client.get_file_metadata(filename)
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        metadata = result.get("result", {})
        
        # Format useful info
        formatted = {
            "filename": metadata.get("filename"),
            "size_mb": round(metadata.get("size", 0) / 1024 / 1024, 2),
            "modified": metadata.get("modified"),
            "slicer": metadata.get("slicer"),
            "slicer_version": metadata.get("slicer_version"),
            "estimated_time": metadata.get("estimated_time"),
            "estimated_time_formatted": format_time(metadata.get("estimated_time")),
            "filament_total_mm": metadata.get("filament_total"),
            "filament_total_grams": metadata.get("filament_weight_total"),
            "layer_height": metadata.get("layer_height"),
            "first_layer_height": metadata.get("first_layer_height"),
            "object_height": metadata.get("object_height"),
            "first_layer_bed_temp": metadata.get("first_layer_bed_temp"),
            "first_layer_extr_temp": metadata.get("first_layer_extr_temp"),
            "nozzle_diameter": metadata.get("nozzle_diameter"),
            "has_thumbnails": len(metadata.get("thumbnails", [])) > 0,
        }
        
        return json.dumps(formatted, indent=2)
    
    @mcp.tool()
    async def list_config_files() -> str:
        """List all configuration files (*.cfg) in the config directory."""
        client = get_client()
        result = await client.get_directory("config")
        
        if "error" in result:
            return json.dumps({"error": result["error"]})
        
        data = result.get("result", {})
        
        config_files = []
        for item in data.get("files", []):
            filename = item.get("filename", "")
            if filename.endswith(".cfg"):
                config_files.append({
                    "name": filename,
                    "size": item.get("size"),
                    "modified": item.get("modified"),
                })
        
        return json.dumps({"config_files": config_files}, indent=2)
    
    @mcp.tool()
    async def search_in_file(filepath: str, search_term: str, root: Optional[str] = None) -> str:
        """
        Search for a term in a file and return matching lines.

        Args:
            filepath: Path to file, either 'root/relative/path' (e.g. 'config/printer.cfg',
                'gcodes/sub/file.gcode', 'logs/klippy.log') or relative to `root` when given.
            search_term: Text to search for (case-insensitive)
            root: Optional explicit Moonraker root ('config', 'gcodes', 'logs', 'timelapse').
                Inferred from filepath's leading segment when omitted.
        """
        # First read the file
        client = get_client()

        resolved_root, relative_path = _infer_root_and_path(filepath, root)

        disallow_reason = _check_path_allowed(resolved_root, relative_path)
        if disallow_reason:
            return json.dumps({"error": disallow_reason})

        content, error = await fetch_file_text(client, resolved_root, relative_path)
        if error:
            return json.dumps({"error": error})

        matches = []
        search_lower = search_term.lower()

        for i, line in enumerate(content.split('\n'), 1):
            if search_lower in line.lower():
                matches.append({
                    "line_number": i,
                    "content": line.strip()
                })

        return json.dumps({
            "filepath": f"{resolved_root}/{relative_path}",
            "search_term": search_term,
            "matches": matches,
            "match_count": len(matches)
        }, indent=2)


def format_time(seconds: float) -> str:
    """Format seconds into human readable time."""
    if not seconds:
        return "unknown"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"
