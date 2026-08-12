"""
Disk persistence for the FMEA page's rows, so an engineer's edits (S/O/D
scores, maintenance tasks, and rows they've added) survive closing and
reopening the app - unlike the rest of this app's state, which lives only in
st.session_state and resets on a fresh session.

Written to a plain JSON file under data/ (same on-disk shape as the existing
"Save FMEA (.json)" download button already produces), rather than a
database, since this is a single-user local app and the existing manual
export/import already established JSON as this page's save format.
"""
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_STATE_PATH = os.path.join(_DATA_DIR, "fmea_state.json")


def load_saved_rows():
    """Returns the persisted rows list, or None if no valid save exists yet
    (first run, or a corrupted/foreign file - falls back to the built-in
    defaults in that case rather than failing to load the page)."""
    if not os.path.isfile(_STATE_PATH):
        return None
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        rows = payload.get("rows")
        return rows if isinstance(rows, list) and rows else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def save_rows(rows):
    """Overwrites the persisted state with the current rows - write to a
    temp file and atomically replace, so a crash mid-write can't corrupt
    the previous good save."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    payload = {"format": "Electrical Equipment Protection Suite FMEA", "version": 1, "rows": rows}
    tmp_path = _STATE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, _STATE_PATH)
