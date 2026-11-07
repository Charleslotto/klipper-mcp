"""
Filesystem Tools
Read, write, list, upload, and delete files on the printer
"""
import json
import os
from typing import Optional
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


GCODE_EXTENSIONS = (".gcode", ".gco", ".g")
DEFAULT_UPLOAD_MAX_BYTES = 256 * 1024 * 1024
UPLOAD_DOWNLOAD_TIMEOUT_SECONDS = 300


def _upload_max_bytes() -> int:
    return int(getattr(config, "UPLOAD_MAX_BYTES", DEFAULT_UPLOAD_MAX_BYTES))


async def _download(url: str, max_bytes: int) -> bytes:
    """Download `url` (http/https only) into memory, refusing bodies over `max_bytes`."""
    import aiohttp
    from urllib.parse import urlparse

    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"Only http and https URLs are supported, got {url!r}")

    timeout = aiohttp.ClientTimeout(total=UPLOAD_DOWNLOAD_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise ValueError(f"Download failed: HTTP {response.status} from {url}")
            if response.content_length is not None and response.content_length > max_bytes:
                raise ValueError(f"File is {response.content_length} bytes, over the {max_bytes}-byte limit")
            chunks = []
            size = 0
            async for chunk in response.content.iter_chunked(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"File is over the {max_bytes}-byte limit")
                chunks.append(chunk)
            return b"".join(chunks)


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
    async def read_file(filepath: str, max_lines: int = 500, root: Optional[str] = None) -> str:
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

        For G-code files, use get_gcode_metadata instead for analysis.
        """
        client = get_client()

        resolved_root, relative_path = _infer_root_and_path(filepath, root)

        disallow_reason = _check_path_allowed(resolved_root, relative_path)
        if disallow_reason:
            return json.dumps({"error": disallow_reason})

        # Use Moonraker's file download endpoint
        session = await client._get_session()
        url = f"{client.base_url}/server/files/{resolved_root}/{relative_path}"

        try:
            async with session.get(url) as response:
                if response.status == 404:
                    return json.dumps({"error": f"File not found: {resolved_root}/{relative_path}"})
                response.raise_for_status()
                content = await response.text()

                # Limit lines
                lines = content.split('\n')
                if len(lines) > max_lines:
                    content = '\n'.join(lines[:max_lines])
                    truncated = True
                else:
                    truncated = False

                return json.dumps({
                    "filepath": f"{resolved_root}/{relative_path}",
                    "content": content,
                    "lines": min(len(lines), max_lines),
                    "truncated": truncated,
                    "total_lines": len(lines) if truncated else None
                })
        except Exception as e:
            return json.dumps({"error": str(e)})
    
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
    async def upload_gcode(filename: str, content: Optional[str] = None, url: Optional[str] = None) -> str:
        """
        Upload a G-code file to the printer's gcodes folder, ready for start_print.
        Pass exactly one of `content` (the G-code text, for small files) or `url`
        (an http/https link the printer downloads the file from, for large files).
        Only .gcode/.gco/.g files under gcodes/ are accepted; an existing file with
        the same name is replaced. Needs no PIN: it cannot touch config files.

        Args:
            filename: File name relative to the gcodes folder (e.g. 'toy_house.gcode' or 'parts/house.gcode')
            content: G-code text to upload
            url: http(s) URL to download the G-code from
        """
        if (content is None) == (url is None):
            return json.dumps({"error": "Pass exactly one of content or url."})

        relative_path = filename.strip()
        if relative_path.lower().startswith(("gcodes/", "gcode/")):
            relative_path = relative_path.split("/", 1)[1]
        if not relative_path.lower().endswith(GCODE_EXTENSIONS):
            return json.dumps({"error": f"Only {', '.join(GCODE_EXTENSIONS)} files can be uploaded, got {filename!r}"})
        if filename.startswith("/"):
            return json.dumps({"error": f"Invalid or disallowed path: {filename!r}"})

        disallow_reason = _check_path_allowed("gcodes", relative_path)
        if disallow_reason:
            return json.dumps({"error": disallow_reason})
        relative_path = os.path.normpath(relative_path)

        max_bytes = _upload_max_bytes()
        if url is not None:
            try:
                data = await _download(url, max_bytes)
            except Exception as e:
                return json.dumps({"error": str(e)})
        else:
            data = content
            if len(content.encode("utf-8")) > max_bytes:
                return json.dumps({"error": f"Content is over the {max_bytes}-byte limit"})

        size = len(data) if isinstance(data, bytes) else len(data.encode("utf-8"))

        try:
            result = await upload_to_moonraker(get_client(), "gcodes", relative_path, data)
        except Exception as e:
            return json.dumps({"error": str(e)})

        if "error" in result:
            return json.dumps({"error": result["error"]})

        return json.dumps({
            "success": True,
            "filepath": f"gcodes/{relative_path}",
            "bytes": size,
            "source": "url" if url is not None else "content",
            "moonraker_result": result.get("result", result),
            "message": "G-code uploaded; start it with start_print"
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

        session = await client._get_session()
        url = f"{client.base_url}/server/files/{resolved_root}/{relative_path}"

        try:
            async with session.get(url) as response:
                if response.status == 404:
                    return json.dumps({"error": f"File not found: {resolved_root}/{relative_path}"})
                response.raise_for_status()
                content = await response.text()

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
        except Exception as e:
            return json.dumps({"error": str(e)})


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
