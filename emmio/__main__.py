"""Emmio entry point."""
import sys
import threading
from pathlib import Path

import telebot
from telebot.types import Message

from emmio.server import TelegramServer
from emmio.ui import set_log, Logger
from emmio.user_data import UserData

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


def main():
    """Emmio entry point."""
    set_log(Logger)

    data_path: Path = Path(sys.argv[1])
    user_id: str = sys.argv[2]
    token: str = sys.argv[3]

    user_data: UserData = UserData.from_directory(data_path, user_id)
    bot: telebot.TeleBot = telebot.TeleBot(token)
    server: TelegramServer = TelegramServer(user_data, bot)

    @bot.message_handler(commands=["start"])
    def start(message: Message):
        """Start Emmio process."""
        server.start(message)

    @bot.message_handler(commands=["status"])
    def status(message: Message):
        """Start Emmio process."""
        server.status()

    @bot.message_handler(commands=["stat"])
    def stat(message: Message):
        """Start Emmio process."""
        server.statistics(message)

    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(e)
        main()


if __name__ == "__main__":
    main()
