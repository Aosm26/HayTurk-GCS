import sqlite3
import sys

def main(mbtiles_path):
    conn = sqlite3.connect(mbtiles_path)
    cur = conn.cursor()
    report_lines = []
    report_lines.append("Zoom | X | Y (Slippy) | Y (MBTiles) | Boyut (byte)")
    report_lines.append("-" * 50)
    count = 0
    for row in cur.execute("SELECT zoom_level, tile_column, tile_row, length(tile_data) FROM tiles ORDER BY zoom_level, tile_column, tile_row"):
        z, x, y_mbtiles, size = row
        y_slippy = (2 ** z - 1) - y_mbtiles
        line = f"{z:4} | {x:5} | {y_slippy:8} | {y_mbtiles:9} | {size:10}"
        print(line)
        report_lines.append(line)
        count += 1
    report_lines.append("-" * 50)
    report_lines.append(f"Toplam tile sayısı: {count}")
    print("-" * 50)
    print(f"Toplam tile sayısı: {count}")
    # Örnek bir tile'ı kaydetmek için:
    cur.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles LIMIT 1")
    z, x, y_mbtiles, data = cur.fetchone()
    y_slippy = (2 ** z - 1) - y_mbtiles
    tile_msg = f"Örnek tile kaydedildi: tile_z{z}_x{x}_y{y_slippy}.png"
    with open(f"tile_z{z}_x{x}_y{y_slippy}.png", "wb") as f:
        f.write(data)
    print(tile_msg)
    report_lines.append(tile_msg)
    with open("tiles_report.txt", "w", encoding="utf-8") as f:
        for line in report_lines:
            f.write(line + "\n")
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanım: python mbtiles_tile_listele.py map.mbtiles")
        sys.exit(1)
    main(sys.argv[1]) 