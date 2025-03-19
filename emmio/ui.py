"""Emmio console user interface."""

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self, override

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

RichCompatible = (
    RichElementText | RichElementPanel | RichElementTable | RichElementPadding
)

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


def table(columns: list[str], rows: list[list[str]]) -> str:
    """Draw table with simple text."""

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


class Element:
    """Interface element."""


class InlineElement(Element):
    """Inline element.

    Inline elements may be concatenated into one string. Inline elements cannot
    contain block elements.
    """


class BlockElement(Element):
    """Block element.

    Block elements may contain inline elements, but not other block elements.
    """


class Text(InlineElement):
    """Text element."""

    def __init__(self, text: str | InlineElement | None = None):
        self.elements: list[InlineElement | str] = (
            [] if text is None else [text]
        )

    def add(self, element: InlineElement | str) -> Self:
        """Chainable method to add element to the text."""
        self.elements.append(element)
        return self

    def is_empty(self) -> bool:
        """Check whether the text is empty."""
        return len(self.elements) == 0


@dataclass
class Formatted(InlineElement):
    """Formatted text element."""

    text: InlineElement | str
    format_: str

    def __post_init__(self) -> None:
        assert self.format_ in ["bold", "italic", "underline"]


@dataclass
class Colorized(InlineElement):
    """Colorized text element."""

    text: InlineElement | str
    color: str


@dataclass
class Block(BlockElement):
    """Block of text."""

    text: InlineElement | str
    padding: tuple[int, int, int, int]


@dataclass
class Title(BlockElement):
    """Title of the program."""

    text: InlineElement | str


@dataclass
class Header(BlockElement):
    """Header of a block."""

    text: InlineElement | str


class Table(BlockElement):
    """Table of text."""

    def __init__(
        self,
        columns: list[InlineElement | str],
        rows: list[list[InlineElement | str]],
        style: str = "rounded",
    ) -> None:
        assert style in ["rounded"]
        self.style: str = style
        self.columns: list[InlineElement | str] = columns
        self.rows: list[list[InlineElement | str]] = rows

    def add_column(self, column: InlineElement | str) -> None:
        """Add column header to the table."""
        self.columns.append(column)

    def add_row(self, row: list[InlineElement | str]) -> None:
        """Add row to the table."""
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
        """Return user input character."""
        raise NotImplementedError()

    @abstractmethod
    def get_word(
        self, right_word: str, alternative_forms: set[str], language: Language
    ) -> str:
        """Return user input word and check it against the right word.

        :param right_word: right word
        :param alternative_forms: set of alternative forms of the right word
        :param language: language of the word
        """
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

    def print(self, text: Element | str) -> None:
        print(self.construct(text))

    def construct(self, element: Element | str) -> str:
        """Construct string from element."""

        if isinstance(element, str):
            return element

        if isinstance(element, Text):
            result: str = ""
            for sub_element in element.elements:
                result += self.construct(sub_element)
            return result

        # Ignore block margins in terminal interface.
        if isinstance(element, Block):
            return self.construct(element.text)

        # Ignore colors and formatting in terminal interface.
        if isinstance(element, (Formatted, Colorized, Title, Header)):
            return self.construct(element.text)

        if isinstance(element, Table):
            columns: list[str] = []
            rows: list[list[str]] = []
            for column in element.columns:
                columns.append(self.construct(column))
            for row in element.rows:
                rows.append([self.construct(cell) for cell in row])
            return table(columns, rows)

        raise ValueError(
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

    @staticmethod
    def get_option(text: str, key: str) -> Text:
        """Get text of an option."""
        return Text().add(f"[{key.upper()}] {text}")

    @override
    def choice(
        self, options: list[tuple[str, str]], prompt: str | None = None
    ) -> str:

        if prompt is not None:
            self.print(prompt)

        options_text: Text = Text()
        for index, (text, key) in enumerate(options):
            options_text.add(self.get_option(text, key))
            if index < len(options) - 1:
                options_text.add("  ")

        self.print(options_text)
        while True:
            char: str = self.get_char()
            if char == "":
                return options[0][0]
            for text, key in options:
                if key.upper() == char or key.lower() == char:
                    return text

    @override
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

            buffer: str = "\r" + (len(word) + 1) * " " + "\r"

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

    def print(self, text: Element | str) -> None:
        self.console.print(self.construct_rich(text))

    def construct_rich(self, element: Element | str) -> RichCompatible | str:
        """Construct rich element from text."""

        if isinstance(element, str):
            return element

        if isinstance(element, Text):
            result: RichElementText = RichElementText()
            for sub_element in element.elements:
                result.append(self.construct(sub_element))
            return result

        if isinstance(element, Title):
            return RichElementPanel(self.construct(element.text))

        if isinstance(element, Header):
            return RichElementPanel(self.construct(element.text))

        if isinstance(element, Formatted):
            sub_element = self.construct(element.text)
            wrapped: RichElementText

            if isinstance(sub_element, RichElementText):
                wrapped = sub_element
            else:
                wrapped = RichElementText(sub_element)

            match element.format_:
                case "bold":
                    wrapped.stylize("bold")
                case "italic":
                    wrapped.stylize("italic")
                case "underline":
                    wrapped.stylize("underline")

            return wrapped

        if isinstance(element, Colorized):
            sub_element = self.construct(element.text)
            if isinstance(sub_element, RichElementText):
                sub_element.stylize(element.color)
                return sub_element
            rich_element: RichElementText = RichElementText(sub_element)
            rich_element.stylize(element.color)
            return rich_element

        if isinstance(element, Block):
            return RichElementPadding(
                self.construct(element.text), element.padding
            )

        if isinstance(element, Table):
            rich_table: RichElementTable = RichElementTable()
            if element.style == "rounded":
                rich_table.box = box.ROUNDED
            for column in element.columns:
                rich_table.add_column(self.construct(column))
            for row in element.rows:
                rich_table.add_row(*[self.construct(cell) for cell in row])
            return rich_table

        assert False, element

    @override
    @staticmethod
    def get_option(text: str, key: str) -> Text:
        """Get text of an option."""
        return Text().add(Formatted(key.upper(), "bold")).add(" ").add(text)

    def button(self, text: str) -> None:
        self.console.print(f"[b]<{text}>[/b]")
        self.get_char()


def get_char() -> str:
    """Read character from user input."""
    return readchar.readkey()


BOXES: str = " ▏▎▍▌▋▊▉"
BOXES_LENGTH: int = len(BOXES)


def progress(a: int) -> str:
    """Draw progress bar with Unicode characters."""
    return ((a // 8) * "█") + BOXES[a % 8]


ENTER: int = 13
ESCAPE: int = 27
BACKSPACE: int = 127


def get_interface(interface: str) -> Interface:
    """Get interface by its identifier."""

    match interface:
        case "terminal":
            return TerminalInterface(use_input=True)
        case "rich":
            return RichInterface(use_input=True)
        case _:
            raise ValueError(f"Unsupported interface: `{interface}`.")
