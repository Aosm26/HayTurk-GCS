import serial
import struct
import threading
import time

com_port = 'COM10'
baudrate = 57600

ser = serial.Serial(com_port, baudrate, timeout=1)
print(f"{com_port} portu dinleniyor...")

def oku():
    while True:
        try:
            data = ser.read(24)  # 3 x double = 24 byte bekliyoruz
            if len(data) == 24:
                vals = struct.unpack('<3d', data)  # Little-endian 3 double
                print(f"Gelen dizi: lat={vals[0]}, lon={vals[1]}, alt={vals[2]}")
            elif len(data) > 0:
                print(f"Beklenmeyen uzunluk: {len(data)} byte")
        except Exception as e:
            print(f"Okuma hatası: {e}")
            break

def yaz():
    lat = 39.9208
    lon = 32.8541
    alt = 890.0
    while True:
        try:
            data = struct.pack('<3d', lat, lon, alt)
            ser.write(data)
            print(f"Gönderilen: lat={lat}, lon={lon}, alt={alt}")
            time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Gönderme hatası: {e}")

okuma_thread = threading.Thread(target=oku, daemon=True)
okuma_thread.start()

try:
    yaz()
except KeyboardInterrupt:
    print("\nÇıkış yapılıyor...")

ser.close()
