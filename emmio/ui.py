"""Emmio console user interface."""

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, override

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

    lengths: list[int] = [len(x) for x in columns]
    for row in rows:
        for index in range(len(columns)):
            lengths[index] = max(lengths[index], len(row[index]))
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

    def __init__(self, text, format: str) -> None:
        assert format in ["bold", "italic", "underline"]
        self.text = text
        self.format: str = format


class Colorized:
    """Colorized text element."""

    def __init__(self, text, color: str) -> None:
        self.text = text
        self.color: str = color


class Block:
    """Block of text."""

    def __init__(self, text, padding: tuple[int, int, int, int]) -> None:
        if text is None:
            raise Exception("Text is None")
        self.text = text
        self.padding: tuple[int, int, int, int] = padding


@dataclass
class Title:
    """Title of the program."""

    text: str


@dataclass
class Header:
    """Header of a block."""

    text: str


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


class Interface(ABC):
    """User input/output interface."""

    def __init__(self, use_input: bool) -> None:
        self.use_input: bool = use_input

    @abstractmethod
    def print(self, text) -> None:
        """Simply print text message."""
        raise NotImplementedError()

    @abstractmethod
    def input(self, prompt: str) -> str:
        """Return user input."""
        raise NotImplementedError()

    @abstractmethod
    def get_char(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def get_word(
        self, right_word: str, alternative_forms: set[str], language: Language
    ) -> str:
        raise NotImplementedError()

    @abstractmethod
    def choice(
        self, options: list[tuple[str, str]], prompt: str | None = None
    ) -> str:
        """Return user choice from list of options.

        First option is assumed to be main and it's short key is also Enter.

        :param options: list of tuples of (option text, option short key)
        :param prompt: prompt to print before options
        """
        raise NotImplementedError()

    @abstractmethod
    def button(self, text: str) -> None:
        """Print button."""
        raise NotImplementedError()


class TerminalInterface(Interface):
    """Simple terminal interface with only necessary unicode characters."""

    def __init__(self, use_input: bool):
        super().__init__(use_input)

    def print(self, text) -> None:

        if isinstance(text, str):
            print(text)
        elif isinstance(text, Text):
            print(self.construct(text))
        elif isinstance(text, Title):
            print(self.construct(text.text))
        elif isinstance(text, Header):
            print(self.construct(text.text))
        elif isinstance(text, Block):
            print(self.construct(text.text))
        elif isinstance(text, Table):
            print(table(text.columns, text.rows))
        else:
            raise Exception(
                f"Unsuppoted text type in terminal interface `{type(text)}`."
            )

    def construct(self, element) -> str:
        if isinstance(element, str):
            return element
        elif isinstance(element, Text):
            result: str = ""
            for element in element.elements:
                result += self.construct(element)
            return result
        elif isinstance(element, Block):
            return "\n" + self.construct(element.text) + "\n"
        elif isinstance(element, Formatted):
            return self.construct(element.text)
        else:
            raise Exception(
                f"Unsuppoted text type in terminal interface `{type(element)}`."
            )

    @override
    def button(self, text: str) -> None:
        print(f"<{text}>")
        input()

    @override
    def input(self, prompt: str) -> str:
        return input(prompt)

    @override
    def get_char(self) -> str:
        return input() if self.use_input else get_char()

    @override
    def choice(
        self, options: list[tuple[str, str]], prompt: str | None = None
    ) -> str:

        if prompt is not None:
            self.print(prompt)
        self.print(
            " ".join(f"[{text} ({key.upper()})]" for text, key in options)
        )
        while True:
            char: str = self.get_char()
            if char == "":
                return options[0][0]
            for text, key in options:
                if key.upper() == char or key.lower() == char:
                    return text

    def get_word(
        self, right_word: str, alternative_forms: set[str], language: Language
    ) -> str:

        if self.use_input:
            return input()

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
    """Terminal interface with complex Unicode characters and colors."""

    def __init__(self, use_input: bool) -> None:
        super().__init__(use_input)
        self.console: Console = Console(highlight=False)
        self.use_input: bool = use_input

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

        elif isinstance(element, Header):
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

    def button(self, text: str) -> None:
        self.console.print(f"[b]<{text}>[/b]")
        self.get_char()


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


def get_interface(interface: str) -> Interface:
    match interface:
        case "terminal":
            return TerminalInterface(use_input=True)
        case "rich":
            return RichInterface(use_input=True)
        case _:
            raise ValueError(f"Unsupported interface: `{interface}`.")
