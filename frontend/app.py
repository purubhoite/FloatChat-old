# frontend/app.py

import json
import requests
import pandas as pd

import dash
from dash import Dash, html, dcc, Input, Output, State, dash_table
from dash.exceptions import PreventUpdate
import dash_leaflet as dl
import plotly.graph_objects as go

# -----------------------------------------------
# Dash app
# -----------------------------------------------

app: Dash = dash.Dash(__name__)
app.title = "Indian Ocean ARGO Explorer"

BACKEND_URL = "http://localhost:8000"  # FastAPI backend


# ------------ Layout helpers ------------

def build_map_base_layer():
    """Static base map tile layer."""
    return dl.TileLayer(
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attribution="&copy; OpenStreetMap contributors",
    )


def build_app_layout() -> html.Div:
    return html.Div(
        className="app-root",
        children=[
            # Header
            html.Header(
                className="app-header",
                children=[
                    html.H1("Indian Ocean ARGO Explorer"),
                    html.P(
                        "AI-powered ARGO & BGC data exploration "
                        "(chat + map + plots)"
                    ),
                ],
            ),

            # Main
            html.Div(
                className="app-main",
                children=[
                    # Left: Map
                    html.Div(
                        className="app-map-container",
                        children=[
                            dl.Map(
                                id="main-map",
                                className="map-container",
                                center=(0, 70),
                                zoom=3,
                                children=[
                                    build_map_base_layer(),
                                    # Layer for query result markers
                                    dl.LayerGroup(id="map-result-layer"),
                                ],
                            )
                        ],
                    ),

                    # Right: Chat + Result
                    html.Div(
                        className="app-right-column",
                        children=[
                            # Stores for backend response
                            dcc.Store(id="ask-rows-store", storage_type="memory"),
                            dcc.Store(id="ask-viz-store", storage_type="memory"),
                            dcc.Store(id="chat-store", storage_type="memory"),
                            # NEW: store for selected profile (from map or dropdown)
                            dcc.Store(id="selected-profile-store", storage_type="memory"),

                            # Chat panel
                            html.Div(
                                className="chat-panel",
                                children=[
                                    html.Div(
                                        id="chat-messages",
                                        className="chat-messages",
                                    ),
                                    html.Div(
                                        className="chat-input-row",
                                        children=[
                                            dcc.Input(
                                                id="chat-input",
                                                className="chat-input",
                                                type="text",
                                                placeholder=(
                                                    "Ask about salinity profiles, BGC parameters, "
                                                    "float locations, trajectories..."
                                                ),
                                                debounce=False,
                                            ),
                                            html.Button(
                                                "Send",
                                                id="chat-send-btn",
                                                className="chat-send-btn",
                                                n_clicks=0,
                                            ),
                                        ],
                                    ),
                                ],
                            ),

                            # Result / plots panel
                            html.Div(
                                className="result-panel",
                                children=[
                                    html.H2("Results & Plots", id="result-title"),
                                    html.Div(
                                        id="result-meta",
                                        className="result-meta",
                                    ),
                                    html.Div(
                                        className="result-controls",
                                        children=[
                                            dcc.Dropdown(
                                                id="variable-select",
                                                placeholder="Select variable to plot",
                                                clearable=False,
                                            ),
                                            dcc.Dropdown(
                                                id="profile-select",
                                                placeholder="Profiles (All or single)",
                                                clearable=False,
                                            ),
                                        ],
                                    ),
                                    dcc.Graph(
                                        id="result-graph",
                                        figure=go.Figure(),
                                        style={"height": "300px"},
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Bottom: Data table + download
            html.Div(
                className="table-panel",
                children=[
                    html.H3("Result Table"),
                    dash_table.DataTable(
                        id="result-table",
                        columns=[],
                        data=[],
                        page_size=10,
                        style_table={"overflowX": "auto", "maxHeight": "250px"},
                        style_cell={
                            "fontSize": 12,
                            "padding": "4px",
                            "whiteSpace": "nowrap",
                            "textOverflow": "ellipsis",
                            "maxWidth": 150,
                        },
                    ),
                    html.Button(
                        "Download CSV",
                        id="download-csv-btn",
                        className="download-btn",
                        n_clicks=0,
                    ),
                    dcc.Download(id="download-csv"),
                ],
            ),

            # Floating overlay for profile metadata
            html.Div(
                id="profile-overlay",
                className="profile-overlay",
                children=None,
            ),
        ],
    )


app.layout = build_app_layout()


# -----------------------------------------------
# Callbacks
# -----------------------------------------------

# 1) Chat: send query to backend, store response + update chat history
@app.callback(
    Output("chat-store", "data"),
    Output("ask-rows-store", "data"),
    Output("ask-viz-store", "data"),
    Input("chat-send-btn", "n_clicks"),
    State("chat-input", "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def handle_chat_send(n_clicks, user_text, chat_data):
    if not user_text or not user_text.strip():
        raise PreventUpdate

    user_text = user_text.strip()

    if chat_data is None:
        chat_data = []

    # Append user message
    chat_data.append({"role": "user", "text": user_text})

    # Call backend /ask
    rows = None
    viz = None
    try:
        r = requests.post(
            f"{BACKEND_URL}/ask",
            json={"query": user_text},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        explanation = data.get("explanation") or "No explanation returned."
        rows = data.get("data", {}).get("rows")
        viz = data.get("viz")

        chat_data.append({"role": "assistant", "text": explanation})
    except Exception as e:
        # On error, append error message in chat
        chat_data.append({"role": "assistant", "text": f"Backend error: {e}"})
        rows = None
        viz = None

    return chat_data, rows, viz


# 2) Render chat messages
@app.callback(
    Output("chat-messages", "children"),
    Input("chat-store", "data"),
)
def render_chat_messages(chat_data):
    if not chat_data:
        # Initial greeting
        return [
            html.Div(
                className="chat-message chat-message-assistant",
                children=[
                    html.Div(className="chat-message-role", children="Assistant"),
                    html.Div(
                        className="chat-message-text",
                        children=(
                            "Hi! Ask me about ARGO & BGC data in the Indian Ocean.\n"
                            "I will query the backend, run NL→SQL, and show map + plots here."
                        ),
                    ),
                ],
            )
        ]

    children = []
    for msg in chat_data:
        role = msg.get("role", "assistant")
        text = msg.get("text", "")

        if role == "user":
            cls = "chat-message chat-message-user"
            role_label = "You"
        else:
            cls = "chat-message chat-message-assistant"
            role_label = "Assistant"

        children.append(
            html.Div(
                className=cls,
                children=[
                    html.Div(className="chat-message-role", children=role_label),
                    html.Div(className="chat-message-text", children=text),
                ],
            )
        )

    return children


# 3) Update map markers from ask-rows-store (now with trajectories)
@app.callback(
    Output("map-result-layer", "children"),
    Input("ask-rows-store", "data"),
)
def update_map_markers(rows):
    if not rows:
        return []

    df = pd.DataFrame(rows)

    if df.empty or "latitude" not in df.columns or "longitude" not in df.columns:
        return []

    # --- Markers: one per profile (as before) ---
    markers = []
    seen_profiles = set()

    for _, row in df.iterrows():
        lat = row.get("latitude")
        lon = row.get("longitude")
        pid = row.get("profile_id")
        fid = row.get("float_id")

        if pd.isna(lat) or pd.isna(lon):
            continue

        key = pid if pid is not None else (lat, lon, fid)
        if key in seen_profiles:
            continue
        seen_profiles.add(key)

        if pid is not None:
            label = f"Profile {pid}"
            pid_str = str(pid)
        elif fid:
            label = f"Float {fid}"
            pid_str = str(fid)
        else:
            label = "Profile"
            pid_str = label

        markers.append(
            dl.CircleMarker(
                id={"type": "profile-marker", "profile_id": pid_str},
                center=(lat, lon),
                radius=7,
                color="red",
                fill=True,
                fillOpacity=0.9,
                children=[
                    dl.Tooltip(label),
                    dl.Popup(
                        html.Div(
                            [
                                html.H4(label),
                                html.P(f"Lat: {lat:.2f}, Lon: {lon:.2f}"),
                                html.P("Click marker to inspect this profile."),
                            ]
                        )
                    ),
                ],
            )
        )

    # --- Trajectories: polylines per float_id ---
    polylines = []
    if "float_id" in df.columns:
        # drop rows with missing lat/lon
        gdf = df.dropna(subset=["latitude", "longitude"])

        if "profile_time" in gdf.columns:
            # ensure time is sortable
            try:
                gdf["__pt"] = pd.to_datetime(gdf["profile_time"])
                sort_key = "__pt"
            except Exception:
                sort_key = "profile_time"
        else:
            sort_key = None

        for fid, g in gdf.groupby("float_id"):
            if len(g) < 2:
                continue  # not enough points to form a trajectory

            if sort_key:
                g = g.sort_values(by=sort_key)

            coords = list(zip(g["latitude"], g["longitude"]))
            polylines.append(
                dl.Polyline(
                    positions=coords,
                    weight=2,
                    opacity=0.7,
                )
            )

    # Return markers + trajectories in one layer
    return markers + polylines











# 3b) When a marker is clicked → update selected-profile-store
@app.callback(
    Output("selected-profile-store", "data"),
    Input({"type": "profile-marker", "profile_id": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def on_marker_click(n_clicks):
    # Use callback_context to find which marker triggered
    from dash import callback_context
    ctx = callback_context

    if not ctx.triggered:
        raise PreventUpdate

    prop_id = ctx.triggered[0]["prop_id"]  # like '{"type":"profile-marker","profile_id":"123"}.n_clicks'
    id_json = prop_id.split(".")[0]

    try:
        trig_id = json.loads(id_json)
    except Exception:
        raise PreventUpdate

    pid = trig_id.get("profile_id")
    if not pid:
        raise PreventUpdate

    # Store the clicked profile_id as string
    return str(pid)


# 4) Update variable/profile dropdowns + meta from rows + viz + selected profile
@app.callback(
    Output("variable-select", "options"),
    Output("variable-select", "value"),
    Output("profile-select", "options"),
    Output("profile-select", "value"),
    Output("result-meta", "children"),
    Input("ask-rows-store", "data"),
    Input("ask-viz-store", "data"),
    Input("selected-profile-store", "data"),
)
def update_controls_and_meta(rows, viz, selected_profile):
    if not rows:
        return [], None, [], None, "No data yet. Ask a question to see results."

    df = pd.DataFrame(rows)
    if df.empty:
        return [], None, [], None, "No data (empty result)."

    # ---- Variable selector ----
    candidate_vars = []
    if viz and isinstance(viz, dict):
        for v in viz.get("variables") or []:
            if v in df.columns:
                candidate_vars.append(v)

    # Fallback: any numeric columns as candidates
    if not candidate_vars:
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        candidate_vars = numeric_cols

    var_options = [{"label": v, "value": v} for v in candidate_vars]
    var_value = candidate_vars[0] if candidate_vars else None

    # ---- Profile selector ----
    profile_options = []
    profile_value = None
    n_profiles = 0

    selected_profile_str = str(selected_profile) if selected_profile is not None else None

    if "profile_id" in df.columns:
        unique_profiles = (
            df["profile_id"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        unique_profiles = sorted(unique_profiles, key=lambda x: int(x) if x.isdigit() else x)
        n_profiles = len(unique_profiles)

        # First option: All profiles
        profile_options.append({"label": "All profiles", "value": "__all__"})
        for pid in unique_profiles:
            profile_options.append(
                {"label": f"Profile {pid}", "value": pid}
            )

        # Default selected value:
        if selected_profile_str and selected_profile_str in unique_profiles:
            profile_value = selected_profile_str
        else:
            profile_value = "__all__" if profile_options else None

    # ---- Meta text ----
    n_rows = len(df)
    parts = [f"{n_rows} rows"]

    if n_profiles:
        parts.append(f"{n_profiles} profiles")

    if "profile_time" in df.columns:
        try:
            tmin = pd.to_datetime(df["profile_time"]).min()
            tmax = pd.to_datetime(df["profile_time"]).max()
            parts.append(f"time: {tmin.date()} → {tmax.date()}")
        except Exception:
            pass

    meta_text = " | ".join(parts)

    return var_options, var_value, profile_options, profile_value, meta_text


# 5) Update Plotly graph from ask-rows-store + viz-intent + UI selections
@app.callback(
    Output("result-graph", "figure"),
    Output("result-title", "children"),
    Input("ask-rows-store", "data"),
    Input("ask-viz-store", "data"),
    Input("variable-select", "value"),
    Input("profile-select", "value"),
)
def update_result_graph(rows, viz, variable_value, profile_value):
    if not rows:
        return go.Figure(), "Results & Plots"

    df = pd.DataFrame(rows)
    title = "Results & Plots"

    if not viz or not isinstance(viz, dict):
        fig = go.Figure()
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10),
            annotations=[
                dict(
                    text="No specific visualization suggested.",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                )
            ],
        )
        return fig, title

    kind = viz.get("kind", "table")
    primary_var = variable_value or viz.get("primary_variable")
    x_col = viz.get("x")
    y_col = viz.get("y")
    group_by = viz.get("group_by") or []

    # Helper to ensure column exists
    def col_ok(c: str) -> bool:
        return c is not None and c in df.columns

    # Filter by selected profile if applicable
    if profile_value and profile_value != "__all__" and "profile_id" in df.columns:
        df = df[df["profile_id"].astype(str) == str(profile_value)]

    # PROFILE PLOT: depth vs variable
    if (
        kind == "profile_plot"
        and col_ok(y_col)
        and primary_var
        and primary_var in df.columns
    ):
        fig = go.Figure()
        gb_col = group_by[0] if group_by else None

        if gb_col and gb_col in df.columns and (profile_value == "__all__" or not profile_value):
            # Overlay multiple profiles
            for val, g in df.groupby(gb_col):
                fig.add_trace(
                    go.Scatter(
                        x=g[primary_var],
                        y=g[y_col],
                        mode="lines",
                        name=str(val),
                    )
                )
        else:
            # Single profile (or no grouping column)
            fig.add_trace(
                go.Scatter(
                    x=df[primary_var],
                    y=df[y_col],
                    mode="lines",
                    name=primary_var,
                )
            )

        fig.update_yaxes(autorange="reversed", title=y_col)
        fig.update_xaxes(title=primary_var)
        title = f"Profile plot: {primary_var} vs {y_col}"
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        return fig, title

    # TIME-SERIES
    if (
        kind == "time_series"
        and col_ok(x_col)
        and primary_var
        and primary_var in df.columns
    ):
        fig = go.Figure()
        gb_col = group_by[0] if group_by else None

        if gb_col and gb_col in df.columns and (profile_value == "__all__" or not profile_value):
            for val, g in df.groupby(gb_col):
                fig.add_trace(
                    go.Scatter(
                        x=g[x_col],
                        y=g[primary_var],
                        mode="lines+markers",
                        name=str(val),
                    )
                )
        else:
            fig.add_trace(
                go.Scatter(
                    x=df[x_col],
                    y=df[primary_var],
                    mode="lines+markers",
                    name=primary_var,
                )
            )

        fig.update_xaxes(title=x_col)
        fig.update_yaxes(title=primary_var)
        title = f"Time series: {primary_var} vs {x_col}"
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        return fig, title

    # DEPTH-TIME (simple scatter colored by variable)
    if (
        kind == "depth_time"
        and col_ok(x_col)
        and col_ok(y_col)
        and primary_var
        and primary_var in df.columns
    ):
        fig = go.Figure(
            data=go.Scattergl(
                x=df[x_col],
                y=df[y_col],
                mode="markers",
                marker=dict(
                    size=4,
                    color=df[primary_var],
                    colorbar=dict(title=primary_var),
                    colorscale="Viridis",
                ),
            )
        )
        fig.update_yaxes(autorange="reversed", title=y_col)
        fig.update_xaxes(title=x_col)
        title = f"Depth-time view: {primary_var}"
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        return fig, title

    # Fallback: table-like summary
    fig = go.Figure()
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        annotations=[
            dict(
                text=f"No specialized visualization implemented for kind='{kind}'. Showing table below.",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
        ],
    )
    return fig, title


# 6) Update result table from ask-rows-store
@app.callback(
    Output("result-table", "columns"),
    Output("result-table", "data"),
    Input("ask-rows-store", "data"),
)
def update_result_table(rows):
    if not rows:
        return [], []

    first = rows[0]
    columns = [{"name": k, "id": k} for k in first.keys()]
    return columns, rows


# 7) Download CSV of current rows
@app.callback(
    Output("download-csv", "data"),
    Input("download-csv-btn", "n_clicks"),
    State("ask-rows-store", "data"),
    prevent_initial_call=True,
)
def download_csv(n_clicks, rows):
    if not rows:
        raise PreventUpdate

    df = pd.DataFrame(rows)
    # use Dash helper to send CSV
    return dcc.send_data_frame(df.to_csv, "argo_results.csv", index=False)


# 8) Floating profile metadata overlay
@app.callback(
    Output("profile-overlay", "children"),
    Input("selected-profile-store", "data"),
    Input("ask-rows-store", "data"),
)
def update_profile_overlay(selected_profile, rows):
    if not rows or not selected_profile or selected_profile == "__all__":
        return None

    df = pd.DataFrame(rows)
    if "profile_id" not in df.columns:
        return None

    mask = df["profile_id"].astype(str) == str(selected_profile)
    g = df[mask]
    if g.empty:
        return None

    # Gather metadata
    float_id = g["float_id"].iloc[0] if "float_id" in g.columns else None
    lat = g["latitude"].iloc[0] if "latitude" in g.columns else None
    lon = g["longitude"].iloc[0] if "longitude" in g.columns else None

    try:
        t0 = pd.to_datetime(g["profile_time"]).iloc[0] if "profile_time" in g.columns else None
    except Exception:
        t0 = g["profile_time"].iloc[0] if "profile_time" in g.columns else None

    n_levels = len(g)
    max_depth = float(g["depth_m"].max()) if "depth_m" in g.columns else None

    data_mode = g["data_mode"].iloc[0] if "data_mode" in g.columns else None
    has_bgc = g["has_bgc"].iloc[0] if "has_bgc" in g.columns else None

    lines = []

    lines.append(html.H4(f"Profile {selected_profile}", className="overlay-title"))

    if float_id is not None:
        lines.append(html.Div(f"Float: {float_id}"))

    if lat is not None and lon is not None:
        lines.append(html.Div(f"Lat/Lon: {lat:.2f}°, {lon:.2f}°"))

    if t0 is not None:
        lines.append(html.Div(f"Time: {t0}"))

    lines.append(html.Div(f"Depth levels: {n_levels}"))
    if max_depth is not None:
        lines.append(html.Div(f"Max depth: {max_depth:.0f} m"))

    if data_mode is not None:
        lines.append(html.Div(f"Data mode: {data_mode}"))

    if has_bgc is not None:
        lines.append(html.Div(f"BGC data: {'Yes' if has_bgc else 'No'}"))

    return html.Div(
        className="profile-overlay-card",
        children=lines,
    )


if __name__ == "__main__":
    app.run(debug=True)
