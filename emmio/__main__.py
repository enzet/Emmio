"""Emmio entry point."""

import asyncio
import getpass
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

from emmio.data import Data
from emmio.paths import EMMIO_DEFAULT_DIRECTORY
from emmio.ui import Interface, get_interface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


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

    arguments: Namespace = parser.parse_args(sys.argv[1:])

    interface: Interface = get_interface(arguments.interface)

    data_path: Path = (
        Path.home() / EMMIO_DEFAULT_DIRECTORY
        if arguments.data is None
        else Path(arguments.data)
    )
    data_path.mkdir(parents=True, exist_ok=True)

    data: Data = Data.from_directory(data_path)

    user_id: str

    match arguments.command:
        case "execute":
            from emmio.run import Emmio

            user_id = arguments.user if arguments.user else getpass.getuser()
            await Emmio(data_path, interface, data, user_id).process_command(
                arguments.single_command
            )

        case _:
            from emmio.run import Emmio

            user_id = arguments.user if arguments.user else getpass.getuser()
            await Emmio(data_path, interface, data, user_id).run()


def main() -> None:
    """Entry point."""

    asyncio.run(asynchronous_main())


if __name__ == "__main__":
    main()
