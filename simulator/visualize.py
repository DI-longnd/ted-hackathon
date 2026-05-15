"""
Visualize Mock Data — So sánh shape với real data
==================================================
Chạy: python visualize_mock.py
Output: visualize_mock_sample_1.png, _2.png, _3.png
"""

import pandas as pd
import matplotlib.pyplot as plt
import random

# ─────────────────────────────────────────────
# CONFIG — chỉnh nếu cần
# ─────────────────────────────────────────────
CSV_PATH    = "mock_robot_spray_data.csv"
RANDOM_SEED = 42
N_SAMPLES   = 3   # số file muốn visualize

COLS = [
    'air_motor_rotation_speed_actual_value',
    'air_motor_electro_pneumatic_output_value_bit',
    'high_pressure_level_1_voltage',
    'high_pressure_level_1_current',
    'paint_pressure_dcl',
    'paint_flow_rate_cc_per_min',
]

# ─────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────
print(f"Loading {CSV_PATH} ...")
df = pd.read_csv(CSV_PATH)
all_files = df['start_time'].unique()
print(f"Total files: {len(all_files)}")
print()

# Pick samples: file đầu, file giữa, file ngẫu nhiên
random.seed(RANDOM_SEED)
sample_files = [
    all_files[1],                          # file đầu tiên
    all_files[len(all_files) // 2 + 1],        # file giữa
    all_files[random.randint(100, 2900)],  # file random
]

# ─────────────────────────────────────────────
# PLOT
# ─────────────────────────────────────────────
for fi, st in enumerate(sample_files):
    sample = df[df['start_time'] == st].reset_index(drop=True)
    n = len(sample)

    fig, axes = plt.subplots(len(COLS), 1, figsize=(12, 18), sharex=True)
    fig.suptitle(
        f"Mock Sample {fi + 1}  |  start_time = {st}  |  n_records = {n}",
        fontsize=12, fontweight='bold', y=1.01
    )

    for i, col in enumerate(COLS):
        ax = axes[i]
        ax.plot(sample.index, sample[col], linewidth=0.9, color='steelblue')
        ax.set_title(col, fontsize=9, loc='left', pad=3)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=8)

        # Annotate phase boundaries
        idle_end     = 12
        rampup_end   = 34
        shutdown_start = n - 18
        winddown_start = n - 38

        for xpos, label, color in [
            (idle_end,      "RAMP",     "orange"),
            (rampup_end,    "ACTIVE",   "green"),
            (winddown_start,"WINDDOWN", "purple"),
            (shutdown_start,"SHUTDOWN", "red"),
        ]:
            ax.axvline(x=xpos, color=color, linestyle='--', linewidth=0.8, alpha=0.6)
            if i == 0:
                ax.text(xpos + 1, ax.get_ylim()[1] * 0.95, label,
                        color=color, fontsize=7, va='top')

    plt.tight_layout()
    out_path = f"visualize_mock_sample_{fi + 1}.png"
    plt.savefig(out_path, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: {out_path}  (n_records={n})")

print()
print("Done! So sánh 3 file trên với chart real data nhé.")