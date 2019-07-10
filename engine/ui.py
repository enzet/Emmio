"""
Emmio console user interface.

Author: Sergey Vartanov (me@enzet.ru).
"""

import os
import sys
import termios
import tty


def get_char():
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
    if ord(character) == 13:
        return "Enter"
    return character


def show(words, status=None, color=None, is_center=False):
    """
    Show text in the center of the screen.
    """
    words = words.split('\n')
    (width, height) = get_terminal_size()
    s = ''
    if status:
        s += status
        s += '\n'
    if is_center:
        s += int((height - len(words)) / 2 - 1) * '\n'
    max_word = max(words, key=lambda x: len(x))
    for word in words:
        if is_center:
            s += int((width / 2) - len(max_word) / 2) * ' '
        if color:
            s += '\033[' + str(color) + 'm'
        s += word + '\n'
        if color:
            s += '\033[0m'
    if is_center:
        s += int((height - len(words)) / 2 - 1) * '\n'
    sys.stdout.write(s)


ENTER = 13
ESCAPE = 27
BACKSPACE = 127


def get_word(right_word):
    word = ""

    result = 'wrong'

    while True:
        char = get_char()
        
        if ord(char) == BACKSPACE:
            word = word[:-1]
        elif ord(char) == ESCAPE:
            break
        elif ord(char) == ENTER:
            break
        else:
            word += char
        
        sys.stdout.write("                    ")
        sys.stdout.write("\r")
        if word == right_word:
            sys.stdout.write("\033[32m")
        sys.stdout.write(word)
        if word == right_word:
            sys.stdout.write("\033[0m")
        sys.stdout.flush()

        if word == right_word:
            result = 'right'
            break
        if word == "\\skip":
            result = 'skip'
            break
        if word == "\\quit":
            result = 'quit'
            break

    return result


class Logger:
    """
    Log messages writer.
    """
    BOXES = [' ', '▏', '▎', '▍', '▌', '▋', '▊', '▉']

    def __init__(self) -> None:
        pass

    def write(self, message: str) -> None:
        print(message)

    def progress_bar(self, number: int, total: int, length: int=20,
            step: int=1000) -> None:

        if number == -1:
            print('%3s' % '100' + ' % ' + (length * '█') + '▏')
        elif number % step == 0:
            parts = length * 8
            p = number / float(total)
            l = int(p * parts)
            fl = int(l / 8)
            pr = int(l - fl * 8)
            print('%3s' % str(int(int(p * 1000) / 10)) + ' % ' + (fl * '█') +
                self.BOXES[pr] + int(length - fl - 1) * ' ' + '▏')
            sys.stdout.write("\033[F")


class VerboseLogger(Logger):
    """
    Log that writes all messages.
    """
    def __init__(self) -> None:
        super().__init__()

    def write(self, message: str) -> None:
        super().write(message)

    def progress_bar(self, number: int, total: int, length: int=20,
            step: int=1000) -> None:
        super().progress_bar(number, total, length, step)


class SilentLogger(Logger):
    """
    Log that does nothing.
    """
    def __init__(self):
        super().__init__()

    def write(self, message: str) -> None:
        pass

    def progress_bar(self, number: int, total: int, length: int=20,
            step: int=1000) -> None:
        pass


log = SilentLogger()


def write(message: str) -> None:
    """
    Write message.
    """
    log.write(message)


def progress_bar(number, total, length: int=20, step: int=1000) -> None:
    log.progress_bar(number, total, length, step)


def set_log(class_):
    global log
    log = class_()


def get_terminal_size() -> (int, int):
    """
    Get size of the terminal in symbols and lines.

    :return: height (lines), width (symbols)
    """
    env = os.environ

    def ioctl_GWINSZ(fd):
        try:
            import fcntl, termios, struct, os
            cr = struct.unpack('hh', fcntl.ioctl(fd, termios.TIOCGWINSZ, '1234'))
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
        cr = (env.get('LINES', 25), env.get('COLUMNS', 80))

    return int(cr[1]), int(cr[0])


if __name__ == "__main__":
    get_word("test")
