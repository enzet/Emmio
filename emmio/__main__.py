"""Emmio entry point."""
import logging
import sys
from argparse import Namespace, ArgumentParser
from pathlib import Path

import coloredlogs as coloredlogs

from emmio.data import Data
from emmio.ui import RichInterface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

EMMIO_DEFAULT_DIRECTORY: str = ".emmio"


def main():
    """Emmio entry point."""

    coloredlogs.install(level=logging.DEBUG, fmt="%(message)s")

    parser: ArgumentParser = ArgumentParser("Emmio")
    parser.add_argument("--data", help="path to data directory")

    subparser = parser.add_subparsers(dest="command")

    # Command `learn`.
    learn_parser: ArgumentParser = subparser.add_parser(
        "learn", help="start learning process"
    )

    learn_parser.add_argument("--user", help="user name")

    # Command `server`.
    server_parser: ArgumentParser = subparser.add_parser(
        "server", help="run Emmio server"
    )

    server_parser.add_argument("--user", help="user name")
    server_parser.add_argument("--mode", help="server mode", default="terminal")
    server_parser.add_argument("--token", help="Telegram messenger token")

    # Commands for frequency and word lists.

    # Command `list <command>`.
    list_parser: ArgumentParser = subparser.add_parser(
        "list", help="manipulating frequency and word lists"
    )
    list_subparser = list_parser.add_subparsers(dest="subcommand")

    # Command `list info`.
    list_subparser.add_parser("info", help="information about loaded lists")

    # Command `list show <id>`.
    list_show_parser: ArgumentParser = list_subparser.add_parser("show")
    list_show_parser.add_argument("id")

    # Command `list add <id>`.
    list_add_parser: ArgumentParser = list_subparser.add_parser("add")
    list_add_parser.add_argument("id")
    list_add_parser.add_argument("--input", help="input text file path")
    list_add_parser.add_argument(
        "--id", help="output frequency list identifier"
    )
    list_add_parser.add_argument("--language", help="language code")

    # Old interface.

    run_parser: ArgumentParser = subparser.add_parser("run")

    run_parser.add_argument("--user", help="user name")

    arguments: Namespace = parser.parse_args(sys.argv[1:])

    data_path: Path = Path.home() / EMMIO_DEFAULT_DIRECTORY
    if arguments.data:
        data_path = Path(arguments.data)
    data_path.mkdir(parents=True, exist_ok=True)

    data: Data = Data.from_directory(data_path)

    match arguments.command:

        case "server":
            from emmio.server import start

            logging.basicConfig(level=logging.DEBUG)
            start(data, arguments)

        case "list":
            match arguments.subcommand:
                case "info":
                    print("Frequency lists:")
                    for key in data.lists.frequency_lists:
                        print(f"    {key}")
                    print("Word lists:")
                    for key in data.lists.word_lists:
                        print(f"    {key}")
                case "show":
                    if list_ := data.get_list(arguments.id):
                        print(list_.get_info())
                    else:
                        print("No such list.")

        case "run":
            from emmio.main import Emmio

            robot: Emmio = Emmio(
                data_path, RichInterface(), data, arguments.user
            )
            robot.run()

        case _:
            logging.fatal(f"Unknown command `{arguments.command}`.")


if __name__ == "__main__":
    main()
