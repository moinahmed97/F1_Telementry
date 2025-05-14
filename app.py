import dash
from dash import dcc, html, Input, Output, State, no_update
import plotly.graph_objs as go
import pandas as pd
import httpx
import logging
import asyncio
import nest_asyncio
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

nest_asyncio.apply()

app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "F1 Telemetry Dashboard - V5"

API_BASE_URL = "https://api.openf1.org/v1"
DEFAULT_SESSION_KEY = "9158"
DEFAULT_TIME_WINDOW_MINUTES = 60
DEFAULT_SMOOTHING_WINDOW = 5

app.layout = html.Div(
    [
        html.H1("Live F1 Telemetry Comparison", style={"textAlign": "center", "marginBottom": "20px"}),
        
        dcc.Store(id="driver-mapping-store"),
        
        html.Div(
            [
                dcc.Input(
                    id="session-input",
                    type="text",
                    placeholder="Enter Session Key (e.g., 9158 or latest)",
                    value=DEFAULT_SESSION_KEY,
                    style={"marginRight": "10px", "padding": "8px", "borderRadius": "4px", "border": "1px solid #ccc"},
                ),
                html.Button(
                    "Load Session & Drivers", 
                    id="load-session-button", 
                    n_clicks=0,
                    style={"padding": "8px 12px", "borderRadius": "4px", "border": "1px solid #007bff", "backgroundColor": "#007bff", "color": "white", "cursor": "pointer"}
                ),
            ],
            style={"display": "flex", "justifyContent": "center", "alignItems": "center", "padding": "10px", "gap": "10px"},
        ),
        html.Div(
            [
                dcc.Dropdown(
                    id="driver-dropdown",
                    multi=True,
                    placeholder="Select Drivers (after loading session)",
                    style={"minWidth": "300px", "marginRight": "10px", "width": "calc(50% - 5px)"}, 
                ),
                dcc.Input(
                    id="time-window-input",
                    type="number",
                    placeholder="Time Window (minutes for 'latest')",
                    value=DEFAULT_TIME_WINDOW_MINUTES,
                    min=1,
                    step=1,
                    style={"width": "200px", "padding": "8px", "borderRadius": "4px", "border": "1px solid #ccc"},
                ),
            ],
            style={"display": "flex", "justifyContent": "center", "alignItems": "center", "padding": "10px 0 20px 0", "gap": "10px"},
        ),
        
        dcc.Interval(id="live-update", interval=15 * 1000, n_intervals=0),
        
        html.Div(
            [
                dcc.Loading(id="loading-throttle", type="default", 
                            children=dcc.Graph(id="throttle-graph", style={"height": "55vh", "width": "100%"})
                           ) 
            ],
            style={"padding": "10px", "width": "98%", "margin": "auto"},
        ),
        html.Div(
            [
                dcc.Loading(id="loading-brake", type="default", 
                            children=dcc.Graph(id="brake-graph", style={"height": "55vh", "width": "100%"})
                           )
            ],
            style={"padding": "10px", "width": "98%", "margin": "auto"},
        ),
        html.Div(
            [
                dcc.Loading(id="loading-speed", type="default", 
                            children=dcc.Graph(id="speed-graph", style={"height": "55vh", "width": "100%"})
                           )
            ],
            style={"padding": "10px", "width": "98%", "margin": "auto"},
        ),
        html.Div(
            [
                dcc.Loading(id="loading-gear", type="default", 
                            children=dcc.Graph(id="gear-graph", style={"height": "55vh", "width": "100%"})
                           )
            ],
            style={"padding": "10px", "width": "98%", "margin": "auto"},
        ),
    ],
    style={"fontFamily": "Arial, sans-serif"},
)

async def fetch_drivers_for_session(session_key):
    if not session_key: return {}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{API_BASE_URL}/drivers", params={"session_key": session_key})
            response.raise_for_status()
            drivers_data = response.json()
            return {int(driver["driver_number"]): driver["full_name"] for driver in drivers_data if driver.get("driver_number") is not None and driver.get("full_name")}
    except Exception as e:
        logger.error(f"Error fetching/processing driver data for session {session_key}: {e}")
    return {}

