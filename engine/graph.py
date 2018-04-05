import sys, yaml
from datetime import datetime

def known(t, s, b):
    if not (t['plan'] in [1000000000, 2000000000]):
        if t['answers'][-1] == 'n':
            s[-1].append(b)
        else:
            p = len(t['answers']) - t['answers'].rfind('n') - 1
            if p > 9:
                p = 9
            s[p].append(b)


def dump_times(file_name, answers, scale=1):
    """
    Dump times diagram.

    :param file_name: output DOT file name
    :param answers: user answers
    :param scale: diagram scale (1 is for 1 day)
    """
    out = open(file_name, 'w+')

    s = {-1: []}
    for k in range(1, 20):
        s[k] = []

    now = (datetime.now() - datetime(1970, 1, 1)).total_seconds() / \
        60.0 / 60.0 / 24.0

    a = answers

    for k in a:
        known(a[k], s, max(0, int((a[k]['plan'] / 60.0 / 24.0 - now) * scale + 1)))

    keys = set([])
    for k in s:
        s[k].sort()
        s[k] = get_column(s[k])
        for key in s[k]:
            keys.add(key)

    if len(keys) < 3:
        keys = set({1, 2, 3})

    for key in range(max(keys) + 1):
        out.write(str(key) + ' ')
        for k in [-1, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
            if key in s[k]:
                out.write(str(s[k][key]) + ' ')
            else:
                out.write('0 ')
        out.write('\n')

    out.close()


def dump_times_all(file_name, answers, scale=1):
    """
    Dump times diagram.

    :param file_name: output DOT file name
    :param answers: user answers
    :param scale: diagram scale (1 is for 1 day)
    """
    out = open(file_name, 'w+')

    dictionary_names = ['dictionary/french_russian_fr_wiktionary', 'mueller7']

    data = {}
    for dictionary_name in dictionary_names:
        data[dictionary_name] = {}

    now = (datetime.now() - datetime(1970, 1, 1)).total_seconds() / \
        60.0 / 60.0 / 24.0

    intervals = set()

    for question in answers:
        for dictionary_name in dictionary_names:
            if question.startswith(dictionary_name):
                interval = max(0,
                    int((answers[question]['plan'] / 60.0 / 24.0 - now) \
                        * scale + 1))
                if interval in data[dictionary_name]:
                    data[dictionary_name][interval] += 1
                else:
                    data[dictionary_name][interval] = 1
                intervals.add(interval)

    for interval in intervals:
        out.write(str(interval) + ' ')
        for dictionary_name in dictionary_names:
            if interval in data[dictionary_name]:
                out.write(str(data[dictionary_name][interval]) + ' ')
            else:
                out.write('0 ')
        out.write('\n')

    out.close()


def get_column(t):
    if len(t) == 0:
        return {}
    result = {}
    previous = t[0]
    number = 1
    for a in t[1:]:
        if a == previous:
            number += 1
        else:
            result[previous] = number
            number = 1
            previous = a
    result[previous] = number
    return result


def dump_quality(file_name, answers, is_sum=False):
    out = open(file_name, 'w+')
    quality = {}
    # k = 0
    for question in answers:
        if 'answers' in answers[question]:
            vector = answers[question]['answers']
            if vector == 'y':
                continue
            know = vector[-1]
            if know == 'n':
                times = 1
            else:
                times = 1
                for letter in reversed(vector):
                    if letter != 'y':
                        break
                    else:
                        times += 1
            if is_sum and times < 3:
                continue
            if times in quality:
                quality[times] += 1
            else:
                quality[times] = 1
            if is_sum:
                for key in range(3, times):
                    if key in quality:
                        quality[key] += 1
                    else:
                        quality[key] = 1
    out.write('0 0\n')
    for key in range(1, max(list(quality.keys()) + [9]) + 1):
        if key in quality:
            out.write(str(key) + ' ' + str(quality[key]) + '\n')
        else:
            out.write(str(key) + ' 0\n')
    out.close()


def dump_hard_words(file_name, answers):
    out = open(file_name, 'w+')
    questions = sorted(answers.keys(), key=lambda x: -len(answers[x]['answers'].replace('y', '')) if 'answers' in answers[x] else 0)
    for question in questions[:15]:
        out.write(question + ' ' + str(len(answers[question]['answers'].replace('y', '')) if 'answers' in answers[question] else 0) + '\n')
    out.close()


