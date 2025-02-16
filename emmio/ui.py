"""Emmio console user interface."""

import sys
import readchar

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


def button():
    pass


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
        """Add table.  Length of `columns` should be equal of length of each
        element of `rows`.
        """
        raise NotImplementedError()

    def colorize(self, text: str, color: str) -> str:
        return text

    def box(self, message: str) -> None:
        self.print(message)

    def run(self) -> None:
        raise NotImplementedError()

    def stop(self) -> None:
        raise NotImplementedError()

    def choice(self, options: list[str], prompt: str | None = None) -> str:
        raise NotImplementedError()


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
        print(message)

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
        self.console.print(text)

    def header(self, text: str) -> None:
        self.console.print(Panel(text))

    def box(self, text: str) -> None:
        self.console.print(Panel(text, expand=False))

    def table(self, columns: list[str], rows: list[list[str]]) -> None:
        show_footer: bool = rows and rows[-1][0] == "Total"

        element: Table = Table(box=box.ROUNDED, show_footer=show_footer)
        for index, column in enumerate(columns):
            element.add_column(
                column, footer=rows[-1][index] if show_footer else ""
            )
        for row in rows[:-1] if show_footer else rows:
            element.add_row(*row)

        self.console.print(element)

    def colorize(self, text: str, color: str):
        if color in colors:
            return f"[{color}]{text}[/{color}]"
        return text

    def choice(self, options: list[str], prompt: str | None = None) -> str:
        self.console.print(
            ((prompt + " ") if prompt else "")
            + " ".join(f"\\[{x}]" for x in options)
        )
        while True:
            char: str = input()
            for option in options:
                if not option:
                    raise RuntimeError()
                for c in option:
                    if "A" <= c <= "Z":
                        break
                if c.lower() == char:
                    return option.lower()


def get_char() -> str:
    """Read character from user input."""
    return readchar.readkey()


BOXES: str = " ▏▎▍▌▋▊▉"
BOXES_LENGTH: int = len(BOXES)


def progress(a: int) -> str:
    return ((a // 8) * "█") + BOXES[a % 8]


ENTER: int = 13
ESCAPE: int = 27
BACKSPACE: int = 127


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
