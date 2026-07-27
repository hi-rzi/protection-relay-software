"""
GSUT Differential Protection - Dash edition, full feature parity with
views/transformer_gsut.py (Streamlit). Same engines/transformer.py math.
"""
import base64
import io

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, ctx, dash_table, dcc, html

from common.ui_helpers import MR_CT_TAPS_2000_5
from engines.transformer import TransformerDifferentialRelay, winding_internal_vector, raw_input_for_internal_vector

dash.register_page(__name__, path="/transformer_gsut", name="Generator Step-Up Transformer", category="Transformer")

PRESET = {
    "mva": 873.6,
    "kv_hv": 538.125, "kv_lv": 23.0,
    "ct_hv": 1600, "ct_lv": 24000, "ct_sec": 5.0,
    "tap_hv": 1.0, "tap_lv": 1.1,
    "bias": 30, "min_operate": 30, "hoc": 5,
}
PHASES = ["Phase A", "Phase B", "Phase C"]


def build_relay(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity):
    windings = [
        {"name": "HV (525kV)", "kv": kv_hv, "ct_ratio": ct_hv, "ct_secondary_rating": ct_sec, "tap": tap_hv, "ct_connection": "DELTA"},
        {"name": "LV (23kV)", "kv": kv_lv, "ct_ratio": ct_lv, "ct_secondary_rating": ct_sec, "tap": tap_lv, "ct_connection": "WYE"},
    ]
    return TransformerDifferentialRelay(
        mva_rated=mva, windings=windings,
        bias_pct=bias, min_operate_pct=min_op, hoc_multiple=hoc,
        convention=convention, ct_polarity=polarity,
    )


def labeled(label, component):
    return html.Div([dbc.Label(label, className="small text-muted mb-0"), component], className="mb-3")


def slider(id_, min_, max_, step, value):
    return dcc.Slider(id=id_, min=min_, max=max_, step=step, value=value,
                       tooltip={"placement": "bottom", "always_visible": True}, marks=None)


def sidebar():
    return dbc.Card(dbc.CardBody([
        html.H5("Equipment Presets"),
        html.P("POMI GSUT 87GT7/87GT8 — 873.6 MVA", className="small text-muted"),
        html.H6("Protection Characteristic", className="mt-3"),
        labeled("Bias, τ (%)", slider("bias", 5, 60, 1, PRESET["bias"])),
        labeled("Minimum Operate (%)", slider("min_operate", 5, 60, 1, PRESET["min_operate"])),
        labeled("HOC (x tap current)", slider("hoc", 2, 20, 0.5, PRESET["hoc"])),
        dbc.Button("Advanced Settings", id="adv_toggle", size="sm", color="secondary", outline=True, className="mt-2"),
        dbc.Collapse(id="adv_collapse", is_open=False, children=[
            html.Hr(),
            html.H6("Transformer & CT Spec"),
            labeled("Transformer Rating (MVA)", dbc.Input(id="mva", type="number", value=PRESET["mva"], step=0.1)),
            labeled("HV Rated Voltage (kV)", dbc.Input(id="kv_hv", type="number", value=PRESET["kv_hv"], step=1)),
            labeled("HV CT Ratio Tap (Multi-Ratio, Primary A)", dcc.Dropdown(
                id="ct_hv", clearable=False, value=PRESET["ct_hv"],
                options=[{"label": f"{t}:5", "value": t} for t in MR_CT_TAPS_2000_5]
            )),
            labeled("LV Rated Voltage (kV)", dbc.Input(id="kv_lv", type="number", value=PRESET["kv_lv"], step=0.1)),
            labeled("LV CT Ratio (Primary A)", dbc.Input(id="ct_lv", type="number", value=PRESET["ct_lv"], step=100)),
            labeled("CT Secondary Rating (A)", dcc.Dropdown(
                id="ct_sec", clearable=False, value=PRESET["ct_sec"],
                options=[{"label": "1 A", "value": 1.0}, {"label": "5 A", "value": 5.0}]
            )),
            html.H6("CT Matching Taps", className="mt-3"),
            labeled("HV Tap (T1)", slider("tap_hv", 0.4, 2.18, 0.01, PRESET["tap_hv"])),
            labeled("LV Tap (T2)", slider("tap_lv", 0.4, 2.18, 0.01, PRESET["tap_lv"])),
            html.H6("Wiring & Convention", className="mt-3"),
            labeled("Restraint Standard", dbc.RadioItems(
                id="convention", value="IEEE", inline=True,
                options=[{"label": "IEEE", "value": "IEEE"}, {"label": "IEC", "value": "IEC"}]
            )),
            labeled("Polarity Reference", dbc.RadioItems(
                id="polarity", value="OPPOSITE", inline=True,
                options=[{"label": "OPPOSITE", "value": "OPPOSITE"}, {"label": "SAME", "value": "SAME"}]
            )),
        ]),
        dbc.Alert(
            "Delta-connected CTs get an automatic √3 magnitude step-up and a +30° phase "
            "shift — the standard compensation for a Wye/Delta power transformer.",
            color="light", className="small mt-3"
        ),
    ]), className="h-100")


