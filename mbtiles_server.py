#!/usr/bin/env python3
"""
MBTiles Server Module
Serves map tiles from .mbtiles files using HTTP server
"""

import sqlite3
import io
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import sys
from urllib.parse import urlparse

class MBTilesHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip('/').split('/')
        if len(parts) == 4 and parts[0] == 'tiles':
            try:
                _, z, x, y_png = parts
                y = y_png.split('.')[0]
                z, x, y = int(z), int(x), int(y)
                conn = sqlite3.connect(sys.argv[1])
                cur = conn.cursor()
                cur.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?", (z, x, (2**z - 1 - y)))
                row = cur.fetchone()
                conn.close()
                if row:
                    self.send_response(200)
                    self.send_header('Content-type', 'image/png')
                    self.end_headers()
                    self.wfile.write(row[0])
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def get_tile(self, z, x, y):
        """Get tile data from MBTiles database"""
        try:
            if not os.path.exists(sys.argv[1]):
                print(f"MBTiles file not found: {sys.argv[1]}")
                return None
            
            conn = sqlite3.connect(sys.argv[1])
            cursor = conn.cursor()
            
            # Query tile data
            cursor.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                (z, x, y)
            )
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return result[0]
            else:
                return None
                
        except Exception as e:
            print(f"Error reading tile from MBTiles: {e}")
            return None
    
    def serve_map_page(self):
        """Serve HTML page with interactive map"""
        html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>HAYTÜRK Ground Control Station - Map</title>
    <meta charset="utf-8">
    <style>
        body { margin: 0; padding: 0; }
        #map { width: 100%; height: 100vh; }
        .aircraft-marker {
            background-color: red;
            border: 2px solid white;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            position: absolute;
            transform: translate(-50%, -50%);
            z-index: 1000;
        }
    </style>
    <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
</head>
<body>
    <div id="map"></div>
    <div id="aircraft" class="aircraft-marker" style="display: none;"></div>
    
    <script>
        // Initialize map
        var map = L.map('map').setView([39.9334, 32.8597], 13); // Ankara center
        
        // Add MBTiles layer
        L.tileLayer('http://localhost:8080/{z}/{x}/{y}.png', {
            attribution: 'HAYTÜRK Offline Map',
            maxZoom: 18,
            minZoom: 10
        }).addTo(map);
        
        // Aircraft marker
        var aircraftMarker = null;
        
        // Function to update aircraft position
        window.updateAircraftPosition = function(lat, lon) {
            if (aircraftMarker) {
                aircraftMarker.setLatLng([lat, lon]);
            } else {
                aircraftMarker = L.marker([lat, lon], {
                    icon: L.divIcon({
                        className: 'aircraft-icon',
                        html: '<div style="background-color: red; border: 2px solid white; border-radius: 50%; width: 20px; height: 20px;"></div>',
                        iconSize: [20, 20],
                        iconAnchor: [10, 10]
                    })
                }).addTo(map);
            }
            
            // Center map on aircraft if it's the first position
            if (!window.aircraftInitialized) {
                map.setView([lat, lon], 15);
                window.aircraftInitialized = true;
            }
        };
        
        // Add some sample waypoints for Ankara
        var waypoints = [
            {lat: 39.9334, lon: 32.8597, name: "Kızılay"},
            {lat: 39.9454, lon: 32.8597, name: "Ulus"},
            {lat: 39.9204, lon: 32.8597, name: "Çankaya"},
            {lat: 39.9254, lon: 32.8367, name: "Anıtkabir"}
        ];
        
        waypoints.forEach(function(wp) {
            L.marker([wp.lat, wp.lon])
                .bindPopup(wp.name)
                .addTo(map);
        });
        
        // Add flight path
        var flightPath = L.polyline([
            [39.9334, 32.8597],
            [39.9454, 32.8597],
            [39.9204, 32.8597],
            [39.9254, 32.8367]
        ], {color: 'blue', weight: 3}).addTo(map);
        
        // Add HSS (Hazardous Areas)
        var hss1 = L.circle([39.9334, 32.8597], {
            color: 'red',
            fillColor: '#f03',
            fillOpacity: 0.3,
            radius: 500
        }).addTo(map).bindPopup("HSS Zone 1");
        
        var hss2 = L.circle([39.9454, 32.8597], {
            color: 'red',
            fillColor: '#f03',
            fillOpacity: 0.3,
            radius: 300
        }).addTo(map).bindPopup("HSS Zone 2");
        
        console.log("HAYTÜRK Map initialized");
    </script>
</body>
</html>
        """
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(html_content)))
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to reduce logging noise"""
        # Only log errors and important messages
        if '404' in format or '500' in format:
            super().log_message(format, *args)

def create_mbtiles_server(mbtiles_path, port=8080):
    """Create and return an MBTiles HTTP server"""
    
    class MBTilesServer(HTTPServer):
        def __init__(self, server_address, RequestHandlerClass, mbtiles_path):
            self.mbtiles_path = mbtiles_path
            super().__init__(server_address, RequestHandlerClass)
        
        def finish_request(self, request, client_address):
            """Override to pass mbtiles_path to handler"""
            self.RequestHandlerClass(self.mbtiles_path, request, client_address, self)
    
    # Create server
    server = MBTilesServer(('localhost', port), MBTilesHandler, mbtiles_path)
    
    print(f"MBTiles server created for {mbtiles_path} on port {port}")
    return server

def start_mbtiles_server(mbtiles_path, port=8080):
    """Start MBTiles server in a separate thread"""
    if not os.path.exists(mbtiles_path):
        print(f"MBTiles file not found: {mbtiles_path}")
        return None
    
    server = create_mbtiles_server(mbtiles_path, port)
    
    def run_server():
        try:
            print(f"Starting MBTiles server on port {port}")
            server.serve_forever()
        except KeyboardInterrupt:
            print("MBTiles server stopped")
        except Exception as e:
            print(f"MBTiles server error: {e}")
        finally:
            server.shutdown()
    
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Wait a moment for server to start
    time.sleep(1)
    
    return server

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Kullanım: python mbtiles_server.py map.mbtiles 8080")
        sys.exit(1)
    mbtiles = sys.argv[1]
    port = int(sys.argv[2])
    server = HTTPServer(('127.0.0.1', port), MBTilesHandler)
    print(f"Serving {mbtiles} at http://127.0.0.1:{port}/tiles/{{z}}/{{x}}/{{y}}.png")
    server.serve_forever() 