"""
Mock IoT Generator v3 — Welding Robot + Phase-Aware Anomaly Injection
======================================================================
Tạo 154 chu trình (1 ngày) cho inference/demo.
Anomaly: window-based injection — cứ 7 files có 1 lỗi (~1h/lỗi)
Pattern rotation: Dropout → Surge → Deviation → Instability → Transition → lặp lại

Sensors:
  - wire_feed_speed_m_min : dao động quanh mean, không về 0
  - wire_temperature_c    : ramp up → sine wave → decay
  - welding_current_a     : 0 → ramp → plateau → decay → 0
"""

import os
import random
import math
import csv
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# 1. CONFIGURATION
# ─────────────────────────────────────────────
ROBOT_CODE      = 6
PROGRAM_NUMBER  = 116
TOTAL_FILES     = 154          # 1 ngày ~24h
ANOMALY_WINDOW  = 7            # cứ 7 files có 1 lỗi (~1h/lỗi)
OUTPUT_DIR      = "./mock_data_output"
START_DATETIME  = datetime(2025, 7, 1, 0, 0, 0)
RECORD_INTERVAL = 0.25         # 4 Hz

# Sensor hợp lệ cho từng pattern
VALID_COMBINATIONS = {
    "Dropout"     : ["wire_feed_speed_m_min", "welding_current_a"],
    "Surge"       : ["wire_feed_speed_m_min", "wire_temperature_c", "welding_current_a"],
    "Deviation"   : ["wire_feed_speed_m_min", "wire_temperature_c", "welding_current_a"],
    "Instability" : ["wire_feed_speed_m_min", "wire_temperature_c", "welding_current_a"],
    "Transition"  : ["wire_temperature_c", "welding_current_a"],
}

# Sensors có ramp rõ ràng — dùng cho Transition
RAMP_SENSORS = {"wire_temperature_c", "welding_current_a"}

# Pattern rotation cố định để demo đủ loại lỗi
PATTERN_ROTATION = ["Dropout", "Surge", "Deviation", "Instability", "Transition"]


# ─────────────────────────────────────────────
# 2. HELPERS
# ─────────────────────────────────────────────

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

def gauss(mean, std, lo=None, hi=None):
    v = random.gauss(mean, std)
    if lo is not None or hi is not None:
        v = clamp(v, lo if lo is not None else -1e18, hi if hi is not None else 1e18)
    return v

def sample_n_records():
    r = random.random()
    if r < 0.75:   return int(gauss(278, 22, 200, 320))
    elif r < 0.93: return int(gauss(360, 30, 320, 430))
    else:          return int(gauss(500, 28, 430, 554))

def sample_gap_seconds():
    r = random.random()
    if r < 0.70:   return random.randint(79, 300)
    elif r < 0.90: return random.randint(300, 900)
    else:          return random.randint(900, 3660)


# ─────────────────────────────────────────────
# 3. PER-FILE PROFILE
# ─────────────────────────────────────────────

def sample_file_profile():
    return {
        "current_mean"        : gauss(130, 25, 80, 180),
        "wire_feed_mean"      : gauss(4.0, 0.5, 3.0, 5.0),
        "wire_feed_std"       : gauss(0.05, 0.01, 0.02, 0.08),
        "wire_temp_base"      : gauss(280, 20, 240, 320),
        "idle_records"        : random.randint(8, 16),
        "rampup_records"      : random.randint(18, 28),
        "shutdown_records"    : random.randint(10, 18),
        "winddown_records"    : random.randint(30, 50),
        "winddown_stable_hold": random.randint(3, 6),
    }


# ─────────────────────────────────────────────
# 4. SENSOR GENERATORS
# ─────────────────────────────────────────────

