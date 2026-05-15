import pandas as pd
import numpy as np
from scipy import stats
from typing import Iterator
from pyspark.sql import Window
from pyspark.sql import functions as F
from pyspark.sql.types import *

# ======================================================================
# 1. CẤU HÌNH HỆ THỐNG
# ======================================================================
WINDOW_SIZE = 32
STRIDE = 8

INPUT_TABLE = "dbxws_multimodalai001.bronze_layer.robot_data_107M_sources_24_02"
OUTPUT_TABLE = "dbxws_multimodalai001.bronze_layer.slicingwindow_robot_data_107M_sources_24_02_fix"

# INPUT_TABLE = f"dbxws_multimodalai001.bronze_layer.data_training_variable_robot"
# OUTPUT_TABLE = "dbxws_multimodalai001.silver_layer.slicingwindow_data_training_variable_robot"

SENSOR_COLUMNS = {
    "air_motor_rotation_speed": "air_motor_rotation_speed_actual_value",
    "electro_pneumatic_output": "air_motor_electro_pneumatic_output_value_bit",
    "high_pressure_current": "high_pressure_level_1_current",
    "high_pressure_voltage": "high_pressure_level_1_voltage",
    "paint_pressure": "paint_pressure_dc1",
    "paint_flow_rate": "paint_flow_rate_cc_per_min"
}

SENSOR_ORDER = [
    "air_motor_rotation_speed", "electro_pneumatic_output", "high_pressure_current",
    "high_pressure_voltage", "paint_pressure", "paint_flow_rate"
]

GROUP_COLS = ["robot_code", "program_number", "start_time"]
DIMENSION_COLS = ["step_no", "paint_color_no"]

# Định nghĩa Feature Names chuẩn để dùng cho Alias
FEATURE_NAMES = [
    "mean", "stddev", "kurtosis", "skewness",
    "max", "min", "range", "rms",
    "slope", "crest_factor"
]

# Schema cho Struct trả về từ Pandas UDF
features_struct_schema = StructType([
    StructField("mean", DoubleType()),
    StructField("stddev", DoubleType()),
    StructField("kurtosis", DoubleType()),
    StructField("skewness", DoubleType()),
    StructField("max", DoubleType()),
    StructField("min", DoubleType()),
    StructField("range", DoubleType()),
    StructField("rms", DoubleType()),
    StructField("slope", DoubleType()),
    StructField("crest_factor", DoubleType())
])

# ======================================================================
# 2. PANDAS UDF (TOÁN HỌC VECTOR HÓA)
# ======================================================================
@F.pandas_udf(features_struct_schema)
def calculate_sensor_features_udf(batch_iterator: Iterator[pd.Series]) -> Iterator[pd.DataFrame]:
    """
    Tính toán 10 features bằng NumPy/SciPy trên từng lô (Batch).
    Khớp chính xác thuật toán với Spark (ddof=1, fisher=True).
    """
    for s_batch in batch_iterator:
        # Convert Series of Lists to 2D NumPy Array (N x 32)
        matrix = np.array(s_batch.tolist())

        # Phép toán cơ bản
        v_mean = np.mean(matrix, axis=1)
        v_std  = np.std(matrix, axis=1, ddof=1)  # ddof=1 để khớp với Spark Sample StdDev
        v_max  = np.max(matrix, axis=1)
        v_min  = np.min(matrix, axis=1)
        v_rms  = np.sqrt(np.mean(matrix**2, axis=1))

        # Thống kê bậc cao (SciPy)
        # fisher=True cho Excess Kurtosis (giống Spark), skew tính độ xiên
        v_kurt = stats.kurtosis(matrix, axis=1, fisher=True, bias=False)
        v_skew = stats.skew(matrix, axis=1, bias=False)

        v_range = v_max - v_min
        v_slope = (matrix[:, -1] - matrix[:, 0]) / WINDOW_SIZE
        v_crest = np.where(v_rms > 0, v_max / v_rms, 0.0)

        yield pd.DataFrame({
            "mean": v_mean, "stddev": v_std, "kurtosis": v_kurt, "skewness": v_skew,
            "max": v_max, "min": v_min, "range": v_range, "rms": v_rms,
            "slope": v_slope, "crest_factor": v_crest
        })

# ======================================================================
# 3. LUỒNG XỬ LÝ CHÍNH (PIPELINE)
# ======================================================================