def phase_row(phase, idx):
    def_ang_hv = -120.0 * idx
    p = phase.split()[-1].lower()
    return dbc.Row([
        dbc.Col(html.B(phase), width=1, className="d-flex align-items-center"),
        dbc.Col(labeled("HV Amps (A)", dbc.Input(id=f"i_hv_{p}", type="number", value=0.0)), width=2),
        dbc.Col(labeled("HV Angle (°)", dbc.Input(id=f"a_hv_{p}", type="number", value=def_ang_hv)), width=2),
        dbc.Col(labeled("LV Amps (A)", dbc.Input(id=f"i_lv_{p}", type="number", value=0.0)), width=2),
        dbc.Col(labeled("LV Angle (°)", dbc.Input(id=f"a_lv_{p}", type="number", value=0.0)), width=2),
    ], className="mb-2")


def sld_tab():
    return dbc.Card(dbc.CardBody([
        html.H5("Protection Zone — Single Line Diagram"),
        html.P("Shows where the CTs sit and what falls inside the 87GT differential zone.", className="small text-muted"),
        html.Img(src=dash.get_asset_url("sld/gsut.png"), style={"width": "100%", "maxWidth": "700px"}),
    ]))


def live_sim_tab():
    return html.Div([
        dbc.Card(dbc.CardBody([
            html.H5("Live Vector Simulation"),
            html.P("Winding Operating Phase Inputs", className="fw-bold mb-2"),
            html.Div(id="rated_info", className="mb-2"),
            phase_row("Phase A", 0),
            phase_row("Phase B", 1),
            phase_row("Phase C", 2),
            html.Div(id="trip-banner", className="alert mt-2", children="—"),
            html.Div(id="verdict-table", className="mt-3"),
        ]), className="my-3"),
        dbc.Card(dbc.CardBody([
            html.H5("Differential Bias Characteristic Curve"),
            dcc.Graph(id="char-curve"),
        ])),
    ])


def commissioning_tab():
    cols = []
    default_restraints = {"Phase A": 0.5, "Phase B": 2.5, "Phase C": 5.0}
    for phase in PHASES:
        p = phase.split()[-1].lower()
        cols.append(dbc.Col([
            html.B(phase),
            labeled("Target Restraint (pu)", slider(f"rest_target_{p}", 0.1, 20.0, 0.1, default_restraints[phase])),
            html.Div(id=f"boundary_result_{p}"),
        ], width=4))

    return html.Div([
        dbc.Card(dbc.CardBody([
            html.H5("Commissioning & Secondary Current Injection Assistant"),
            html.P("Pick a target restraint current for each phase to calculate the exact secondary Amps to inject."),
            dbc.Row(cols),
        ]), className="mb-3"),
        dbc.Card(dbc.CardBody([
            html.H5("Auto-Sweep Full Curve Test Table"),
            dbc.Row([
                dbc.Col(labeled("Sweep Start (pu)", dbc.Input(id="sweep_start", type="number", value=0.2, step=0.1)), width=4),
                dbc.Col(labeled("Sweep End (pu)", dbc.Input(id="sweep_end", type="number", value=6.0, step=0.5)), width=4),
                dbc.Col(labeled("Sweep Step (pu)", dbc.Input(id="sweep_step", type="number", value=0.5, step=0.1)), width=4),
            ]),
            dbc.Button("Generate Sweep Table", id="sweep_btn", color="primary", size="sm"),
            html.Div(id="sweep_table", className="mt-3"),
            dbc.Button("Download Sweep Table as CSV", id="sweep_csv_btn", size="sm", color="secondary", className="mt-2"),
            dcc.Download(id="sweep_csv_download"),
            dcc.Store(id="sweep_store"),
        ])),
    ])


