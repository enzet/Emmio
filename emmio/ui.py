"""Emmio console user interface."""

import sys
from typing import Any
import readchar

from rich import box
from rich.console import Console
from rich.padding import Padding as RichElementPadding
from rich.panel import Panel as RichElementPanel
from rich.table import Table as RichElementTable
from rich.text import Text as RichElementText

from emmio.language import Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

colors = {
    "gray": "2",
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


class Text:
    """Text element."""

    def __init__(self):
        self.elements: list[Any] = []

    def add(self, element: Any) -> "Text":
        """Chainable method to add element to the text."""
        self.elements.append(element)
        return self

    def is_empty(self) -> bool:
        """Check whether the text is empty."""
        return len(self.elements) == 0


class Formatted:
    """Formatted text element."""

    def __init__(self, text: Text, format: str):
        assert format in ["bold", "italic", "underline"]
        self.text: Text = text
        self.format: str = format


class Colorized:
    """Colorized text element."""

    def __init__(self, text: Text, color: str):
        self.text: Text = text
        self.color: str = color


class Block:
    """Block of text."""

    def __init__(self, text: Text, padding: tuple[int, int, int, int]):
        if text is None:
            raise Exception("Text is None")
        self.text: Text = text
        self.padding: tuple[int, int, int, int] = padding


class Title:
    """Title of the program."""

    def __init__(self, text: str):
        self.text: str = text


class Table:
    """Table of text."""

    def __init__(
        self,
        columns: list[Text | str],
        rows: list[list[Text | str]],
        style: str = "rounded",
    ) -> None:
        assert style in ["rounded"]
        self.style: str = style
        self.columns: list[Text | str] = columns
        self.rows: list[list[Text | str]] = rows

    def add_column(self, column: Text | str) -> None:
        self.columns.append(column)

    def add_row(self, row: list[Text | str]) -> None:
        self.rows.append(row)


class Interface:
    """User input/output interface."""

    def print(self, text) -> None:
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

    def button(self, text: str) -> None:
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
        self.console: Console = Console(highlight=False)

    def print(self, text) -> None:

        if isinstance(text, Text):
            for element in text.elements:
                self.print(element)

        else:
            rich_supported: Any = self.construct(text)
            self.console.print(rich_supported)

    def construct(self, element: Any) -> Any:
        """Construct rich element from text."""

        if isinstance(element, str):
            return element

        elif isinstance(element, Title):
            return RichElementPanel(self.construct(element.text))

        elif isinstance(element, Formatted):
            sub_element = self.construct(element.text)
            if not isinstance(sub_element, RichElementText):
                sub_element = RichElementText(sub_element)
            if element.format == "bold":
                sub_element.stylize("bold")
            elif element.format == "italic":
                sub_element.stylize("italic")
            elif element.format == "underline":
                sub_element.stylize("underline")
            return sub_element

        elif isinstance(element, Colorized):
            sub_element = self.construct(element.text)
            if isinstance(sub_element, RichElementText):
                sub_element.stylize(element.color)
                return sub_element
            else:
                rich_element: RichElementText = RichElementText(sub_element)
                rich_element.stylize(element.color)
                return rich_element

        elif isinstance(element, Block):
            return RichElementPadding(
                self.construct(element.text), element.padding
            )

        elif isinstance(element, Table):
            table: RichElementTable = RichElementTable()
            if element.style == "rounded":
                table.box = box.ROUNDED
            for column in element.columns:
                table.add_column(column)
            for row in element.rows:
                table.add_row(*row)
            return table

        elif isinstance(element, Text):
            result: RichElementText = RichElementText()
            for sub_element in element.elements:
                result.append(self.construct(sub_element))
            return result

        assert False, element

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

    def button(self, text: str) -> None:
        self.console.print(f"[b]<{text}>[/b]")
        get_char()


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
        self.console.print(RichElementPanel(text))

    def box(self, text: str) -> None:
        self.console.print(RichElementPanel(text))

    def print(self, text: str) -> None:
        self.console.print(RichElementPanel(text))
