import sys
import threading
from pathlib import Path

import telebot
from telebot.types import Message

from emmio.server import TelegramServer
from emmio.ui import set_log, Logger
from emmio.user_data import UserData


def main():
    set_log(Logger)

    data_path: Path = Path(sys.argv[1])
    user_id: str = sys.argv[2]
    token: str = sys.argv[3]

    user_data: UserData = UserData.from_directory(data_path, user_id)
    bot: telebot.TeleBot = telebot.TeleBot(token)
    server: TelegramServer = TelegramServer(user_data, bot)
    print(threading.get_ident())

    @bot.message_handler(commands=["start"])
    def start(message: Message):
        bot.send_message(message.chat.id, "Welcome to Emmio.")
        bot.register_next_step_handler(message, server.receive_message)
        server.id_ = message.chat.id
        server.step()

    bot.polling(none_stop=True)


if __name__ == "__main__":
    main()