def test_point_tab():
    return html.Div([
        dbc.Card(dbc.CardBody([
            html.H5("Test Point Verification & Curve"),
            html.P("Enter measured test results and see them plotted against the calculated characteristic curve."),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id="tp_phase", options=[{"label": p, "value": p} for p in PHASES + ["Other"]], value="Phase A", clearable=False), width=2),
                dbc.Col(dbc.Input(id="tp_restraint", type="number", placeholder="Restraint (A)", value=1.0), width=2),
                dbc.Col(dbc.Input(id="tp_diff", type="number", placeholder="Measured Diff (A)", value=0.3), width=2),
                dbc.Col(dbc.Input(id="tp_label", type="text", placeholder="Label (optional)"), width=3),
                dbc.Col(dbc.Button("Add Test Point", id="tp_add_btn", color="primary", size="sm"), width=3),
            ], className="mb-3 align-items-center"),
            dbc.ButtonGroup([
                dbc.Input(id="tp_remove_idx", type="number", value=0, min=0, size="sm", style={"width": "80px"}),
                dbc.Button("Remove Row", id="tp_remove_btn", size="sm", color="secondary"),
                dbc.Button("Clear All", id="tp_clear_btn", size="sm", color="danger"),
            ], className="mb-3"),
            html.Div(id="tp_table"),
            dcc.Store(id="tp_store", data=[]),
        ]), className="mb-3"),
        dbc.Card(dbc.CardBody([
            html.H5("Differential Bias Characteristic Curve"),
            dbc.RadioItems(
                id="cal_source", inline=True,
                options=[
                    {"label": "Connect my test points", "value": "connect"},
                    {"label": "Theoretical relay characteristic", "value": "theoretical"},
                ], value="theoretical", className="mb-2"
            ),
            dcc.Graph(id="tp_curve"),
        ])),
    ])


layout = dbc.Container([
    html.H3("Generator Step-Up Transformer (GSUT) Differential Protection"),
    html.P(
        "873.6MVA, 525kV Grounded Wye / 23kV Delta — CAC1-10-M3 percentage-bias differential relay "
        "(Mitsubishi, 2-winding).", className="text-muted"
    ),
    dbc.Row([
        dbc.Col(sidebar(), width=3),
        dbc.Col([
            dcc.Tabs(id="gsut_tabs", value="tab-sld", children=[
                dcc.Tab(label="Protection Zone (SLD)", value="tab-sld", children=[sld_tab()]),
                dcc.Tab(label="Live Vector Simulation", value="tab-sim", children=[live_sim_tab()]),
                dcc.Tab(label="Commissioning & Injection Tool", value="tab-comm", children=[commissioning_tab()]),
                dcc.Tab(label="Test Point Verification & Curve", value="tab-tp", children=[test_point_tab()]),
            ]),
        ], width=9),
    ]),
], fluid=True, className="py-3")


@callback(Output("adv_collapse", "is_open"), Input("adv_toggle", "n_clicks"), State("adv_collapse", "is_open"))
def toggle_advanced(n, is_open):
    if n:
        return not is_open
    return is_open


def _relay_from_settings(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity):
    return build_relay(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity)


