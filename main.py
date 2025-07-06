import sys
import json
import csv
import time
import threading
import struct
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QLabel, QLineEdit, 
                             QPushButton, QComboBox, QTextEdit, QGroupBox,
                             QFrame, QSplitter, QTabWidget, QProgressBar,
                             QMessageBox)
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt, QUrl, QObject, pyqtSlot
from PyQt5.QtGui import QFont, QPixmap, QPalette, QColor
from PyQt5.QtWebEngineWidgets import QWebEngineView
import folium
import pandas as pd
import requests
import websockets
import asyncio
import os
import serial
import serial.tools.list_ports
from PyQt5.QtWebChannel import QWebChannel
import math
import subprocess
# MBTiles server will be imported when needed

class TelemetryThread(QThread):
    """Thread for handling telemetry data updates from serial port"""
    telemetry_updated = pyqtSignal(dict)
    connection_status = pyqtSignal(bool, str)  # connected, message
    
    def __init__(self, port='COM2', baudrate=57600, interval=1.0):
        super().__init__()
        self.running = False
        self.connected = False
        self.port = port
        self.baudrate = baudrate
        self.interval = interval
        self.ser = None
        self.auto_reconnect = True
    
    def run(self):
        self.running = True
        sim_counter = 0
        
        while self.running:
            # Seri port bağlantısını kontrol et
            if not self.connected and self.auto_reconnect:
                try:
                    if self.ser and self.ser.is_open:
                        self.ser.close()
                    self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
                    self.connected = True
                    self.connection_status.emit(True, f"Connected to {self.port}")
                    print(f"Serial port {self.port} opened successfully.")
                except Exception as e:
                    self.connected = False
                    self.connection_status.emit(False, f"Failed to connect to {self.port}: {str(e)}")
                    print(f"Warning: Could not open serial port {self.port}: {e}")
                    print("Running in simulation mode with mock telemetry data.")
                    self.ser = None
            
            # Telemetry verisi gönder
            if self.connected:
                if self.ser and self.ser.is_open:
                    # Gerçek serial port verisi (binary format)
                    try:
                        # 24 byte oku (3 x double = 24 byte)
                        data = self.ser.read(24)
                        if len(data) == 24:
                            # Little-endian 3 double değer olarak parse et
                            vals = struct.unpack('<3d', data)
                            lat, lon, alt = vals
                            
                            telemetry_data = {
                                'gps': {'lat': lat, 'lon': lon, 'alt': alt},
                                'speed': 25.0 + (sim_counter % 10),
                                'battery': max(85, 100 - (sim_counter % 15)),
                                'mode': 'AUTONOMOUS',
                                'status': 'CONNECTED',
                                'timestamp': datetime.now().strftime('%H:%M:%S')
                            }
                            self.telemetry_updated.emit(telemetry_data)
                            print(f"Gelen binary veri: lat={lat}, lon={lon}, alt={alt}")
                        elif len(data) > 0:
                            print(f"Beklenmeyen veri uzunluğu: {len(data)} byte")
                    except Exception as read_err:
                        print(f"Serial read error: {read_err}")
                        # Bağlantı hatası durumunda simülasyon moduna geç
                        self.connected = False
                        self.connection_status.emit(False, f"Serial read error: {read_err}")
                else:
                    # Simülasyon verisi
                    import random
                    
                    # Ankara merkez etrafında dairesel hareket
                    center_lat = 39.9334
                    center_lon = 32.8597
                    radius = 0.001  # Yaklaşık 100m
                    
                    angle = (sim_counter * 0.1) % (2 * math.pi)
                    lat = center_lat + radius * math.cos(angle)
                    lon = center_lon + radius * math.sin(angle)
                    alt = 100 + 20 * math.sin(angle * 2)
                    
                    telemetry_data = {
                        'gps': {'lat': lat, 'lon': lon, 'alt': alt},
                        'speed': 25.0 + random.uniform(-2, 2),
                        'battery': max(85, 100 - (sim_counter % 15)),
                        'mode': 'AUTONOMOUS',
                        'status': 'SIMULATION',
                        'timestamp': datetime.now().strftime('%H:%M:%S')
                    }
                    self.telemetry_updated.emit(telemetry_data)
            
            sim_counter += 1
            self.msleep(int(self.interval * 1000))
        
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"Serial port {self.port} closed.")
    
    def stop(self):
        self.running = False
        self.auto_reconnect = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.wait()
    
    def set_port(self, port):
        """Change the serial port"""
        self.port = port
        self.connected = False
        if self.ser and self.ser.is_open:
            self.ser.close()
    
    def set_baudrate(self, baudrate):
        """Change the baudrate"""
        self.baudrate = baudrate
        self.connected = False
        if self.ser and self.ser.is_open:
            self.ser.close()

