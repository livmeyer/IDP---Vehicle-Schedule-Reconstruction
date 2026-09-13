import itertools
from collections import defaultdict

import numpy as np
import pandas as pd
from gtfs_parser import GTFS

import Scheduler
from Configuration import Config
from Deadhead_Calculator import DeadheadDistanceLookup


def try_combining_routes(first_line: str, first_line_connection: str, second_line: str, second_line_connection: str, trips: pd.DataFrame,
                         dist_lookup: DeadheadDistanceLookup, config: Config, vehicles_per_line: dict[str, tuple[int, int]], gtfs: GTFS):
    # Find Connecting Points
    trips_first_line = trips[trips["route_id"] == first_line]
    trips_second_line = trips[trips["route_id"] == second_line]


    first_start: str = trips_first_line[(trips_first_line["parent_station"] == first_line_connection) & trips_first_line["start"]][
        "stop_id"].value_counts().idxmax()
    second_start: str = trips_second_line[(trips_second_line["parent_station"] == second_line_connection) & trips_second_line["start"]][
        "stop_id"].value_counts().idxmax()

    interline_deadhead_mapping: dict[str, dict[str, str]] = {
        first_line: {first_line_connection: second_start},
        second_line: {second_line_connection: first_start}
    }

    o, t, required_vehicles, non_service = Scheduler.schedule_tasks(
        pd.concat([trips_first_line, trips_second_line], ignore_index=True).sort_values("time"),
        0,
        config.minimumTerminal * 60,
        config.maximumTerminal * 60,
        dist_lookup,
        interline_deadhead_mapping
    )

    first_short_name = gtfs.routes[gtfs.routes["route_id"] == first_line]["route_short_name"].item()
    second_short_name = gtfs.routes[gtfs.routes["route_id"] == second_line]["route_short_name"].item()

    reduction_vehicles = vehicles_per_line[first_short_name][0] + vehicles_per_line[second_short_name][0] - required_vehicles
    reduction_noop_time = vehicles_per_line[first_short_name][1] + vehicles_per_line[second_short_name][1] - non_service
    if reduction_vehicles >= 0 and reduction_noop_time > 0:
        print(first_line, first_line_connection, " -> " , second_line, second_line_connection)
        print("Reduction: ",  reduction_vehicles)
        print("Reduction in Non Service Time: " ,  reduction_noop_time)
    return


def interlining(trips: pd.DataFrame, gtfs: GTFS, dist_lookup: DeadheadDistanceLookup, vehicles_per_line: dict[str, tuple[int, int]], config: Config):
    trips = trips.merge(gtfs.stops, on="stop_id")[
        ["stop_id", "route_id", "trip_id", "time", "start", "parent_station"]
    ]

    lines = defaultdict(list[str])
    stop_id_lines = defaultdict(list[str])

    for route_name in trips["route_id"].unique().__iter__():
        trips_on_route = trips[trips["route_id"] == route_name]
        sum_terminals = len(trips_on_route.index)
        if sum_terminals < 8:
            continue

        parent_stations_count = trips_on_route["parent_station"].value_counts()
        for parent_station in parent_stations_count[parent_stations_count == parent_stations_count.max()].index:
            lines[trips_on_route[trips_on_route["parent_station"] == parent_station]["parent_station"].max()].append(route_name)
            stop_id_lines[trips_on_route[trips_on_route["parent_station"] == parent_station]["stop_id"].max()].append(route_name)

    for stop, line_list in lines.items():
        for a, b in itertools.pairwise(line_list):
            try_combining_routes(a, stop, b, stop, trips, dist_lookup, config, vehicles_per_line, gtfs)

    deadheads = dist_lookup.construct_mat(list(stop_id_lines.keys()))
    deadheads = np.maximum(deadheads, deadheads.T)
    np.fill_diagonal(deadheads, np.inf)
    deadheads[np.triu_indices_from(deadheads, k=1)] = np.inf
    possible_combinations = np.argwhere(deadheads <= 300)

    for u, v in possible_combinations:
        stop_a = gtfs.stops[gtfs.stops["stop_id"] == list(stop_id_lines.keys())[u]]["parent_station"].item()
        stop_b = gtfs.stops[gtfs.stops["stop_id"] == list(stop_id_lines.keys())[v]]["parent_station"].item()
        for a in list(stop_id_lines.values())[u]:
            for b in list(stop_id_lines.values())[v]:
                if a != b:
                    try_combining_routes(a, stop_a, b, stop_b, trips, dist_lookup, config, vehicles_per_line, gtfs)