SETTINGS_INPUTS = [
    Input("mva", "value"), Input("kv_hv", "value"), Input("ct_hv", "value"),
    Input("kv_lv", "value"), Input("ct_lv", "value"), Input("ct_sec", "value"),
    Input("tap_hv", "value"), Input("tap_lv", "value"),
    Input("bias", "value"), Input("min_operate", "value"), Input("hoc", "value"),
    Input("convention", "value"), Input("polarity", "value"),
]


@callback(
    Output("rated_info", "children"),
    Output("i_hv_a", "value"), Output("a_hv_a", "value"),
    Output("i_lv_a", "value"), Output("a_lv_a", "value"),
    *SETTINGS_INPUTS,
)
def update_rated_defaults(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity):
    if any(v is None for v in [mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc]):
        raise dash.exceptions.PreventUpdate
    relay = _relay_from_settings(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity)
    info = f"HV (525kV) Nominal Rated Current: {relay.windings[0]['i_rated_pri']:.1f} A | LV (23kV) Nominal Rated Current: {relay.windings[1]['i_rated_pri']:.1f} A"

    def_val_hv = relay.windings[0]["i_rated_pri"]
    def_ang_hv = 0.0
    vec_hv_internal = winding_internal_vector(relay, 0, def_val_hv, def_ang_hv)
    target_lv_internal = vec_hv_internal if polarity == "OPPOSITE" else -vec_hv_internal
    def_val_lv, def_ang_lv = raw_input_for_internal_vector(relay, 1, target_lv_internal)

    return info, def_val_hv, def_ang_hv, def_val_lv, def_ang_lv


@callback(
    Output("trip-banner", "children"),
    Output("trip-banner", "className"),
    Output("verdict-table", "children"),
    Output("char-curve", "figure"),
    *SETTINGS_INPUTS,
    Input("i_hv_a", "value"), Input("a_hv_a", "value"), Input("i_lv_a", "value"), Input("a_lv_a", "value"),
    Input("i_hv_b", "value"), Input("a_hv_b", "value"), Input("i_lv_b", "value"), Input("a_lv_b", "value"),
    Input("i_hv_c", "value"), Input("a_hv_c", "value"), Input("i_lv_c", "value"), Input("a_lv_c", "value"),
)
def update_live_sim(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity,
                     i_hv_a, a_hv_a, i_lv_a, a_lv_a, i_hv_b, a_hv_b, i_lv_b, a_lv_b, i_hv_c, a_hv_c, i_lv_c, a_lv_c):
    values = [mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc]
    if any(v is None for v in values):
        raise dash.exceptions.PreventUpdate

    relay = _relay_from_settings(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity)

    phase_pts = {
        "Phase A": [(i_hv_a or 0.0, a_hv_a or 0.0), (i_lv_a or 0.0, a_lv_a or 0.0)],
        "Phase B": [(i_hv_b or 0.0, a_hv_b or 0.0), (i_lv_b or 0.0, a_lv_b or 0.0)],
        "Phase C": [(i_hv_c or 0.0, a_hv_c or 0.0), (i_lv_c or 0.0, a_lv_c or 0.0)],
    }
    evals = {p: relay.evaluate_protection(pts) for p, pts in phase_pts.items()}

    any_trip = any(e["is_trip"] for e in evals.values())
    banner_text = "PROTECTIVE RELAY TRIP INITIATED!" if any_trip else "SYSTEM HEALTHY (Stability / Restraint Zone)"
    banner_class = "alert mt-2 " + ("alert-danger" if any_trip else "alert-success")

    df = pd.DataFrame([{
        "Phase": p, "I_op [pu]": f"{e['i_op_pu']:.3f}", "I_rest [pu]": f"{e['i_rest_pu']:.3f}",
        "Threshold [pu]": f"{e['i_threshold_pu']:.3f}", "Verdict": e["status"],
    } for p, e in evals.items()])
    table = dbc.Table.from_dataframe(df, striped=True, bordered=True, hover=True, size="sm")

    amps_base = relay.windings[0]["i_rated_sec"]
    max_x = max(6.0, max(e["i_rest_pu"] for e in evals.values()) + 1.5, relay.hoc_pu + 1.0)
    x_line = np.linspace(0, max_x, 400)
    y_line = [relay.calculate_trip_threshold(x) for x in x_line]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_line, y=y_line, mode="lines", name="CAL.", line=dict(color="#2563EB", width=3)))
    fig.add_trace(go.Scatter(x=[0, max_x], y=[relay.hoc_pu, relay.hoc_pu], mode="lines", name="HOC (Unrestrained)",
                              line=dict(color="#DC2626", width=2, dash="dash")))
    phase_colors = {"Phase A": "red", "Phase B": "green", "Phase C": "blue"}
    for p in PHASES:
        e = evals[p]
        fig.add_trace(go.Scatter(
            x=[e["i_rest_pu"]], y=[e["i_op_pu"]], mode="markers+text", name=p, text=[p], textposition="top center",
            marker=dict(size=14, color=phase_colors[p], symbol="x" if e["is_trip"] else "circle"),
        ))
    fig.update_layout(
        title="Transformer Differential Bias Characteristic",
        xaxis_title="Restraint Current I_rest (pu)", yaxis_title="Differential/Operating Current I_op (pu)",
        template="plotly_white", height=450,
    )

    return banner_text, banner_class, table, fig


