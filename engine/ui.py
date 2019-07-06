"""
Emmio console user interface.

Author: Sergey Vartanov (me@enzet.ru).
"""

import sys
import termios
import tty

import engine.console


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
    (width, height) = engine.console.getTerminalSize()
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
        
        # print(char, "<", ord(char), ">")
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
    BOXES = [' ', '▏', '▎', '▍', '▌', '▋', '▊', '▉']

    def __init__(self):
        pass

    def write(self, message: str):
        print(message)

    def progress_bar(self, number, total, length: int=20, step: int=1000):
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
    def __init__(self):
        super().__init__()

    def write(self, message: str):
        super().write(message)

    def progress_bar(self, number, total, length: int=20, step: int=1000):
        super().progress_bar(number, total, length, step)


class SilentLogger(Logger):
    def __init__(self):
        super().__init__()

    def write(self, message: str):
        pass

    def progress_bar(self, number, total, length: int=20, step: int=1000):
        pass


log = SilentLogger()


def write(message: str):
    log.write(message)


def progress_bar(number, total, length: int=20, step: int=1000):
    log.progress_bar(number, total, length, step)


def set_log(class_):
    global log
    log = class_()


if __name__ == "__main__":
    get_word("test")
