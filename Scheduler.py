import csv
import heapq
from collections import defaultdict

import pandas as pd

from Configuration import Config
from Deadhead_Calculator import DeadheadDistanceLookup


def time_to_seconds(time_str: str) -> int:
    h, m, s = time_str.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def seconds_to_time(total_seconds: int) -> str:
    if total_seconds < 0:
        raise ValueError("Resulting time cannot be negative.")
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def schedule_tasks(tasks: pd.DataFrame, start_vehicle_id_counter: int, min_terminal_sec: int, max_terminal_sec: int,
                   deadhead_lookup: DeadheadDistanceLookup, interlining_mapping: dict[str, dict[str, str]] = {}
                   ) -> tuple[dict[str,int], list[dict[str, str | bool | int]], int, int]:
    available_vehicles: defaultdict[int, list[str]] = defaultdict(list)
    vehicles_and_trips: dict[str, int] = {}
    tasks["time_sec"] = tasks["time"].apply(time_to_seconds)
    assigned_vehicles = {}

    vehicle_id_counter = start_vehicle_id_counter
    non_service_sec = 0

    vehicle_first_trip = {}
    vehicle_last_trip = {}

    deadhead_interlining_rows: list[dict[str, str | bool | int]] = []

    for trip in tasks.itertuples():
        t_sec = trip.time_sec
        station = trip.parent_station

        if trip.start:
            matched_vehicle = None

            station_heap = available_vehicles[station]
            while station_heap and station_heap[0][1] < t_sec:
                heapq.heappop(station_heap)

            if station_heap and station_heap[0][0] <= t_sec:
                avail_time_sec, max_wait_sec, v_id = heapq.heappop(station_heap)
                assigned_vehicles[trip.trip_id] = v_id
                matched_vehicle = v_id
                non_service_sec += t_sec - avail_time_sec

            if matched_vehicle is None:
                v_id = vehicle_id_counter
                assigned_vehicles[trip.trip_id] = v_id
                vehicle_id_counter += 1

            v_assigned = assigned_vehicles[trip.trip_id]
            vehicles_and_trips[trip.trip_id] = v_assigned

            if v_assigned not in vehicle_first_trip:
                vehicle_first_trip[v_assigned] = trip

        else:
            if (trip.route_id in interlining_mapping) and (trip.parent_station in interlining_mapping[trip.route_id]):
                destination_id: str = interlining_mapping[trip.route_id][trip.parent_station]
                dh_time: int = deadhead_lookup.get_duration(trip.stop_id, destination_id)
                ready_sec = t_sec + dh_time
                max_wait_sec = t_sec + dh_time + max_terminal_sec
                non_service_sec += dh_time

                interlining_id: str = f"interlining_{trip.trip_id}"

                deadhead_interlining_rows.extend([
                    {
                        "stop_id": trip.stop_id,
                        "route_id": interlining_id,
                        "trip_id": trip.trip_id,
                        "time": seconds_to_time(t_sec),
                        "start": True
                    },
                    {
                        "stop_id": destination_id,
                        "route_id": interlining_id,
                        "trip_id": trip.trip_id,
                        "time": seconds_to_time(t_sec + dh_time),
                        "start": False,
                    }, ])
            else:
                ready_sec = t_sec + min_terminal_sec
                max_wait_sec = t_sec + max_terminal_sec
            v_id = assigned_vehicles.pop(trip.trip_id)

            heapq.heappush(available_vehicles[station], (ready_sec, max_wait_sec, v_id))

            vehicle_last_trip[v_id] = trip

    for vehicle in range(start_vehicle_id_counter, vehicle_id_counter):
        first_trip = vehicle_first_trip[vehicle]
        last_trip = vehicle_last_trip[vehicle]

        first_stop, first_route, first_time_sec = (
            first_trip.stop_id,
            first_trip.route_id,
            first_trip.time_sec,
        )
        last_stop, last_route, last_time_sec = (
            last_trip.stop_id,
            last_trip.route_id,
            last_trip.time_sec,
        )

        depot, deadhead_begin = deadhead_lookup.from_depot(first_stop)
        deadhead_end = deadhead_lookup.get_duration(last_stop, depot)

        non_service_sec += min_terminal_sec + deadhead_begin + deadhead_end

        depart_trip_name = f"{vehicle}_fromDepot"
        return_trip_name = f"{vehicle}_toDepot"

        depot_depart_sec = first_time_sec - min_terminal_sec - int(deadhead_begin)
        station_arrive_sec = first_time_sec - min_terminal_sec
        depot_return_sec = last_time_sec + int(deadhead_end)

        deadhead_interlining_rows.extend([
            {
                "stop_id": depot,
                "route_id": first_route,
                "trip_id": depart_trip_name,
                "time": seconds_to_time(depot_depart_sec),
                "start": True,
            },
            {
                "stop_id": first_stop,
                "route_id": first_route,
                "trip_id": depart_trip_name,
                "time": seconds_to_time(station_arrive_sec),
                "start": False,
            },
            {
                "stop_id": last_stop,
                "route_id": last_route,
                "trip_id": return_trip_name,
                "time": seconds_to_time(last_time_sec),
                "start": True,
            },
            {
                "stop_id": depot,
                "route_id": first_route,
                "trip_id": return_trip_name,
                "time": seconds_to_time(depot_return_sec),
                "start": False,
            },
        ])

        vehicles_and_trips[depart_trip_name] = vehicle
        vehicles_and_trips[return_trip_name] = vehicle

    return [vehicles_and_trips, deadhead_interlining_rows, vehicle_id_counter, non_service_sec]


