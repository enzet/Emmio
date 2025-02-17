"""Emmio entry point."""

import asyncio
import getpass
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


def process_list_command(data, arguments):
    match arguments.subcommand:
        case "info":
            print("Frequency lists:")
            for key in data.get_lists_data().frequency_lists:
                print(f"    {key}")
            print("Word lists:")
            for key in data.get_lists_data().word_lists:
                print(f"    {key}")
        case "show":
            if list_ := data.get_list(arguments.id):
                print(list_.get_info())
            else:
                print("No such list.")


async def asynchronous_main():
    """Emmio entry point."""

    coloredlogs.install(
        level=logging.INFO,
        fmt="%(message)s",
        level_styles=dict(info=dict(color="yellow"), error=dict(color="red")),
    )

    parser: ArgumentParser = ArgumentParser("Emmio")
    parser.add_argument("--data", help="path to data directory")
    parser.add_argument("--user", help="user name")
    parser.add_argument(
        "--use-input",
        help="use `input()` function instead of `getchar()`",
        action="store_true",
    )

    subparser = parser.add_subparsers(dest="command", required=False)

    # Command `execute`.
    execute_parser: ArgumentParser = subparser.add_parser(
        "execute", help="run single Emmio command"
    )
    execute_parser.add_argument("single_command")

    # Command `server`.
    server_parser: ArgumentParser = subparser.add_parser(
        "server", help="run Emmio server"
    )
    server_parser.add_argument("--user", help="user name")
    server_parser.add_argument("--mode", help="server mode", default="terminal")
    server_parser.add_argument("--token", help="Telegram messenger token")

    # Command `dictionary <language 1> <language 2>`.
    dictionary_parser: ArgumentParser = subparser.add_parser(
        "dictionary", help="translate words"
    )
    dictionary_parser.add_argument("language_1", help="first language")
    dictionary_parser.add_argument("language_2", help="second language")

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

    if arguments.data:
        data_path = Path(arguments.data)
    else:
        data_path: Path = Path.home() / EMMIO_DEFAULT_DIRECTORY

    data_path.mkdir(parents=True, exist_ok=True)

    data: Data = Data.from_directory(data_path)

    match arguments.command:
        case "server":
            from emmio.server import start

            logging.basicConfig(level=logging.DEBUG)
            start(data, arguments)

        case "dictionary":
            from emmio.dictionary.ui import start

            start(data, arguments)

        case "list":
            process_list_command(data, arguments)

        case "execute":
            from emmio.run import Emmio

            user_id: str = (
                arguments.user if arguments.user else getpass.getuser()
            )
            robot: Emmio = Emmio(
                data_path,
                RichInterface(arguments.use_input),
                data,
                user_id,
            )
            await robot.process_command(arguments.single_command)

        case _:
            from emmio.run import Emmio

            user_id: str = (
                arguments.user if arguments.user else getpass.getuser()
            )
            robot: Emmio = Emmio(
                data_path,
                RichInterface(arguments.use_input),
                data,
                user_id,
            )
            await robot.run()


def main() -> None:
    asyncio.run(asynchronous_main())


if __name__ == "__main__":
    sys.exit(main())
