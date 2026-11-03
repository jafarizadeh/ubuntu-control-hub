"""Normalize a read-only LG webOS power response without guessing from ping."""
import ast


def classify_power_reply(raw):
    """Return on, off, screen_off, or unknown; never infer from LAN availability."""
    if not isinstance(raw, str) or not 0 < len(raw) <= 500:
        return "unknown"
    try:
        payload = ast.literal_eval(raw)
    except (ValueError, SyntaxError, TypeError, RecursionError, MemoryError):
        return "unknown"
    if not isinstance(payload, dict) or payload.get("returnValue") is not True:
        return "unknown"
    state = payload.get("state")
    if state == "Active":
        return "on"
    if state == "Screen Off":
        return "screen_off"
    if state in ("Suspend", "Power Off"):
        return "off"
    return "unknown"
