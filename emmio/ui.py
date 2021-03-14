"""
Emmio console user interface.

Author: Sergey Vartanov (me@enzet.ru).
"""

import os
import sys
import termios
import tty

from iso639 import languages

from emmio.language import decode_esperanto

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


def get_char() -> str:
    """
    Read character from user input.
    """
    file_descriptor = sys.stdin.fileno()
    settings = termios.tcgetattr(sys.stdin.fileno())
    try:
        tty.setraw(sys.stdin.fileno())
        character = sys.stdin.read(1)
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, settings)
    return character


def show(words, status=None, color=None, is_center=False):
    """
    Show text in the center of the screen.
    """
    words = words.split("\n")
    (width, height) = get_terminal_size()
    s = ""
    if status:
        s += status
        s += "\n"
    if is_center:
        s += int((height - len(words)) / 2 - 1) * "\n"
    max_word = max(words, key=lambda x: len(x))
    for word in words:
        if is_center:
            s += int((width / 2) - len(max_word) / 2) * " "
        if color:
            s += "\033[" + str(color) + "m"
        s += word + "\n"
        if color:
            s += "\033[0m"
    if is_center:
        s += int((height - len(words)) / 2 - 1) * "\n"
    sys.stdout.write(s)


ENTER = 13
ESCAPE = 27
BACKSPACE = 127


def get_word(right_word: str, language) -> str:

    sys.stdout.write(len(right_word) * "_")
    sys.stdout.write("\r")
    sys.stdout.flush()

    word: str = ""

    while True:
        char = get_char()

        if ord(char) == BACKSPACE:
            word = word[:-1]
        elif ord(char) == ESCAPE:
            word = ""
        elif ord(char) == ENTER:
            sys.stdout.write("\n")
            return word
        else:
            word += char

        sys.stdout.write("\r")
        sys.stdout.write("                    ")
        sys.stdout.write("\r")

        if language == languages.get(part1="eo"):
            word = decode_esperanto(word)

        sys.stdout.write(word + (len(right_word) - len(word)) * "_")
        sys.stdout.write("\r")
        if word == right_word:
            sys.stdout.write("\033[32m")
        sys.stdout.write(word)
        if word == right_word:
            sys.stdout.write("\033[0m")
        sys.stdout.flush()

        if word == right_word:
            sys.stdout.write("\n")
            return word


class Logger:
    """
    Log messages writer.
    """
    BOXES = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]

    def __init__(self):
        pass

    def write(self, message: str, color: str = None) -> None:
        """ Write text to the screen. """
        if color:
            print(colorize(message, color))
        else:
            print(message)

    def log(self, message: str) -> None:
        """ Write log message. """
        write(f"Info: {str(message)}.")

    def error(self, message) -> None:
        """ Write error message. """
        write(f"Error: {str(message)}.", "red")

    def warning(self, message) -> None:
        """ Write warning. """
        write(f"Warning: {str(message)}.", "yellow")

    def network(self, message) -> None:
        """ Write network operation message. """
        write(f"Network: {str(message)}.", "blue")

    def progress_bar(
            self, number: int, total: int, length: int = 20,
            step: int = 1000) -> None:

        if number == -1:
            print("%3s" % "100" + " % " + (length * "█") + "▏")
        elif number % step == 0:
            parts = length * 8
            p = number / float(total)
            l = int(p * parts)
            fl = int(l / 8)
            pr = int(l - fl * 8)
            print("%3s" % str(int(int(p * 1000) / 10)) + " % " + (fl * "█") +
                  self.BOXES[pr] + int(length - fl - 1) * " " + "▏")
            sys.stdout.write("\033[F")


class SilentLogger(Logger):
    """ Log that write normal messages and network operation messages. """

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
            self, number: int, total: int, length: int = 20,
            step: int = 1000) -> None:
        pass


logger = SilentLogger()


def write(message: str, color: str = None) -> None:
    """ Write message. """
    logger.write(message, color)


def log(message: str) -> None:
    logger.log(message)


def network(message: str) -> None:
    logger.network(message)


def warning(message: str) -> None:
    logger.warning(message)


def error(message: str) -> None:
    logger.error(message)


def progress_bar(number, total, length: int = 20, step: int = 1000) -> None:
    logger.progress_bar(number, total, length, step)


def set_log(class_):
    global logger
    logger = class_()


def get_terminal_size() -> (int, int):
    """
    Get size of the terminal in symbols and lines.

    :return: height (lines), width (symbols)
    """

    def ioctl_GWINSZ(fd):
        try:
            import fcntl, termios, struct, os
            cr = struct.unpack(
                "hh", fcntl.ioctl(fd, termios.TIOCGWINSZ, "1234"))
        except:
            return
        return cr

    cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)

    if not cr:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            cr = ioctl_GWINSZ(fd)
            os.close(fd)
        except:
            pass

    if not cr:
        cr = (os.environ.get("LINES", 25), os.environ.get("COLUMNS", 80))

    return int(cr[1]), int(cr[0])


def one_button(text: str) -> None:
    input(f"[{text}] ")


def header(text: str) -> None:
    print()
    print("    " + "─" * len(text))
    print("    " + text)
    print("    " + "─" * len(text))
    print()


def box(text) -> str:
    s = "┌─" + "─" * len(text) + "─┐\n"
    s += f"│ {text} │\n"
    s += "└─" + "─" * len(text) + "─┘"
    return s


class InputOutput:
    def __init__(self):
        pass

    def get(self) -> str:
        pass

    def put(self, message: str) -> None:
        pass


class TelegramIO(InputOutput):
    def __init__(self):
        super().__init__()

    def get(self) -> str:
        pass

    def put(self, message: str) -> None:
        pass


class TerminalIO(InputOutput):
    def __init__(self):
        super().__init__()

    def get(self) -> str:
        return input()

    def put(self, message: str) -> None:
        print(message)
