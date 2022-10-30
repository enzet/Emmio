import getpass
from argparse import Namespace
from pathlib import Path

import telebot
from telebot.types import Message

from emmio import ui
from emmio.server import EmmioServer, TerminalServer, TelegramServer
from emmio.user_data import UserData


def start(data_path: Path, arguments: Namespace):
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
