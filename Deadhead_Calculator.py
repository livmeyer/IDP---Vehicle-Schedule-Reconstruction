from collections import defaultdict


from gtfs_parser import GTFS
import numpy as np
from numpy.f2py.auxfuncs import throw_error
from openrouteservice import Client
import pandas as pd



class DeadheadDistanceLookup:
    def __init__(self, deadhead_mat, starting_stops: pd.Series, depot_stops: pd.Series, ending_stops: pd.Series):
        self.depots = depot_stops
        self.matrix = deadhead_mat
        all_stops = pd.concat([
            starting_stops,
            depot_stops,
            ending_stops
        ], ignore_index=True)
        self.stop_to_index = defaultdict(list)
        for idx, stop_id in enumerate(all_stops):
            self.stop_to_index[stop_id].append(idx)

    def from_depot(self, stop_id: str) -> tuple[str, float]:
        minTime = float("inf")
        dep = ""
        for depot in self.depots:
            time = self.get_duration(stop_id,depot)
            if time < minTime:
                minTime = time
                dep = depot

        if dep == "":
            print(self.stop_to_index[stop_id])
            throw_error("You Fucked Up")
        return dep, minTime

    def get_duration(self, origin_id, destination_id) -> float:
        try:
            from_idx = self.stop_to_index[origin_id][0]
            to_idx = self.stop_to_index[destination_id][-1]
            return self.matrix[from_idx, to_idx]

        except KeyError as e:
            raise KeyError(f"Stop ID {e} was not found in the compiled deadhead matrix.")


def calculate_all_deadheads(trips: pd.DataFrame, depots: pd.DataFrame, parsed_gtfs: GTFS, use_api: bool, api_key: str,
                            deadhead_filepath: str) -> DeadheadDistanceLookup:
    trips = (trips[['stop_id', 'start']].drop_duplicates()
             .merge(parsed_gtfs.stops[['stop_id', 'stop_lon', 'stop_lat']], on='stop_id'))
    startingPoints = trips[trips["start"]]
    endingPoints = trips[trips["start"] == False]

    if use_api:
        coords = list(pd.concat([
            startingPoints[["stop_lon", "stop_lat"]],
            depots[["stop_lon", "stop_lat"]],
            endingPoints[["stop_lon", "stop_lat"]],
        ], ignore_index=True).itertuples(index=False, name=None))

        xLen = len(startingPoints) + len(depots)
        yLen = len(endingPoints) + len(depots)

        # Construct Matrix of Deadheading Distances
        deadhead_mat = np.full((xLen, yLen), np.inf)
        ors_client = Client(key=api_key)
        for i in range(0, startingPoints.shape[0] + depots.shape[0], 50):
            for j in range(startingPoints.shape[0], len(coords), 50):
                continue
                resp = ors_client.distance_matrix(
                    locations=coords,
                    sources=list(range(i, min(len(coords), i + 50))),
                    destinations=list(range(j, min(len(coords), j + 50))),
                    metrics=["duration"],
                )
                xInd = i - xLen
                yInd = j - yLen
                deadhead_mat[xInd:min(deaheadMat.shape[0], xInd + 50), yInd::min(deadheadMat.shape[1], yInd + 50)] = resp['durations']
        np.savetxt(deadhead_filepath, deadhead_mat, delimiter=",")
    else:
        deadhead_mat = np.loadtxt(deadhead_filepath, delimiter=",")

    return DeadheadDistanceLookup(deadhead_mat, startingPoints['stop_id'], depots['stop_id'], endingPoints['stop_id'])
