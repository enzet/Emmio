"""
Emmio console user interface.
"""

import sys
import termios
import tty

from rich import box
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from emmio.language import Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

colors = {
    "grey": "2",
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "fill_black": "40",
    "fill_red": "41",
    "fill_green": "42",
    "fill_yellow": "43",
    "fill_blue": "44",
    "fill_magenta": "45",
    "fill_cyan": "46",
    "fill_white": "47",
}


def colorize(text: str, color: str):
    if color in colors:
        return f"\033[{colors[color]}m{text}\033[0m"
    else:
        return text


class Interface:
    """
    User input/output interface.
    """

    def print(self, text: str) -> None:
        """Simply print text message."""
        raise NotImplementedError()

    def header(self, text: str) -> None:
        """Print header."""
        raise NotImplementedError()

    def input(self, prompt: str) -> str:
        """Return user input."""
        raise NotImplementedError()

    def get_word(
        self, right_word: str, alternative_forms: set[str], language: Language
    ) -> str:
        raise NotImplementedError()

    def table(self, columns: list[str], rows: list[list[str]]) -> None:
        """
        Add table.  Length of `columns` should be equal of length of each
        element of `rows`.
        """
        raise NotImplementedError()

    def colorize(self, text: str, color: str) -> str:
        return text

    def box(self, message: str) -> None:
        self.print(message)

    def run(self) -> None:
        pass

    def stop(self) -> None:
        pass


class TerminalInterface(Interface):
    def header(self, message: str) -> None:
        pass

    def run(self) -> None:
        pass

    def print(self, message: str) -> None:
        print(message)

    def input(self, prompt: str) -> str:
        return input(prompt)

    def box(self, text: str) -> None:
        s = "┌─" + "─" * len(text) + "─┐\n"
        s += f"│ {text} │\n"
        s += "└─" + "─" * len(text) + "─┘"
        self.print(s)

    def table(self, columns: list[str], rows: list[list[str]]) -> None:
        lengths: list[int] = [
            max(len(row[i]) for row in rows) for i in range(len(columns))
        ]
        self.print(
            " ".join(columns[i].ljust(lengths[i]) for i in range(len(columns)))
        )
        for row in rows:
            self.print(
                " ".join(row[i].ljust(lengths[i]) for i in range(len(columns)))
            )

    def colorize(self, text: str, color: str):
        if color in colors:
            return f"\033[{colors[color]}m{text}\033[0m"
        else:
            return text

    def get_word(
        self, right_word: str, alternative_forms: set[str], language: Language
    ) -> str:
        sys.stdout.write(len(right_word) * "_")
        sys.stdout.write("\r")
        sys.stdout.flush()

        word: str = ""

        def is_right() -> bool:
            return word == right_word

        while True:
            char: str = get_char()

            if ord(char) == BACKSPACE:
                word = word[:-1]
            elif ord(char) == ESCAPE:
                word = ""
            elif ord(char) == ENTER:
                sys.stdout.write("\n")
                return word
            else:
                word += char

            sys.stdout.write("\r                    \r")

            word = language.decode_text(word)

            sys.stdout.write(word + (len(right_word) - len(word)) * "_" + "\r")
            if is_right():
                sys.stdout.write("\033[32m")
            if word in alternative_forms:
                sys.stdout.write("\033[33m")
            sys.stdout.write(word)
            if is_right() or word in alternative_forms:
                sys.stdout.write("\033[0m")
            sys.stdout.flush()

            if is_right():
                sys.stdout.write("\n")
                return word


class RichInterface(TerminalInterface):
    def __init__(self):
        self.console = Console()

    def print(self, text: str) -> None:
        print(text)

    def header(self, text: str) -> None:
        self.console.print(Panel(text))

    def box(self, text: str) -> None:
        self.console.print(Panel(text, expand=False))

    def table(self, columns: list[str], rows: list[list[str]]) -> None:

        show_footer: bool = rows[-1][0] == "Total"

        table: Table = Table(box=box.ROUNDED, show_footer=show_footer)
        for index, column in enumerate(columns):
            table.add_column(
                column, footer=rows[-1][index] if show_footer else ""
            )
        for row in rows[:-1] if show_footer else rows:
            table.add_row(*row)

        self.console.print(table)


def get_char() -> str:
    """Read character from user input."""
    file_descriptor = sys.stdin.fileno()
    settings = termios.tcgetattr(sys.stdin.fileno())
    try:
        tty.setraw(sys.stdin.fileno())
        character = sys.stdin.read(1)
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, settings)
    return character


BOXES: str = " ▏▎▍▌▋▊▉"
BOXES_LENGTH: int = len(BOXES)


def progress(a: int) -> str:
    return ((a // 8) * "█") + BOXES[a % 8]


ENTER: int = 13
ESCAPE: int = 27
BACKSPACE: int = 127


class Logger:
    """
    Log messages writer.
    """

    def __init__(self):
        pass

    def write(self, message: str, color: str = None) -> None:
        """Write text to the screen."""
        print(
            TerminalInterface().colorize(message, color) if color else message
        )

    def log(self, message: str) -> None:
        """Write log message."""
        write(f"Info: {str(message)}.")

    def error(self, message) -> None:
        """Write error message."""
        write(f"Error: {str(message)}.", "red")

    def warning(self, message) -> None:
        """Write warning."""
        write(f"Warning: {str(message)}.", "yellow")

    def network(self, message) -> None:
        """Write network operation message."""
        write(f"Network: {str(message)}.", "blue")

    def progress_bar(
        self,
        number: int,
        total: int,
        length: int = 20,
        step: int = 1000,
        text: str = "",
    ) -> None:
        """
        Draw progress bar using Unicode symbols.

        :param number: current value
        :param total: maximum value
        :param length: progress bar length.
        :param step: frequency of progress bar updating (assuming that numbers go
            subsequently)
        :param text: short description
        """
        if number == -1:
            sys.stdout.write(f"100 % {length * '█'}▏{text}\n")
        elif number % step == 0:
            ratio: float = number / total
            parts: int = int(ratio * length * BOXES_LENGTH)
            fill_length: int = int(parts / BOXES_LENGTH)
            box: str = BOXES[int(parts - fill_length * BOXES_LENGTH)]
            sys.stdout.write(
                f"{str(int(int(ratio * 1000.0) / 10.0)):>3} % "
                f"{fill_length * '█'}{box}"
                f"{int(length - fill_length - 1) * ' '}▏{text}\n\033[F"
            )


class SilentLogger(Logger):
    """Log that write normal messages and network operation messages."""

    def __init__(self):
        super().__init__()

    def write(self, message: str, color: str = None) -> None:
        super().write(message, color)

    def log(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def network(self, message: str) -> None:
        super().network(message)

    def progress_bar(
        self, number: int, total: int, length: int = 20, step: int = 1000
    ) -> None:
        pass


# Logging

logger: Logger = SilentLogger()


def write(message: str, color: str = None) -> None:
    """Write message."""
    logger.write(message, color)


def log(message: str) -> None:
    logger.log(message)


def network(message: str) -> None:
    logger.network(message)


def warning(message: str) -> None:
    logger.warning(message)


def error(message: str) -> None:
    logger.error(message)


def progress_bar(
    number: int, total: int, length: int = 20, step: int = 1000
) -> None:
    logger.progress_bar(number, total, length, step)


def set_log(class_):
    global logger
    logger = class_()
