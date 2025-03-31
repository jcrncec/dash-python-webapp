import os
import re
import shutil
import zipfile
import contextlib
import io
import xml.etree.ElementTree as ET
import pandas as pd
from io import BytesIO
from dash import Dash, html, dcc, dash_table, Input, Output, State, ctx
import dash_bootstrap_components as dbc
import base64
from processor import (
    extract_kml_from_kmz,
    delete_files_in_folder,
    remove_cdata_from_kml,
    extract_coordinates_from_kml,
    merge_kml_files
)

# Setup
KMZ_DIR = "kmz"
KML_DIR = "kml"
os.makedirs(KMZ_DIR, exist_ok=True)
os.makedirs(KML_DIR, exist_ok=True)

CITIES = [
    "Zagreb", "Split", "Dubrovnik", "Zadar",
    "Rijeka", "Varaždin", "Opatija", "Pula", "Poreč"
]

app = Dash(__name__, external_stylesheets=[dbc.themes.FLATLY])
app.title = "KMZ/KML Processor"

# Layout
app.layout = dbc.Container([
    html.H1("📍 KMZ/KML Processor for Croatian Cities", className="my-4"),

    dbc.Row([
        dbc.Col([
            dcc.Dropdown(
                options=[{"label": c, "value": c} for c in CITIES],
                placeholder="Choose a city",
                id="city-dropdown"
            )
        ], md=6),
        dbc.Col([
            dbc.Input(type="text", placeholder="Or enter a custom city", id="custom-city")
        ], md=6)
    ], className="mb-3"),

    dcc.Upload(
        id="upload-data",
        children=html.Div([
            "Drag and drop or ",
            html.A("select KMZ/KML files")
        ]),
        style={
            "width": "100%",
            "height": "80px",
            "lineHeight": "80px",
            "borderWidth": "1px",
            "borderStyle": "dashed",
            "borderRadius": "5px",
            "textAlign": "center",
        },
        multiple=True
    ),

    dbc.Button("🚀 Process Files", id="process-button", color="primary", className="my-3"),

    html.Div(id="output-alert"),
    html.Div(id="output-sql"),
    html.Div(id="output-table"),
    html.Div(id="output-map"),
    html.Div(id="output-download")
])

# Callback
@app.callback(
    Output("output-alert", "children"),
    Output("output-sql", "children"),
    Output("output-table", "children"),
    Output("output-map", "children"),
    Output("output-download", "children"),
    Input("process-button", "n_clicks"),
    State("upload-data", "contents"),
    State("upload-data", "filename"),
    State("city-dropdown", "value"),
    State("custom-city", "value"),
    prevent_initial_call=True
)
def process_files(n_clicks, contents, filenames, selected_city, custom_city):
    if not contents:
        return dbc.Alert("Please upload at least one KMZ or KML file.", color="warning"), "", "", "", ""

    city = custom_city.strip() if custom_city else selected_city
    if not city:
        return dbc.Alert("Please select or enter a city name.", color="warning"), "", "", "", ""

    delete_files_in_folder(KMZ_DIR)
    delete_files_in_folder(KML_DIR)

    count = 30000
    all_coords = []
    polygons = []
    sql_output_all = []

    for content, filename in zip(contents, filenames):
        ext = os.path.splitext(filename)[1].lower()
        data = content.split(',')[1]
        decoded = base64.b64decode(data)

        file_path = os.path.join(KMZ_DIR, filename)
        with open(file_path, "wb") as f:
            f.write(decoded)

        if ext == ".kmz":
            kml_path = extract_kml_from_kmz(file_path, KML_DIR)
        elif ext == ".kml":
            kml_path = os.path.join(KML_DIR, filename)
            shutil.move(file_path, kml_path)
        else:
            continue

        cleaned_kml = remove_cdata_from_kml(kml_path)

        uuid_match = re.search(
            r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', filename)
        working_street_id = uuid_match.group(0) if uuid_match else city.replace(" ", "_")

        output_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer):
            count = extract_coordinates_from_kml(cleaned_kml, count, working_street_id)
        sql_output_all.append(output_buffer.getvalue())

        # Read coordinates for mapping
        try:
            tree = ET.parse(cleaned_kml)
            root = tree.getroot()
            ns = {'kml': 'http://www.opengis.net/kml/2.2'}

            for placemark in root.findall('.//kml:Placemark', ns):
                for coords_element in placemark.findall('.//kml:coordinates', ns):
                    coords_text = coords_element.text.strip()
                    polygon_coords = []
                    for coord in coords_text.split():
                        parts = coord.split(',')
                        if len(parts) >= 2:
                            lon, lat = float(parts[0]), float(parts[1])
                            all_coords.append({"lat": lat, "lon": lon, "file": filename})
                            polygon_coords.append([lon, lat])
                    if polygon_coords:
                        polygons.append({
                            "name": filename,
                            "polygon": [polygon_coords]
                        })
        except Exception as e:
            continue

    merged_kml_path = os.path.join(KML_DIR, "merged_output.kml")
    merge_kml_files(KML_DIR, merged_kml_path, count)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zipf:
        for f in os.listdir(KML_DIR):
            if f.endswith(".kml"):
                zipf.write(os.path.join(KML_DIR, f), arcname=f)
    zip_buffer.seek(0)

    # Table output
    table = dash_table.DataTable(
        data=all_coords,
        columns=[{"name": i, "id": i} for i in ["lat", "lon", "file"]],
        style_table={"overflowX": "auto"},
        page_size=10,
        style_cell={"textAlign": "left"},
    )

    # Map
    map_fig = None
    if polygons:
        import plotly.graph_objs as go
        map_fig = go.Figure()
        for poly in polygons:
            for ring in poly["polygon"]:
                lons, lats = zip(*ring)
                map_fig.add_trace(go.Scattermapbox(
                    lon=lons,
                    lat=lats,
                    mode='lines',
                    fill='toself',
                    name=poly["name"],
                    line=dict(width=2)
                ))
        first = polygons[0]["polygon"][0][0]
        map_fig.update_layout(
            mapbox_style="open-street-map",
            mapbox_zoom=14,
            mapbox_center={"lat": first[1], "lon": first[0]},
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
        )

    return (
        dbc.Alert("✅ Processing complete! Your files are ready.", color="success"),
        html.Pre("".join(sql_output_all), style={"whiteSpace": "pre-wrap", "fontSize": "13px"}),
        table,
        dcc.Graph(figure=map_fig) if map_fig else html.Div("No polygons found."),
        html.A("📥 Download All Processed KMLs (ZIP)", href="data:application/zip;base64," +
               base64.b64encode(zip_buffer.read()).decode(),
               download=f"{city}_kml_output.zip", className="btn btn-success mt-3")
    )

if __name__ == "__main__":
    app.run(debug=True)
