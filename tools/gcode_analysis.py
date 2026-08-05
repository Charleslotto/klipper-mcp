"""
G-code Analysis Tools
Parse and analyze G-code files
"""
import json
import re
from typing import Optional
import config
from moonraker import get_client


def register_gcode_analysis_tools(mcp):
    """Register G-code analysis tools."""
    
    @mcp.tool()
    async def analyze_gcode_file(filename: str) -> str:
        """
        Analyze a G-code file and extract key information.
        
        Args:
            filename: Name of the G-code file to analyze
        """
        client = get_client()
        
        # Get metadata first (already parsed by slicer)
        metadata = await client.get_file_metadata(filename)
        
        if "error" in metadata:
            return json.dumps({"error": metadata["error"]})
        
        meta = metadata.get("result", {})
        
        analysis = {
            "filename": filename,
            "slicer": {
                "name": meta.get("slicer"),
                "version": meta.get("slicer_version"),
            },
            "print_estimates": {
                "estimated_time": format_time(meta.get("estimated_time")),
                "layer_count": meta.get("layer_count"),
                "first_layer_height": meta.get("first_layer_height"),
                "layer_height": meta.get("layer_height"),
                "object_height": meta.get("object_height"),
            },
            "filament": {
                "total_mm": meta.get("filament_total"),
                "total_meters": round(meta.get("filament_total", 0) / 1000, 2),
                "weight_g": meta.get("filament_weight_total"),
                "type": meta.get("filament_type"),
                "name": meta.get("filament_name"),
            },
            "temperatures": {
                "first_layer_extruder": meta.get("first_layer_extr_temp"),
                "first_layer_bed": meta.get("first_layer_bed_temp"),
                "extruder": meta.get("nozzle_diameter"),
            },
            "speeds": {
                "max_speed": meta.get("max_speed"),
                "max_accel": meta.get("max_accel"),
            },
            "thumbnails": len(meta.get("thumbnails", [])) if meta.get("thumbnails") else 0,
            "size_bytes": meta.get("size"),
            "modified": meta.get("modified"),
        }
        
        return json.dumps(analysis, indent=2)
    
    @mcp.tool()
    async def extract_gcode_comments(filename: str, limit: int = 100) -> str:
        """
        Extract comment lines from a G-code file.
        Useful for finding slicer settings and notes.
        
        Args:
            filename: Name of the G-code file
            limit: Maximum number of comments to extract (default: 100)
        """
        client = get_client()

        # A comment extraction has no way to know up front where the comments
        # of interest live (many slicers interleave per-line comments like
        # ";TYPE:WALL-INNER" throughout the whole file, not just head/tail),
        # so a full read is still required here.
        try:
            content = await client.get_file_content_range("gcodes", filename)
        except Exception as e:
            status = getattr(e, "status", None)
            if status == 404:
                return json.dumps({"error": f"File not found: {filename}"})
            return json.dumps({"error": str(e)})

        comments = []
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith(';'):
                comments.append(line)
                if len(comments) >= limit:
                    break
        
        # Categorize comments
        settings_comments = [c for c in comments if '=' in c]
        info_comments = [c for c in comments if '=' not in c]
        
        return json.dumps({
            "filename": filename,
            "total_comments_found": len(comments),
            "settings_style_comments": settings_comments[:50],
            "info_comments": info_comments[:50],
        }, indent=2)
    
    @mcp.tool()
    async def get_gcode_move_stats(filename: str) -> str:
        """
        Analyze movement commands in a G-code file.
        Calculates travel vs extrusion statistics.
        
        Args:
            filename: Name of the G-code file
        """
        client = get_client()

        # Move statistics require scanning every G0/G1/G2/G3 line in the
        # file, so there's no reasonable byte range to narrow this to - a
        # full read is unavoidable here.
        try:
            content = await client.get_file_content_range("gcodes", filename)
        except Exception as e:
            status = getattr(e, "status", None)
            if status == 404:
                return json.dumps({"error": f"File not found: {filename}"})
            return json.dumps({"error": str(e)})

        stats = {
            "g0_moves": 0,  # Travel
            "g1_moves": 0,  # Linear with potential extrusion
            "g2_g3_arcs": 0,  # Arc moves
            "retractions": 0,
            "z_hops": 0,
            "temperature_changes": 0,
            "fan_changes": 0,
            "tool_changes": 0,
            "total_lines": 0,
        }
        
        prev_z = None
        prev_e = None
        
        for line in content.split('\n'):
            stats["total_lines"] += 1
            line = line.split(';')[0].strip().upper()
            
            if line.startswith('G0'):
                stats["g0_moves"] += 1
            elif line.startswith('G1'):
                stats["g1_moves"] += 1
                
                # Check for retraction (negative E)
                e_match = re.search(r'E([-\d.]+)', line)
                if e_match:
                    e_val = float(e_match.group(1))
                    if prev_e is not None and e_val < prev_e:
                        stats["retractions"] += 1
                    prev_e = e_val
                
                # Check for Z-hop
                z_match = re.search(r'Z([\d.]+)', line)
                if z_match:
                    z_val = float(z_match.group(1))
                    if prev_z is not None and z_val > prev_z + 0.1:  # More than 0.1mm up
                        stats["z_hops"] += 1
                    prev_z = z_val
                    
            elif line.startswith(('G2', 'G3')):
                stats["g2_g3_arcs"] += 1
            elif line.startswith(('M104', 'M109', 'M140', 'M190')):
                stats["temperature_changes"] += 1
            elif line.startswith(('M106', 'M107')):
                stats["fan_changes"] += 1
            elif line.startswith('T') and line[1:].split()[0].isdigit():
                stats["tool_changes"] += 1
        
        return json.dumps({
            "filename": filename,
            "statistics": stats,
            "analysis": {
                "travel_percent": round(stats["g0_moves"] / max(stats["g0_moves"] + stats["g1_moves"], 1) * 100, 1),
                "uses_arcs": stats["g2_g3_arcs"] > 0,
                "is_multi_tool": stats["tool_changes"] > 0,
            }
        }, indent=2)
    
    @mcp.tool()
    async def find_gcode_section(
        filename: str,
        search_text: str,
        context_lines: int = 10
    ) -> str:
        """
        Find a section in G-code containing specific text.
        
        Args:
            filename: Name of the G-code file
            search_text: Text to search for (case-insensitive)
            context_lines: Number of lines to show around match (default: 10)
        """
        client = get_client()

        # Free-text search has no way to know where a match will be without
        # scanning the whole file, so a full read is unavoidable here.
        try:
            content = await client.get_file_content_range("gcodes", filename)
        except Exception as e:
            status = getattr(e, "status", None)
            if status == 404:
                return json.dumps({"error": f"File not found: {filename}"})
            return json.dumps({"error": str(e)})

        lines = content.split('\n')
        search_lower = search_text.lower()
        
        matches = []
        for i, line in enumerate(lines):
            if search_lower in line.lower():
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                
                context = []
                for j in range(start, end):
                    prefix = ">>> " if j == i else "    "
                    context.append(f"{j + 1}: {prefix}{lines[j]}")
                
                matches.append({
                    "line_number": i + 1,
                    "matched_line": line.strip(),
                    "context": context
                })
                
                if len(matches) >= 5:  # Limit to 5 matches
                    break
        
        return json.dumps({
            "filename": filename,
            "search_text": search_text,
            "matches_found": len(matches),
            "matches": matches
        }, indent=2)
    
    @mcp.tool()
    async def get_layer_gcode(filename: str, layer_number: int) -> str:
        """
        Extract G-code for a specific layer.
        
        Args:
            filename: Name of the G-code file
            layer_number: Layer number to extract (1-based)
        """
        client = get_client()

        # Layer markers could in principle be located via a proportional
        # byte-offset estimate (layer_number / layer_count * file_size), but
        # slicers don't emit uniform-size layers and marker formats vary
        # (0- vs 1-indexed, different comment styles), so a wrong estimate
        # would silently return the wrong layer or incorrect line numbers.
        # Without a precomputed layer->byte-offset index this isn't safely
        # narrowable, so a full read is used here.
        try:
            content = await client.get_file_content_range("gcodes", filename)
        except Exception as e:
            status = getattr(e, "status", None)
            if status == 404:
                return json.dumps({"error": f"File not found: {filename}"})
            return json.dumps({"error": str(e)})

        lines = content.split('\n')

        # Find layer markers (common patterns)
        layer_patterns = [
            rf';LAYER:{layer_number}',  # Cura
            rf'; layer {layer_number}',  # PrusaSlicer/SuperSlicer
            rf';LAYER_CHANGE',  # Some slicers
            rf';Z:{layer_number}',
        ]
        
        current_layer = 0
        layer_start = None
        layer_end = None
        
        for i, line in enumerate(lines):
            # Check for layer change
            if ';LAYER:' in line.upper() or '; LAYER ' in line.upper():
                if layer_start is not None and current_layer == layer_number:
                    layer_end = i
                    break
                
                # Try to extract layer number
                match = re.search(r'(?:LAYER:|LAYER\s+)(\d+)', line.upper())
                if match:
                    current_layer = int(match.group(1))
                    if current_layer == layer_number:
                        layer_start = i
        
        if layer_start is None:
            return json.dumps({
                "error": f"Layer {layer_number} not found",
                "hint": "Layer numbering varies by slicer (may start at 0 or 1)"
            })
        
        if layer_end is None:
            layer_end = min(layer_start + 1000, len(lines))  # Cap at 1000 lines
        
        layer_lines = lines[layer_start:layer_end]
        
        return json.dumps({
            "filename": filename,
            "layer_number": layer_number,
            "start_line": layer_start + 1,
            "end_line": layer_end,
            "line_count": len(layer_lines),
            "gcode": '\n'.join(layer_lines[:500])  # Limit output size
        }, indent=2)
    
    @mcp.tool()
    async def validate_gcode(filename: str) -> str:
        """
        Validate G-code file for common issues.

        Args:
            filename: Name of the G-code file to validate
        """
        client = get_client()

        # Only the first ~500 lines and last ~100 lines are actually inspected
        # below, so for large files fetch bounded head/tail byte ranges via
        # get_file_content_range() instead of downloading the whole file.
        HEAD_BYTES = 65536   # comfortably covers 500 lines of gcode
        TAIL_BYTES = 16384   # comfortably covers 100 lines of gcode

        file_size = None
        metadata = await client.get_file_metadata(filename)
        if "error" not in metadata:
            file_size = metadata.get("result", {}).get("size")

        try:
            if file_size and file_size > HEAD_BYTES + TAIL_BYTES:
                head_content = await client.get_file_content_range(
                    "gcodes", filename, start=0, end=HEAD_BYTES - 1
                )
                tail_start = max(file_size - TAIL_BYTES, HEAD_BYTES)
                tail_content = await client.get_file_content_range(
                    "gcodes", filename, start=tail_start
                )

                head_lines = head_content.split('\n')[:500]
                tail_lines_all = tail_content.split('\n')
                # The tail range almost certainly starts mid-line; drop the
                # (possibly partial) first line of the tail chunk.
                if len(tail_lines_all) > 1:
                    tail_lines_all = tail_lines_all[1:]
                tail_lines = tail_lines_all[-100:]

                sample_line_count = len(head_lines) + len(tail_lines_all)
                sample_byte_count = len(head_content) + len(tail_content)
                avg_bytes_per_line = (sample_byte_count / sample_line_count) if sample_line_count else 1
                total_lines = int(file_size / avg_bytes_per_line) if avg_bytes_per_line else 0
                total_lines_exact = False
            else:
                content = await client.get_file_content_range("gcodes", filename)
                all_lines = content.split('\n')
                head_lines = all_lines[:500]
                tail_lines = all_lines[-100:]
                total_lines = len(all_lines)
                total_lines_exact = True
        except Exception as e:
            status = getattr(e, "status", None)
            if status == 404:
                return json.dumps({"error": f"File not found: {filename}"})
            return json.dumps({"error": str(e)})

        issues = []
        warnings = []

        has_start_gcode = False
        has_end_gcode = False
        has_home = False
        has_temp_set = False
        has_bed_temp = False
        max_temp = 0
        max_bed_temp = 0

        for i, line in enumerate(head_lines):  # Check first 500 lines
            line_upper = line.strip().upper()

            if line_upper.startswith('G28'):
                has_home = True
            elif line_upper.startswith(('M104', 'M109')):
                has_temp_set = True
                match = re.search(r'S(\d+)', line_upper)
                if match:
                    temp = int(match.group(1))
                    max_temp = max(max_temp, temp)
                    if temp > 300:
                        issues.append(f"Line {i+1}: Unusually high hotend temp: {temp}°C")
            elif line_upper.startswith(('M140', 'M190')):
                has_bed_temp = True
                match = re.search(r'S(\d+)', line_upper)
                if match:
                    temp = int(match.group(1))
                    max_bed_temp = max(max_bed_temp, temp)
                    if temp > 120:
                        warnings.append(f"Line {i+1}: High bed temp: {temp}°C")

            # Check for start gcode marker
            if 'START' in line_upper and 'GCODE' in line_upper:
                has_start_gcode = True

        # Check last 100 lines for end gcode
        for i, line in enumerate(tail_lines):
            if 'END' in line.upper() and 'GCODE' in line.upper():
                has_end_gcode = True
                break
            if line.strip().upper() in ['M84', 'M104 S0', 'M140 S0']:
                has_end_gcode = True

        # Compile validation results
        if not has_home:
            warnings.append("No G28 homing command found in first 500 lines")

        if not has_temp_set:
            issues.append("No hotend temperature command found")

        return json.dumps({
            "filename": filename,
            "valid": len(issues) == 0,
            "checks": {
                "has_home_command": has_home,
                "has_start_gcode_marker": has_start_gcode,
                "has_end_gcode": has_end_gcode,
                "has_hotend_temp": has_temp_set,
                "has_bed_temp": has_bed_temp,
                "max_hotend_temp": max_temp,
                "max_bed_temp": max_bed_temp,
            },
            "issues": issues,
            "warnings": warnings,
            "total_lines": total_lines,
            "total_lines_exact": total_lines_exact,
        }, indent=2)


def format_time(seconds: float) -> str:
    """Format seconds into human-readable time."""
    if not seconds:
        return "unknown"
    
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"
