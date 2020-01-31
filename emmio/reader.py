# -*- coding: utf-8 -*- from __future__ import unicode_literals

import json
import yaml

from emmio.util import error


def read_priority(file_name):
    priority_list = []
    priority_list_file = open(file_name)
    line = priority_list_file.readline()
    while len(line) > 3:
        pr = int(line[line.find(': ') + 2:])
        if pr > 0:
            k = [line[:line.find(': ')], pr]
            priority_list.append(k)
        line = priority_list_file.readline()
    return priority_list


def read_answers_fast(file_name):
    answers = {}
    input_file = open(file_name)
    line = None
    read = False
    dictionary_name = None
    while line != '':
        line = input_file.readline()
        if line == '':
            break
        if line[0] != ' ':
            dictionary_name = line[:-2]
            answers[dictionary_name] = {}
        else:
            element = \
                {'last': int(line[line.find('last: 2') + 6:line.find(', plan')]),
                 'plan': int(line[line.find('plan: ', 10) + 6:line.find('}')])}

            answers_position = line.find('answers:')
            if answers_position != -1:
                element['answers'] = \
                    line[answers_position + 9:line.find(',', answers_position)]

            added_position = line.find('added:')
            if added_position != -1:
                element['added'] = \
                    int(line[added_position + 7:line.find(',', added_position)])

            key = line[2:line.find(':')]

            if key[0] == "'":
                key = key[1:-1]

            answers[dictionary_name][key] = element
    return answers


def read_dict(file_name, format='dict'):
    """
    Construct dictionary with key and values as Unicode strings.

    :param file_name: dictionary file name.
    :param format: dictionary file format (dict or yaml).

    :return parsed dictionary as Python dict structure.
    """
    dictionary = {}

    if format == 'dict':
        key, value = '', ''
        with open(file_name) as file:
            lines = file.readlines()
            if file_name == 'mueller7.dict':
                for line in lines:
                    line = line[:-1]
                    if len(line) > 0 and \
                            ('a' <= line[0] <= 'z' or 'A' <= line[0] <= 'Z'):
                        if key:
                            dictionary[key] = value
                        key = line
                        value = ''
                    else:
                        value += line + '\n'

            else:
                for line in lines:
                    line = line[:-1]
                    if len(line) > 0 and line[0] not in ' \t':
                        if key:
                            dictionary[key] = value
                        key = line
                        value = ''
                    else:
                        value += line + '\n'

            if key:
                dictionary[key] = value
    elif format == 'yaml':
        structure = yaml.load(open(file_name).read())
        if isinstance(structure, list):
            for element in structure:
                if isinstance(element, list):
                    question = element[0]
                    answer = None
                    if len(element) > 2:
                        answer = element[1:]
                    else:
                        answer = element[1]
                    dictionary[question] = answer
                else:
                    error('unknown YAML dictionary element format: ' +
                        str(element))
        elif isinstance(structure, dict):
            for question in structure:
                answer = structure[question]
                dictionary[question] = answer
    else:
        error('unknown dictionary format: ' + format)
    return dictionary
