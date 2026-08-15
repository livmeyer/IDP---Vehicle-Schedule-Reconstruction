from collections import defaultdict
import csv
import heapq
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

#def assign_vehicles_on_route(target_routes: list(str)):


def build_schedule(
        trips: pd.DataFrame,
        deadhead_lookup: DeadheadDistanceLookup,
        gtfs,
        config: Config,
    ) -> pd.DataFrame:
    min_terminal_sec = config.minimumTerminal * 60
    max_terminal_sec = config.maximumTerminal * 60

    trips = trips.merge(gtfs.stops, on="stop_id")[
        ["stop_id", "route_id", "trip_id", "time", "start", "parent_station"]
    ]
    trips["time_sec"] = trips["time"].apply(time_to_seconds)

    route_map = gtfs.routes.set_index("route_id")["route_short_name"].to_dict()
    trips["route_short_name"] = trips["route_id"].map(route_map)

    vehicle_id_counter = 0
    vehicles_and_trips = defaultdict(list)
    total_nonservice_sec = 0

    vehicle_first_trip = {}
    vehicle_last_trip = {}

    # Target routes filter (hardcoded or dynamic)
    target_routes = {"185"}

    for route_name in target_routes:
        available_vehicles = defaultdict(list)
        assigned_vehicles = {}

        tasks_on_route = trips[trips["route_short_name"] == route_name].sort_values(
            "time_sec"
        )

        if len(tasks_on_route) < 8:
            continue

        for trip in tasks_on_route.itertuples():
            t_sec = trip.time_sec
            station = trip.parent_station

            if trip.start:
                matched_vehicle = None

                station_heap = available_vehicles[station]
                while station_heap and station_heap[0][1] < t_sec:
                    heapq.heappop(station_heap)

                # Check if there's a valid available vehicle
                if station_heap and station_heap[0][0] <= t_sec:
                    avail_time_sec, max_wait_sec, v_id = heapq.heappop(station_heap)
                    assigned_vehicles[trip.trip_id] = v_id
                    matched_vehicle = v_id
                    total_nonservice_sec += t_sec - avail_time_sec

                if matched_vehicle is None:
                    v_id = vehicle_id_counter
                    assigned_vehicles[trip.trip_id] = v_id
                    vehicle_id_counter += 1

                v_assigned = assigned_vehicles[trip.trip_id]
                vehicles_and_trips[v_assigned].append(trip.trip_id)

                if v_assigned not in vehicle_first_trip:
                    vehicle_first_trip[v_assigned] = trip

            else:
                ready_sec = t_sec + min_terminal_sec
                max_wait_sec = t_sec + max_terminal_sec
                v_id = assigned_vehicles.pop(trip.trip_id)

                heapq.heappush(available_vehicles[station], (ready_sec, max_wait_sec, v_id))

                vehicle_last_trip[v_id] = trip

    deadhead_rows = []

    for vehicle in range(vehicle_id_counter):
        if vehicle not in vehicle_first_trip:
            continue

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
        deadhead_end = deadhead_lookup.get_duration(depot, last_stop)

        total_nonservice_sec += min_terminal_sec + deadhead_begin + deadhead_end

        depart_trip_name = f"{vehicle}_fromDepot"
        return_trip_name = f"{vehicle}_toDepot"

        # Calculate exact seconds directly
        depot_depart_sec = first_time_sec - min_terminal_sec - int(deadhead_begin)
        station_arrive_sec = first_time_sec - min_terminal_sec
        depot_return_sec = last_time_sec + int(deadhead_end)

        deadhead_rows.extend([
            {
                "stop_id": depot,
                "route_id": first_route,
                "trip_id": depart_trip_name,
                "time": seconds_to_time(depot_depart_sec),
                "time_sec": depot_depart_sec,
                "start": True,
                "parent_station": "",
            },
            {
                "stop_id": first_stop,
                "route_id": first_route,
                "trip_id": depart_trip_name,
                "time": seconds_to_time(station_arrive_sec),
                "time_sec": station_arrive_sec,
                "start": False,
                "parent_station": "",
            },
            {
                "stop_id": last_stop,
                "route_id": last_route,
                "trip_id": return_trip_name,
                "time": seconds_to_time(last_time_sec),
                "time_sec": last_time_sec,
                "start": True,
                "parent_station": "",
            },
            {
                "stop_id": depot,
                "route_id": first_route,
                "trip_id": return_trip_name,
                "time": seconds_to_time(depot_return_sec),
                "time_sec": depot_return_sec,
                "start": False,
                "parent_station": "",
            },
        ])

        vehicles_and_trips[vehicle].extend([depart_trip_name, return_trip_name])

    if deadhead_rows:
        trips = pd.concat([trips, pd.DataFrame(deadhead_rows)], ignore_index=True)

    output_trips = trips.drop(columns=["time_sec", "route_short_name"], errors="ignore")

    output_trips.to_csv("sup_trips.csv", index=False)

    with open("sup_vehicleAssignments.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["vehicle_id", "trip_id"])
        for vehicle, tasks in vehicles_and_trips.items():
            for task in tasks:
                writer.writerow([vehicle, task])

    print(f"Total nonoperational time (seconds): {total_nonservice_sec} ({seconds_to_time(total_nonservice_sec)})")
    return trips