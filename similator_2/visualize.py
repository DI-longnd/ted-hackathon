"""
Visualize Mock Data — Phase-aware (FIXED VERSION)
==================================================
- Sửa tên file CSV cho khớp với generator v3
- Bypass lỗi missing 'phase': Nếu không có cột phase, vẫn vẽ biểu đồ dữ liệu bình thường.
"""

import pandas as pd
import matplotlib.pyplot as plt
import random

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
CSV_PATH = "mock_welding_robot_data.csv" # Đã sửa tên file
RANDOM_SEED = 42

COLS = [
    "wire_feed_speed_mm_min",
    # "welding_voltage_v",
    "wire_temperature_c",
    "welding_current_a",
]

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
print(f"Loading {CSV_PATH} ...")
df = pd.read_csv(CSV_PATH)

# Chuyển từ việc raise Error sang Cảnh báo (Warning) và bypass
has_phase = "phase" in df.columns
if not has_phase:
    print("⚠️ Không tìm thấy cột 'phase'. Sẽ vẽ biểu đồ dữ liệu sensor mà không có các đường ranh giới pha.")

all_files = df["start_time"].unique()
print(f"Total files: {len(all_files)}\n")

random.seed(RANDOM_SEED)

# ─────────────────────────────────────────────
# SAFE SAMPLE SELECTION
# ─────────────────────────────────────────────
sample_files = [
    all_files[0],
    all_files[len(all_files) // 2],
    all_files[random.randint(0, len(all_files) - 1)]
]

# ─────────────────────────────────────────────
# PLOT FUNCTION
# ─────────────────────────────────────────────
for fi, st in enumerate(sample_files):

    sample = df[df["start_time"] == st].reset_index(drop=True)
    n = len(sample)

    fig, axes = plt.subplots(len(COLS), 1, figsize=(12, 16), sharex=True)

    fig.suptitle(
        f"Mock Sample {fi + 1} | start_time = {st} | n_records = {n}",
        fontsize=12, fontweight="bold"
    )

    # Tính toán ranh giới phase nếu có dữ liệu
    if has_phase:
        phase_changes = sample["phase"].ne(sample["phase"].shift())
        boundary_indices = sample.index[phase_changes].tolist()
        phase_labels = sample.loc[boundary_indices, "phase"].tolist()

    # ─────────────────────────────────────────
    # PLOT EACH SENSOR
    # ─────────────────────────────────────────
    for i, col in enumerate(COLS):
        ax = axes[i]

        ax.plot(sample.index, sample[col],
                linewidth=0.9, color="steelblue")

        ax.set_title(col, fontsize=9, loc="left")
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=8)

        # ─────────────────────────────────────────
        # DRAW PHASE LINES (CHỈ VẼ KHI CÓ CỘT PHASE)
        # ─────────────────────────────────────────
        if has_phase:
            colors = {
                "idle": "gray",
                "rampup": "orange",
                "active": "green",
                "winddown": "purple",
                "shutdown": "red"
            }

            for idx, phase in zip(boundary_indices, phase_labels):
                ax.axvline(
                    x=idx,
                    color=colors.get(phase, "black"),
                    linestyle="--",
                    linewidth=0.8,
                    alpha=0.6
                )

                # annotate only top plot
                if i == 0:
                    ax.text(
                        idx + 0.5,
                        ax.get_ylim()[1] * 0.95,
                        phase.upper(),
                        color=colors.get(phase, "black"),
                        fontsize=7,
                        va="top"
                    )

    plt.tight_layout()

    out_path = f"visualize_mock_sample_{fi + 1}.png"
    plt.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close()

    print(f"✅ Saved: {out_path} (n_records={n})")

print("\n🎉 Done! Visualization completed.")