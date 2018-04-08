"""
Emmio console user interface.

Author: Sergey Vartanov (me@enzet.ru).
"""

import sys
import termios
import tty

import console


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
    return character


def show(words, status=None, color=None, is_center=False):
    """
    Show text in the center of the screen.
    """
    words = words.split('\n')
    (width, height) = console.getTerminalSize()
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

if __name__ == "__main__":
    get_word("test")
