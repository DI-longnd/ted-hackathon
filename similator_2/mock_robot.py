"""
Mock Data Generator v3.3 — IoT Welding Robot (MIG/MAG)
=======================================================
Changes vs v3.2:
  [FIX-7] wire_feed RAMPUP  : ramp UP từ mean*0.6 → mean, overshoot nhẹ
  [FIX-8] wire_feed WINDDOWN: giảm dần mean → 0 (dừng cấp dây fill crater)
  [FIX-9] wire_feed SHUTDOWN: = 0 (motor dừng hoàn toàn)
  [FIX-10] voltage WINDDOWN : giảm nhẹ v_mean → v_mean*0.8 (crater fill voltage)
"""

from cmath import phase
import random
import math
import csv
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
ROBOT_CODE      = 6
PROGRAM_NUMBER  = 116
TOTAL_FILES     = 6000
OUTPUT_PATH     = "mock_welding_robot_data.csv"
START_DATETIME  = datetime(2025, 7, 1, 0, 0, 0)
RECORD_INTERVAL = 0.25  # seconds between records — 4 Hz


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


def sample_n_records():
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
# PER-FILE PROFILE
# ─────────────────────────────────────────────

def sample_file_profile():
    return {
        "voltage_mean"        : gauss(22.0, 2.0, 18.0, 26.0),
        "current_mean"        : gauss(130, 25, 80, 180),
        # "wire_feed_mean"      : gauss(4000, 500, 3000, 5000),
        # "wire_feed_std"       : gauss(15, 5, 8, 25),
        "wire_feed_mean": gauss(4.0, 0.5, 3.0, 5.0),   # m/min
        "wire_feed_std" : gauss(0.05, 0.01, 0.02, 0.08), # std tương ứng
        "wire_temp_base": gauss(280, 20, 240, 320), 
        "idle_records"        : random.randint(8, 16),
        "rampup_records"      : random.randint(18, 28),
        "shutdown_records"    : random.randint(10, 18),
        "winddown_records"    : random.randint(30, 50),
        "winddown_stable_hold": random.randint(3, 6),
    }


# ─────────────────────────────────────────────
# SENSOR GENERATORS
# ─────────────────────────────────────────────

def gen_wire_feed_speed(phase, record_idx, profile, rampup_records, winddown_records):
    mean = profile["wire_feed_mean"]
    std  = profile["wire_feed_std"]

    # ── Low-freq wave: sóng lớn trải dài
    slow_wave = (mean * 0.014) * math.sin(2 * math.pi * record_idx / 22)

    # ── Mid-freq wave: dao động vừa
    mid_wave  = (mean * 0.007) * math.sin(2 * math.pi * record_idx / 9 + 1.2)

    # ── Smooth noise: texture nhẹ, không răng cưa
    smooth_noise = gauss(0, std * 0.4)

    if phase == "idle":
        base = mean * 0.9
        val  = base + 0.4 * slow_wave + smooth_noise
        return round(clamp(val, mean * 0.85, mean * 0.95), 3)

    elif phase == "rampup":
        t    = record_idx / max(rampup_records, 1)
        base = mean * 0.9 + mean * 0.1 * t
        damp = t  # biên độ tăng dần theo ramp
        val  = base + damp * (slow_wave + mid_wave) + smooth_noise
        return round(clamp(val, mean * 0.85, mean + 0.1), 3)

    elif phase == "active":
        val = mean + slow_wave + mid_wave + smooth_noise
        return round(clamp(val, mean - 0.12, mean + 0.12), 3)

    elif phase == "winddown":
        t    = record_idx / max(winddown_records, 1)
        base = mean - mean * 0.1 * t
        damp = 1 - 0.5 * t  # biên độ giảm dần
        val  = base + damp * (slow_wave + mid_wave) + smooth_noise
        return round(clamp(val, mean * 0.85, mean + 0.1), 3)

    else:  # shutdown
        base = mean * 0.9
        val  = base + 0.3 * slow_wave + smooth_noise
        return round(clamp(val, mean * 0.85, mean * 0.95), 3)

