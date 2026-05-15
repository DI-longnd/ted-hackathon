"""
Mock Data Generator v2 — IoT Robot Spray Painting
===================================================
Fixes vs v1:
  [#1] Voltage per-file baseline variation (std=0.3 across files)
  [#2] Flow ON/OFF clusters — wider range, long bursts, mid-cycle pause
  [#3] Phase boundaries — jitter on idle/rampup/shutdown length
  [#4] N_records distribution — better match real data multi-modal shape
  [#5] Pressure tỉ lệ — bias 0.2 > 0.1 (65/35)
  [#6] Current wind-down — stable thêm rồi mới decay nhanh
  [#7] Electro per-file base range variation
  [#8] Mid-cycle long flow pause (~10% chance)
  [#9] Rotation per-file mean variation
"""

import random
import math
import csv
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
ROBOT_CODE      = 6
PROGRAM_NUMBER  = 116
PAINT_COLOR_NO  = 0
TOTAL_FILES     = 6000
OUTPUT_PATH     = "mock_robot_spray_data.csv"
START_DATETIME  = datetime(2025, 7, 1, 0, 0, 0)
RECORD_INTERVAL = 0.2  # seconds between records


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

def gauss(mean, std, lo=None, hi=None):
    v = random.gauss(mean, std)
    if lo is not None or hi is not None:
        v = clamp(v, lo if lo is not None else -1e18, hi if hi is not None else 1e18)
    return v


# FIX #4 — N_records: better multi-modal distribution matching real data
def sample_n_records():
    """
    Real data: mode ~277-281, significant tail up to 554
    3 buckets:
      75%: 200–320  (typical short-medium runs)
      18%: 320–430  (longer runs)
       7%: 430–554  (long runs — match real data tail)
    """
    r = random.random()
    if r < 0.75:
        return int(gauss(278, 22, 200, 320))
    elif r < 0.93:
        return int(gauss(360, 30, 320, 430))
    else:
        return int(gauss(500, 28, 430, 554))


def sample_gap_seconds():
    r = random.random()
    if r < 0.70:
        return random.randint(79, 300)
    elif r < 0.90:
        return random.randint(300, 900)
    else:
        return random.randint(900, 3660)


# ─────────────────────────────────────────────
# PER-FILE PROFILE  (FIX #1 #7 #9)
# Called once per file — defines the "character" of this spray cycle
# ─────────────────────────────────────────────

def sample_file_profile():
    """
    Returns a dict of per-file constants that give each file
    a slightly different operating baseline.
    """
    return {
        # FIX #1: voltage baseline per file — range ~-59.3 to -60.3
        "voltage_mean"      : gauss(-59.8, 0.3, -60.5, -59.0),

        # FIX #9: rotation mean per file — range ~247.5 to 252.5
        # "rotation_mean"     : gauss(250.0, 1.5, 247.0, 253.0),

        "rotation_mean" : gauss(250.0, 1.5, 247.0, 253.0),
        "rotation_std"  : gauss(1.5, 0.3, 0.8, 2.5),  # per-file noise width — hẹp

        # FIX #7: electro per-file range — some files run hotter/cooler
        "electro_range_hi"  : random.choice([800, 900, 1000, 1100]),
        "electro_base"      : gauss(0, 50, 0, 150),   # occasional non-zero floor

        # flow active value — continuous range instead of just [240,250]
        "flow_active_val"   : round(gauss(245, 8, 230, 265), 0),

        # FIX #3: phase length jitter
        "idle_records"      : random.randint(8, 16),       # was fixed 12
        "rampup_records"    : random.randint(18, 28),       # was fixed 22
        "shutdown_records"  : random.randint(14, 22),       # was fixed 18
        "winddown_records"  : random.randint(15, 28),       # was fixed 20

        # FIX #6: current wind-down — stable_hold before decay starts
        "current_mean"      : gauss(47, 2, 42, 53),        # per-file current level
        "winddown_stable_hold": random.randint(5, 12),      # records before decay kicks in
    }


