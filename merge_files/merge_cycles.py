"""
merge_cycles.py
───────────────────────────────────────────────────────
Gộp tất cả file cycle_*.csv trong thư mục mock_data_output
thành 1 file CSV duy nhất.

Tự động thêm 2 cột:
  - label       : "normal" hoặc "anomaly" (đọc từ tên file)
  - source_file : tên file gốc (để traceback nếu cần)

CÁCH DÙNG:
  python merge_cycles.py

OUTPUT:
  ./mock_data_output/merged_cycles.csv
"""

import pandas as pd
from pathlib import Path

# ── Cấu hình ─────────────────────────────────────────
# mock_data_output nằm cùng cấp với thư mục databricks_sdk
# nên phải đi lên 1 cấp (..) rồi mới vào mock_data_output
INPUT_DIR   = Path(__file__).parent.parent / "mock_data_output"
OUTPUT_FILE = INPUT_DIR / "merged_cycles.csv"
# ─────────────────────────────────────────────────────


def extract_label(filename: str) -> str:
    """
    Đọc label từ tên file.
    cycle_00001_normal.csv  → "normal"
    cycle_00010_anomaly.csv → "anomaly"
    """
    name = filename.lower()
    if "anomaly" in name:
        return "anomaly"
    elif "normal" in name:
        return "normal"
    return "unknown"


def merge_all(input_dir: Path, output_file: Path) -> pd.DataFrame:
    csv_files = sorted(input_dir.glob("cycle_*.csv"))

    if not csv_files:
        raise FileNotFoundError(
            f"Không tìm thấy file cycle_*.csv nào trong: {input_dir.resolve()}"
        )

    print(f"📂 Tìm thấy {len(csv_files)} files trong '{input_dir}'")
    print("─" * 55)

    frames = []
    errors = []

    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path)
            df.insert(0, "source_file", csv_path.name)   # cột đầu tiên
            df.insert(1, "label", extract_label(csv_path.name))  # cột thứ hai
            frames.append(df)
            print(f"  ✅ {csv_path.name:40s}  {len(df):>6,} rows")
        except Exception as e:
            errors.append(csv_path.name)
            print(f"  ❌ {csv_path.name}: {e}")

    if not frames:
        raise RuntimeError("Không đọc được file nào thành công.")

    merged = pd.concat(frames, ignore_index=True)

    # Sắp xếp theo timestamp nếu cột tồn tại
    if "timestamp" in merged.columns:
        merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True, errors="coerce")
        merged = merged.sort_values("timestamp").reset_index(drop=True)

    merged.to_csv(output_file, index=False)

    print("─" * 55)
    print(f"✅ Đã gộp xong!")
    print(f"   Files OK    : {len(frames)}")
    print(f"   Files lỗi   : {len(errors)}")
    print(f"   Tổng rows   : {len(merged):,}")
    print(f"   normal rows : {(merged['label'] == 'normal').sum():,}")
    print(f"   anomaly rows: {(merged['label'] == 'anomaly').sum():,}")
    print(f"   Columns     : {list(merged.columns)}")
    print(f"\n📄 Output: {output_file.resolve()}")

    return merged


if __name__ == "__main__":
    merge_all(INPUT_DIR, OUTPUT_FILE)