print("\n[STEP 1] Loading and Partitioning data...")
raw_data = spark.table(INPUT_TABLE).select(
    *GROUP_COLS, *DIMENSION_COLS, "serial_number", "timestamp", *SENSOR_COLUMNS.values()
).repartition(100, *GROUP_COLS)


raw_data = raw_data.dropDuplicates()


print("\n[STEP 2] Windowing and Collecting Arrays...")
# Chỉ dùng 1 Spec duy nhất để Spark tối ưu hóa Sort
sliding_spec = Window.partitionBy(*GROUP_COLS).orderBy("serial_number").rowsBetween(-(WINDOW_SIZE - 1), 0)

# Gom mảng và metadata (Min/Max/Size)
df_windowed = raw_data.withColumn("row_num", F.row_number().over(Window.partitionBy(*GROUP_COLS).orderBy("serial_number")))

for sensor_short, sensor_col in SENSOR_COLUMNS.items():
    df_windowed = df_windowed.withColumn(f"{sensor_short}_array", F.collect_list(sensor_col).over(sliding_spec))

df_windowed = df_windowed.withColumn("window_start_time", F.min("timestamp").over(sliding_spec)) \
                         .withColumn("window_end_time", F.col("timestamp")) \
                         .withColumn("window_start_serial", F.min("serial_number").over(sliding_spec)) \
                         .withColumn("window_end_serial", F.col("serial_number")) \
                         .withColumn("actual_window_size", F.size(f"{SENSOR_ORDER[0]}_array"))

for dim_col in DIMENSION_COLS:
    df_windowed = df_windowed.withColumn(f"{dim_col}_list", F.collect_set(dim_col).over(sliding_spec))

# [STEP 4] CHIẾN THUẬT QUYẾT ĐỊNH: LỌC SỚM & CACHE
print("\n[STEP 4] Reducing volume: Filtering Stride and full windows...")
# Chỉ giữ lại những window đủ 32 mẫu và nằm đúng vị trí Stride
# df_optimized = df_windowed.filter(
#     (F.col("actual_window_size") == WINDOW_SIZE) &
#     (F.col("row_num") % STRIDE == 0)
# ).cache()

df_optimized = df_windowed.filter(
    (F.col("actual_window_size") == WINDOW_SIZE) &
    (F.col("row_num") % STRIDE == 0)
)

# Trigger Action để đưa data vào RAM, làm phẳng DAG trước khi tính toán nặng
total_windows = df_optimized.count()
print(f"✅ Windows to process: {total_windows:,}")

# [STEP 5] TÍNH TOÁN FEATURE BẰNG PANDAS UDF
print("\n[STEP 5] Calculating features via Vectorized UDF...")
final_df = df_optimized
for sensor in SENSOR_ORDER:
    final_df = final_df.withColumn(f"{sensor}_struct", calculate_sensor_features_udf(F.col(f"{sensor}_array")))

# [STEP 6] SELECT VÀ ĐẶT TÊN CỘT (TRÁNH LỖI DUPLICATE COLUMN)
print("\n[STEP 6] Flattening and Renaming columns...")
final_df = final_df.withColumn("window_id", F.monotonically_increasing_id())

# Tạo mảng raw_values_array tổng hợp
sensor_arrays_cols = [F.col(f"{sensor}_array") for sensor in SENSOR_ORDER]
final_df = final_df.withColumn("raw_values_array", F.concat(*sensor_arrays_cols))

# Xây dựng danh sách Select cuối cùng
select_exprs = [F.col(c) for c in GROUP_COLS]
select_exprs.extend([F.col(f"{dim}_list") for dim in DIMENSION_COLS])
select_exprs.extend([
    "window_id", "window_start_time", "window_end_time",
    "window_start_serial", "window_end_serial", "raw_values_array"
])

# Truy cập từng field trong struct và gán alias {sensor}_{feature}
for sensor in SENSOR_ORDER:
    for feat in FEATURE_NAMES:
        select_exprs.append(F.col(f"{sensor}_struct.{feat}").alias(f"{sensor}_{feat}"))

final_output = final_df.select(*select_exprs)

# [STEP 7] LƯU DỮ LIỆU
print(f"\n[STEP 7] Saving to {OUTPUT_TABLE}...")
final_output.write.format("delta").mode("overwrite") \
            .option("overwriteSchema", "true") \
            .partitionBy("robot_code") \
            .saveAsTable(OUTPUT_TABLE)

print("\n" + "="*80)
print("✅ PIPELINE COMPLETED SUCCESSFULLY WITH OPTIMIZED DAG")
print("="*80)

result = spark.table(OUTPUT_TABLE)

display(result.count())