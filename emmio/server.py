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
from emmio.learning.worker import LearningWorker
from emmio.lexicon.core import Lexicon
from emmio.sentence.database import SentenceDatabase
from emmio.ui import debug
from emmio.user_data import UserData
from emmio.util import format_delta

MAXIMUM_MESSAGE_SIZE: int = 512
HIDE_SYMBOL: str = "░"


class Worker:
    """Any learning or checking worker."""

    def __lt__(self, other: "Worker") -> bool:
        raise NotImplementedError()

    def is_ready(self) -> bool:
        """Check if worker has next message to send."""
        pass

    @staticmethod
    def get_greetings() -> str:
        """Return greetings to tell that worker is ready."""
        return "Hello."

    def get_next_question(self) -> list[str]:
        """Return list of next messages."""
        pass

    def process_answer(self, message) -> str:
        """Process user response."""
        pass


class LexiconWorker(Worker):
    def __init__(self, lexicon: Lexicon):
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


class Server:
    def send(self, message: str):
        pass

    def receive(self, message: str):
        pass


class EmmioServer(Server):
    """Server for Emmio learning and testing processes."""

    def __init__(self, user_data: UserData):
        self.user_data = user_data

        sentence_db: SentenceDatabase = SentenceDatabase(
            user_data.path / "sentence.db"
        )
        self.learnings: list[LearningWorker] = [
            LearningWorker(
                user_data.get_course(x), user_data, Path("cache"), sentence_db
            )
            for x in user_data.course_ids
            if user_data.get_course(x).is_learning
        ]
        self.lexicons: list[LexiconWorker] = [
            LexiconWorker(user_data.get_lexicon(x))
            for x in user_data.get_lexicon_languages()
        ]
        self.id_: int = 0

        # Current state.

        self.worker: Optional[Worker] = None
        self.state: ServerState = ServerState.NOTHING

    def status(self) -> None:
        if not self.id_:
            return
        if self.state == ServerState.ASKING:
            self.send("Waiting for answer.")
        elif self.state == ServerState.NOTHING:
            now: datetime = datetime.now()
            time_to_repetition: timedelta = (
                min(x.get_nearest() for x in self.user_data.courses.values())
                - now
            )
            time_to_new: timedelta = util.day_end(now) - now

            if time_to_repetition < time_to_new:
                self.send(f"Repetition in {format_delta(time_to_repetition)}.")
            else:
                self.send(f"New question in {format_delta(time_to_new)}.")
        else:
            self.send("Alive.")

    def step(self, message: Optional[str] = None) -> bool:

        if self.state == ServerState.NOTHING:

            if self.learnings and (
                (nearest := sorted(self.learnings)[0]).is_ready()
            ):
                self.worker = nearest
                self.send(nearest.get_greetings())
                self.state = ServerState.WORKER
                return False

            elif self.lexicons and (
                (nearest := sorted(self.lexicons)[0]).is_ready()
            ):
                self.worker = nearest
                self.send(nearest.get_greetings())
                self.state = ServerState.WORKER
                return False

            else:
                debug(f"{datetime.now()} Waiting...")
                sleep(60)
                return False

        if self.state == ServerState.WORKER:
            if self.worker.is_ready():
                markup = types.ReplyKeyboardMarkup(
                    row_width=2,
                    resize_keyboard=True,
                    one_time_keyboard=True,
                )
                markup.add(
                    types.KeyboardButton("Skip"),
                    types.KeyboardButton("Don't know"),
                )
                for text in self.worker.get_next_question():
                    self.send(text)
                self.state = ServerState.ASKING
                return True

            else:
                self.send("No more questions.")
                self.state = ServerState.NOTHING
                return False

        if self.state == ServerState.ASKING:
            respond: str = self.worker.process_answer(message)
            if respond:
                self.send(respond)
                if respond.startswith("Right answer"):
                    sleep(1.5)
                elif respond.startswith("Right"):
                    sleep(0.4)

            self.state = ServerState.WORKER
            return False

        assert False, "Unknown server state"


class TerminalServer(EmmioServer):
    """Emmio server with command-line interface."""

    def __init__(self, user_data: UserData, interface: ui.Interface):
        super().__init__(user_data)
        self.interface: ui.Interface = interface

    def send(self, message: str):
        self.interface.print(message)

    def start(self):
        while True:
            is_waiting_for_answer: bool = self.step()
            if is_waiting_for_answer:
                a = input("> ")
                self.receive(a)


class TelegramServer(EmmioServer):
    """Emmio server for Telegram messenger."""

    def __init__(self, user_data: UserData, bot: telebot.TeleBot) -> None:
        super().__init__(user_data)

        self.bot: telebot.TeleBot = bot

    def send(self, message: str, markup=None):

        if len(message) > MAXIMUM_MESSAGE_SIZE:
            message = message[:MAXIMUM_MESSAGE_SIZE] + "..."

        try:
            self.bot.send_message(self.id_, message, reply_markup=markup)
        except telebot.apihelper.ApiTelegramException:
            pass

    def receive_message(self, message: Message):
        self.id_ = message.chat.id

        if message.text.startswith("/status"):
            self.status()
            return

        if message.text.startswith("/stat"):
            self.statistics(message)
            return

        while True:
            is_waiting_for_answer: bool = self.step(message.text)
            if is_waiting_for_answer:
                break

    def statistics(self, message: Message):
        self.send(message.text)
