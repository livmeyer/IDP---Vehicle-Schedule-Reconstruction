import pandas as pd

def read_depot(file_path: str) -> pd.DataFrame:
    depots_df = pd.read_csv(file_path)
    depots_df["stop_lon"] = depots_df["stop_lon"].astype(float)
    depots_df["stop_lat"] = depots_df["stop_lat"].astype(float)
    return depots_df