# ─────────────────────────────────────────────
# SENSOR GENERATORS
# ─────────────────────────────────────────────

# def gen_rotation_speed(phase, record_idx, profile, idle_records):
#     # FIX #9: use per-file rotation_mean
#     mean = profile["rotation_mean"]
#     if phase == "idle":
#         t    = record_idx / idle_records
#         base = (mean + 18) - 18 * t          # ramp down from mean+18 → mean
#         return round(clamp(base + gauss(0, 1.5), 240, 272), 1)
#     else:
#         return round(gauss(mean, 3.5, 240, 268), 1)

def gen_rotation_speed(phase, record_idx, profile, idle_records):
    mean = profile["rotation_mean"]
    std  = profile["rotation_std"]   # hẹp per-file, ~0.8–2.5
    
    if phase == "idle":
        t    = record_idx / idle_records
        base = (mean + 18) - 18 * t   # ramp down từ mean+18 → mean
        return round(clamp(base + gauss(0, 1.5), 240, 272), 1)
    else:
        # ACTIVE/RAMPUP/WINDDOWN/SHUTDOWN: dao động hẹp quanh per-file mean
        return round(gauss(mean, std, mean - 5, mean + 5), 1)

def gen_electro_pneumatic(phase, record_idx, profile, idle_records, rampup_records):
    # FIX #7: use per-file electro_range_hi and base
    hi   = profile["electro_range_hi"]
    base = profile["electro_base"]

    if phase == "idle":
        if record_idx < 4:
            return 0.0
        progress = (record_idx - 4) / max(idle_records - 4, 1)
        return round(gauss(progress * 400, 80, 0, 600), 1)
    elif phase == "rampup":
        progress = record_idx / rampup_records
        return round(gauss(progress * (hi * 0.6), 120, 0, hi * 0.85), 1)
    elif phase in ("active", "winddown"):
        if random.random() < 0.05:
            return 0.0
        return round(random.uniform(base, hi), 1)
    else:
        return 0.0


def gen_voltage(phase, record_idx, profile, rampup_records):
    # FIX #1: use per-file voltage_mean
    v_mean = profile["voltage_mean"]

    if phase == "idle":
        return 0.0
    elif phase == "rampup":
        t     = record_idx / rampup_records
        curve = 1 - math.exp(-5 * t)
        base  = v_mean * curve
        noise = gauss(0, 0.3 * (1 - t))
        return round(clamp(base + noise, v_mean - 2, 0), 6)
    elif phase in ("active", "winddown"):
        return round(gauss(v_mean, 0.15, v_mean - 1.5, v_mean + 1.0), 6)
    else:
        return 0.0


def gen_current(phase, record_idx, profile, rampup_records, winddown_records):
    # FIX #6: per-file current_mean, delayed wind-down decay
    c_mean        = profile["current_mean"]
    stable_hold   = profile["winddown_stable_hold"]

    if phase == "idle":
        return 0.0
    elif phase == "rampup":
        t          = record_idx / rampup_records
        ramp_curve = min(1.0, t * 2)
        base       = c_mean * ramp_curve
        return round(clamp(base + gauss(0, 2), 0, c_mean + 10), 1)
    elif phase == "active":
        return round(gauss(c_mean, 4, c_mean - 12, c_mean + 10), 1)
    elif phase == "winddown":
        # FIX #6: hold stable for first `stable_hold` records, then decay fast
        if record_idx < stable_hold:
            return round(gauss(c_mean, 4, c_mean - 10, c_mean + 8), 1)
        else:
            decay_progress = (record_idx - stable_hold) / max(winddown_records - stable_hold, 1)
            base = c_mean - (c_mean - 33) * decay_progress
            return round(clamp(base + gauss(0, 2), 28, c_mean + 5), 1)
    else:
        return 0.0