@app.callback(
    Output("driver-dropdown", "options"),
    Output("driver-dropdown", "value"), 
    Output("driver-mapping-store", "data"),
    Input("load-session-button", "n_clicks"),
    State("session-input", "value"),
    prevent_initial_call=True,
)
def update_driver_options_and_mapping(n_clicks, session_key):
    if n_clicks == 0 or not session_key:
        return [], [], dash.no_update
    
    logger.info(f"Load button clicked (n_clicks: {n_clicks}). Fetching drivers for session: {session_key}")
    driver_mapping = asyncio.run(fetch_drivers_for_session(session_key))
    
    if not driver_mapping:
        logger.warning(f"No driver data found for session: {session_key}")
        return [], [], {}
        
    options = sorted([{"label": name, "value": num} for num, name in driver_mapping.items()], key=lambda x: x['label'])
    logger.info(f"Driver options for session {session_key}: {len(options)} drivers")
    return options, [], driver_mapping

async def fetch_car_data(session_key, driver_numbers, window_minutes=None):
    if not session_key or not driver_numbers:
        logger.warning("fetch_car_data: called with no session_key or no driver_numbers.")
        return pd.DataFrame()

    all_driver_dfs = []
    date_filter_param = {}
    if str(session_key).lower() == "latest" and window_minutes is not None and window_minutes > 0:
        start_time = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        date_filter_param["date>="] = start_time.isoformat(timespec='milliseconds')
        logger.info(f"Applying date filter for 'latest' session: date >= {date_filter_param['date>=']}")
    elif str(session_key).lower() != "latest":
        logger.info(f"Fetching historical data for session {session_key}. Time window input is ignored for fetching.")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            tasks = []
            for num in driver_numbers:
                params = {"session_key": session_key, "driver_number": int(num)}
                if date_filter_param:
                    params.update(date_filter_param)
                tasks.append(client.get(f"{API_BASE_URL}/car_data", params=params))
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for i, response in enumerate(responses):
                driver_num = driver_numbers[i]
                if isinstance(response, httpx.Response) and response.status_code == 200:
                    data = response.json()
                    if data:
                        df = pd.DataFrame(data)
                        if not df.empty:
                            df["date"] = pd.to_datetime(df["date"])
                            for col in ['throttle', 'brake', 'speed', 'rpm', 'n_gear']:
                                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
                            for col_smooth in ['throttle', 'brake', 'speed', 'rpm']:
                                if col_smooth in df.columns and pd.api.types.is_numeric_dtype(df[col_smooth]):
                                    df[col_smooth] = df[col_smooth].rolling(window=DEFAULT_SMOOTHING_WINDOW, min_periods=1).mean()
                            all_driver_dfs.append(df)
                        else: logger.info(f"Empty DataFrame created for driver {driver_num}, session {session_key}")
                    else: logger.info(f"Empty JSON list received for driver {driver_num}, session {session_key}")
                elif isinstance(response, Exception): logger.error(f"Request failed for driver {driver_num}, session {session_key}: {response}")
                else: logger.error(f"API error for driver {driver_num}, session {session_key}: {response.status_code} - {response.text}")
        
        if not all_driver_dfs: 
            logger.warning("No dataframes were successfully fetched or processed from any driver.")
            return pd.DataFrame()
        
        combined_df = pd.concat(all_driver_dfs).sort_values("date").ffill()
        logger.info(f"Successfully fetched/combined data for {len(all_driver_dfs)} driver(s). Shape: {combined_df.shape}")
        return combined_df
    except Exception as e:
        logger.error(f"Generic error in fetch_car_data: {e}")
    return pd.DataFrame()

def create_styled_figure(df, metric, selected_drivers, driver_mapping, session_key):
    fig_data = []
    dash_styles = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot'] 

    for i, driver_num in enumerate(selected_drivers):
        driver_df = df[df["driver_number"] == driver_num]
        if not driver_df.empty:
            driver_name = driver_mapping.get(driver_num, f"Driver {driver_num}")
            
            line_props = {
                "width": 2.0, 
                "dash": dash_styles[i % len(dash_styles)] 
            }
            if metric == 'n_gear':
                line_props['shape'] = 'hv'

            if metric in driver_df.columns and not driver_df[metric].dropna().empty:
                fig_data.append(
                    go.Scatter(
                        x=driver_df["date"], 
                        y=driver_df[metric], 
                        name=driver_name, 
                        line=line_props, 
                        mode="lines",
                        opacity=0.75, 
                        hovertemplate=f"<b>{driver_name}</b><br>{metric.replace('_', ' ').capitalize()}: %{{y}}<br>Time: %{{x|%H:%M:%S}}<extra></extra>"
                    )
                )
            else: 
                logger.warning(f"Metric '{metric}' missing or empty for driver {driver_name} (ID: {driver_num}). Skipping trace.")
    
    uirevision_key = f"{session_key}-{'-'.join(map(str, sorted(selected_drivers)))}-{metric}"
    
    layout_title = f"{metric.replace('_', ' ').upper()} COMPARISON"
    yaxis_title = metric.replace("_", " ").capitalize()
    if metric == 'n_gear':
        yaxis_title = "Gear"

    layout = go.Layout(
        title=layout_title, 
        margin=dict(t=50, b=50, l=70, r=40), 
        xaxis=dict(title="Time", tickformat="%H:%M:%S", gridcolor="#e0e0e0", showgrid=True), 
        yaxis=dict(title=yaxis_title, gridcolor="#e0e0e0", showgrid=True, type='linear' if metric != 'n_gear' else 'category'),
        plot_bgcolor="white", 
        paper_bgcolor="white", 
        font=dict(family="Arial, sans-serif", size=12, color="#333"), 
        hovermode="x unified", 
        showlegend=True, 
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor='rgba(255,255,255,0.8)', bordercolor='#ccc', borderwidth=1), 
        uirevision=uirevision_key
    )
    
    if not fig_data:
        layout.annotations = [dict(text=f"No data available for {metric.replace('_', ' ').capitalize()}", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)]
    
    return {"data": fig_data, "layout": layout}

