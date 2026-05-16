# frontend/app.py

import json
import requests
import pandas as pd

import dash
from dash import Dash, html, dcc, Input, Output, State, dash_table, ClientsideFunction
from dash.exceptions import PreventUpdate
import dash_leaflet as dl
import plotly.graph_objects as go

BGC_VARS = ["doxy_umol_kg", "chlorophyll_mg_m3", "nitrate_umol_kg", "ph_total"]

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
                            # NEW: store for selected float (from map)
                            dcc.Store(id="selected-float-store", storage_type="memory"),
                            # NEW: store for generated SQL
                            dcc.Store(id="ask-sql-store", storage_type="memory"),
                            # NEW: loading state store
                            dcc.Store(id="chat-loading-store", storage_type="memory", data=False),
                            # NEW: trigger store for async request
                            dcc.Store(id="chat-request-trigger", storage_type="memory", data=None),
                            # NEW: store for uploaded NetCDF file metadata (filename only for now)
                            dcc.Store(id="nc-file-store", storage_type="memory"),

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
                                                n_submit=0,
                                            ),
                                            html.Button(
                                                "🎤",
                                                id="mic-btn",
                                                className="mic-btn",
                                                n_clicks=0,
                                                title="Speak Query",
                                            ),
                                            dcc.Upload(
                                                id="nc-upload",
                                                children=html.Button(
                                                    "Upload .nc",
                                                    id="nc-upload-btn",
                                                    className="nc-upload-btn",
                                                    title="Upload NetCDF file",
                                                ),
                                                multiple=False,
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

                            # Result panel (Plot + Controls)
                            html.Div(
                                className="result-panel",
                                children=[
                                    html.Div(
                                        className="result-header",
                                        children=[
                                            html.H2(id="result-title", children="Results & Plots"),
                                            html.Span(id="viz-type-badge", className="viz-type-badge", children=""),
                                        ]
                                    ),
                                    

                                    # NEW: Summary/Details for SQL
                                    html.Details(
                                        className="result-sql-details",
                                        children=[
                                            html.Summary("View Generated SQL", style={"cursor": "pointer", "fontSize": "0.85rem", "color": "#64748b", "marginBottom": "0.5rem"}),
                                            html.Pre(id="result-sql-container", style={
                                                "backgroundColor": "#1e293b",
                                                "color": "#a5f3fc",
                                                "padding": "0.75rem",
                                                "borderRadius": "0.5rem",
                                                "overflowX": "auto",
                                                "fontSize": "0.8rem",
                                                "whiteSpace": "pre-wrap"
                                            })
                                        ],
                                        style={"marginBottom": "1rem"}
                                    ),
                                    html.Div(
                                        className="result-controls",
                                        children=[
                                            dcc.Dropdown(
                                                id="variable-select",
                                                placeholder="Select variable...",
                                                clearable=True,
                                                style={"fontSize": 14},
                                            ),
                                            dcc.Dropdown(
                                                id="profile-select",
                                                placeholder="Select profile/float...",
                                                clearable=True,
                                                style={"fontSize": 14},
                                            ),
                                        ],
                                    ),

                                    # Plotly Graph
                                    dcc.Loading(
                                        id="result-graph-loading",
                                        type="default",
                                        children=dcc.Graph(
                                            id="result-graph",
                                            figure=go.Figure(),
                                            style={"height": "300px"},
                                        ),
                                    ),

                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Bottom: Data table + download (Collapsible)
            html.Div(
                className="table-panel",
                children=[
                    html.Button(
                        "Result Table ▼",
                        id="table-toggle-btn",
                        className="table-header-toggle",
                        n_clicks=0,
                    ),
                    dcc.Store(id="table-is-open", data=False),
                    
                    # Collapsible content
                    html.Div(
                        id="table-content",
                        className="table-content",
                        style={"display": "none"},  # Hidden by default
                        children=[
                            dcc.Loading(
                                id="result-table-loading",
                                type="default",
                                children=dash_table.DataTable(
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
                ],
            ),

            # Floating overlay for profile metadata
            html.Div(id="profile-overlay", className="profile-overlay"),
        ],
    )


app.layout = build_app_layout()


# -----------------------------------------------
# Callbacks
# -----------------------------------------------

# 0) Handle NetCDF upload: send to backend for data extraction and inject into stores
@app.callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("nc-file-store", "data"),
    Output("ask-rows-store", "data", allow_duplicate=True),
    Output("ask-viz-store", "data", allow_duplicate=True),
    Input("nc-upload", "contents"),
    State("nc-upload", "filename"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def on_nc_upload(contents, filename, chat_data):
    # If no file uploaded, do nothing
    if contents is None or not filename:
        raise PreventUpdate

    if chat_data is None:
        chat_data = []

    summary_text = f"NetCDF file uploaded: {filename}."
    nc_meta = {"filename": filename}
    rows = None
    viz = None

    # Call backend /upload_nc to get full data extraction
    try:
        r = requests.post(
            f"{BACKEND_URL}/upload_nc",
            json={"filename": filename, "contents": contents},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("ok"):
            nc_meta = data
            if data.get("summary_text"):
                summary_text = data["summary_text"]
            
            # Extract rows from the data payload
            data_payload = data.get("data", {})
            rows = data_payload.get("rows")
            
            # Build viz intent for uploaded NetCDF data
            if rows:
                # Determine visualization type based on available columns
                df_cols = [col["name"] for col in data_payload.get("schema", {}).get("columns", [])]
                
                viz = {
                    "primary_kind": "table",  # Default to table for uploaded data
                    "show_map": any("lat" in c.lower() or "lon" in c.lower() for c in df_cols),
                    "variables": data.get("variables", []),
                    "n_profiles": 1,
                    "level": "measurement",
                }
                
                # Check for depth column to enable profile view
                depth_info = data.get("depth")
                if depth_info and depth_info.get("var") in df_cols:
                    viz["depth_col"] = depth_info["var"]
                    viz["primary_kind"] = "profile_plot"
                
                # Check for time column to enable time series
                time_info = data.get("time")
                if time_info and time_info.get("var") in df_cols:
                    viz["time_col"] = time_info["var"]
                    if viz.get("depth_col") is None:
                        viz["primary_kind"] = "time_series"
                
                # Set primary variable if available
                if data.get("variables"):
                    viz["primary_variable"] = data["variables"][0]
                
        else:
            err = data.get("error") or "Unknown error from backend."
            summary_text = (
                f"NetCDF file '{filename}' uploaded, but backend could not process it: {err}"
            )
    except Exception as e:
        summary_text = (
            f"NetCDF file '{filename}' uploaded, but backend processing failed: {e}"
        )

    # Append a system-style assistant message so LLM sees detailed NetCDF context
    chat_data.append({"role": "assistant", "text": summary_text})

    return chat_data, nc_meta, rows, viz

# 1a) FAST: Append loading message to chat when send is clicked
@app.callback(
    Output("chat-store", "data"),
    Output("chat-request-trigger", "data"),
    Input("chat-send-btn", "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input", "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def on_chat_send_show_loading(n_clicks, n_submit, user_text, chat_data):
    """Fast callback: append user message and loading indicator."""
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    if not user_text or not user_text.strip():
        raise PreventUpdate

    user_text = user_text.strip()

    if chat_data is None:
        chat_data = []

    # Append user message
    chat_data.append({"role": "user", "text": user_text})
    # Append loading message
    chat_data.append({"role": "assistant", "text": " Thinking...", "is_loading": True})

    # Trigger the slow request callback
    return chat_data, user_text


# 1b) SLOW: Fetch backend response and replace loading message
@app.callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("ask-rows-store", "data"),
    Output("ask-viz-store", "data"),
    Output("ask-sql-store", "data"),
    Input("chat-request-trigger", "data"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def fetch_backend_response(user_text, chat_data):
    """Slow callback: fetch from backend and replace loading message."""
    if not user_text:
        raise PreventUpdate

    rows = None
    viz = None
    sql_text = None

    # Build conversation history (all messages except the last loading one)
    conversation_history = []
    if chat_data:
        # Include all messages except the current (last) loading message
        for msg in chat_data[:-1]:
            conversation_history.append({
                "role": msg.get("role"),
                "text": msg.get("text", "")
            })

    # Call backend /ask with conversation context
    try:
        r = requests.post(
            f"{BACKEND_URL}/ask",
            json={
                "query": user_text,
                "conversation_history": conversation_history
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        explanation = data.get("explanation") or "No explanation returned."
        rows = data.get("data", {}).get("rows")
        viz = data.get("viz")
        sql_text = data.get("sql")

        # Replace the last (loading) message with the actual response
        if chat_data and len(chat_data) > 0:
            chat_data[-1] = {"role": "assistant", "text": explanation}
    except Exception as e:
        # Replace loading message with error
        if chat_data and len(chat_data) > 0:
            chat_data[-1] = {"role": "assistant", "text": f"Backend error: {e}"}

    return chat_data, rows, viz, sql_text


# Clear chat input immediately on send (so it does not wait for backend roundtrip)
@app.callback(
    Output("chat-input", "value", allow_duplicate=True),
    Input("chat-send-btn", "n_clicks"),
    Input("chat-input", "n_submit"),
    State("chat-input", "value"),
    prevent_initial_call=True,
)
def clear_chat_input_immediate(n_clicks, n_submit, user_text):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate
    # Only clear input if there's actual text
    if not user_text or not user_text.strip():
        raise PreventUpdate
    return ""


# 2) Render chat messages
@app.callback(
    Output("chat-messages", "children"),
    Input("chat-store", "data"),
)
def render_chat_messages(chat_data):
    if not chat_data:
        # Initial greeting
        children = [
            html.Div(
                className="chat-message chat-message-assistant",
                children=[
                    html.Div(className="chat-message-role", children="Assistant"),
                    html.Div(
                        className="chat-message-text",
                        children=(
                            "Hi! Ask me about ARGO & BGC data in the Indian Ocean.\n"
                            "Try: 'Show salinity profiles near the Equator' or 'Plot deep oxygen trends'."
                        ),
                    ),
                ],
            )
        ]
        return children

    children = []
    for msg in chat_data:
        role = msg.get("role")
        text = msg.get("text", "")
        is_loading = msg.get("is_loading", False)

        if role == "user":
            cls = "chat-message chat-message-user"
            role_label = "You"
        else:
            cls = "chat-message chat-message-assistant"
            if is_loading:
                cls += " chat-message-loading"
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


# 2b) Render SQL in the details block
@app.callback(
    Output("result-sql-container", "children"),
    Input("ask-sql-store", "data"),
)
def render_sql_debug(sql_text):
    if not sql_text:
        return "No SQL generated."
    return sql_text


# 3) Update map markers from ask-rows-store + selected-float-store
@app.callback(
    Output("map-result-layer", "children"),
    Input("ask-rows-store", "data"),
    Input("selected-float-store", "data"),
)
def update_map_markers(rows, selected_float):
    if not rows:
        return []

    df = pd.DataFrame(rows)
    if df.empty or "latitude" not in df.columns or "longitude" not in df.columns:
        return []

    # Helper to check if float matches selected
    sel_float_str = str(selected_float) if selected_float else None

    children = []

    # 1. Group by Float ID
    if "float_id" in df.columns:
        grouped = df.groupby("float_id")
        
        for fid, g in grouped:
            fid_str = str(fid)
            
            # Is this float selected?
            is_selected = (sel_float_str == fid_str)
            
            # Sort by time/cycle to find latest and draw path
            if "profile_time" in g.columns:
                try:
                    g = g.sort_values("profile_time")
                except:
                    pass
            elif "cycle_number" in g.columns:
                g = g.sort_values("cycle_number")

            # --- A) If selected: Show Trajectory + All Profile Markers ---
            if is_selected:
                # 1. Trajectory Polyline
                if len(g) > 1:
                    coords = list(zip(g["latitude"], g["longitude"]))
                    children.append(
                        dl.Polyline(
                            positions=coords,
                            color="blue",
                            weight=3,
                            opacity=0.8,
                            dashArray="10, 10" # Animation style visual
                        )
                    )
                
                # 2. Profile Markers (Red)
                for _, row in g.iterrows():
                    lat, lon = row["latitude"], row["longitude"]
                    pid = row.get("profile_id", "Unknown")
                    if pd.isna(lat) or pd.isna(lon):
                        continue
                        
                    children.append(
                        dl.CircleMarker(
                            id={"type": "profile-marker", "profile_id": str(pid)},
                            center=(lat, lon),
                            radius=6,
                            color="red",
                            fill=True,
                            fillOpacity=0.8,
                            children=[
                                dl.Tooltip(f"Profile {pid}"),
                                dl.Popup(f"Profile {pid}<br>Lat: {lat:.2f}, Lon: {lon:.2f}")
                            ]
                        )
                    )
            
            # --- B) If NOT selected: Show ONE Float Marker (Latest) ---
            else:
                # Get last point
                last_row = g.iloc[-1]
                lat, lon = last_row["latitude"], last_row["longitude"]
                
                if pd.isna(lat) or pd.isna(lon):
                    continue

                children.append(
                    dl.CircleMarker(
                        id={"type": "float-marker", "float_id": fid_str},
                        center=(lat, lon),
                        radius=8,
                        color="#0f172a",  # distinct color (navy)
                        fillColor="#38bdf8", # sky blue
                        fill=True,
                        fillOpacity=1.0,
                        children=[
                            dl.Tooltip(f"Float {fid} (Click path)"),
                            dl.Popup(f"Float {fid}<br>Latest: {lat:.2f}, {lon:.2f}<br>Click to see trajectory.")
                        ]
                    )
                )

    # 2. Fallback: If no float_id, just plot profiles (red markers)
    else:
        for _, row in df.iterrows():
            lat, lon = row["latitude"], row["longitude"]
            pid = row.get("profile_id")
            if pd.isna(lat): continue
            
            children.append(
                dl.CircleMarker(
                    id={"type": "profile-marker", "profile_id": str(pid)},
                    center=(lat, lon),
                    radius=6,
                    color="red",
                    fill=True,
                    fillOpacity=0.8,
                    children=[
                         dl.Tooltip(f"Profile {pid}"),
                    ]
                )
            )

    return children


# 3b) Handle Marker Clicks (Float -> Expand, Profile -> Select)
@app.callback(
    Output("selected-float-store", "data"),
    Output("selected-profile-store", "data"),
    Input({"type": "float-marker", "float_id": dash.ALL}, "n_clicks"),
    Input({"type": "profile-marker", "profile_id": dash.ALL}, "n_clicks"),
    State("selected-float-store", "data"),
    State("selected-profile-store", "data"),
    prevent_initial_call=True,
)
def on_marker_click(float_clicks, profile_clicks, cur_float, cur_profile):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    prop_id = ctx.triggered[0]["prop_id"]
    try:
        # prop_id ex: '{"type":"float-marker","float_id":"190123"}.n_clicks'
        dict_str = prop_id.split(".")[0]
        id_dict = json.loads(dict_str)
        
        m_type = id_dict.get("type")
        
        if m_type == "float-marker":
            # Float click -> Update float store, keep profile same (or clear?)
            # Let's toggle? Or just set.
            clicked_fid = id_dict.get("float_id")
            # If already selected, maybe toggle off? Optional. Let's just set for now.
            return clicked_fid, cur_profile
            
        elif m_type == "profile-marker":
            # Profile click -> Update profile store, keep float same
            clicked_pid = id_dict.get("profile_id")
            return cur_float, str(clicked_pid)
            
    except Exception:
        raise PreventUpdate

    raise PreventUpdate


# 4) Update variable/profile dropdowns + meta + viz badge from rows + viz + selected profile
@app.callback(
    Output("variable-select", "options"),
    Output("variable-select", "value"),
    Output("profile-select", "options"),
    Output("profile-select", "value"),

    Output("viz-type-badge", "children"),
    Input("ask-rows-store", "data"),
    Input("ask-viz-store", "data"),
    Input("selected-profile-store", "data"),
)
def update_controls_and_meta(rows, viz, selected_profile):
    # Human-readable viz type labels
    VIZ_TYPE_LABELS = {
        "profile_plot": "📊 Vertical Profile",
        "overlaid_profiles": "📈 Overlaid Profiles",
        "section_plot": "🌡️ Section Plot",
        "ts_diagram": "💧 T-S Diagram",
        "time_series": "📉 Time Series",
        "map": "🗺️ Map View",
        "comparison": "⚖️ Comparison",
        "table": "📅 Data Table",
    }

    if not rows:
        return [], None, [], None, ""

    df = pd.DataFrame(rows)
    cols = df.columns.tolist()

    # ---- Variable selector ----
    # Candidates: BGC_VARS + temp/sal
    candidates = ["temperature_c", "salinity_psu"] + BGC_VARS
    available = [c for c in candidates if c in cols]
    
    var_options = [{"label": c, "value": c} for c in available]
    
    # helper for preferred var
    def get_preferred_var():
        # if viz intent has primary_variable, use it
        if viz and viz.get("primary_variable") in available:
            return viz.get("primary_variable")
        # else pick first available
        return available[0] if available else None

    var_value = get_preferred_var()

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
        # Sort accurately
        try:
            unique_profiles = sorted(unique_profiles, key=lambda x: int(x))
        except:
            unique_profiles = sorted(unique_profiles)
            
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

    # ---- Viz type badge ----
    viz_kind = ""
    if viz and isinstance(viz, dict):
        kind = viz.get("primary_kind") or viz.get("kind", "table")
        viz_kind = VIZ_TYPE_LABELS.get(kind, f"📊 {kind}")

    return var_options, var_value, profile_options, profile_value, viz_kind



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
    """
    Render visualization based on viz intent from backend.
    
    Supports:
    - profile_plot: Single vertical profile (variable vs depth)
    - overlaid_profiles: Multiple profiles overlaid
    - section_plot: Hovmöller/section (depth vs time heatmap)
    - ts_diagram: Temperature-Salinity diagram
    - time_series: Variable over time
    - comparison: Multi-float comparison
    - map: Location/trajectory (handled by map component)
    - table: Tabular display (fallback)
    """
    if not rows:
        return go.Figure(), "Results & Plots"

    df = pd.DataFrame(rows)
    # Ensure title default
    title = "Results & Plots"

    if not viz or not isinstance(viz, dict):
        # Fallback simple plot if possible
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

    # Support both old "kind" and new "primary_kind" for backwards compatibility
    kind = viz.get("primary_kind") or viz.get("kind", "table")
    primary_var = variable_value or viz.get("primary_variable")
    x_col = viz.get("x")
    y_col = viz.get("y")
    depth_col = viz.get("depth_col") or ("depth_m" if "depth_m" in df.columns else "pressure_dbar" if "pressure_dbar" in df.columns else None)
    time_col = viz.get("time_col") or ("profile_time" if "profile_time" in df.columns else None)
    group_by = viz.get("group_by") or []
    n_profiles = viz.get("n_profiles", 0)
    n_floats = viz.get("n_floats", 0)

    def col_ok(c):
        return c is not None and c in df.columns

    # Filter by selected profile if applicable
    df_filtered = df.copy()
    if profile_value and profile_value != "__all__" and "profile_id" in df.columns:
        df_filtered = df[df["profile_id"].astype(str) == str(profile_value)]

    # =========================================================================
    # 1. T-S DIAGRAM (Temperature vs Salinity scatter)
    # =========================================================================
    if kind == "ts_diagram":
        if "salinity_psu" in df_filtered.columns and "temperature_c" in df_filtered.columns:
            fig = go.Figure()
            
            # Color by profile_id if available
            if "profile_id" in df_filtered.columns and profile_value == "__all__":
                for pid, g in df_filtered.groupby("profile_id"):
                    fig.add_trace(
                        go.Scatter(
                            x=g["salinity_psu"],
                            y=g["temperature_c"],
                            mode="markers",
                            name=f"Profile {pid}",
                            marker=dict(size=5),
                        )
                    )
            else:
                fig.add_trace(
                    go.Scatter(
                        x=df_filtered["salinity_psu"],
                        y=df_filtered["temperature_c"],
                        mode="markers",
                        marker=dict(
                            size=5,
                            color=df_filtered[depth_col] if col_ok(depth_col) else None,
                            colorscale="Viridis",
                            colorbar=dict(title="Depth (m)") if col_ok(depth_col) else None,
                            reversescale=True,
                        ),
                    )
                )
            
            fig.update_xaxes(title="Salinity (PSU)")
            fig.update_yaxes(title="Temperature (°C)")
            title = "T-S Diagram (Water Mass Analysis)"
            fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
            return fig, title

    # =========================================================================
    # 2. COMPARISON (Multi-float side by side)
    # =========================================================================
    if kind == "comparison":
        if n_floats >= 2 and "float_id" in df_filtered.columns and primary_var and col_ok(primary_var):
            fig = go.Figure()
            
            for fid, g in df_filtered.groupby("float_id"):
                if col_ok(depth_col):
                    # Profile comparison: variable vs depth for each float
                    fig.add_trace(
                        go.Scatter(
                            x=g[primary_var],
                            y=g[depth_col],
                            mode="lines+markers",
                            name=f"Float {fid}",
                            marker=dict(size=4),
                        )
                    )
            
            if col_ok(depth_col):
                fig.update_yaxes(autorange="reversed", title=depth_col)
            fig.update_xaxes(title=primary_var)
            title = f"Float Comparison: {primary_var}"
            fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
            return fig, title

    # =========================================================================
    # 3. SECTION PLOT / HOVMÖLLER (Depth vs Time heatmap)
    # =========================================================================
    if kind == "section_plot":
        if col_ok(time_col) and col_ok(depth_col) and primary_var and col_ok(primary_var):
            try:
                df_plot = df_filtered.copy()
                df_plot["__time"] = pd.to_datetime(df_plot[time_col])
                df_plot = df_plot.sort_values(["__time", depth_col])
                
                # Create scatter plot with color representing the variable
                fig = go.Figure(
                    data=go.Scattergl(
                        x=df_plot["__time"],
                        y=df_plot[depth_col],
                        mode="markers",
                        marker=dict(
                            size=6,
                            color=df_plot[primary_var],
                            colorbar=dict(title=primary_var),
                            colorscale="Viridis",
                        ),
                    )
                )
                fig.update_yaxes(autorange="reversed", title=f"Depth ({depth_col})")
                fig.update_xaxes(title="Time")
                title = f"Section Plot: {primary_var} (Depth vs Time)"
                fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
                return fig, title
            except Exception:
                pass

    # =========================================================================
    # 4. OVERLAID PROFILES (Multiple cycles on one plot)
    # =========================================================================
    if kind == "overlaid_profiles":
        if col_ok(depth_col) and primary_var and col_ok(primary_var):
            fig = go.Figure()
            
            # Logic: If specific profile selected, show just that. 
            # If "All profiles", show multiple lines (limit to 50 for performance)
            if "profile_id" in df_filtered.columns and profile_value == "__all__":
                # Color-code by profile
                profile_ids = df_filtered["profile_id"].unique()
                colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", 
                          "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
                
                # Sort profiles safely
                try:
                    profile_ids = sorted(profile_ids, key=lambda x: int(x))
                except:
                    profile_ids = sorted(profile_ids, key=str)

                limit_n = 50
                for i, pid in enumerate(profile_ids[:limit_n]):
                    g = df_filtered[df_filtered["profile_id"] == pid].sort_values(depth_col)
                    fig.add_trace(
                        go.Scatter(
                            x=g[primary_var],
                            y=g[depth_col],
                            mode="lines",
                            name=f"Profile {pid}",
                            line=dict(color=colors[i % len(colors)]),
                        )
                    )
            else:
                # Single profile case
                df_sorted = df_filtered.sort_values(depth_col)
                fig.add_trace(
                    go.Scatter(
                        x=df_sorted[primary_var],
                        y=df_sorted[depth_col],
                        mode="lines",
                        name=f"Profile {profile_value}" if profile_value else primary_var,
                    )
                )
            
            fig.update_yaxes(autorange="reversed", title=f"Depth ({depth_col})")
            fig.update_xaxes(title=primary_var)
            title = f"Overlaid Profiles: {primary_var}"
            fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
            return fig, title

    # =========================================================================
    # 5. SINGLE PROFILE PLOT (Variable vs Depth)
    # =========================================================================
    if kind == "profile_plot":
        try:
            if col_ok(depth_col) and primary_var and col_ok(primary_var):
                fig = go.Figure()
                gb_col = group_by[0] if group_by else ("profile_id" if "profile_id" in df_filtered.columns else None)
    
                # If "All profiles" and we have a grouping column (like profile_id), plot multiple lines
                if gb_col and gb_col in df_filtered.columns and profile_value == "__all__":
                    # Limit to prevent browser crash if accidental huge query
                    unique_vals = df_filtered[gb_col].unique()
                    limit_n = 20  
                    
                    for i, val in enumerate(unique_vals[:limit_n]):
                        g = df_filtered[df_filtered[gb_col] == val]
                        g_sorted = g.sort_values(depth_col)
                        fig.add_trace(
                            go.Scatter(
                                x=g_sorted[primary_var],
                                y=g_sorted[depth_col],
                                mode="lines",
                                name=f"{gb_col} {val}",
                            )
                        )
                else:
                    # Single line (either one profile selected, or no grouping available)
                    df_sorted = df_filtered.sort_values(depth_col)
                    fig.add_trace(
                        go.Scatter(
                            x=df_sorted[primary_var],
                            y=df_sorted[depth_col],
                            mode="lines",
                            name=primary_var,
                        )
                    )
    
                fig.update_yaxes(autorange="reversed", title=f"Depth ({depth_col})")
                fig.update_xaxes(title=primary_var)
                title = f"Vertical Profile: {primary_var}"
                fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
                return fig, title
        except Exception:
            return go.Figure(), "Error rendering plot"

    # =========================================================================
    # 6. TIME-SERIES (Variable over time)
    # =========================================================================
    if kind == "time_series":
        if col_ok(time_col) and primary_var and col_ok(primary_var):
            fig = go.Figure()
            gb_col = group_by[0] if group_by else None

            try:
                df_plot = df_filtered.copy()
                df_plot["__time"] = pd.to_datetime(df_plot[time_col])
            except Exception:
                df_plot = df_filtered.copy()
                df_plot["__time"] = df_plot[time_col]

            if gb_col and gb_col in df_plot.columns and profile_value == "__all__":
                for val, g in df_plot.groupby(gb_col):
                    g_sorted = g.sort_values("__time")
                    fig.add_trace(
                        go.Scatter(
                            x=g_sorted["__time"],
                            y=g_sorted[primary_var],
                            mode="lines+markers",
                            name=str(val),
                            marker=dict(size=5),
                        )
                    )
            else:
                df_sorted = df_plot.sort_values("__time")
                fig.add_trace(
                    go.Scatter(
                        x=df_sorted["__time"],
                        y=df_sorted[primary_var],
                        mode="lines+markers",
                        name=primary_var,
                        marker=dict(size=5),
                    )
                )

            fig.update_xaxes(title="Time")
            fig.update_yaxes(title=primary_var)
            title = f"Time Series: {primary_var}"
            fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
            return fig, title

    # =========================================================================
    # 7. MAP (handled separately by map callback, show message here)
    # =========================================================================
    if kind == "map":
        fig = go.Figure()
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10),
            annotations=[
                dict(
                    text="📍 Spatial data shown on map (left panel)",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=14),
                )
            ],
        )
        title = "Map View"
        return fig, title

    # =========================================================================
    # 8. FALLBACK: Table only
    # =========================================================================
    fig = go.Figure()
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        annotations=[
            dict(
                text=f"Visualization: {kind}. See data table below.",
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


# 9) Toggle result table collapse
@app.callback(
    Output("table-content", "style"),
    Output("table-toggle-btn", "children"),
    Output("table-is-open", "data"),
    Input("table-toggle-btn", "n_clicks"),
    State("table-is-open", "data"),
    prevent_initial_call=True,
)
def toggle_table_collapse(n_clicks, is_open):
    if n_clicks is None:
        raise PreventUpdate
    
    new_state = not is_open
    if new_state:
        # Open
        style = {} # Managed by CSS max-height
        label = "Result Table ▲"
    else:
        # Closed
        style = {"borderTop": "none"} # Hide border when closed if needed, but CSS handles opacity
        label = "Result Table ▼"
        
    # We can't easily switch className dynamically to the output component's existing className in standard Dash 
    # unless we output to "className".
    # BUT, 'table-content' has the transition. 
    # Let's just output style for MAX-HEIGHT to be robust if we can't change class.
    # Actually, the user asked for max-height transition.
    # We can output a STYLE dict that changes max-height.
    
    if new_state:
        return {"maxHeight": "500px", "opacity": "1", "padding": "1rem"}, label, new_state
    else:
        return {"maxHeight": "0px", "opacity": "0", "padding": "0 1rem", "borderTop": "none", "overflow": "hidden"}, label, new_state



# 6) Clientside callback for voice input
app.clientside_callback(
    ClientsideFunction(
        namespace="clientside",
        function_name="recordAudio"
    ),
    Output("chat-input", "value", allow_duplicate=True),
    Input("mic-btn", "n_clicks"),
    State("chat-input", "value"),
    prevent_initial_call=True,
)

if __name__ == "__main__":
    app.run(debug=True)
