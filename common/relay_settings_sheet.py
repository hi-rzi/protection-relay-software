import pandas as pd


def render_settings_sheet(container, relay_type, rows, key_prefix):
    """
    rows: list of (Parameter, Value) tuples using the SAME terminology as
    that relay's own instruction manual / settings summary - e.g. "T1 (HV
    Tap)", "Bias (Tau, %)", "51 Tap (A sec.)".

    This is a settings CHECKLIST for an engineer to manually enter into the
    relay's own settings software or front-panel HMI - it is deliberately
    NOT a native, importable project file for that software. This app has
    no access to each vendor's proprietary settings-file format (e.g. GE's
    EnerVista/URPC project files), so producing one and calling it
    "importable" would risk being silently wrong in a way that's much
    harder to catch than a plain documentation mismatch - it could put
    wrong settings directly into a relay in service.
    """
    container.markdown("#### Relay-Ready Settings Sheet")
    container.caption(
        f"A checklist of every setting, named exactly as the {relay_type} instruction "
        "manual/settings summary names it, for manual entry into the relay's own settings "
        "software or front-panel HMI. This is a reference sheet, not an importable relay "
        "project file — this app doesn't have access to the vendor's proprietary settings-file "
        "format, and guessing at one risks silently wrong settings reaching a relay in service."
    )
    df = pd.DataFrame(rows, columns=["Parameter", "Value"])
    container.dataframe(df, use_container_width=True, hide_index=True)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    container.download_button(
        "Download Settings Sheet (.csv)", data=csv_bytes,
        file_name=f"{key_prefix}_Settings_Sheet.csv", mime="text/csv",
        key=f"{key_prefix}_settings_sheet_dl",
    )