def gen_welding_voltage(phase, record_idx, profile, rampup_records, winddown_records):
    """
    IDLE    : 0V
    RAMPUP  : exponential 0 → voltage_mean
    ACTIVE  : ổn định ±0.4V
    WINDDOWN: [FIX-10] giảm nhẹ v_mean → v_mean*0.8 (crater fill voltage thấp hơn)
    SHUTDOWN: 0V
    """
    v_mean = profile["voltage_mean"]

    if phase == "idle":
        return 0.0
    elif phase == "rampup":
        t     = record_idx / rampup_records
        curve = 1 - math.exp(-5 * t)
        base  = v_mean * curve
        noise = gauss(0, 0.5 * (1 - t))
        return round(clamp(base + noise, 0, v_mean + 2), 3)
    elif phase == "active":
        return round(gauss(v_mean, 0.4, v_mean - 3, v_mean + 3), 3)
    elif phase == "winddown":
        # [FIX-10] Giảm tuyến tính từ v_mean → v_mean*0.8
        t      = record_idx / max(winddown_records, 1)
        target = v_mean - (v_mean * 0.2) * t
        return round(gauss(target, 0.4, v_mean * 0.75, v_mean + 1), 3)
    else:
        return 0.0




def gen_wire_temperature(phase, record_idx, profile, rampup_records, winddown_records, shutdown_records):
    """
    wire_temperature_c — nhiệt độ dây hàn tại contact tip (°C)
    IDLE    : ~25°C (nhiệt độ môi trường)
    RAMPUP  : tăng dần 25 → temp_base (tip nóng lên khi arc bắt đầu)
    ACTIVE  : ổn định quanh temp_base ±10°C
    WINDDOWN: giảm chậm temp_base → ~150°C (nguội dần)
    SHUTDOWN: tiếp tục giảm ~150 → ~60°C
    """
    temp_base = profile["wire_temp_base"]

    if phase == "idle":
        return round(gauss(25, 2, 20, 35), 1)

    elif phase == "rampup":
        t    = record_idx / max(rampup_records, 1)
        base = 25 + (temp_base - 25) * t
        return round(clamp(base + gauss(0, 5), 20, temp_base + 10), 1)

    # elif phase == "active":
    #     return round(gauss(temp_base, 8, temp_base - 30, temp_base + 30), 1)

    elif phase == "active":
            # Sine wave smooth + noise nhỏ — nhái ảnh 3
            sine  = 25 * math.sin(2 * math.pi * 0.05 * record_idx)
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
    """
    IDLE    : 0A
    RAMPUP  : ramp tuyến tính 0 → current_mean
    ACTIVE  : ổn định ±8A
    WINDDOWN: stable ngắn 3–6 records → decay dài rõ ràng → ~30A
    SHUTDOWN: 0A
    """
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
        else:
            decay_progress = (record_idx - stable_hold) / max(winddown_records - stable_hold, 1)
            base = c_mean - (c_mean - 30) * decay_progress
            return round(clamp(base + gauss(0, 4), 25, c_mean + 5), 1)
    else:
        return 0.0


# ─────────────────────────────────────────────
# GENERATE ONE FILE
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

        # [FIX-7,8,9] truyền thêm rampup_records, winddown_records vào wire_feed
        wire_feed = gen_wire_feed_speed(phase, phase_idx, profile, rampup_records, winddown_records)

        # [FIX-10] truyền thêm winddown_records vào voltage
        # voltage   = gen_welding_voltage(phase, phase_idx, profile, rampup_records, winddown_records)
        wire_temp = gen_wire_temperature(phase, phase_idx, profile, rampup_records, winddown_records, shutdown_records)

        current   = gen_welding_current(phase, phase_idx, profile, rampup_records, winddown_records)

        records.append({
            "robot_code"             : ROBOT_CODE,
            "start_time"             : start_time_str,
            "program_number"         : PROGRAM_NUMBER,
            "infer_recorded_date"    : infer_recorded_date_str,
            "serial_number"          : i + 1,
            "phase"                  : phase,
            # "wire_feed_speed_mm_min" : wire_feed,
            "wire_feed_speed_m_min" : wire_feed,

            # "welding_voltage_v"      : voltage,
            "wire_temperature_c"     : wire_temp,
            "welding_current_a"      : current,
            "timestamp"              : timestamp_str,
        })

    return records


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("🚀 Starting mock data generation v3.3 — Welding Robot")
    print(f"   Total files : {TOTAL_FILES}")
    print(f"   Output      : {OUTPUT_PATH}")
    print(f"   Interval    : {RECORD_INTERVAL}s (4 Hz)")
    print()

    fieldnames = [
        "robot_code", "start_time", "program_number",
        "infer_recorded_date", "serial_number", "phase",
        # "wire_feed_speed_mm_min",
        "wire_feed_speed_m_min",
        # "welding_voltage_v",
        "wire_temperature_c",
        "welding_current_a",
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