def gen_wire_feed_speed(phase, record_idx, profile, rampup_records, winddown_records):
    mean = profile["wire_feed_mean"]
    std  = profile["wire_feed_std"]

    slow_wave    = (mean * 0.014) * math.sin(2 * math.pi * record_idx / 22)
    mid_wave     = (mean * 0.007) * math.sin(2 * math.pi * record_idx / 9 + 1.2)
    smooth_noise = gauss(0, std * 0.4)

    if phase == "idle":
        base = mean * 0.9
        return round(clamp(base + 0.4 * slow_wave + smooth_noise, mean * 0.85, mean * 0.95), 3)
    elif phase == "rampup":
        t    = record_idx / max(rampup_records, 1)
        base = mean * 0.9 + mean * 0.1 * t
        damp = t
        return round(clamp(base + damp * (slow_wave + mid_wave) + smooth_noise, mean * 0.85, mean + 0.1), 3)
    elif phase == "active":
        return round(clamp(mean + slow_wave + mid_wave + smooth_noise, mean - 0.12, mean + 0.12), 3)
    elif phase == "winddown":
        t    = record_idx / max(winddown_records, 1)
        base = mean - mean * 0.1 * t
        damp = 1 - 0.5 * t
        return round(clamp(base + damp * (slow_wave + mid_wave) + smooth_noise, mean * 0.85, mean + 0.1), 3)
    else:  # shutdown
        base = mean * 0.9
        return round(clamp(base + 0.3 * slow_wave + smooth_noise, mean * 0.85, mean * 0.95), 3)


def gen_wire_temperature(phase, record_idx, profile, rampup_records, winddown_records, shutdown_records):
    temp_base = profile["wire_temp_base"]

    if phase == "idle":
        return round(gauss(25, 2, 20, 35), 1)
    elif phase == "rampup":
        t    = record_idx / max(rampup_records, 1)
        base = 25 + (temp_base - 25) * t
        return round(clamp(base + gauss(0, 5), 20, temp_base + 10), 1)
    elif phase == "active":
        sine = 25 * math.sin(2 * math.pi * 0.05 * record_idx)
        return round(clamp(temp_base + sine + gauss(0, 3), temp_base - 35, temp_base + 35), 1)
    elif phase == "winddown":
        t    = record_idx / max(winddown_records, 1)
        base = temp_base - (temp_base - 150) * t
        return round(clamp(base + gauss(0, 5), 140, temp_base + 10), 1)
    else:  # shutdown
        t    = record_idx / max(shutdown_records, 1)
        base = 150 - (150 - 60) * t
        return round(clamp(base + gauss(0, 3), 55, 160), 1)


def gen_welding_current(phase, record_idx, profile, rampup_records, winddown_records):
    c_mean      = profile["current_mean"]
    stable_hold = profile["winddown_stable_hold"]

    if phase == "idle":
        return 0.0
    elif phase == "rampup":
        t          = record_idx / rampup_records
        ramp_curve = min(1.0, t * 2)
        base       = c_mean * ramp_curve
        return round(clamp(base + gauss(0, 5), 0, c_mean + 20), 1)
    elif phase == "active":
        return round(gauss(c_mean, 8, c_mean - 25, c_mean + 20), 1)
    elif phase == "winddown":
        if record_idx < stable_hold:
            return round(gauss(c_mean, 8, c_mean - 15, c_mean + 10), 1)
        decay_progress = (record_idx - stable_hold) / max(winddown_records - stable_hold, 1)
        base = c_mean - (c_mean - 30) * decay_progress
        return round(clamp(base + gauss(0, 4), 25, c_mean + 5), 1)
    else:
        return 0.0


# ─────────────────────────────────────────────
# 5. GENERATE ONE FILE
# ─────────────────────────────────────────────

