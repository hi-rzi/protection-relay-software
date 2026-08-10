"""
FD Fan (Forced Draft Fan) service glue for the Flask page. Just wires the
shared SR469/87M logic in fan_motor_common.py — this motor has no
IFC66KD2A/HFC22B2A relay stack (not confirmed/modeled per
common/motor_fan_page.py / views/motor_fd_fan.py).
"""
from web.services import fan_motor_common as common

build_relay = common.build_relay
build_diff87m = common.build_diff87m
settings_sheet_rows = common.settings_sheet_rows
settings_sheet_rows_87m = common.settings_sheet_rows_87m


def recompute(payload):
    out, relay, diff87m_relay = common.recompute_common(payload)
    return out
