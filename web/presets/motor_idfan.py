"""
PRESETS dict, ported verbatim from views/motor_idfan.py (lines 39-65).
Source: Motor_Protection_Setting_-_IDFAN.pdf, Sections 5.1 / 5.1.1 / 5.1.2 / 5.13
(GE IFC66KD2A 50/50/51, GE HFC22B2A backup instantaneous, GE HFC23C1A 87M
self-balancing differential — Induced Draft Fan, 10,001HP, 13.2kV).
"""

PRESETS = {
    "POMI ID Fan 50/50/51 (7EM/8EM) - 10,001HP": {
        "motor_fla": 392, "locked_rotor_amps": 1869, "locked_rotor_amps_80pct": 1495,
        "accel_time_100": 12.6, "accel_time_80": 19.0,
        "safe_stall_100_ambient": 31.0, "safe_stall_80_ambient": 48.0,
        "safe_stall_100_hot": 28.0, "safe_stall_80_hot": 43.0,
        "ct_ratio": 600, "ct_sec": 5.0,
        "tap_51": 4.0, "time_dial": 4.5,
        "pickup_50a": 47.0, "dropout_50b": 3.3, "target_seal_in": 0.2,
        "enable_backup": True, "backup_ct_ratio": 3000, "backup_pickup_50": 10.0,
        # 87M self-balancing differential (Section 5.13) - Induced Draft Fans use a
        # different, larger CT (100/5, Low tap) than every other motor (50/5, High tap).
        # Pickup is 20A primary either way: 20/(100/5) = 1.0A secondary here.
        "diff87m_ct_ratio": 100, "diff87m_pickup_sec": 1.0,
    },
    "Custom Profile": {
        "motor_fla": 100, "locked_rotor_amps": 600, "locked_rotor_amps_80pct": 480,
        "accel_time_100": 10.0, "accel_time_80": 15.0,
        "safe_stall_100_ambient": 20.0, "safe_stall_80_ambient": 30.0,
        "safe_stall_100_hot": 18.0, "safe_stall_80_hot": 27.0,
        "ct_ratio": 100, "ct_sec": 5.0,
        "tap_51": 4.0, "time_dial": 5.0,
        "pickup_50a": 50.0, "dropout_50b": 3.0, "target_seal_in": 0.2,
        "enable_backup": True, "backup_ct_ratio": 200, "backup_pickup_50": 10.0,
        "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
    },
}

# IFC66KD2A 51 element discrete tap positions (A secondary), per GEK-49949.
TAP_51_OPTIONS = [2.5, 2.8, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.5]

# Standard CT secondary ratings offered across every relay on this page.
CT_SEC_OPTIONS = [1.0, 5.0]
