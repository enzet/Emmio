"""Emmio entry point."""
import argparse
import getpass
import sys
from pathlib import Path

import telebot
from telebot.types import Message

from emmio import ui
from emmio.server import TelegramServer, TerminalServer, EmmioServer
from emmio.ui import set_log, Logger
from emmio.user_data import UserData

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

EMMIO_DEFAULT_DIRECTORY: str = ".emmio"


def main():
    """Emmio entry point."""
    set_log(Logger)

    parser: argparse.ArgumentParser = argparse.ArgumentParser("Emmio")
    parser.add_argument("--data", help="path to data directory")
    parser.add_argument("--user", help="user name")
    parser.add_argument("--mode", help="interface mode")
    parser.add_argument("--token", help="Telegram messenger token")
    arguments: argparse.Namespace = parser.parse_args(sys.argv[1:])

    data_path: Path = Path.home() / EMMIO_DEFAULT_DIRECTORY
    if arguments.data:
        data_path = Path(arguments.data)
    data_path.mkdir(parents=True, exist_ok=True)

    user_id: str = getpass.getuser()
    if arguments.user:
        user_id: str = arguments.user

    user_data: UserData = UserData.from_directory(data_path, user_id)
    server: EmmioServer

    if arguments.mode == "messenger":
        ui.logger = ui.SilentLogger()
        server: TerminalServer = TerminalServer(
            user_data, ui.TerminalMessengerInterface()
        )
        server.start()

    elif arguments.mode == "terminal":
        ui.logger = ui.SilentLogger()
        server: TerminalServer = TerminalServer(
            user_data, ui.TerminalInterface()
        )
        server.start()

    elif arguments.mode == "telegram":
        bot: telebot.TeleBot = telebot.TeleBot(arguments.token)
        server: TelegramServer = TelegramServer(user_data, bot)

        @bot.message_handler()
        def receive(message: Message):
            """Get current statistics."""
            server.receive_message(message)

        while True:
            try:
                bot.polling(non_stop=True)
            except Exception as e:
                print(e)


if __name__ == "__main__":
    main()
