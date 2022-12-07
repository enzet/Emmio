import getpass
from argparse import Namespace
from dataclasses import dataclass
from datetime import timedelta, datetime
from enum import Enum
from pathlib import Path
from time import sleep
from typing import Optional

import telebot
import telebot.apihelper
from telebot import types
from telebot.types import Message

from emmio import ui, util
from emmio.data import Data
from emmio.language import construct_language
from emmio.learning.core import Learning
from emmio.learning.worker import LearningWorker
from emmio.lexicon.core import Lexicon
from emmio.sentence.database import SentenceDatabase
from emmio.ui import debug
from emmio.user_data import UserData
from emmio.util import format_delta
from emmio.worker import Worker

MAXIMUM_MESSAGE_SIZE: int = 512


class LexiconWorker(Worker):
    def __init__(self, lexicon: Lexicon) -> None:
        self.lexicon: Lexicon = lexicon

    def __lt__(self, other: "LexiconWorker") -> bool:
        pass

    def is_ready(self) -> bool:
        pass

    def do(self) -> None:
        pass


class ServerState(Enum):
    NOTHING = 0
    WORKER = 1
    ASKING = 2
    PROCESSING = 3


class EmmioServer:
    """Server for Emmio learning and testing processes."""

    def __init__(self, user_data: UserData):
        self.user_data: UserData = user_data

        sentence_db: SentenceDatabase = SentenceDatabase(
            user_data.path / "sentence.db"
        )
        frequency_db: FrequencyDatabase = FrequencyDatabase(
            user_data.path / "frequency.db"
        )
        learnings: list[Learning] = [
            user_data.get_course(x)
            for x in user_data.course_ids
            if user_data.get_course(x).is_learning
        ]

        self.learnings: list[LearningWorker] = [
            LearningWorker(
                learning,
                user_data.get_lexicon(construct_language(learning.subject)),
                user_data,
                Path("cache"),
                sentence_db,
                frequency_db,
            )
            for learning in learnings
        ]
        self.lexicons: list[LexiconWorker] = [
            # LexiconWorker(user_data.get_lexicon(x))
            # for x in user_data.get_lexicon_languages()
        ]
        self.id_: int = 0

        # Current state.

        self.worker: Optional[Worker] = None
        self.state: ServerState = ServerState.NOTHING

    def send(self, message: str):
        pass

    def receive(self, message: str):
        pass

    def status(self) -> None:
        if not self.id_:
            return
        if self.state == ServerState.ASKING:
            self.send("Waiting for answer.")
        elif self.state == ServerState.NOTHING:
            now: datetime = datetime.now()
            time_to_repetition: timedelta = (
                min(x.get_nearest() for x in self.data.courses.values()) - now
            )
            time_to_new: timedelta = util.day_end(now) - now

            if time_to_repetition < time_to_new:
                self.send(f"Repetition in {format_delta(time_to_repetition)}.")
            else:
                self.send(f"New question in {format_delta(time_to_new)}.")
        else:
            self.send("Alive.")

    def step(self, message: Optional[str] = None) -> str:
        """Return true if server is left in awaiting answer status."""

        if message == "/stop":
            return "stop"

        if message == "/stat":
            return "stat"

        if self.state == ServerState.NOTHING:

            if self.learnings and (
                (nearest := sorted(self.learnings)[0]).is_ready()
            ):
                self.worker = nearest
                self.send(nearest.get_greetings())
                self.state = ServerState.WORKER
                return ""

            elif self.lexicons and (
                (nearest := sorted(self.lexicons)[0]).is_ready()
            ):
                self.worker = nearest
                self.send(nearest.get_greetings())
                self.state = ServerState.WORKER
                return ""

            else:
                debug(f"{datetime.now()} Waiting...")
                sleep(60)
                return ""

        if self.state == ServerState.WORKER:
            if self.worker.is_ready():
                markup = types.ReplyKeyboardMarkup(
                    resize_keyboard=True, one_time_keyboard=True
                )
                markup.add(
                    types.KeyboardButton("Skip"),
                    types.KeyboardButton("Next sentence"),
                    types.KeyboardButton("Don't know"),
                )
                for text in self.worker.get_next_question():
                    self.send(text)
                self.state = ServerState.ASKING
                return "wait for answer"

            else:
                self.send("No more questions.")
                self.state = ServerState.NOTHING
                return ""

        if self.state == ServerState.ASKING:
            respond: str = self.worker.process_answer(message)
            if respond:
                self.send(respond)
                if respond.startswith("Right answer"):
                    sleep(1.5)
                elif respond.startswith("Right"):
                    sleep(0.4)

            self.state = ServerState.WORKER
            return ""

        assert False, "Unknown server state"


@dataclass
class TerminalMessage:
    text: str


class TerminalServer(EmmioServer):
    """Emmio server with command-line interface."""

    def __init__(self, data: Data, interface: ui.Interface):
        super().__init__(data)
        self.interface: ui.Interface = interface

    def send(self, message: str):
        self.interface.print(message)

    def statistics(self):
        interface = ui.StringInterface()
        self.data.get_stat(interface)
        self.send(interface.string)

    def receive_message(self, message: str):

        if message.startswith("/status"):
            self.status()
            return

        if message.startswith("/stat"):
            self.statistics()
            return

        while True:
            state: str = self.step(message)
            if state == "stop":
                break
            if state == "wait for answer":
                break

    def start(self):
        while True:
            self.receive_message(input("> "))


class TelegramServer(EmmioServer):
    """Emmio server for Telegram messenger."""

    def __init__(self, data: Data, bot: telebot.TeleBot) -> None:
        super().__init__(data)

        self.bot: telebot.TeleBot = bot

    def statistics(self):
        interface = ui.StringMarkdownInterface()
        self.data.get_stat(interface)
        self.send(interface.string)

    def send(self, message: str, markup=None):

        if len(message) > MAXIMUM_MESSAGE_SIZE:
            message = message[:MAXIMUM_MESSAGE_SIZE] + "..."

        try:
            self.bot.send_message(
                self.id_, message, parse_mode="Markdown", reply_markup=markup
            )
        except telebot.apihelper.ApiTelegramException:
            pass

    def receive_message(self, message: Message):

        print(f"Received {message.text}.")

        self.id_ = message.chat.id

        if message.text.startswith("/status"):
            self.status()
            return

        if message.text.startswith("/stat"):
            self.statistics()
            return

        while True:
            state: str = self.step(message.text)
            if state == "stop":
                break
            if state == "wait for answer":
                break


def start(data_path: Path, arguments: Namespace):
    if arguments.user:
        user_id: str = arguments.user
    else:
        user_id: str = getpass.getuser()

    data: Data = Data.from_directory(data_path, user_id)
    server: EmmioServer

    if arguments.mode == "messenger":
        ui.logger = ui.SilentLogger()
        server: TerminalServer = TerminalServer(
            data, ui.TerminalMessengerInterface()
        )
        server.start()

    elif arguments.mode == "terminal":
        ui.logger = ui.SilentLogger()
        server: TerminalServer = TerminalServer(data, ui.TerminalInterface())
        server.start()

    elif arguments.mode == "telegram":
        bot: telebot.TeleBot = telebot.TeleBot(arguments.token)
        server: TelegramServer = TelegramServer(data, bot)

        @bot.message_handler()
        def receive(message: Message):
            """Get current statistics."""
            server.receive_message(message)

        while True:
            try:
                bot.polling(non_stop=True)
            except Exception as e:
                print(e)
