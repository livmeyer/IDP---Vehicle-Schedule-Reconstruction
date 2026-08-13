from collections import defaultdict
import csv
from datetime import timedelta
from gtfs_parser import GTFS
import pandas as pd

from Configuration import Config
from Deadhead_Calculator import DeadheadDistanceLookup

def parse_gtfs_time(time_str: str) -> timedelta:
    hours, minutes, seconds = map(int, time_str.split(":"))
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)

def format_gtfs_timedelta(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def add_minutes_to_gtfs_time(time_str: str, minutes_to_add: int = 5) -> str:
    td = parse_gtfs_time(time_str) + timedelta(minutes=minutes_to_add)
    return format_gtfs_timedelta(td)

def subtract_minutes_from_gtfs_time(time_str: str, minutes_to_subtract: int = 5) -> str:
    td = parse_gtfs_time(time_str) - timedelta(minutes=minutes_to_subtract)
    if td.total_seconds() < 0:
        raise ValueError(f"Resulting time would be negative: {time_str} minus {minutes_to_subtract} minutes")
    return format_gtfs_timedelta(td)

def build_schedule(trips: pd.DataFrame, deadhead_lookup: DeadheadDistanceLookup, gtfs: GTFS, config: Config) -> pd.DataFrame:
    # Extract unique route names
    route_names = (
        trips[["route_id"]]
        .drop_duplicates()
        .merge(gtfs.routes, on="route_id")[["route_id", "route_short_name"]]
    )

    vehicle_id_counter = 0
    vehicles_and_trips = defaultdict(list)

    # Enrich the input trips dataframe with station information
    trips = trips.merge(gtfs.stops, on="stop_id")[["stop_id", "route_id", "trip_id", "time", "start", "parent_station"]]

    for route in ["142", "54"]:  # route_names["route_short_name"].unique():
        available_vehicles = defaultdict(list)
        assigned_vehicles = {}

        route_ids_on_route = route_names[route_names["route_short_name"] == route]["route_id"]
        tasks_on_route = trips[trips["route_id"].isin(route_ids_on_route)].sort_values("time")

        if len(tasks_on_route) < 8:
            continue

        for trip in tasks_on_route.itertuples():
            if trip.start:
                matching_vehicle = None

                # Search for an available vehicle at the terminal station
                if available_vehicles[trip.parent_station]:
                    for vehicle, avail_time, max_wait in available_vehicles[trip.parent_station]:
                        if avail_time <= trip.time and trip.time <= max_wait:
                            assigned_vehicles[trip.trip_id] = vehicle
                            matching_vehicle = (vehicle, avail_time, max_wait)
                            break

                if matching_vehicle:
                    available_vehicles[trip.parent_station].remove(matching_vehicle)
                else:
                    # Create a new vehicle allocation
                    assigned_vehicles[trip.trip_id] = vehicle_id_counter
                    vehicle_id_counter += 1

                vehicles_and_trips[assigned_vehicles[trip.trip_id]].append(trip.trip_id)
            else:
                # Trip finishes: Return vehicle back to terminal station pool after cleanup buffer
                ready_time = add_minutes_to_gtfs_time(trip.time, config.minimumTerminal)
                max_wait = add_minutes_to_gtfs_time(trip.time, config.maximumTerminal)
                v_id = assigned_vehicles.pop(trip.trip_id)
                available_vehicles[trip.parent_station].append((v_id, ready_time, max_wait))

    # Deadheading Calculation Stage
    deadhead_rows = []

    for vehicle in range(vehicle_id_counter):
        vehicle_trips = trips[trips["trip_id"].isin(vehicles_and_trips[vehicle])]
        if vehicle_trips.empty:
            continue

        first_trip = vehicle_trips.iloc[vehicle_trips['time'] == vehicle_trips['time'].min()]
        last_trip = vehicle_trips[vehicle_trips['time'] == vehicle_trips['time'].max()]

        first_stop = first_trip['stop_id'].iloc[0]
        first_route = first_trip['route_id'].iloc[0]
        first_time = first_trip['time'].iloc[0]

        last_stop = last_trip['stop_id'].iloc[0]
        last_route = last_trip['route_id'].iloc[0]
        last_time = last_trip['time'].iloc[0]

        depot, deadhead_duration = deadhead_lookup.from_depot(first_stop)
        deadhead_minutes = int(deadhead_duration / 60)

        depart_trip_name = f"{vehicle}_fromDepot"
        return_trip_name = f"{vehicle}_toDepot"

        deadhead_rows.extend([
            {
                'stop_id': depot,
                'route_id': first_route,
                'trip_id': depart_trip_name,
                'time': subtract_minutes_from_gtfs_time(first_time, config.minimumTerminal + deadhead_minutes),
                'start': True,
                'parent_station': ''
            },
            {
                'stop_id': first_stop,
                'route_id': first_route,
                'trip_id': depart_trip_name,
                'time': subtract_minutes_from_gtfs_time(first_time, config.minimumTerminal),
                'start': False,
                'parent_station': ''
            },
            {
                'stop_id': last_stop,
                'route_id': last_route,
                'trip_id': return_trip_name,
                'time': last_time,
                'start': True,
                'parent_station': ''
            },
            {
                'stop_id': depot,
                'route_id': first_route,
                'trip_id': return_trip_name,
                'time': add_minutes_to_gtfs_time(last_time, int(deadhead_lookup.get_duration(depot, last_stop)/60)),
                'start': False,
                'parent_station': ''
            }
        ])

        # Track generated deadheads inside assignment structures
        vehicles_and_trips[vehicle].extend([depart_trip_name, return_trip_name])

    # Efficient batch append execution
    if deadhead_rows:
        trips = pd.concat([trips, pd.DataFrame(deadhead_rows)], ignore_index=True)

    # Output exports
    trips.to_csv("sup_trips.txt", index=False)

    with open("sup_vehicleAssignments.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for vehicle, tasks in vehicles_and_trips.items():
            for task in tasks:
                writer.writerow([vehicle, task])

    return trips