def build_schedule(
        trips: pd.DataFrame,
        deadhead_lookup: DeadheadDistanceLookup,
        gtfs,
        config: Config
) -> dict[str, tuple[int, int]]:
    min_terminal_sec = config.minimumTerminal * 60
    max_terminal_sec = config.maximumTerminal * 60

    trips = trips.merge(gtfs.stops, on="stop_id")[
        ["stop_id", "route_id", "trip_id", "time", "start", "parent_station"]
    ]

    route_map = gtfs.routes.set_index("route_id")["route_short_name"].to_dict()
    trips["route_short_name"] = trips["route_id"].map(route_map)

    vehicle_id_counter = 0
    vehicles_and_trips: dict[str, int] = {}
    total_nonservice_sec = 0
    deadhead_rows: list[dict[str, str | bool | int]] = []
    route_vehicle_num: dict[str, tuple[int, int]] = {}

    for route_name in trips["route_short_name"].unique().__iter__():
        tasks_on_route = trips[trips["route_short_name"] == route_name].sort_values(
            "time"
        )
        if len(tasks_on_route) >= 8:
            vnt, dhr, vi, non_service_sec = schedule_tasks(tasks_on_route, vehicle_id_counter, min_terminal_sec, max_terminal_sec, deadhead_lookup)
            vehicles_and_trips.update(vnt)
            route_vehicle_num[route_name] = [vi - vehicle_id_counter, non_service_sec]
            vehicle_id_counter = vi
            deadhead_rows.extend(dhr)
            total_nonservice_sec += non_service_sec

    trips = pd.concat([trips.drop(columns=["time_sec", "route_short_name", "parent_station"], errors="ignore"), pd.DataFrame(deadhead_rows)],
                      ignore_index=True)

    trips = pd.merge(
        trips[trips["start"]][["stop_id", "route_id", "trip_id", "time"]]
        .rename(columns={"time": "departure_time", "stop_id": "start_terminal_id"}),

        trips[~trips["start"]][["stop_id", "trip_id", "time"]]
        .rename(columns={"time": "arrival_time", "stop_id": "arrival_terminal_id"}),

        on="trip_id",
        how="inner"
    )

    vehicle_assignment_df = pd.DataFrame(vehicles_and_trips.items(), columns=["trip_id", "vehicle_id"])
    trips = trips.merge(vehicle_assignment_df, on="trip_id", how="inner")

    trips.to_csv("sup_trips.csv", index=False)
    vehicle_assignment_df.to_csv("sup_vehicleAssignments.csv", index=False)


    print(f"Total nonoperational time (seconds): {total_nonservice_sec} ({seconds_to_time(total_nonservice_sec)})")
    return route_vehicle_num
