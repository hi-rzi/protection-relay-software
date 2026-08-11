"""
Registry of user-defined custom relays (views/custom_relays.py) - unlike every
other equipment page (one fixed relay per page), this page lets a user create
any number of relay definitions and only renders the CURRENTLY SELECTED one's
widgets each rerun (the rest stay off-screen entirely, not just CSS-hidden
like the section-nav pattern elsewhere).

That matters because Streamlit purges a widget's session_state entry at the
end of any rerun in which that widget isn't instantiated - so a plain
`key=f"{relay_id}__field"` scheme (fine for every OTHER page, which always
renders its one relay's widgets every rerun) would silently wipe a relay's
settings the moment the user switched to a different relay and back.

The fix: keep each relay's actual field values in a plain dict under
FIELDS_KEY, which is never itself a widget key and so is immune to that
purge. Widgets for the selected relay seed their session_state key from this
dict on first appearance (see views/custom_relays.py's `ensure()` helper)
and the view writes each widget's return value straight back into the dict
every rerun - so the dict, not the ephemeral widget key, is the source of
truth that survives switching relays.

export_profile_button()/restore_profile_uploader() (common/profile_io.py)
still work unmodified: they walk session_state by the f"{relay_id}__" widget
key prefix, which is always populated correctly for whichever relay is
currently selected and rendered.
"""
import uuid

import streamlit as st

REGISTRY_KEY = "custom_relay_ids"
FIELDS_KEY = "custom_relay_fields"


def _all_fields():
    return st.session_state.setdefault(FIELDS_KEY, {})


def get_fields(rid):
    """The persistent field dict for one relay - create/read/write freely,
    it survives that relay not being the selected/rendered one."""
    return _all_fields().setdefault(rid, {})


def list_relays():
    """Returns [(id, display_name), ...] in creation order."""
    ids = st.session_state.setdefault(REGISTRY_KEY, [])
    fields = _all_fields()
    return [(rid, fields.get(rid, {}).get("display_name", "Untitled Relay")) for rid in ids]


def create_relay(display_name="New Custom Relay"):
    ids = st.session_state.setdefault(REGISTRY_KEY, [])
    rid = f"cr_{uuid.uuid4().hex[:8]}"
    ids.append(rid)
    get_fields(rid)["display_name"] = display_name
    return rid


def delete_relay(rid):
    ids = st.session_state.setdefault(REGISTRY_KEY, [])
    if rid in ids:
        ids.remove(rid)
    _all_fields().pop(rid, None)
    # Sweep any live widget-key session_state for this relay too (only
    # present if it was the selected/rendered one at the time of deletion).
    for key in [key for key in st.session_state if key.startswith(f"{rid}__")]:
        del st.session_state[key]