@callback(
    [Output(f"boundary_result_{p}", "children") for p in ["a", "b", "c"]],
    *SETTINGS_INPUTS,
    Input("rest_target_a", "value"), Input("rest_target_b", "value"), Input("rest_target_c", "value"),
)
def update_commissioning(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity,
                          r_a, r_b, r_c):
    values = [mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc]
    if any(v is None for v in values):
        raise dash.exceptions.PreventUpdate
    relay = _relay_from_settings(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity)

    results = []
    for r_val in [r_a, r_b, r_c]:
        if r_val is None:
            r_val = 0.0
        boundary_op = relay.calculate_trip_threshold(r_val)
        sec_hv = (r_val + boundary_op / 2.0) * relay.windings[0]["i_rated_sec"]
        sec_lv = (r_val - boundary_op / 2.0) * relay.windings[1]["i_rated_sec"]
        results.append(html.Div([
            html.Div(f"Boundary I_op: {boundary_op:.3f} pu", className="fw-bold"),
            html.Div(f"HV inject: {sec_hv:.3f} A", className="small"),
            html.Div(f"LV inject: {sec_lv:.3f} A", className="small"),
        ]))
    return results


@callback(
    Output("sweep_table", "children"),
    Output("sweep_store", "data"),
    Input("sweep_btn", "n_clicks"),
    State("sweep_start", "value"), State("sweep_end", "value"), State("sweep_step", "value"),
    *[State(i.component_id, i.component_property) for i in SETTINGS_INPUTS],
    prevent_initial_call=True,
)
def generate_sweep(n_clicks, sweep_start, sweep_end, sweep_step, mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity):
    if sweep_end <= sweep_start or sweep_step <= 0:
        return dbc.Alert("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.", color="danger"), dash.no_update

    relay = _relay_from_settings(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity)
    sweep_points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
    rows = []
    for i_rest in sweep_points:
        boundary_op = relay.calculate_trip_threshold(i_rest)
        sec_hv = (i_rest + boundary_op / 2.0) * relay.windings[0]["i_rated_sec"]
        sec_lv = (i_rest - boundary_op / 2.0) * relay.windings[1]["i_rated_sec"]
        rows.append({
            "I_rest (pu)": round(float(i_rest), 3), "Boundary I_op (pu)": round(boundary_op, 3),
            "HV Injection (A)": round(sec_hv, 3), "LV Injection (A)": round(sec_lv, 3),
        })
    df = pd.DataFrame(rows)
    table = dash_table.DataTable(data=df.to_dict("records"), columns=[{"name": c, "id": c} for c in df.columns],
                                  style_table={"overflowX": "auto"}, page_size=10)
    return table, rows


