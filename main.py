import argparse
import gtfs_parser

import Configuration
import Deadhead_Calculator
import Depot_Parser
import Simple_Schedule
import Task_List_Builder


def print_message(message: str):
    print("\n--------------------------------------------------------------")
    print(message)
    print("--------------------------------------------------------------")


def create_schedule(config_path: str = 'config.json'):
    # Parse Config
    print_message("Reading Config")
    config = Configuration.load_config(config_path)
    print(config)

    # Parse GTFS
    print_message("Reading GTFS Archive")
    gtfs_data = gtfs_parser.GTFSFactory(config.gtfs_path)
    print(gtfs_data)

    # Parse Depots
    print_message("Reading Depots")
    depots = Depot_Parser.read_depot(config.depot_path)
    print(depots.head())

    # Identify Bus Tasks
    print_message("Identifying Bus Tasks")
    tasks = Task_List_Builder.build_task_list_no_block(gtfs_data, config.date, config.routeTypes)
    print(tasks.head())

    # Identify Deadheading Distances
    print_message("Calculate Deadheading Costs")
    deadhead_lookup = Deadhead_Calculator.calculate_all_deadheads(tasks, depots, gtfs_data, config.generateDeadheadMat, config.api_key,
                                                                 config.deadheadFile)

    # Construct Vehicle Schedule
    print_message("Calculating Vehicle Schedule")
    Simple_Schedule.build_schedule(tasks, deadhead_lookup, gtfs_data, config)
    Simple_Schedule.interlining(tasks, gtfs_data, deadhead_lookup)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='Vehicle Schedule Builder',
        description='A Program to reconstruct a possible Vehicle Schedule from GTFS Archive',
        epilog='TUM - Lehrstuhl für Verkehrstechnik - 2026')
    parser.add_argument('--generate-config', nargs='?', const='config.json', default=argparse.SUPPRESS,
                        help='Generate an empty config file to call; Defaults to "config.json"')
    parser.add_argument('--config', nargs='?', default='config.json',
                        help='Config file path; Defaults to "config.json"')
    args = parser.parse_args()

    if 'generate_config' in args:
        Configuration.Config.generate_config(
            args.generate_config if args.generate_config is not None else 'config.json')
    else:
        create_schedule(args.config)
