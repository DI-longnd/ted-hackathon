import pandas as pd

df = pd.read_csv('mock_robot_spray_data.csv')

print(df.groupby(["robot_code", "program_number", "start_time"]).size())

# print(df.sample)