@callback(
    Output("sweep_csv_download", "data"),
    Input("sweep_csv_btn", "n_clicks"),
    State("sweep_store", "data"),
    prevent_initial_call=True,
)
def download_sweep_csv(n_clicks, data):
    if not data:
        raise dash.exceptions.PreventUpdate
    df = pd.DataFrame(data)
    return dcc.send_data_frame(df.to_csv, "87GT_Sweep_Test_Table.csv", index=False)


@callback(
    Output("tp_store", "data"),
    Input("tp_add_btn", "n_clicks"), Input("tp_remove_btn", "n_clicks"), Input("tp_clear_btn", "n_clicks"),
    State("tp_phase", "value"), State("tp_restraint", "value"), State("tp_diff", "value"), State("tp_label", "value"),
    State("tp_remove_idx", "value"), State("tp_store", "data"),
    prevent_initial_call=True,
)
def modify_test_points(add_n, remove_n, clear_n, phase, restraint, diff, label, remove_idx, data):
    data = list(data or [])
    trigger = ctx.triggered_id
    if trigger == "tp_add_btn":
        data.append({
            "Phase": phase, "Restraint (A)": round(restraint or 0.0, 3),
            "Measured Diff (A)": round(diff or 0.0, 3), "Label": label or "",
        })
    elif trigger == "tp_remove_btn":
        idx = int(remove_idx or 0)
        if 0 <= idx < len(data):
            data.pop(idx)
    elif trigger == "tp_clear_btn":
        data = []
    return data


@callback(
    Output("tp_table", "children"),
    Output("tp_curve", "figure"),
    Input("tp_store", "data"),
    Input("cal_source", "value"),
    *SETTINGS_INPUTS,
)
def render_test_points(data, cal_source, mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity):
    values = [mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc]
    if any(v is None for v in values):
        raise dash.exceptions.PreventUpdate
    relay = _relay_from_settings(mva, kv_hv, ct_hv, kv_lv, ct_lv, ct_sec, tap_hv, tap_lv, bias, min_op, hoc, convention, polarity)
    amps_base = relay.windings[0]["i_rated_sec"]
    data = data or []

    if data:
        table = dbc.Table.from_dataframe(pd.DataFrame(data), striped=True, bordered=True, hover=True, size="sm")
    else:
        table = dbc.Alert("No test points added yet.", color="light")

    fig = go.Figure()
    if cal_source == "connect" and len(data) >= 2:
        sorted_pts = sorted(data, key=lambda tp: tp["Restraint (A)"])
        curve_x = [tp["Restraint (A)"] for tp in sorted_pts]
        curve_y = [tp["Measured Diff (A)"] for tp in sorted_pts]
        fig.add_trace(go.Scatter(x=curve_x, y=curve_y, mode="lines", name="CAL.", line=dict(color="#2E8B57", width=3)))
    else:
        max_restraint = max([tp["Restraint (A)"] / amps_base for tp in data] + [relay.hoc_pu + 2.0])
        curve_x_pu = np.linspace(0, max_restraint * 1.2 + 0.5, 300)
        curve_y_pu = [relay.calculate_trip_threshold(x) for x in curve_x_pu]
        fig.add_trace(go.Scatter(x=curve_x_pu * amps_base, y=np.array(curve_y_pu) * amps_base, mode="lines",
                                  name="CAL.", line=dict(color="#2E8B57", width=3)))

    tp_marker_colors = {"Phase A": "#D63384", "Phase B": "#6C757D", "Phase C": "#1E3A8A", "Other": "#F59E0B"}
    for tp in data:
        trace_name = tp["Phase"] + (f" ({tp['Label']})" if tp.get("Label") else "")
        fig.add_trace(go.Scatter(
            x=[tp["Restraint (A)"]], y=[tp["Measured Diff (A)"]], mode="markers", name=trace_name,
            marker=dict(size=12, color=tp_marker_colors.get(tp["Phase"], "#F59E0B")),
        ))
    fig.update_layout(title="Differential Bias Characteristic Curve", xaxis_title="Restraint Current (A)",
                       yaxis_title="Diff. Current (A)", template="plotly_white", height=420)

    return table, fig