def generate_file_records(file_start_dt, n_records):
    records        = []
    profile        = sample_file_profile()
    start_time_str = file_start_dt.strftime("%Y-%m-%d %H:%M:%S")

    idle_records     = profile["idle_records"]
    rampup_records   = profile["rampup_records"]
    shutdown_records = profile["shutdown_records"]
    winddown_records = profile["winddown_records"]

    min_active  = 20
    total_fixed = idle_records + rampup_records + winddown_records + shutdown_records
    if total_fixed + min_active > n_records:
        scale            = (n_records - min_active) / total_fixed
        idle_records     = max(6,  int(idle_records     * scale))
        rampup_records   = max(10, int(rampup_records   * scale))
        winddown_records = max(15, int(winddown_records * scale))
        shutdown_records = max(8,  int(shutdown_records * scale))

    idle_end       = idle_records
    rampup_end     = idle_end + rampup_records
    winddown_start = n_records - winddown_records - shutdown_records
    shutdown_start = n_records - shutdown_records

    for i in range(n_records):
        if i < idle_end:
            phase, phase_idx = "idle",     i
        elif i < rampup_end:
            phase, phase_idx = "rampup",   i - idle_end
        elif i < winddown_start:
            phase, phase_idx = "active",   i - rampup_end
        elif i < shutdown_start:
            phase, phase_idx = "winddown", i - winddown_start
        else:
            phase, phase_idx = "shutdown", i - shutdown_start

        infer_dt                = file_start_dt + timedelta(seconds=i * RECORD_INTERVAL)
        infer_recorded_date_str = infer_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        timestamp_str           = infer_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"

        wire_feed = gen_wire_feed_speed(phase, phase_idx, profile, rampup_records, winddown_records)
        wire_temp = gen_wire_temperature(phase, phase_idx, profile, rampup_records, winddown_records, shutdown_records)
        current   = gen_welding_current(phase, phase_idx, profile, rampup_records, winddown_records)

        records.append({
            "robot_code"            : ROBOT_CODE,
            "start_time"            : start_time_str,
            "program_number"        : PROGRAM_NUMBER,
            "infer_recorded_date"   : infer_recorded_date_str,
            "serial_number"         : i + 1,
            "phase"                 : phase,
            "wire_feed_speed_m_min" : wire_feed,
            "wire_temperature_c"    : wire_temp,
            "welding_current_a"     : current,
            "timestamp"             : timestamp_str,
        })

    return records, idle_end, rampup_end, winddown_start, shutdown_start


# ─────────────────────────────────────────────
# 6. ANOMALY INJECTOR
# ─────────────────────────────────────────────

