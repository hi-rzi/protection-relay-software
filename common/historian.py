import pandas as pd
import plotly.graph_objects as go


def render_historian_overlay(container, key_prefix, reference_lines=None):
    """
    Lets the user upload a CSV of real measured operating currents (a
    historian/SCADA export) and overlays them as a time series against this
    relay's key current thresholds - a check against REAL observed loading,
    not just the synthetic test points used elsewhere on this page.

    Expected CSV: a "timestamp" column plus one or more numeric current
    columns (any column names - each becomes its own line on the chart).
    Deliberately does NOT attempt to recompute this relay's own I_op/I_rest
    from this data: a general historian only logs current MAGNITUDE, not
    the phase angle the differential relays' math needs, so overlaying real
    magnitudes against RATED/PICKUP reference lines is the honest
    comparison this kind of data actually supports.

    reference_lines: optional list of (label, value) tuples drawn as
    horizontal dashed reference lines (e.g. rated current, pickup level).
    """
    container.markdown("#### Historian Data Overlay")
    container.caption(
        "Upload a CSV export of real measured currents (a \"timestamp\" column plus one or "
        "more numeric current columns) to see actual plant operation against this relay's "
        "rated/pickup levels - a check against real conditions, not just synthetic test "
        "points. Historian exports only log current magnitude, not phase angle, so this "
        "overlays magnitude against thresholds rather than recomputing the relay's own trip "
        "math from this data."
    )
    uploaded = container.file_uploader("Upload historian CSV", type=["csv"], key=f"{key_prefix}_historian_csv")
    if uploaded is None:
        return

    try:
        df = pd.read_csv(uploaded)
    except Exception as exc:
        container.error(f"Could not read this CSV: {exc}")
        return

    if "timestamp" not in df.columns:
        container.error("The CSV must have a \"timestamp\" column.")
        return

    numeric_cols = [c for c in df.columns if c != "timestamp" and pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        container.error("No numeric current columns found besides \"timestamp\".")
        return

    x_axis = df["timestamp"]
    try:
        x_axis = pd.to_datetime(df["timestamp"])
    except (ValueError, TypeError):
        container.warning("Could not parse \"timestamp\" as dates — plotting against row order instead.")

    fig = go.Figure()
    for col in numeric_cols:
        fig.add_trace(go.Scatter(x=x_axis, y=df[col], mode="lines", name=col))
    for label, value in (reference_lines or []):
        if value is None:
            continue
        fig.add_hline(y=value, line=dict(dash="dash", color="#DC2626"), annotation_text=label)
    fig.update_layout(
        title="Historian Current vs. Relay Thresholds",
        xaxis_title="Time", yaxis_title="Current (A)",
        template="plotly_white", height=450,
    )
    container.plotly_chart(fig, use_container_width=True)

    stats_rows = [
        {"Column": col, "Min (A)": f"{df[col].min():.1f}", "Max (A)": f"{df[col].max():.1f}", "Mean (A)": f"{df[col].mean():.1f}"}
        for col in numeric_cols
    ]
    container.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)
