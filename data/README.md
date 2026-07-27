
# data/

Raw source files for the Hokkaido grid capstone. **Not committed** (see `.gitignore`) —
regenerable from the sources below.

## hepco_demand_2026-04.csv
HEPCO area supply-demand actuals (エリア需給実績), April 2026, from Hokkaido Electric
Power's disclosure page. Encoding CP932, line endings CRLF, 30-minute grain, unit MW.

## weather_sapporo_2026-04.json
Open-Meteo ERA5 historical reanalysis. Sapporo (lat 43.06, lon 141.35 requested; ERA5
grid-cell centre 43.058, 141.429), April 2026, hourly, timezone Asia/Tokyo.
Endpoint: https://archive-api.open-meteo.com/v1/archive

Regenerate:
    curl "https://archive-api.open-meteo.com/v1/archive?latitude=43.06&longitude=141.35&start_date=2026-04-01&end_date=2026-04-30&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,snowfall&timezone=Asia/Tokyo" -o data/weather_sapporo_2026-04.json

Licence: CC BY 4.0 — attribution required:
> Open-Meteo.com, CC BY 4.0. Zippenfenig, P. (2023). Open-Meteo.com Weather API.
> Zenodo. https://doi.org/10.5281/ZENODO.7970649
> ERA5 data by ECMWF / Copernicus Climate Change Service.