class AnomalyInjector:

    def __init__(self):
        self.deviation_config = {
            "wire_feed_speed_m_min" : lambda: random.uniform(0.3, 0.8),
            "wire_temperature_c"    : lambda: random.uniform(30, 80),
            "welding_current_a"     : lambda: random.uniform(20, 50),
        }

    def _phase_bounds(self, phase_name, idle_end, rampup_end, winddown_start, shutdown_start):
        if phase_name == "Rampup":    return idle_end, rampup_end
        elif phase_name == "Active":  return rampup_end, winddown_start
        elif phase_name == "Winddown": return winddown_start, shutdown_start
        return None, None

    def _safe_window(self, t_start, t_end, L):
        if (t_end - t_start) < L: return None, None
        actual_start = random.randint(t_start, t_end - L)
        return actual_start, actual_start + L

    def inject(self, df, pattern, target_sensor, phase_name,
               idle_end, rampup_end, winddown_start, shutdown_start):

        if target_sensor not in VALID_COMBINATIONS.get(pattern, []):
            return df, None

        t_start, t_end = self._phase_bounds(
            phase_name, idle_end, rampup_end, winddown_start, shutdown_start
        )
        if t_start is None: return df, None

        df_injected   = df.copy()
        target_series = df_injected[target_sensor].values.astype(float)
        actual_start  = t_start
        actual_end    = t_end
        injection_val = None

        # ── A. DROPOUT ────────────────────────────────────────────────────────
        if pattern == "Dropout":
            L = random.randint(10, 20)
            actual_start, actual_end = self._safe_window(t_start, t_end, L)
            if actual_start is None: return df, None
            target_series[actual_start:actual_end] = np.random.normal(0, 0.001, L)
            injection_val = "drop_to_~0"

        # ── B. SURGE ──────────────────────────────────────────────────────────
        elif pattern == "Surge":
            L     = random.randint(3, 8)   # tăng từ 1–3 lên 3–8 để dễ detect hơn
            found = False
            for _ in range(20):
                actual_start, actual_end = self._safe_window(t_start, t_end, L)
                if actual_start is None: return df, None
                if np.any(np.abs(target_series[actual_start:actual_end]) > 0.01):
                    found = True
                    break
            if not found: return df, None
            multiplier = random.uniform(2.0, 3.0)
            target_series[actual_start:actual_end] *= multiplier
            injection_val = round(multiplier, 3)

        # ── C. DEVIATION ──────────────────────────────────────────────────────
        elif pattern == "Deviation":
            min_L     = 40
            phase_len = t_end - t_start
            if phase_len < min_L: return df, None
            L            = random.randint(min_L, min(80, phase_len))
            actual_start = random.randint(t_start, t_end - L)
            actual_end   = actual_start + L
            offset       = self.deviation_config.get(target_sensor, lambda: 0)()
            target_series[actual_start:actual_end] += offset
            injection_val = round(offset, 4)

        # ── D. INSTABILITY ────────────────────────────────────────────────────
        elif pattern == "Instability":
            min_L     = 20
            phase_len = t_end - t_start
            if phase_len < min_L: return df, None
            L            = random.randint(min_L, phase_len)
            actual_start = random.randint(t_start, t_end - L)
            actual_end   = actual_start + L

            active_vals = target_series[t_start:t_end]
            base_std    = np.std(active_vals) if np.std(active_vals) > 0 else 1.0
            noise_std   = base_std * random.uniform(5, 10)
            noise       = np.random.normal(0, noise_std, L)
            amplitude   = np.mean(np.abs(active_vals)) * 0.1
            t_arr       = np.arange(L)
            sine_wave   = amplitude * np.sin(2 * np.pi * 0.1 * t_arr)
            target_series[actual_start:actual_end] += (noise + sine_wave)
            injection_val = f"noise_std={round(noise_std,2)}_sin_amp={round(amplitude,2)}"

        # ── E. TRANSITION ─────────────────────────────────────────────────────
        elif pattern == "Transition":
            if target_sensor not in RAMP_SENSORS: return df, None
            if phase_name == "Active": return df, None

            if phase_name == "Rampup":
                seg_len      = min(15, rampup_end - idle_end)
                actual_start = idle_end
                actual_end   = idle_end + seg_len
                window       = 10
            else:  # Winddown
                seg_len      = min(15, shutdown_start - winddown_start)
                actual_start = winddown_start
                actual_end   = winddown_start + seg_len
                window       = 8

            if (actual_end - actual_start) < 2: return df, None
            smoothed = (
                pd.Series(target_series[actual_start:actual_end])
                .rolling(window=window, min_periods=1).mean().values
            )
            target_series[actual_start:actual_end] = smoothed
            injection_val = f"sluggish_window={window}"

        else:
            return df, None

        df_injected[target_sensor] = target_series
        gt_record = {
            "is_anomaly"     : 1,
            "anomaly_type"   : pattern,
            "target_sensor"  : target_sensor,
            "phase_location" : phase_name,
            "start_index"    : int(actual_start),
            "end_index"      : int(actual_end),
            "injection_value": injection_val,
            "n_injected"     : int(actual_end - actual_start),
        }
        return df_injected, gt_record


# ─────────────────────────────────────────────
# 7. ORCHESTRATOR
# ─────────────────────────────────────────────

