"""Emmio entry point."""
import logging
from argparse import Namespace, ArgumentParser
import sys
from pathlib import Path

from emmio.ui import set_log, Logger

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

EMMIO_DEFAULT_DIRECTORY: str = ".emmio"


def main():
    """Emmio entry point."""
    set_log(Logger)

    parser: ArgumentParser = ArgumentParser("Emmio")
    subparser = parser.add_subparsers(dest="command")

    # Server.

    server_parser: ArgumentParser = subparser.add_parser("server")

    server_parser.add_argument("--data", help="path to data directory")
    server_parser.add_argument("--user", help="user name")
    server_parser.add_argument(
        "--mode",
        help="server mode",
        default="terminal",
    )
    server_parser.add_argument("--token", help="Telegram messenger token")

    # Frequency list parser.

    frequency_parser: ArgumentParser = subparser.add_parser("frequency")

    frequency_parser.add_argument("--data", help="path to data directory")
    frequency_parser.add_argument("--input", help="input text file path")
    frequency_parser.add_argument(
        "--id", help="output frequency list identifier"
    )
    frequency_parser.add_argument("--language", help="language code")

    arguments: Namespace = parser.parse_args(sys.argv[1:])

    data_path: Path = Path.home() / EMMIO_DEFAULT_DIRECTORY
    if arguments.data:
        data_path = Path(arguments.data)
    data_path.mkdir(parents=True, exist_ok=True)

    if arguments.command == "server":
        from emmio.entry import start

        start(data_path, arguments)

    elif arguments.command == "frequency":
        from emmio.text import construct_frequency_list

        construct_frequency_list(arguments)

    else:
        logging.fatal(f"Unknown command `{arguments.command}`.")


if __name__ == "__main__":
    main()
