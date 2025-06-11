

document.addEventListener('DOMContentLoaded', function() {
    const sessionSelect = document.getElementById('session-select');
    const driverSelect = document.getElementById('driver-select');
    const updateButton = document.getElementById('update-graphs-button');

    const graphDivs = {
        throttle: document.getElementById('throttle-graph'),
        brake: document.getElementById('brake-graph'),
        speed: document.getElementById('speed-graph'),
        n_gear: document.getElementById('gear-graph')
    };

    const colors = ['#FF4500', '#1E90FF', '#32CD32', '#9400D3', '#FFD700', '#ADFF2F', '#FF1493', '#00FFFF', '#FF8C00'];
    const dash_styles = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot', 'solid', 'dash', 'dot'];

    function capitalizeFirstLetter(string) {
        if (!string) return '';
        return string.charAt(0).toUpperCase() + string.slice(1);
    }

    async function fetchData(url) {
        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("Error fetching data:", error);
            return null;
        }
    }

    async function populateSessions() {
        const sessions = await fetchData('/api/sessions');
        if (sessions) {
            sessionSelect.innerHTML = '';
            sessions.forEach(session => {
                const option = document.createElement('option');
                option.value = session.value;
                option.textContent = session.label;
                sessionSelect.appendChild(option);
            });
            if (sessions.length > 0) {
                populateDrivers(sessionSelect.value);
            }
        }
    }

    async function populateDrivers(sessionKey) {
        const driverOptions = await fetchData(`/api/drivers/${sessionKey}`);
        if (driverOptions) {
            driverSelect.innerHTML = '';
            driverOptions.forEach(driver => {
                const option = document.createElement('option');
                option.value = driver.value;
                option.textContent = driver.label;
                driverSelect.appendChild(option);
            });
            if (driverOptions.length > 0) {
                driverSelect.options[0].selected = true;
                if (driverOptions.length > 1) {
                    driverSelect.options[1].selected = true;
                }
            }
        }
    }

    function plotTelemetry(data, driverMapping) {
        const metrics = ['throttle', 'brake', 'speed', 'n_gear'];

        for (const metric in graphDivs) {
            Plotly.purge(graphDivs[metric]);
        }

        metrics.forEach(metric => {
            const traces = [];
            const selectedDrivers = Array.from(driverSelect.selectedOptions).map(option => parseInt(option.value));
            const cleanMetricName = capitalizeFirstLetter(metric.replace('_', ' '));
            const yaxisTitle = (metric === 'n_gear') ? 'Gear' : `${cleanMetricName} ${metric === 'speed' ? '(km/h)' : (metric === 'throttle' || metric === 'brake' ? '(%)' : '')}`;

            const dataByDriver = {};
            data.forEach(d => {
                if (selectedDrivers.includes(d.driver_number)) {
                    if (!dataByDriver[d.driver_number]) {
                        dataByDriver[d.driver_number] = [];
                    }
                    dataByDriver[d.driver_number].push(d);
                }
            });

            let i = 0;
            for (const driverNum in dataByDriver) {
                const driverData = dataByDriver[driverNum];
                const driverName = driverMapping[driverNum] || `Driver ${driverNum}`;
                driverData.sort((a, b) => a.date_ms - b.date_ms);

                const x = driverData.map(d => new Date(d.date_ms));
                const y = driverData.map(d => d[metric]);

                if (y.every(val => val === null || val === undefined)) {
                    console.warn(`No valid data for metric '${metric}' for driver ${driverName}. Skipping trace.`);
                    continue;
                }
                
                traces.push({
                    x: x,
                    y: y,
                    mode: 'lines',
                    name: driverName,
                    line: {
                        color: colors[i % colors.length],
                        dash: dash_styles[i % dash_styles.length],
                        width: 2.5,
                        shape: (metric === 'n_gear') ? 'hv' : 'linear'
                    },
                    opacity: 0.9,
                    hovertemplate: `<b>${driverName}</b><br>${cleanMetricName}: %{y:.1f}<br>Time: %{x|%H:%M:%S}<extra></extra>`
                });
                i++;
            }

            const layout = {
                title: { text: `${cleanMetricName.toUpperCase()} COMPARISON`, x: 0.5 },
                margin: { t: 60, b: 50, l: 70, r: 40 },
                xaxis: {
                    title: 'Time',
                    tickformat: '%H:%M:%S',
                    gridcolor: '#e0e0e0',
                    showgrid: true,
                    rangeslider: { visible: true, thickness: 0.05 },
                    type: 'date'
                },
                yaxis: {
                    title: yaxisTitle,
                    gridcolor: '#e0e0e0',
                    showgrid: true,
                    type: (metric === 'n_gear') ? 'category' : 'linear',
                    range: (metric === 'throttle' || metric === 'brake') ? [0, 100] : null,
                    zeroline: true,
                    zerolinecolor: '#cccccc'
                },
                plot_bgcolor: '#f8f8f8',
                paper_bgcolor: 'white',
                font: { family: 'Arial, sans-serif', size: 12, color: '#333' },
                hovermode: 'x unified',
                showlegend: true,
                legend: { orientation: 'h', yanchor: 'bottom', y: 1.02, xanchor: 'right', x: 1 },
                uirevision: `${sessionSelect.value}-${selectedDrivers.join('-')}-${metric}`
            };

            if (traces.length === 0) {
                layout.annotations = [{
                    text: `No data available for ${cleanMetricName} for the selected drivers.`,
                    showarrow: false, xref: "paper", yref: "paper", x: 0.5, y: 0.5,
                    font: { size: 16, color: "#888" }
                }];
            }

            Plotly.newPlot(graphDivs[metric], traces, layout, {responsive: true});
        });
    }

    sessionSelect.addEventListener('change', (event) => {
        populateDrivers(event.target.value);
    });

    updateButton.addEventListener('click', async () => {
        const selectedSession = sessionSelect.value;
        const selectedDrivers = Array.from(driverSelect.selectedOptions).map(option => option.value);

        if (!selectedSession || selectedDrivers.length === 0) {
            alert('Please select a session and at least one driver.');
            return;
        }

        const driversToFetch = selectedDrivers.slice(0, 2);
        if (selectedDrivers.length > 2) {
            console.warn("Limiting selection to the first two drivers for clarity.");
        }

        const telemetryData = await fetchData(`/api/telemetry?session=${selectedSession}&drivers=${driversToFetch.join(',')}`);
        if (telemetryData && telemetryData.data && telemetryData.driver_mapping) {
            plotTelemetry(telemetryData.data, telemetryData.driver_mapping);
        } else {
            console.error("Failed to load telemetry data.");
        }
    });

    populateSessions();
});