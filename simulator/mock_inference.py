import numpy as np
import pandas as pd
import random

# ─────────────────────────────────────────────────────────────────────────────
# SENSORS CÓ RAMP RÕ RÀNG — chỉ dùng cho TRANSITION
# ─────────────────────────────────────────────────────────────────────────────
RAMP_SENSORS = {
    "high_pressure_level_1_voltage",
    "high_pressure_level_1_current",
}

# ─────────────────────────────────────────────────────────────────────────────
# ANOMALY INJECTOR
# ─────────────────────────────────────────────────────────────────────────────

class AnomalyInjector:
    """
    Bơm lỗi vào một DataFrame (1 vòng chạy) theo 5 pattern:
      A. DROPOUT     — mất tín hiệu / tụt áp
      B. SURGE       — gai vọt / quá tải
      C. DEVIATION   — lệch dải vận hành
      D. INSTABILITY — chập chờn / răng cưa
      E. TRANSITION  — phản hồi trễ / ì máy

    Returns:
      df_injected  : DataFrame đã bị bóp méo
      gt_record    : dict Ground Truth (None nếu injection bị skip)
    """

    def __init__(self):
        # FIX #2: Deviation offset riêng cho từng sensor
        self.deviation_config = {
            "high_pressure_level_1_voltage"           : lambda: random.uniform(5, 15),
            "high_pressure_level_1_current"           : lambda: random.uniform(15, 25),
            "air_motor_rotation_speed_actual_value"   : lambda: random.uniform(8, 15),
            "paint_pressure_dcl"                      : lambda: random.uniform(0.1, 0.2),
            "paint_flow_rate_cc_per_min"              : lambda: random.uniform(50, 100),
        }

    # ── private helpers ───────────────────────────────────────────────────────

    def _phase_bounds(self, phase_name, idle_end, rampup_end, winddown_start, shutdown_start):
        """Trả về (t_start, t_end) của phase được chọn."""
        if phase_name == "Rampup":
            return idle_end, rampup_end
        elif phase_name == "Active":
            return rampup_end, winddown_start
        elif phase_name == "Winddown":
            return winddown_start, shutdown_start
        return None, None

    def _safe_window(self, t_start, t_end, L):
        """
        Chọn actual_start sao cho [actual_start, actual_start+L] nằm trong [t_start, t_end].
        Trả về (actual_start, actual_end) hoặc (None, None) nếu phase quá ngắn.
        """
        phase_len = t_end - t_start
        if phase_len < L:
            return None, None
        actual_start = random.randint(t_start, t_end - L)
        return actual_start, actual_start + L

    # ── public inject ─────────────────────────────────────────────────────────

    def inject(
        self,
        df,
        pattern,
        target_sensor,
        phase_name,
        idle_end,
        rampup_end,
        winddown_start,
        shutdown_start,
    ):
        """
        Parameters
        ----------
        df            : DataFrame của 1 vòng chạy (chưa bị bóp méo)
        pattern       : "Dropout" | "Surge" | "Deviation" | "Instability" | "Transition"
        target_sensor : tên cột sensor cần inject
        phase_name    : "Rampup" | "Active" | "Winddown"
        idle_end / rampup_end / winddown_start / shutdown_start : phase boundary indices

        Returns
        -------
        (df_injected, gt_record)
        gt_record = None nếu injection bị skip (phase quá ngắn, sensor không phù hợp...)
        """
        # Lấy phase bounds
        t_start, t_end = self._phase_bounds(
            phase_name, idle_end, rampup_end, winddown_start, shutdown_start
        )
        if t_start is None:
            return df, None  # phase không hợp lệ (idle / shutdown)

        df_injected   = df.copy()
        target_series = df_injected[target_sensor].values.astype(float)

        actual_start  = t_start
        actual_end    = t_end
        injection_val = None

        # ── A. DROPOUT ────────────────────────────────────────────────────────
        if pattern == "Dropout":
            L = random.randint(10, 20)
            actual_start, actual_end = self._safe_window(t_start, t_end, L)
            if actual_start is None:
                return df, None  # FIX #4: phase quá ngắn

            noise = np.random.normal(0, 0.001, L)
            target_series[actual_start:actual_end] = noise
            injection_val = "drop_to_~0"

        # ── B. SURGE ──────────────────────────────────────────────────────────
        elif pattern == "Surge":
            L = random.randint(1, 3)
            # Tìm window có giá trị != 0 (pressure/flow ở Rampup = 0 → skip)
            found = False
            for _ in range(20):
                actual_start, actual_end = self._safe_window(t_start, t_end, L)
                if actual_start is None:
                    return df, None
                if np.any(np.abs(target_series[actual_start:actual_end]) > 0.01):
                    found = True
                    break
            if not found:
                return df, None

            # FIX #1: voltage âm dùng multiplier [0.1, 0.5] → tụt về gần 0
            #         sensor dương dùng multiplier [2.0, 3.0] → vọt lên cao
            if "voltage" in target_sensor:
                multiplier = random.uniform(0.1, 0.5)
            else:
                multiplier = random.uniform(2.0, 3.0)

            target_series[actual_start:actual_end] *= multiplier
            injection_val = round(multiplier, 3)

        # ── C. DEVIATION ──────────────────────────────────────────────────────
        elif pattern == "Deviation":
            # FIX #1: random L > 40 per spec, không inject toàn phase
            min_L    = 40
            phase_len = t_end - t_start
            if phase_len < min_L:
                return df, None  # FIX #4: phase quá ngắn

            L            = random.randint(min_L, min(80, phase_len))
            actual_start = random.randint(t_start, t_end - L)
            actual_end   = actual_start + L

            offset = self.deviation_config.get(target_sensor, lambda: 0)()
            target_series[actual_start:actual_end] += offset
            injection_val = round(offset, 4)

        # ── D. INSTABILITY ────────────────────────────────────────────────────
        elif pattern == "Instability":
            min_L     = 20
            phase_len = t_end - t_start
            if phase_len < min_L:
                return df, None  # FIX #4

            L            = random.randint(min_L, phase_len)
            actual_start = random.randint(t_start, t_end - L)
            actual_end   = actual_start + L

            # FIX #2: tính std chỉ trên vùng active (t_start:t_end)
            # tránh bị kéo xuống bởi vùng IDLE/SHUTDOWN = 0
            active_vals = target_series[t_start:t_end]
            base_std    = np.std(active_vals) if np.std(active_vals) > 0 else 1.0
            noise_std   = base_std * random.uniform(5, 10)

            noise       = np.random.normal(0, noise_std, L)

            # Sóng sin: biên độ 10% mean của vùng active, tần số 0.1
            active_mean = np.mean(np.abs(active_vals))
            amplitude   = active_mean * 0.1
            t_arr       = np.arange(L)
            sine_wave   = amplitude * np.sin(2 * np.pi * 0.1 * t_arr)

            target_series[actual_start:actual_end] += (noise + sine_wave)
            injection_val = f"noise_std={round(noise_std, 2)}_sin_amp={round(amplitude, 2)}"

        # ── E. TRANSITION ─────────────────────────────────────────────────────
        elif pattern == "Transition":
            # FIX #3: chỉ inject vào sensors có ramp rõ ràng
            if target_sensor not in RAMP_SENSORS:
                return df, None

            # FIX #3: chỉ inject tại Rampup hoặc Winddown (có edge)
            # Nếu bốc trúng Active → skip
            if phase_name == "Active":
                return df, None

            if phase_name == "Rampup":
                # Làm phẳng đoạn ramp-up đầu: robot khởi động chậm
                seg_len      = min(15, rampup_end - idle_end)
                actual_start = idle_end
                actual_end   = idle_end + seg_len
                window       = 10

            elif phase_name == "Winddown":
                # Làm phẳng đoạn decay: van đóng chậm
                seg_len      = min(15, shutdown_start - winddown_start)
                actual_start = winddown_start
                actual_end   = winddown_start + seg_len
                window       = 8

            seg_len = actual_end - actual_start
            if seg_len < 2:
                return df, None  # quá ngắn để smooth

            temp_s   = pd.Series(target_series[actual_start:actual_end])
            smoothed = temp_s.rolling(window=window, min_periods=1).mean().values
            target_series[actual_start:actual_end] = smoothed
            injection_val = f"sluggish_window={window}"

        else:
            # Pattern không hợp lệ
            return df, None

        # Ghi lại series đã chỉnh
        df_injected[target_sensor] = target_series

        # Ground truth record
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