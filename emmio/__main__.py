"""Emmio entry point."""

import asyncio
import getpass
import logging
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

from emmio.data import Data
from emmio.ui import Interface, get_interface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

EMMIO_DEFAULT_DIRECTORY: str = ".emmio"


def get_default_output_directory() -> Path:
    """Get the default output directory, creating it if it doesn't exist."""
    (default_output_directory := Path("out")).mkdir(parents=True, exist_ok=True)
    return default_output_directory


async def asynchronous_main() -> None:
    """Emmio entry point."""

    parser: ArgumentParser = ArgumentParser("Emmio")
    parser.add_argument("--data", help="path to data directory")
    parser.add_argument("--user", help="user name")
    parser.add_argument(
        "--interface",
        help="interface type",
        choices=["terminal", "rich"],
        default="rich",
    )
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

    arguments: Namespace = parser.parse_args(sys.argv[1:])

    interface: Interface = get_interface(arguments.interface)

    data_path: Path = (
        Path.home() / EMMIO_DEFAULT_DIRECTORY
        if arguments.data is None
        else Path(arguments.data)
    )
    data_path.mkdir(parents=True, exist_ok=True)

    data: Data = Data.from_directory(data_path)
    logging.basicConfig(level=logging.DEBUG)

    user_id: str

    match arguments.command:
        case "server":
            from emmio.server import start as start_server  # type: ignore

            logging.basicConfig(level=logging.DEBUG)
            start_server(data, arguments)

        case "execute":
            from emmio.run import Emmio

            user_id = arguments.user if arguments.user else getpass.getuser()
            await Emmio(
                data_path,
                interface,
                data,
                user_id,
            ).process_command(arguments.single_command)

        case _:
            from emmio.run import Emmio

            user_id = arguments.user if arguments.user else getpass.getuser()
            await Emmio(
                data_path,
                interface,
                data,
                user_id,
            ).run()


def main() -> None:
    asyncio.run(asynchronous_main())


if __name__ == "__main__":
    main()
