# app.py (Improved Visualization)
import dash
from dash import dcc, html, Input, Output
import plotly.graph_objs as go
import pandas as pd
import httpx
import logging
import asyncio
import nest_asyncio
from datetime import datetime


logging.basicConfig(level=logging.INFO)


app = dash.Dash(__name__)
app.title = "F1 Telemetry Dashboard - Enhanced"


nest_asyncio.apply()

app.layout = html.Div([
    html.H1("Live F1 Telemetry Comparison", style={'textAlign': 'center'}),
    dcc.Interval(id="live-update", interval=15*1000, n_intervals=0),  # Reduced refresh rate
    
    html.Div([
        dcc.Graph(id="throttle-graph", style={'height': '400px', 'width': '49%', 'display': 'inline-block'}),
        dcc.Graph(id="brake-graph", style={'height': '400px', 'width': '49%', 'display': 'inline-block'}),
    ], style={'padding': '10px'}),
    
    html.Div([
        dcc.Graph(id="speed-graph", style={'height': '400px', 'width': '49%', 'display': 'inline-block'}),
        dcc.Graph(id="gear-graph", style={'height': '400px', 'width': '49%', 'display': 'inline-block'}),
    ], style={'padding': '10px'})
])


async def fetch_car_data():
    try:
        # Hardcoded values for testing
        session_key = 9158
        drivers = [1, 3]
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            responses = await asyncio.gather(
                client.get("https://api.openf1.org/v1/car_data",
                          params={"session_key": session_key, "driver_number": drivers[0]}),
                client.get("https://api.openf1.org/v1/car_data",
                          params={"session_key": session_key, "driver_number": drivers[1]})
            )
            
            dfs = []
            for response in responses:
                if response.status_code == 200:
                    df = pd.DataFrame(response.json())
                    if not df.empty:
                        # Convert and smooth data
                        df["date"] = pd.to_datetime(df["date"])
                        for col in ['throttle', 'brake', 'speed']:
                            df[col] = df[col].rolling(window=15, min_periods=1).mean()  # Increased smoothing
                        dfs.append(df)
            
            if len(dfs) < 2:
                return pd.DataFrame()
                
            combined = pd.concat(dfs)
            return combined.sort_values("date").ffill()
            
    except Exception as e:
        logging.error(f"Data error: {str(e)}")
        return pd.DataFrame()

# ========================
#    VISUALIZATION STYLING
# ========================
def create_styled_figure(df, metric, drivers):
    # Color scheme
    colors = ['#636EFA', '#EF553B']  # Plotly's default blue and red
    
    return {
        'data': [
            go.Scatter(
                x=df[df["driver_number"] == driver]["date"],
                y=df[df["driver_number"] == driver][metric],
                name=f"Driver {driver}",
                line=dict(color=colors[i], width=2),
                mode='lines',
                hovertemplate="<b>%{y}</b><br>%{x|%H:%M:%S}<extra></extra>"
            ) for i, driver in enumerate(drivers)
        ],
        'layout': go.Layout(
            title=f"{metric.upper()} COMPARISON",
            margin=dict(t=40, b=40, l=60, r=30),
            xaxis=dict(
                title="Time",
                tickformat="%H:%M:%S",
                gridcolor='#f0f0f0'
            ),
            yaxis=dict(
                title=metric.capitalize(),
                gridcolor='#f0f0f0'
            ),
            plot_bgcolor='white',
            hovermode='x unified',
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
    }

# ========================
#      CALLBACKS
# ========================
def sync_fetch_car_data():
    return asyncio.run(fetch_car_data())

@app.callback(
    [Output("throttle-graph", "figure"),
     Output("brake-graph", "figure"),
     Output("speed-graph", "figure"),
     Output("gear-graph", "figure")],  # Correct ID here
    [Input("live-update", "n_intervals")]
)
def update_graphs(n):
    try:
        df = sync_fetch_car_data()
        if df.empty:
            return [go.Figure()] * 4
            
        drivers = df["driver_number"].unique()
        return (
            create_styled_figure(df, "throttle", drivers),
            create_styled_figure(df, "brake", drivers),
            create_styled_figure(df, "speed", drivers),
            create_styled_figure(df, "n_gear", drivers)
        )
    except Exception as e:
        logging.error(f"Callback error: {str(e)}")
        return [go.Figure()] * 4

if __name__ == "__main__":
    app.run_server(debug=True, port=8050)