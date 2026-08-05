"""
Shared security helpers used by server.py and (in later phases) tools/*.py.

This module is intentionally NOT registered as an MCP tool module - it exposes
no MCP tools, just plain helper functions. Do not add it to
tools/__init__.py's register_all_tools.
"""
import hmac


def sanitize_gcode_param(value, param_name="value"):
    """Reject control characters that would let a value break out of a single G-code line."""
    if value is None:
        return value
    s = str(value)
    if "\n" in s or "\r" in s or '"' in s:
        raise ValueError(f"Invalid character in {param_name}: newlines and double quotes are not allowed")
    return s


def verify_pin(provided, expected):
    """Constant-time PIN comparison. Returns False if either side is missing."""
    if provided is None or expected is None:
        return False
    return hmac.compare_digest(str(provided), str(expected))
