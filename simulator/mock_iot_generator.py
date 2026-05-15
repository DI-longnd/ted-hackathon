"""
Mock Data Generator v2.1 — IoT Robot Spray Painting + Phase-Aware Anomaly Injection
==================================================================================
Tạo 6000 chu trình vận hành robot dạng Time-series.
Tỷ lệ: 85% file bình thường (Normal), 15% file có tiêm lỗi (Anomaly).
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
PAINT_COLOR_NO  = 0
TOTAL_FILES     = 6000
OUTPUT_DIR      = "./mock_data_output"
START_DATETIME  = datetime(2025, 7, 1, 0, 0, 0)
RECORD_INTERVAL = 0.2

# FIX #1+#2: VALID_COMBINATIONS — sensor hợp lệ cho từng pattern
# Lý do chi tiết: xem tài liệu kỹ thuật
VALID_COMBINATIONS = {
    "Dropout"     : [
        "high_pressure_level_1_voltage",
        "high_pressure_level_1_current",
        "air_motor_rotation_speed_actual_value",
        "paint_pressure_dcl",
    ],
    "Surge"       : [
        "high_pressure_level_1_voltage",
        "high_pressure_level_1_current",
        "air_motor_rotation_speed_actual_value",
        "paint_flow_rate_cc_per_min",
    ],
    "Deviation"   : [
        "high_pressure_level_1_voltage",
        "high_pressure_level_1_current",
        "air_motor_rotation_speed_actual_value",
    ],
    "Instability" : [
        "high_pressure_level_1_voltage",
        "high_pressure_level_1_current",
        "air_motor_rotation_speed_actual_value",
    ],
    "Transition"  : [
        "high_pressure_level_1_voltage",
        "high_pressure_level_1_current",
    ],
}

RAMP_SENSORS = {
    "high_pressure_level_1_voltage",
    "high_pressure_level_1_current",
}

# ─────────────────────────────────────────────
# 2. BASE DATA GENERATOR HELPERS
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

def sample_file_profile():
    return {
        "voltage_mean"        : gauss(-59.8, 0.3, -60.5, -59.0),
        "rotation_mean"       : gauss(250.0, 1.5, 247.0, 253.0),
        "rotation_std"        : gauss(1.5, 0.3, 0.8, 2.5),
        "electro_range_hi"    : random.choice([800, 900, 1000, 1100]),
        "electro_base"        : gauss(0, 50, 0, 150),
        "flow_active_val"     : round(gauss(245, 8, 230, 265), 0),
        "idle_records"        : random.randint(8, 16),
        "rampup_records"      : random.randint(18, 28),
        "shutdown_records"    : random.randint(14, 22),
        "winddown_records"    : random.randint(15, 28),
        "current_mean"        : gauss(47, 2, 42, 53),
        "winddown_stable_hold": random.randint(5, 12),
    }

def gen_rotation_speed(phase, record_idx, profile, idle_records):
    mean = profile["rotation_mean"]
    std  = profile["rotation_std"]
    if phase == "idle":
        t    = record_idx / idle_records
        base = (mean + 18) - 18 * t
        return round(clamp(base + gauss(0, 1.5), 240, 272), 1)
    return round(gauss(mean, std, mean - 5, mean + 5), 1)

def gen_electro_pneumatic(phase, record_idx, profile, idle_records, rampup_records):
    hi   = profile["electro_range_hi"]
    base = profile["electro_base"]
    if phase == "idle":
        if record_idx < 4: return 0.0
        progress = (record_idx - 4) / max(idle_records - 4, 1)
        return round(gauss(progress * 400, 80, 0, 600), 1)
    elif phase == "rampup":
        progress = record_idx / rampup_records
        return round(gauss(progress * (hi * 0.6), 120, 0, hi * 0.85), 1)
    elif phase in ("active", "winddown"):
        if random.random() < 0.05: return 0.0
        return round(random.uniform(base, hi), 1)
    return 0.0

def gen_voltage(phase, record_idx, profile, rampup_records):
    v_mean = profile["voltage_mean"]
    if phase == "idle": return 0.0
    elif phase == "rampup":
        t     = record_idx / rampup_records
        curve = 1 - math.exp(-5 * t)
        base  = v_mean * curve
        noise = gauss(0, 0.3 * (1 - t))
        return round(clamp(base + noise, v_mean - 2, 0), 6)
    elif phase in ("active", "winddown"):
        return round(gauss(v_mean, 0.15, v_mean - 1.5, v_mean + 1.0), 6)
    return 0.0

def gen_current(phase, record_idx, profile, rampup_records, winddown_records):
    c_mean      = profile["current_mean"]
    stable_hold = profile["winddown_stable_hold"]
    if phase == "idle": return 0.0
    elif phase == "rampup":
        t          = record_idx / rampup_records
        ramp_curve = min(1.0, t * 2)
        base       = c_mean * ramp_curve
        return round(clamp(base + gauss(0, 2), 0, c_mean + 10), 1)
    elif phase == "active":
        return round(gauss(c_mean, 4, c_mean - 12, c_mean + 10), 1)
    elif phase == "winddown":
        if record_idx < stable_hold:
            return round(gauss(c_mean, 4, c_mean - 10, c_mean + 8), 1)
        decay_progress = (record_idx - stable_hold) / max(winddown_records - stable_hold, 1)
        base = c_mean - (c_mean - 33) * decay_progress
        return round(clamp(base + gauss(0, 2), 28, c_mean + 5), 1)
    return 0.0

class FlowStateMachine:
    def __init__(self, profile):
        self.active_value      = profile["flow_active_val"]
        self.current_value     = 0.0
        self.records_remaining = 0
        self.phase             = "idle"
        self.mid_pause_budget  = 1 if random.random() < 0.10 else 0

    def set_phase(self, phase):
        self.phase = phase
        if phase in ("idle", "shutdown"):
            self.current_value     = 0.0
            self.records_remaining = 999

    def _next_cluster_len(self, is_on, is_winddown):
        if self.phase == "rampup":
            return random.randint(3, 8) if is_on else random.randint(1, 5)
        if is_winddown:
            return random.randint(1, 5) if is_on else random.randint(3, 12)
        if is_on:
            return random.randint(2, 8) if random.random() < 0.80 else random.randint(9, 16)
        return random.randint(1, 5) if random.random() < 0.80 else random.randint(6, 12)

    def next(self, is_winddown=False):
        if self.phase in ("idle", "shutdown"): return 0.0
        if self.records_remaining <= 0:
            if self.current_value == 0.0:
                if self.mid_pause_budget > 0 and random.random() < 0.005:
                    self.current_value     = 0.0
                    self.records_remaining = random.randint(8, 15)
                    self.mid_pause_budget -= 1
                else:
                    val = random.choice([180.0, 200.0]) if self.phase == "rampup" else float(self.active_value)
                    self.current_value     = val
                    self.records_remaining = self._next_cluster_len(True, is_winddown)
            else:
                self.current_value     = 0.0
                self.records_remaining = self._next_cluster_len(False, is_winddown)
        self.records_remaining -= 1
        return self.current_value

class PressureStateMachine:
    def __init__(self):
        self.current_value     = 0.1
        self.records_remaining = random.randint(10, 25)

    def next(self):
        if self.records_remaining <= 0:
            r = random.random()
            if r < 0.02:
                self.current_value     = 0.3
                self.records_remaining = random.randint(1, 4)
            elif r < 0.35:
                self.current_value     = 0.1
                self.records_remaining = random.randint(8, 25)
            else:
                self.current_value     = 0.2
                self.records_remaining = random.randint(8, 25)
        self.records_remaining -= 1
        return self.current_value

def generate_file_records(file_start_dt, n_records):
    records = []
    profile = sample_file_profile()
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
        winddown_records = max(8,  int(winddown_records * scale))
        shutdown_records = max(8,  int(shutdown_records * scale))

    idle_end       = idle_records
    rampup_end     = idle_end + rampup_records
    winddown_start = n_records - winddown_records - shutdown_records
    shutdown_start = n_records - shutdown_records

    flow_sm     = FlowStateMachine(profile)
    pressure_sm = PressureStateMachine()

    for i in range(n_records):
        if i < idle_end:         phase, phase_idx = "idle",     i
        elif i < rampup_end:     phase, phase_idx = "rampup",   i - idle_end
        elif i < winddown_start: phase, phase_idx = "active",   i - rampup_end
        elif i < shutdown_start: phase, phase_idx = "winddown", i - winddown_start
        else:                    phase, phase_idx = "shutdown",  i - shutdown_start

        if i == 0:             flow_sm.set_phase("idle")
        elif i == idle_end:
            flow_sm.set_phase("rampup")
            flow_sm.current_value     = 0.0
            flow_sm.records_remaining = 0
        elif i == rampup_end:
            flow_sm.phase             = "active"
            flow_sm.current_value     = 0.0
            flow_sm.records_remaining = 0
        elif i == winddown_start: flow_sm.phase = "winddown"
        elif i == shutdown_start: flow_sm.set_phase("shutdown")

        infer_dt                = file_start_dt + timedelta(seconds=i * RECORD_INTERVAL)
        infer_recorded_date_str = infer_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        timestamp_str           = infer_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"

        is_winddown = (phase == "winddown")
        rotation    = gen_rotation_speed(phase, phase_idx, profile, idle_records)
        electro     = gen_electro_pneumatic(phase, phase_idx, profile, idle_records, rampup_records)
        voltage     = gen_voltage(phase, phase_idx, profile, rampup_records)
        current     = gen_current(phase, phase_idx, profile, rampup_records, winddown_records)
        flow        = flow_sm.next(is_winddown=is_winddown)

        if phase in ("idle", "shutdown"):   pressure = 0.0
        elif phase == "rampup":             pressure = 0.0 if phase_idx < rampup_records // 2 else 0.1
        else:                               pressure = pressure_sm.next()

        records.append({
            "robot_code"                                  : ROBOT_CODE,
            "start_time"                                  : start_time_str,
            "program_number"                              : PROGRAM_NUMBER,
            "step_no"                                     : i + 1,
            "paint_color_no"                              : PAINT_COLOR_NO,
            "infer_recorded_date"                         : infer_recorded_date_str,
            "serial_number"                               : i + 1,
            "air_motor_rotation_speed_actual_value"       : rotation,
            "air_motor_electro_pneumatic_output_value_bit": electro,
            "high_pressure_level_1_voltage"               : voltage,
            "high_pressure_level_1_current"               : current,
            "paint_pressure_dcl"                          : pressure,
            "paint_flow_rate_cc_per_min"                  : flow,
            "timestamp"                                   : timestamp_str,
        })

    return records, idle_end, rampup_end, winddown_start, shutdown_start


# ─────────────────────────────────────────────
# 3. ANOMALY INJECTOR
# ─────────────────────────────────────────────

class AnomalyInjector:
    def __init__(self):
        # FIX #3: chỉ giữ sensors hợp lệ cho Deviation
        self.deviation_config = {
            "high_pressure_level_1_voltage"         : lambda: random.uniform(5, 15),
            "high_pressure_level_1_current"         : lambda: random.uniform(15, 25),
            "air_motor_rotation_speed_actual_value" : lambda: random.uniform(8, 15),
        }

    def _phase_bounds(self, phase_name, idle_end, rampup_end, winddown_start, shutdown_start):
        if phase_name == "Rampup":   return idle_end, rampup_end
        elif phase_name == "Active": return rampup_end, winddown_start
        elif phase_name == "Winddown": return winddown_start, shutdown_start
        return None, None

    def _safe_window(self, t_start, t_end, L):
        if (t_end - t_start) < L: return None, None
        actual_start = random.randint(t_start, t_end - L)
        return actual_start, actual_start + L

    def inject(self, df, pattern, target_sensor, phase_name,
               idle_end, rampup_end, winddown_start, shutdown_start):

        # FIX #1: validate combination trước khi inject
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
            L     = random.randint(1, 3)
            found = False
            for _ in range(20):
                actual_start, actual_end = self._safe_window(t_start, t_end, L)
                if actual_start is None: return df, None
                if np.any(np.abs(target_series[actual_start:actual_end]) > 0.01):
                    found = True
                    break
            if not found: return df, None

            multiplier = random.uniform(0.1, 0.5) if "voltage" in target_sensor \
                         else random.uniform(2.0, 3.0)
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
            if phase_name == "Active": return df, None  # không có edge

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
# 4. ORCHESTRATOR
# ─────────────────────────────────────────────

def main():
    print("🚀 Starting Anomaly Injection Pipeline...")
    print(f"   Total files   : {TOTAL_FILES}")
    print(f"   Output folder : {OUTPUT_DIR}/")
    print("-" * 50)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    injector          = AnomalyInjector()
    ground_truth_list = []
    current_dt        = START_DATETIME
    anomaly_count     = 0
    normal_count      = 0

    for file_idx in range(TOTAL_FILES):
        n_records = sample_n_records()
        records, idle_end, rampup_end, winddown_start, shutdown_start = \
            generate_file_records(current_dt, n_records)
        df      = pd.DataFrame(records)
        file_id = f"cycle_{file_idx + 1:05d}"

        # ── FIX #1: chọn pattern → rồi chọn sensor từ valid list ──────────────
        is_anomaly_file = random.random() < 0.15
        injected        = False

        if is_anomaly_file:
            pattern = random.choice(list(VALID_COMBINATIONS.keys()))
            sensor  = random.choice(VALID_COMBINATIONS[pattern])   # FIX #1
            phase   = random.choices(
                ["Rampup", "Active", "Winddown"], weights=[0.2, 0.6, 0.2]
            )[0]

            df_final, gt_record = injector.inject(
                df=df, pattern=pattern, target_sensor=sensor, phase_name=phase,
                idle_end=idle_end, rampup_end=rampup_end,
                winddown_start=winddown_start, shutdown_start=shutdown_start,
            )

            if gt_record is not None:
                gt_record["file_id"]        = file_id
                gt_record["n_records_total"] = n_records
                ground_truth_list.append(gt_record)
                df_final.to_csv(f"{OUTPUT_DIR}/{file_id}_anomaly.csv", index=False)
                injected = True
                anomaly_count += 1

        # ── Ghi file bình thường ───────────────────────────────────────────────
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

        if (file_idx + 1) % 500 == 0:
            print(f"   [{file_idx+1:5d}/{TOTAL_FILES}] "
                  f"normal={normal_count} | anomaly={anomaly_count}")

    # ── Ground Truth ───────────────────────────────────────────────────────────
    print("-" * 50)
    print("⏳ Saving ground_truth_labels.csv ...")

    df_gt = pd.DataFrame(ground_truth_list)[[
        "file_id", "is_anomaly", "anomaly_type", "target_sensor",
        "phase_location", "start_index", "end_index",
        "n_injected", "n_records_total", "injection_value",
    ]]
    df_gt.to_csv("ground_truth_labels.csv", index=False)

    print("✅ Done!")
    print(f"   Normal files  : {normal_count}")
    print(f"   Anomaly files : {anomaly_count} "
          f"({anomaly_count/TOTAL_FILES*100:.1f}%)")
    print(f"   Labels saved  : ground_truth_labels.csv")


if __name__ == "__main__":
    main()