import dash
import dash_bootstrap_components as dbc
from dash import html

dash.register_page(__name__, path="/", name="Home", category="")

layout = dbc.Container([
    html.H2("Electrical Equipment Protection Suite"),
    html.P(
        "Protection settings calculation, commissioning-injection assistance, and settings "
        "verification for POMI's generator, transformer, and motor protection relays.",
        className="text-muted"
    ),
    html.Hr(),
    dbc.Row([
        dbc.Col([
            html.H5("Generator"),
            html.P(
                "Generator Differential Protection (87G) — GE G60 numerical dual-breakpoint "
                "characteristic, or GE CFD22B4A legacy product-restraint characteristic."
            ),
        ], width=4),
        dbc.Col([
            html.H5("Transformer"),
            html.Ul([
                html.Li("Excitation Transformer (EXCT)"),
                html.Li("Generator Step-Up Transformer (GSUT)"),
                html.Li("Overall GSUT-GEN (backup, 3-winding)"),
                html.Li("Auxiliary Transformer"),
            ]),
        ], width=4),
        dbc.Col([
            html.H5("Motor"),
            html.Ul([
                html.Li("Induced Draft (ID) Fan — 50/50/51 time-overcurrent"),
            ]),
        ], width=4),
    ]),
    html.Hr(),
    dbc.Alert(
        "This is the Dash edition of the app, being built alongside the Streamlit version "
        "for a smoother/faster feel. Same relay engines, different UI framework.",
        color="info"
    ),
], fluid=True)