class GroundControlStation(QMainWindow):
    def __init__(self):
        super().__init__()
        self.telemetry_thread = TelemetryThread(port='COM2', baudrate=57600, interval=1.0)
        self.telemetry_thread.telemetry_updated.connect(self.update_telemetry)
        self.telemetry_thread.connection_status.connect(self.on_connection_status)
        self.telemetry_thread.start()
        
        self.connected = False
        self.current_mode = "AUTONOMOUS"
        self.camera_locked = False
        self.camera_fps = 30
        
        # MBTiles server setup
        self.mbtiles_path = 'map/map_ilk_ankara.mbtiles'  # Dizindeki map.mbtiles dosyası
        self.mbtiles_port = 8080
        self.tile_server_proc = None  # mbtiles_server.py başlatmak için
        
        self.init_ui()
        self.setup_timers()
        self.start_mbtiles_server_subprocess()  # mbtiles_server.py başlat
        
    def init_ui(self):
        self.setWindowTitle("Ground Control Station")
        self.setGeometry(100, 100, 1400, 900)
        
        # Set dark theme
        self.set_dark_theme()
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout(central_widget)
        
        # Left panel
        left_panel = self.create_left_panel()
        
        # Center panel (map)
        center_panel = self.create_center_panel()
        
        # Right panel (camera)
        right_panel = self.create_right_panel()
        
        # Add panels to main layout
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(center_panel, 2)
        main_layout.addWidget(right_panel, 1)
        
    def create_left_panel(self):
        """Create the left control panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Serial Port Configuration section
        serial_group = QGroupBox("Serial Port Configuration")
        serial_layout = QVBoxLayout(serial_group)
        
        # Port selection
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        port_layout.addWidget(self.port_combo)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        port_layout.addWidget(self.refresh_btn)
        serial_layout.addLayout(port_layout)
        
        # Baudrate selection
        baud_layout = QHBoxLayout()
        baud_layout.addWidget(QLabel("Baudrate:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(['9600', '19200', '38400', '57600', '115200'])
        self.baud_combo.setCurrentText('57600')
        baud_layout.addWidget(self.baud_combo)
        serial_layout.addLayout(baud_layout)
        
        # Connection control
        conn_layout = QHBoxLayout()
        self.connect_serial_btn = QPushButton("Connect")
        self.connect_serial_btn.clicked.connect(self.connect_serial)
        conn_layout.addWidget(self.connect_serial_btn)
        
        self.disconnect_serial_btn = QPushButton("Disconnect")
        self.disconnect_serial_btn.clicked.connect(self.disconnect_serial)
        self.disconnect_serial_btn.setEnabled(False)
        conn_layout.addWidget(self.disconnect_serial_btn)
        serial_layout.addLayout(conn_layout)
        
        layout.addWidget(serial_group)
        
        # Status section
        status_group = QGroupBox("System Status")
        status_layout = QVBoxLayout(status_group)
        
        # Mode selection
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["AUTONOMOUS", "RC"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        status_layout.addLayout(mode_layout)
        
        # Status labels
        self.status_label = QLabel("Status: DISCONNECTED")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        status_layout.addWidget(self.status_label)
        
        self.mode_status_label = QLabel("Mode: AUTONOMOUS")
        status_layout.addWidget(self.mode_status_label)
        
        layout.addWidget(status_group)
        
        # GPS Data section
        gps_group = QGroupBox("GPS Data")
        gps_layout = QGridLayout(gps_group)
        
        gps_layout.addWidget(QLabel("Latitude:"), 0, 0)
        self.lat_label = QLabel("0.000000")
        gps_layout.addWidget(self.lat_label, 0, 1)
        
        gps_layout.addWidget(QLabel("Longitude:"), 1, 0)
        self.lon_label = QLabel("0.000000")
        gps_layout.addWidget(self.lon_label, 1, 1)
        
        gps_layout.addWidget(QLabel("Altitude:"), 2, 0)
        self.alt_label = QLabel("0 m")
        gps_layout.addWidget(self.alt_label, 2, 1)
        
        layout.addWidget(gps_group)
        
        # Speed and Battery section
        flight_group = QGroupBox("Flight Data")
        flight_layout = QGridLayout(flight_group)
        
        flight_layout.addWidget(QLabel("Speed:"), 0, 0)
        self.speed_label = QLabel("0 m/s")
        flight_layout.addWidget(self.speed_label, 0, 1)
        
        flight_layout.addWidget(QLabel("Battery:"), 1, 0)
        self.battery_progress = QProgressBar()
        self.battery_progress.setRange(0, 100)
        flight_layout.addWidget(self.battery_progress, 1, 1)
        
        layout.addWidget(flight_group)
        
        # Server Login section
        login_group = QGroupBox("Server Login")
        login_layout = QVBoxLayout(login_group)
        
        login_layout.addWidget(QLabel("Username:"))
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Enter username")
        login_layout.addWidget(self.username_edit)
        
        login_layout.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Enter password")
        self.password_edit.setEchoMode(QLineEdit.Password)
        login_layout.addWidget(self.password_edit)
        
        # Connection buttons
        button_layout = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_to_server)
        button_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnect_from_server)
        self.disconnect_btn.setEnabled(False)
        button_layout.addWidget(self.disconnect_btn)
        
        login_layout.addLayout(button_layout)
        layout.addWidget(login_group)
        
        # Telemetry Log section
        log_group = QGroupBox("Telemetry Log")
        log_layout = QVBoxLayout(log_group)
        
        self.telemetry_log = QTextEdit()
        self.telemetry_log.setMaximumHeight(200)
        self.telemetry_log.setReadOnly(True)
        log_layout.addWidget(self.telemetry_log)
        
        layout.addWidget(log_group)
        
        return panel
        
    def create_center_panel(self):
        """Create the center panel with map"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Map title
        map_title = QLabel("Flight Map")
        map_title.setAlignment(Qt.AlignCenter)
        map_title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(map_title)
        
        # QWebEngineView ile Leaflet harita
        self.map_view = QWebEngineView()
        self.web_channel = QWebChannel()
        self.map_view.page().setWebChannel(self.web_channel)
        self.map_view.setHtml(self.leaflet_html(), QUrl(""))
        layout.addWidget(self.map_view)
        
        return panel
        
    def create_right_panel(self):
        """Create the right panel with camera view"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Camera title
        camera_title = QLabel("Camera Feed")
        camera_title.setAlignment(Qt.AlignCenter)
        camera_title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(camera_title)
        
        # Lock status
        lock_layout = QHBoxLayout()
        lock_layout.addWidget(QLabel("Lock:"))
        self.lock_status_label = QLabel("Disconnected")
        self.lock_status_label.setStyleSheet("color: red; font-weight: bold;")
        lock_layout.addWidget(self.lock_status_label)
        layout.addLayout(lock_layout)
        
        # FPS display
        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("FPS:"))
        self.fps_label = QLabel("0")
        fps_layout.addWidget(self.fps_label)
        layout.addLayout(fps_layout)
        
        # Camera view (placeholder)
        self.camera_view = QLabel()
        self.camera_view.setMinimumSize(400, 300)
        self.camera_view.setStyleSheet("""
            QLabel {
                background-color: #2b2b2b;
                border: 2px solid #555;
                border-radius: 5px;
            }
        """)
        self.camera_view.setAlignment(Qt.AlignCenter)
        self.camera_view.setText("Camera Feed\n(Not Available)")
        layout.addWidget(self.camera_view)
        
        return panel
        
    def set_dark_theme(self):
        """Apply dark theme to the application"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666666;
            }
            QLineEdit {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
            }
            QComboBox {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                color: #ffffff;
            }
            QTextEdit {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                color: #ffffff;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
            }
        """)
        
    def setup_timers(self):
        """Setup timers for periodic updates"""
        # Timer for camera FPS simulation
        self.fps_timer = QTimer()
        self.fps_timer.timeout.connect(self.update_camera_fps)
        self.fps_timer.start(1000)  # Update every second
        
    def leaflet_html(self):
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <title>Offline Map</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
        </head>
        <body style="margin:0;">
        <div id="map" style="width: 100vw; height: 97vh;"></div>
        <script>
            var map = L.map('map').setView([39.9334, 32.8597], 14);
            L.tileLayer('http://127.0.0.1:{self.mbtiles_port}/tiles/{{z}}/{{x}}/{{y}}.png', {{
                maxZoom: 18,
                minZoom: 0,
                attribution: 'HAYTÜRK Offline Map'
            }}).addTo(map);
            var marker = L.marker([39.9334, 32.8597]).addTo(map).bindPopup('Ankara');
        </script>
        </body>
        </html>
        '''

    def start_mbtiles_server_subprocess(self):
        python_exe = sys.executable
        tile_server_script = os.path.join(os.path.dirname(__file__), 'mbtiles_server.py')
        if os.path.exists(tile_server_script) and os.path.exists(self.mbtiles_path):
            self.tile_server_proc = subprocess.Popen([python_exe, tile_server_script, self.mbtiles_path, str(self.mbtiles_port)],
                                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"mbtiles_server.py başlatıldı: {self.mbtiles_port}")
        else:
            print(f"mbtiles_server.py veya map.mbtiles bulunamadı!")
            
    def update_camera_fps(self):
        """Update camera FPS display"""
        if self.connected:
            self.fps_label.setText(str(self.camera_fps))
        else:
            self.fps_label.setText("0")
            
    def update_telemetry(self, data):
        """Update telemetry displays with new data"""
        # Update GPS data
        self.lat_label.setText(f"{data['gps']['lat']:.6f}")
        self.lon_label.setText(f"{data['gps']['lon']:.6f}")
        self.alt_label.setText(f"{data['gps']['alt']:.1f} m")
        
        # Update speed and battery
        self.speed_label.setText(f"{data['speed']:.1f} m/s")
        self.battery_progress.setValue(int(data['battery']))
        
        # Update status
        if data['status'] == 'CONNECTED':
            self.status_label.setText("Status: CONNECTED")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText("Status: DISCONNECTED")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            
        # Update mode
        self.mode_status_label.setText(f"Mode: {data['mode']}")
        
        # Update telemetry log
        log_entry = f"[{data['timestamp']}] GPS: ({data['gps']['lat']:.6f}, {data['gps']['lon']:.6f}) | Speed: {data['speed']:.1f} m/s | Battery: {data['battery']:.1f}% | Mode: {data['mode']}\n"
        self.telemetry_log.append(log_entry)
        
        # Save to CSV
        self.save_telemetry_to_csv(data)
        
        # Update map with new position
        self.update_map_position(data['gps'])
        
    def save_telemetry_to_csv(self, data):
        """Save telemetry data to CSV file"""
        filename = f"telemetry_{datetime.now().strftime('%Y%m%d')}.csv"
        
        # Create CSV file with headers if it doesn't exist
        try:
            with open(filename, 'a', newline='') as file:
                writer = csv.writer(file)
                
                # Write data
                writer.writerow([
                    data['timestamp'],
                    data['gps']['lat'],
                    data['gps']['lon'],
                    data['gps']['alt'],
                    data['speed'],
                    data['battery'],
                    data['mode'],
                    data['status']
                ])
        except Exception as e:
            print(f"Error saving telemetry data: {e}")
            
    def update_map_position(self, gps_data):
        """Update map with new aircraft position"""
        # Send JavaScript command to update aircraft position
        js_code = f"""
        if (window.updateAircraftPosition) {{
            window.updateAircraftPosition({gps_data['lat']}, {gps_data['lon']});
        }}
        """
        self.map_view.page().runJavaScript(js_code)
        
    def on_mode_changed(self, mode):
        """Handle mode selection change"""
        self.current_mode = mode
        self.mode_status_label.setText(f"Mode: {mode}")
        
    def connect_to_server(self):
        """Connect to the server"""
        username = self.username_edit.text()
        password = self.password_edit.text()
        
        if username and password:
            # Simulate connection (replace with actual connection logic)
            self.connected = True
            self.telemetry_thread.connected = True
            
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.username_edit.setEnabled(False)
            self.password_edit.setEnabled(False)
            
            # Update camera lock status
            self.camera_locked = True
            self.lock_status_label.setText("Successful")
            self.lock_status_label.setStyleSheet("color: green; font-weight: bold;")
            
            # Add connection log
            self.telemetry_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Connected to server as {username}\n")
        else:
            self.telemetry_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: Username and password required\n")
            
    def disconnect_from_server(self):
        """Disconnect from the server"""
        self.connected = False
        self.telemetry_thread.connected = False
        
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.username_edit.setEnabled(True)
        self.password_edit.setEnabled(True)
        
        # Update camera lock status
        self.camera_locked = False
        self.lock_status_label.setText("Disconnected")
        self.lock_status_label.setStyleSheet("color: red; font-weight: bold;")
        
        # Add disconnection log
        self.telemetry_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Disconnected from server\n")
        
    def refresh_ports(self):
        """Refresh available serial ports"""
        self.port_combo.clear()
        ports = [port.device for port in serial.tools.list_ports.comports()]
        if ports:
            self.port_combo.addItems(ports)
            # Try to select COM2 if available (your telemetry port)
            index = self.port_combo.findText('COM2')
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            # Fallback to COM10 if COM2 not available
            elif self.port_combo.findText('COM10') >= 0:
                self.port_combo.setCurrentIndex(self.port_combo.findText('COM10'))
        else:
            self.port_combo.addItem("No ports found")
    
    def connect_serial(self):
        """Connect to selected serial port"""
        port = self.port_combo.currentText()
        baudrate = int(self.baud_combo.currentText())
        
        if port == "No ports found":
            QMessageBox.warning(self, "Warning", "No serial ports available!")
            return
        
        try:
            self.telemetry_thread.set_port(port)
            self.telemetry_thread.set_baudrate(baudrate)
            
            self.connect_serial_btn.setEnabled(False)
            self.disconnect_serial_btn.setEnabled(True)
            self.port_combo.setEnabled(False)
            self.baud_combo.setEnabled(False)
            
            self.telemetry_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Connecting to {port} at {baudrate} baud...\n")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to connect to {port}: {str(e)}")
            self.telemetry_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Connection failed: {str(e)}\n")
    
    def disconnect_serial(self):
        """Disconnect from serial port"""
        self.telemetry_thread.auto_reconnect = False
        self.telemetry_thread.connected = False
        
        self.connect_serial_btn.setEnabled(True)
        self.disconnect_serial_btn.setEnabled(False)
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        
        self.telemetry_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Disconnected from serial port\n")
    
    def on_connection_status(self, connected, message):
        """Handle connection status updates"""
        if connected:
            self.status_label.setText(f"Status: {message}")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText(f"Status: {message}")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
        
        self.telemetry_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
    
    def closeEvent(self, event):
        """Handle application close event"""
        self.telemetry_thread.stop()
        
        # Shutdown MBTiles server
        if self.tile_server_proc:
            self.tile_server_proc.terminate()
            self.tile_server_proc.wait()
        
        event.accept()

def main():
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("Ground Control Station")
    app.setApplicationVersion("1.0")
    
    # Create and show main window
    window = GroundControlStation()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main() 