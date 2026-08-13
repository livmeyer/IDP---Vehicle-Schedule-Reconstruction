import datetime

import pandas as pd
from gtfs_parser import GTFS


def build_task_list_no_block(gtfs_data: GTFS, schedule_date: datetime.date, route_types: list[str]) -> pd.DataFrame:
    # Filter bus routes
    bus_route_ids = gtfs_data.routes.loc[gtfs_data.routes["route_type"].isin(route_types), "route_id"]

    # Filter trips
    bus_trips = gtfs_data.trips.loc[gtfs_data.trips["route_id"].isin(bus_route_ids), ["route_id", "trip_id", "block_id", "service_id"]]

    # Filter by Date
    if gtfs_data.calendar is not None and gtfs_data.calendar_dates is not None:
        relevant_services = gtfs_data.calendar[
            (gtfs_data.calendar[schedule_date.strftime("%A").lower()] == "1") &
            (gtfs_data.calendar["start_date"] <= schedule_date.strftime("%Y%m%d")) &
            (gtfs_data.calendar["end_date"] >= schedule_date.strftime("%Y%m%d"))
            ].merge(
            gtfs_data.calendar_dates[
                (gtfs_data.calendar_dates["date"] == schedule_date.strftime("%Y%m%d")) &
                (gtfs_data.calendar_dates["exception_type"] == "2")
                ],
            on="service_id",
            how="left_anti"
        )
        relevant_services = pd.concat([
            relevant_services,
            gtfs_data.calendar_dates[
                (gtfs_data.calendar_dates["date"] == schedule_date.strftime("%Y%m%d")) &
                (gtfs_data.calendar_dates["exception_type"] == "1")
            ]["service_id"]
        ])
        bus_trips = bus_trips.merge(relevant_services, on="service_id", how="inner")

    # Get Relevant Stop Times
    stop_times = gtfs_data.stop_times[["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]]
    st = stop_times.merge(bus_trips, on="trip_id", how="inner")

    # Sort sequentially by trip and stop sequence to cleanly locate endpoints
    st_sorted = st.sort_values(["trip_id", "stop_sequence"])

    first_stops = (st_sorted.groupby("trip_id", as_index=False).first()
                   [["route_id", "trip_id", "arrival_time", "stop_id"]]
                   .rename(columns={"arrival_time": "time"}))
    first_stops["start"] = True

    last_stops = (st_sorted.groupby("trip_id", as_index=False).last()
                  [["route_id", "trip_id", "departure_time", "stop_id"]]
                  .rename(columns={"departure_time": "time"}))
    last_stops["start"] = False

    trip_data = pd.concat([first_stops, last_stops], ignore_index=True)
    return trip_data