@app.callback(
    [Output("throttle-graph", "figure"), Output("brake-graph", "figure"), Output("speed-graph", "figure"), Output("gear-graph", "figure")],
    Input("live-update", "n_intervals"), 
    State("session-input", "value"),
    State("driver-dropdown", "value"), 
    State("time-window-input", "value"),
    State("driver-mapping-store", "data"), 
)
def update_graphs(n_intervals, session_key, selected_drivers_str, time_window_minutes, driver_mapping):
    if not session_key or not selected_drivers_str or not driver_mapping:
        if not driver_mapping and selected_drivers_str:
             logger.warning("Driver mapping is missing despite drivers being selected. Cannot proceed.")
        else:
            logger.info("Update_graphs: Not enough data (session, selected drivers, or driver mapping missing). Waiting for user input.")
        no_data_layout = go.Layout(title="Please load session and select drivers.", xaxis={'visible': False}, yaxis={'visible': False})
        empty_fig = {"data": [], "layout": no_data_layout}
        return empty_fig, empty_fig, empty_fig, empty_fig

    try:
        processed_selected_drivers = [int(d) for d in selected_drivers_str]
    except ValueError:
        logger.error(f"Could not convert selected_drivers to int: {selected_drivers_str}")
        error_layout = go.Layout(title="Invalid driver ID in selection.", xaxis={'visible': False}, yaxis={'visible': False})
        error_fig = {"data": [], "layout": error_layout}
        return error_fig, error_fig, error_fig, error_fig

    logger.info(f"Updating graphs for session {session_key}, drivers {processed_selected_drivers}, window {time_window_minutes} mins (window only used for 'latest').")
    df = asyncio.run(fetch_car_data(session_key, processed_selected_drivers, time_window_minutes))

    if df.empty:
        logger.warning("Fetched car data is empty. Displaying empty graphs with message.")
        no_data_layout = go.Layout(title="No telemetry data found for current selection.", xaxis={'visible': False}, yaxis={'visible': False})
        empty_fig = {"data": [], "layout": no_data_layout}
        return empty_fig, empty_fig, empty_fig, empty_fig
    
    actual_drivers_in_df = [d for d in processed_selected_drivers if d in df['driver_number'].unique()]
    if not actual_drivers_in_df:
        logger.warning("None of the selected drivers have data in the fetched dataframe after processing.")
        no_data_layout = go.Layout(title="Data not available for the selected driver(s) in this session.", xaxis={'visible': False}, yaxis={'visible': False})
        empty_fig = {"data": [], "layout": no_data_layout}
        return empty_fig, empty_fig, empty_fig, empty_fig

    throttle_fig = create_styled_figure(df, "throttle", actual_drivers_in_df, driver_mapping, session_key)
    brake_fig = create_styled_figure(df, "brake", actual_drivers_in_df, driver_mapping, session_key)
    speed_fig = create_styled_figure(df, "speed", actual_drivers_in_df, driver_mapping, session_key)
    gear_fig = create_styled_figure(df, "n_gear", actual_drivers_in_df, driver_mapping, session_key)
    
    logger.info(f"Successfully created figures for session {session_key}, drivers {actual_drivers_in_df}. Returning figures to Dash.")
    return throttle_fig, brake_fig, speed_fig, gear_fig

if __name__ == "__main__":
    app.run_server(debug=True, port=8050)
