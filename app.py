import os
from flask import Flask, render_template, jsonify, request
import pandas as pd
import fastf1
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set cache directory for FastF1
fastf1.Cache.enable_cache('cache') 

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Global Variables ---
DEFAULT_SMOOTHING_WINDOW = 15
# In-memory cache to store fetched session data to avoid re-downloading
_cached_telemetry_data = {}

# --- Data Fetching Function ---
def fetch_session_data(session_key):
    """
    Fetches and processes telemetry data for a given session.
    Results are cached in memory to speed up subsequent requests.
    """
    if session_key in _cached_telemetry_data:
        logger.info(f"Using cached telemetry data for session: {session_key}")
        return _cached_telemetry_data[session_key]

    logger.info(f"Fetching new data for session: {session_key}")
    try:
        year_str, event_name, session_name = session_key.split('-', 2)
        year = int(year_str)
        
        session = fastf1.get_session(year, event_name, session_name)
        session.load(telemetry=True, laps=True, weather=False, messages=False)

        valid_drivers_df = session.laps[['Driver', 'DriverNumber']].dropna().drop_duplicates(subset=['DriverNumber'])
        drivers = sorted(valid_drivers_df['DriverNumber'].astype(int).tolist())
        driver_mapping = {int(row.DriverNumber): row.Driver for index, row in valid_drivers_df.iterrows()}

        all_telemetry = pd.DataFrame()
        for driver_num in drivers:
            if driver_num in driver_mapping:
                laps_driver = session.laps.pick_drivers([driver_mapping[driver_num]])
                if not laps_driver.empty:
                    telemetry_data = laps_driver.get_car_data().add_distance()
                    if not telemetry_data.empty:
                        # Standardize column names to lowercase to handle inconsistencies
                        telemetry_data.columns = [col.lower() for col in telemetry_data.columns]
                        
                        telemetry_data['date_ms'] = (telemetry_data['date'].astype('int64') // 10**6)
                        telemetry_data['driver_number'] = driver_num
                        all_telemetry = pd.concat([all_telemetry, telemetry_data])

        if all_telemetry.empty:
            logger.warning(f"No telemetry data found for session: {session_key}")
            return pd.DataFrame(), {}, []

        # Check for available telemetry channels before processing
        metrics_to_smooth = ["throttle", "brake", "speed"]
        available_metrics = [metric for metric in metrics_to_smooth if metric in all_telemetry.columns]
        logger.info(f"Found available telemetry channels to smooth: {available_metrics}")

        for metric in available_metrics:
            all_telemetry[metric] = all_telemetry.groupby('driver_number')[metric].rolling(
                window=DEFAULT_SMOOTHING_WINDOW, min_periods=1, center=True
            ).mean().reset_index(level=0, drop=True)
        
        # Look for 'ngear' (lowercase, no underscore) and rename for consistency
        if 'ngear' in all_telemetry.columns:
            all_telemetry.rename(columns={'ngear': 'n_gear'}, inplace=True)
            all_telemetry['n_gear'] = all_telemetry['n_gear'].astype(str)

        _cached_telemetry_data[session_key] = (all_telemetry, driver_mapping, drivers)
        return all_telemetry, driver_mapping, drivers

    except Exception as e:
        logger.error(f"Error fetching data for session {session_key}: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame(), {}, []

# --- Flask Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')

@app.route('/api/sessions')
def get_sessions():
    """Returns a dynamic list of available F1 sessions from 2019 to the present."""
    sessions = []
    current_year = datetime.now().year
    
    for year in range(current_year, 2018, -1):
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
            for index, event in schedule.iterrows():
                event_name_simple = event['EventName'].replace(' Grand Prix', '').lower()
                
                sessions.append({
                    'label': f"{year} {event['EventName']} - Race",
                    'value': f"{year}-{event_name_simple}-race"
                })
                sessions.append({
                    'label': f"{year} {event['EventName']} - Qualifying",
                    'value': f"{year}-{event_name_simple}-qualifying"
                })
                if 'Sprint' in event and pd.notna(event['Sprint']):
                     sessions.append({
                        'label': f"{year} {event['EventName']} - Sprint",
                        'value': f"{year}-{event_name_simple}-sprint"
                    })
        except Exception as e:
            logger.error(f"Could not fetch schedule for year {year}: {e}")

    return jsonify(sessions)

@app.route('/api/drivers/<session_key>')
def get_drivers(session_key):
    """Returns a list of drivers for a given session, sorted alphabetically."""
    _, driver_mapping, _ = fetch_session_data(session_key)
    driver_options = [{'label': f"{name} ({num})", 'value': num} for num, name in driver_mapping.items()]
    return jsonify(sorted(driver_options, key=lambda x: x['label']))

@app.route('/api/telemetry')
def get_telemetry_data():
    """Returns filtered telemetry data for selected drivers and session."""
    session_key = request.args.get('session')
    selected_drivers_str = request.args.get('drivers')

    if not session_key or not selected_drivers_str:
        return jsonify({"error": "Missing session or drivers parameter"}), 400

    try:
        selected_drivers_nums = [int(d) for d in selected_drivers_str.split(',')]
    except ValueError:
        return jsonify({"error": "Invalid driver numbers"}), 400

    if len(selected_drivers_nums) > 2:
        selected_drivers_nums = selected_drivers_nums[:2]
        logger.warning(f"Limiting driver selection to: {selected_drivers_nums}")

    all_telemetry, driver_mapping, _ = fetch_session_data(session_key)

    if all_telemetry.empty:
        return jsonify({"data": [], "driver_mapping": {}})

    filtered_df = all_telemetry[all_telemetry['driver_number'].isin(selected_drivers_nums)]
    
    # Dynamically select available columns for the final output
    base_cols = ['date_ms', 'driver_number']
    telemetry_cols = ['throttle', 'brake', 'speed', 'n_gear']
    available_cols = [col for col in telemetry_cols if col in filtered_df.columns]
    
    final_cols = base_cols + available_cols

    data_for_json = filtered_df[final_cols].to_dict(orient='records')
    string_driver_mapping = {str(k): v for k, v in driver_mapping.items()}

    return jsonify({
        "data": data_for_json,
        "driver_mapping": string_driver_mapping
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)