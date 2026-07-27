"""
Electrical Equipment Protection Suite - Dash edition.

Same engines/ and common/pdf_report.py as the Streamlit app (app.py) -
only the UI layer is different. Uses Dash's built-in multi-page routing
(pages live in dash_pages/, kept separate from the "pages" name to avoid
any ambiguity with Streamlit's own multipage conventions in this repo).

Run with: python dash_app.py
"""
import dash
import dash_bootstrap_components as dbc
from dash import html

app = dash.Dash(
    __name__,
    use_pages=True,
    pages_folder="dash_pages",
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    title="Electrical Equipment Protection Suite",
    suppress_callback_exceptions=True,
)
server = app.server


def _nav_links():
    # Group registered pages by their custom "category" kwarg, preserving
    # the same Home / Generator / Transformer / Motor grouping the
    # Streamlit sidebar uses.
    categories = {}
    for page in dash.page_registry.values():
        categories.setdefault(page.get("category", ""), []).append(page)

    order = ["", "Generator", "Transformer", "Motor"]
    sections = []
    for cat in order:
        pages = categories.get(cat, [])
        if not pages:
            continue
        if cat:
            sections.append(html.Div(cat, className="text-uppercase text-muted small fw-bold mt-3 mb-1 px-2"))
        for page in pages:
            sections.append(
                dbc.NavLink(
                    page["name"],
                    href=page["path"], active="exact",
                    className="px-2 py-1",
                )
            )
    return sections


app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(
            html.Div([
                html.H5("POMI Relay Suite", className="px-2 mt-2 mb-3"),
                dbc.Nav(_nav_links(), vertical=True, pills=True),
            ], className="border-end vh-100 pt-2"),
            width=2,
        ),
        dbc.Col(dash.page_container, width=10, className="py-3"),
    ]),
], fluid=True)


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=8060, host="0.0.0.0")
