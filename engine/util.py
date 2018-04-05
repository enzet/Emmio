# -*- coding: utf-8 -*- from __future__ import unicode_literals

"""
Utility functions for The Metro Project.

Author: Sergey Vartanov.
"""


colors = {
    'black': '30',
    'red': '31',
    'green': '32',
    'yellow': '33',
    'blue': '34',
    'magenta': '35',
    'cyan': '36',
    'white': '37',
    'fill_black': '40',
    'fill_red': '41',
    'fill_green': '42',
    'fill_yellow': '43',
    'fill_blue': '44',
    'fill_magenta': '45',
    'fill_cyan': '46',
    'fill_white': '47',
}


def color_by_altitude(altitude):
    elem = hex(255 - int(altitude / 70.0 * 255))[2:]
    if len(elem) == 1:
        elem = '0' + elem
    print(elem)
    return elem + elem + '00'


def get_rgb(color):
    return [int(color[:2], 16), int(color[2:4], 16), int(color[4:6], 16)]


def get_color(value, minimum, maximum, colors):
    coef = (value - minimum) / float(maximum - minimum)
    if coef > 1:
        coef = 1
    if coef < 0:
        coef = 0
    r = ''
    n = len(colors)
    m = int(coef * float(n - 1))
    color_1 = get_rgb(colors[m])
    color_2 = get_rgb(colors[m + 1])
    color_coef = (coef - m / float(n - 1)) * (n - 1)
    for i in range(3):
        s = color_1[i] + color_coef * (color_2[i] - color_1[i])
        k = hex(int(s))[2:]
        if len(k) == 1:
            k = '0' + k
        r += k
    return r


def colorize(text, color):
    return '\033[' + colors[color] + 'm' + text + '\033[0m'


def error(message):
    print(colorize('Error: ' + str(message) + '.', 'red'))


def warning(message):
    print(colorize('Warning: ' + str(message) + '.', 'yellow'))


def info(message):
    print('Info: ' + str(message) + '.')


def network(message):
    print(colorize('Network: ' + str(message) + '.', 'fill_blue'))


def debug(message):
    print(colorize(str(message), 'fill_yellow'))


def i2s(number, length):
    if len(str(number)) == length:
        return str(number)
    else:
        return '0' * (length - len(str(number))) + str(number)


def compare(string_1, string_2):
    return string_1 == string_2
