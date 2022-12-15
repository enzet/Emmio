"""Emmio console user interface."""

import sys
import termios
import tty

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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


def table(columns: list[str], rows: list[list[str]]) -> str:

    result: str = ""

    lengths: list[int] = [
        max(len(row[i]) for row in rows) + 1 for i in range(len(columns))
    ]
    result += (
        " ".join(columns[i].ljust(lengths[i]) for i in range(len(columns)))
        + "\n"
    )
    for row in rows:
        result += (
            " ".join(row[i].ljust(lengths[i]) for i in range(len(columns)))
            + "\n"
        )

    return result


class Interface:
    """User input/output interface."""

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


class StringInterface(Interface):
    def __init__(self):
        self.string: str = ""

    def print(self, text: str) -> None:
        self.string += text + "\n"

    def header(self, text: str) -> None:
        self.string += text + "\n"

    def input(self, prompt: str) -> str:
        pass

    def get_word(
        self, right_word: str, alternative_forms: set[str], language: Language
    ) -> str:
        pass

    def table(self, columns: list[str], rows: list[list[str]]) -> None:
        self.string += table(columns, rows)


class StringMarkdownInterface(StringInterface):
    def __init__(self):
        super().__init__()

    def table(self, columns: list[str], rows: list[list[str]]) -> None:
        self.string += "```\n" + table(columns, rows) + "```\n"


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
        self.print(table(columns, rows))

    def colorize(self, text: str, color: str):
        if color in colors:
            return f"\033[{colors[color]}m{text}\033[0m"
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

            buffer: str = "\r                    \r"

            word = language.decode_text(word)

            buffer += word + (len(right_word) - len(word)) * "_" + "\r"
            if is_right():
                buffer += "\033[32m"
            if word in alternative_forms:
                buffer += "\033[33m"
            buffer += word
            if is_right() or word in alternative_forms:
                buffer += "\033[0m"

            if is_right():
                buffer += "\n"

            sys.stdout.write(buffer)
            sys.stdout.flush()

            if is_right():
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

    def colorize(self, text: str, color: str):
        return text


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


def progress_bar(
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
    :param step: frequency of progress bar updating (assuming that numbers
        go subsequently)
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


class TelegramInterface(Interface):
    def print(self, text: str) -> None:
        pass

    def header(self, text: str) -> None:
        pass

    def input(self, prompt: str) -> str:
        pass

    def get_word(
        self, right_word: str, alternative_forms: set[str], language: Language
    ) -> str:
        pass

    def table(self, columns: list[str], rows: list[list[str]]) -> None:
        pass


class TerminalMessengerInterface(TerminalInterface):
    def __init__(self):
        self.console: Console = Console()

    def header(self, text: str) -> None:
        self.console.print(Panel(text))

    def box(self, text: str) -> None:
        self.console.print(Panel(text))

    def print(self, text: str) -> None:
        self.console.print(Panel(text))
