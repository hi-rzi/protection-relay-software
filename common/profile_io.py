"""
Named profile save/load - lets an engineer save whatever's currently entered
under a preset (typically Custom Profile, but works for any preset) to a
JSON file under a name THEY choose, and reload it later.

Generic and prefix-based rather than hand-listing every field per equipment:
every widget on a page that belongs to the currently selected preset already
shares one key prefix (e.g. "GENERATOR__Custom Profile__" or
"EXCT_Custom__" - whatever that page's own widget keys use), the same
prefix the existing "↺ Reset to preset defaults" button already discovers
keys through. Saving/restoring just walks that same prefix, so this needs
no per-page field list to keep in sync as fields are added.
"""
import datetime
import json

import streamlit as st

# Transient, click-only widget state that can share a page's data-field key prefix (e.g. the
# "Reset to preset defaults" button lives at f"{key_prefix}reset_btn"). These aren't real
# settings - saving/restoring them is meaningless at best, and restoring one is a hard
# Streamlit error at worst if that widget has already been instantiated earlier in the same
# script run (as the Reset button always is, since it's drawn right before the profile
# uploader in the sidebar on every page). Excluded from both export and restore.
_EXCLUDED_SUFFIXES = (
    "reset_btn",
    "show_preview_btn", "preview_shown",
    "profile_name", "profile_upload", "profile_upload_hash", "save_profile_dl",
    "run_fault_sim",
)


def _is_data_key(full_key, key_prefix):
    suffix = full_key[len(key_prefix):]
    return not any(suffix == s or suffix.endswith(f"__{s}") for s in _EXCLUDED_SUFFIXES)


def safe_filename(name, fallback="profile"):
    cleaned = "".join(c if c.isalnum() or c in " _-" else "" for c in name).strip()
    cleaned = cleaned.replace(" ", "_")
    return cleaned or fallback


def export_profile_button(container, equipment_tag, key_prefix, default_name, button_key):
    """Renders a Profile Name text input + a Save Profile (.json) download button that
    dumps every session_state key currently under key_prefix (excluding transient,
    click-only widget state - see _EXCLUDED_SUFFIXES)."""
    profile_name = container.text_input(
        "Profile Name", value=default_name, key=f"{button_key}__profile_name",
        help="Used as the downloaded file's name, and shown when you reload it later.",
    )
    settings = {
        k[len(key_prefix):]: v for k, v in st.session_state.items()
        if k.startswith(key_prefix) and _is_data_key(k, key_prefix)
    }
    payload = {
        "format": "Electrical Equipment Protection Suite profile",
        "version": 1,
        "equipment": equipment_tag,
        "profile_name": profile_name,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "settings": settings,
    }
    container.download_button(
        "💾 Save Profile (.json)",
        data=json.dumps(payload, indent=2),
        file_name=f"{safe_filename(profile_name)}.json",
        mime="application/json",
        key=f"{button_key}__save_profile_dl",
        help="Saves every field currently under the selected preset above - typically used with Custom Profile selected, so you can reload your own entered values next time instead of re-typing them.",
    )


def restore_profile_uploader(container, equipment_tag, key_prefix, uploader_key):
    """Renders a file_uploader that restores a profile saved by export_profile_button()
    into the SAME key_prefix - call this before any widget under that prefix is drawn
    in this script run (e.g. in the sidebar, before the tabs)."""
    uploaded = container.file_uploader(
        "Load a saved profile (.json)", type=["json"], key=f"{uploader_key}__profile_upload",
        help="Restores a profile saved from this page earlier - applies to whichever preset is currently selected above (select Custom Profile first if that's what you saved).",
    )
    if uploaded is None:
        return
    hash_key = f"{uploader_key}__profile_upload_hash"
    file_hash = hash(uploaded.getvalue())
    if st.session_state.get(hash_key) == file_hash:
        return
    try:
        payload = json.loads(uploaded.getvalue().decode("utf-8"))
        if payload.get("format") != "Electrical Equipment Protection Suite profile":
            raise ValueError("This does not look like a profile saved from this app.")
        if payload.get("equipment") != equipment_tag:
            raise ValueError(f"This profile is for \"{payload.get('equipment')}\", not this equipment.")
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("The file does not contain a settings section.")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        container.error(f"Could not load profile: {exc}")
        st.session_state[hash_key] = file_hash
        return

    for suffix, value in settings.items():
        full_key = f"{key_prefix}{suffix}"
        if _is_data_key(full_key, key_prefix):
            st.session_state[full_key] = value
    st.session_state[hash_key] = file_hash
    st.toast(f"Loaded profile: {payload.get('profile_name', 'Untitled')}")
    st.rerun()
