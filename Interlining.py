import itertools
from collections import defaultdict

import numpy as np
import pandas as pd
from gtfs_parser import GTFS

import Scheduler
from Configuration import Config
from Deadhead_Calculator import DeadheadDistanceLookup


def try_combining_routes(first_line: str, first_line_connection: str, second_line: str, second_line_connection: str, trips: pd.DataFrame,
                         dist_lookup: DeadheadDistanceLookup, config: Config, vehicles_per_line: dict[str, tuple[int, int]], gtfs: GTFS) -> tuple[
    dict[str, int], list[dict[str, str | bool | int]], int, int]:
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

    trips_vehicle_dict, trip_list, required_vehicles, non_service = Scheduler.schedule_tasks(
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

    return trips_vehicle_dict, trip_list, reduction_vehicles, reduction_noop_time


def interlining(trips: pd.DataFrame, gtfs: GTFS, dist_lookup: DeadheadDistanceLookup, vehicles_per_line: dict[str, tuple[int, int]], config: Config):
    trips = trips.merge(gtfs.stops, on="stop_id")[
        ["stop_id", "route_id", "trip_id", "time", "start", "parent_station"]
    ]

    # trips = trips[trips["route_id"].isin(["3-142-G-016-1", "3-142-G-016-2", "3-54-G-016-2", "3-54-G-016-3", "3-54-G-016-4"])]

    lines = defaultdict(list[str])
    stop_id_lines = defaultdict(list[str])

    tested_Combinations: list[tuple[str, str, dict[str, int], list[dict[str, str | bool | int]], int, int]] = []

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
            tnv, tr, rv, rt = try_combining_routes(a, stop, b, stop, trips, dist_lookup, config, vehicles_per_line, gtfs)
            if rv >= 0 and rt > 0:
                tested_Combinations.append((a, b, tnv, tr, rv, rt))

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
                    tnv, tr, rv, rt = try_combining_routes(a, stop_a, b, stop_b, trips, dist_lookup, config, vehicles_per_line, gtfs)
                    if rv > 0 and rt > 0:
                        tested_Combinations.append((a, b, tnv, tr, rv, rt))

    tested_Combinations = sorted(tested_Combinations, reverse=True, key=lambda x: (x[4], x[5]))

    filtered_Combinations: list[tuple[str, str, dict[str, int], list[dict[str, str | bool | int]], int, int]] = []
    used_lines = []
    for r1, r2, u1, u2, u3, u4 in tested_Combinations:
        if r1 not in used_lines and r2 not in used_lines:
            filtered_Combinations.append((r1, r2, u1, u2, u3, u4))
            used_lines.append(r1)
            used_lines.append(r2)
            print(f"Accepted line: {r1} <--> {r2}")