# ─────────────────────────────────────────────
# FLOW RATE STATE MACHINE  (FIX #2 #8)
# ─────────────────────────────────────────────

class FlowStateMachine:
    """
    FIX #2: Wider on/off cluster ranges — more realistic bursts
    FIX #8: ~10% chance of mid-cycle long pause (8-15 records)
    """

    def __init__(self, profile):
        self.active_value      = profile["flow_active_val"]
        self.current_value     = 0.0
        self.records_remaining = 0
        self.phase             = "idle"
        self.mid_pause_budget  = 1 if random.random() < 0.10 else 0  # FIX #8

    def set_phase(self, phase):
        self.phase = phase
        if phase in ("idle", "shutdown"):
            self.current_value     = 0.0
            self.records_remaining = 999

    def _next_cluster_len(self, is_on, is_winddown):
        """FIX #2: wider range, long clusters allowed"""
        if self.phase == "rampup":
            return random.randint(3, 8) if is_on else random.randint(1, 5)

        if is_winddown:
            return random.randint(1, 5) if is_on else random.randint(3, 12)

        if is_on:
            # 80% normal burst, 20% long burst
            if random.random() < 0.80:
                return random.randint(2, 8)
            else:
                return random.randint(9, 16)
        else:
            # 80% short off, 20% long off
            if random.random() < 0.80:
                return random.randint(1, 5)
            else:
                return random.randint(6, 12)

    def next(self, is_winddown=False):
        if self.phase in ("idle", "shutdown"):
            return 0.0

        if self.records_remaining <= 0:
            if self.current_value == 0.0:
                # turn on — but check if we should inject mid-pause first
                if self.mid_pause_budget > 0 and random.random() < 0.005:
                    # FIX #8: inject a long pause
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


# ─────────────────────────────────────────────
# PRESSURE STATE MACHINE  (FIX #5)
# ─────────────────────────────────────────────

class PressureStateMachine:
    """
    FIX #5: bias 0.2 > 0.1 (65/33 split), rare 0.3 (2%)
    Longer hold durations for more realistic step function
    """

    def __init__(self):
        # Start with 0.1 at rampup transition
        self.current_value     = 0.1
        self.records_remaining = random.randint(10, 25)

    def next(self):
        if self.records_remaining <= 0:
            r = random.random()
            if r < 0.02:
                self.current_value     = 0.3        # rare spike
                self.records_remaining = random.randint(1, 4)
            elif r < 0.35:                           # FIX #5: 33% → 0.1
                self.current_value     = 0.1
                self.records_remaining = random.randint(8, 25)
            else:                                    # FIX #5: 65% → 0.2
                self.current_value     = 0.2
                self.records_remaining = random.randint(8, 25)

        self.records_remaining -= 1
        return self.current_value


# ─────────────────────────────────────────────
# GENERATE ONE FILE
# ─────────────────────────────────────────────