def main():
    print("🚀 Starting Welding Robot Inference Data Generator v3")
    print(f"   Total files   : {TOTAL_FILES} (~1 ngày)")
    print(f"   Anomaly window: {ANOMALY_WINDOW} files (~1h/lỗi)")
    print(f"   Output folder : {OUTPUT_DIR}/")
    print("-" * 55)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    injector          = AnomalyInjector()
    ground_truth_list = []
    current_dt        = START_DATETIME
    anomaly_count     = 0
    normal_count      = 0

    # Pattern rotation — đảm bảo mỗi window 1 pattern khác nhau
    pattern_queue = []

    for file_idx in range(TOTAL_FILES):
        n_records = sample_n_records()
        records, idle_end, rampup_end, winddown_start, shutdown_start = \
            generate_file_records(current_dt, n_records)
        df      = pd.DataFrame(records)
        file_id = f"cycle_{file_idx + 1:05d}"

        # ── Window-based injection ─────────────────────────────────────────────
        window_idx      = file_idx // ANOMALY_WINDOW   # window hiện tại
        pos_in_window   = file_idx % ANOMALY_WINDOW    # vị trí trong window

        # Mỗi window chọn 1 vị trí random để inject
        # Dùng seed cố định theo window để vị trí nhất quán
        rng             = random.Random(window_idx * 9999)
        anomaly_pos     = rng.randint(0, ANOMALY_WINDOW - 1)
        is_anomaly_file = (pos_in_window == anomaly_pos)

        injected = False

        if is_anomaly_file:
            # Pattern rotation theo window_idx
            pattern = PATTERN_ROTATION[window_idx % len(PATTERN_ROTATION)]
            sensor  = random.choice(VALID_COMBINATIONS[pattern])
            phase   = random.choices(
                ["Rampup", "Active", "Winddown"], weights=[0.2, 0.6, 0.2]
            )[0]

            df_final, gt_record = injector.inject(
                df=df, pattern=pattern, target_sensor=sensor, phase_name=phase,
                idle_end=idle_end, rampup_end=rampup_end,
                winddown_start=winddown_start, shutdown_start=shutdown_start,
            )

            if gt_record is not None:
                gt_record["file_id"]         = file_id
                gt_record["n_records_total"] = n_records
                ground_truth_list.append(gt_record)
                df_final.to_csv(f"{OUTPUT_DIR}/{file_id}_anomaly.csv", index=False)
                injected      = True
                anomaly_count += 1

        if not injected:
            ground_truth_list.append({
                "file_id"        : file_id,
                "is_anomaly"     : 0,
                "anomaly_type"   : "Normal",
                "target_sensor"  : None,
                "phase_location" : None,
                "start_index"    : None,
                "end_index"      : None,
                "injection_value": None,
                "n_injected"     : 0,
                "n_records_total": n_records,
            })
            df.to_csv(f"{OUTPUT_DIR}/{file_id}_normal.csv", index=False)
            normal_count += 1

        current_dt += timedelta(
            seconds=n_records * RECORD_INTERVAL + sample_gap_seconds()
        )

    # ── Ground Truth ───────────────────────────────────────────────────────────
    print("-" * 55)
    print("⏳ Saving ground_truth_labels.csv ...")

    df_gt = pd.DataFrame(ground_truth_list)[[
        "file_id", "is_anomaly", "anomaly_type", "target_sensor",
        "phase_location", "start_index", "end_index",
        "n_injected", "n_records_total", "injection_value",
    ]]
    df_gt.to_csv("ground_truth_labels.csv", index=False)

    print("✅ Done!")
    print(f"   Normal files  : {normal_count}")
    print(f"   Anomaly files : {anomaly_count} ({anomaly_count/TOTAL_FILES*100:.1f}%)")
    print(f"   Labels saved  : ground_truth_labels.csv")
    print()
    print("📋 Pattern distribution:")
    for p in PATTERN_ROTATION:
        count = df_gt[df_gt["anomaly_type"] == p].shape[0]
        print(f"   {p:<15}: {count} files")


if __name__ == "__main__":
    main()