def generate_file_records(file_start_dt, n_records):
    records    = []
    profile    = sample_file_profile()
    start_time_str = file_start_dt.strftime("%Y-%m-%d %H:%M:%S")

    # FIX #3: phase lengths from profile (with jitter)
    idle_records     = profile["idle_records"]
    rampup_records   = profile["rampup_records"]
    shutdown_records = profile["shutdown_records"]
    winddown_records = profile["winddown_records"]

    # Guard: ensure phases fit within n_records
    min_active = 20
    total_fixed = idle_records + rampup_records + winddown_records + shutdown_records
    if total_fixed + min_active > n_records:
        # scale down proportionally
        scale        = (n_records - min_active) / total_fixed
        idle_records     = max(6,  int(idle_records     * scale))
        rampup_records   = max(10, int(rampup_records   * scale))
        winddown_records = max(8,  int(winddown_records * scale))
        shutdown_records = max(8,  int(shutdown_records * scale))

    # Phase boundary indices
    idle_end       = idle_records
    rampup_end     = idle_end + rampup_records
    winddown_start = n_records - winddown_records - shutdown_records
    shutdown_start = n_records - shutdown_records

    # State machines
    flow_sm     = FlowStateMachine(profile)
    pressure_sm = PressureStateMachine()

    for i in range(n_records):
        # Determine phase
        if i < idle_end:
            phase     = "idle"
            phase_idx = i
        elif i < rampup_end:
            phase     = "rampup"
            phase_idx = i - idle_end
        elif i < winddown_start:
            phase     = "active"
            phase_idx = i - rampup_end
        elif i < shutdown_start:
            phase     = "winddown"
            phase_idx = i - winddown_start
        else:
            phase     = "shutdown"
            phase_idx = i - shutdown_start

        # Flow state machine phase transitions
        if i == 0:
            flow_sm.set_phase("idle")
        elif i == idle_end:
            flow_sm.set_phase("rampup")
            flow_sm.current_value     = 0.0
            flow_sm.records_remaining = 0
        elif i == rampup_end:
            flow_sm.phase             = "active"
            flow_sm.current_value     = 0.0
            flow_sm.records_remaining = 0
        elif i == winddown_start:
            flow_sm.phase = "winddown"
        elif i == shutdown_start:
            flow_sm.set_phase("shutdown")

        # Timestamps
        infer_dt                = file_start_dt + timedelta(seconds=i * RECORD_INTERVAL)
        infer_recorded_date_str = infer_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        timestamp_str           = infer_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"

        # Sensor values
        is_winddown = (phase == "winddown")

        rotation = gen_rotation_speed(phase, phase_idx, profile, idle_records)
        electro  = gen_electro_pneumatic(phase, phase_idx, profile, idle_records, rampup_records)
        voltage  = gen_voltage(phase, phase_idx, profile, rampup_records)
        current  = gen_current(phase, phase_idx, profile, rampup_records, winddown_records)
        flow     = flow_sm.next(is_winddown=is_winddown)

        if phase in ("idle", "shutdown"):
            pressure = 0.0
        elif phase == "rampup":
            pressure = 0.0 if phase_idx < rampup_records // 2 else 0.1
        else:
            pressure = pressure_sm.next()

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

    return records


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("🚀 Starting mock data generation v2")
    print(f"   Total files : {TOTAL_FILES}")
    print(f"   Output      : {OUTPUT_PATH}")
    print()

    fieldnames = [
        "robot_code", "start_time", "program_number", "step_no",
        "paint_color_no", "infer_recorded_date", "serial_number",
        "air_motor_rotation_speed_actual_value",
        "air_motor_electro_pneumatic_output_value_bit",
        "high_pressure_level_1_voltage",
        "high_pressure_level_1_current",
        "paint_pressure_dcl",
        "paint_flow_rate_cc_per_min",
        "timestamp",
    ]

    current_dt = START_DATETIME
    total_rows = 0

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for file_idx in range(TOTAL_FILES):
            n_records = sample_n_records()
            records   = generate_file_records(current_dt, n_records)

            writer.writerows(records)
            total_rows += n_records

            file_duration_sec = n_records * RECORD_INTERVAL
            gap_sec           = sample_gap_seconds()
            current_dt        = current_dt + timedelta(seconds=file_duration_sec + gap_sec)

            if (file_idx + 1) % 100 == 0:
                print(f"   [{file_idx + 1:4d}/{TOTAL_FILES}] "
                      f"rows so far: {total_rows:,} | "
                      f"current_dt: {current_dt.strftime('%Y-%m-%d %H:%M')}")

    print()
    print("✅ Done!")
    print(f"   Total rows  : {total_rows:,}")
    print(f"   Output      : {OUTPUT_PATH}")
    print(f"   Timespan    : {START_DATETIME.strftime('%Y-%m-%d')} → "
          f"{current_dt.strftime('%Y-%m-%d')}")


if __name__ == "__main__":
    main()