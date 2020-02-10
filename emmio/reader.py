# -*- coding: utf-8 -*- from __future__ import unicode_literals

import yaml

from typing import Any, Dict


def read_answers_fast(file_name: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    answers: Dict[str, Dict[str, Dict[str, Any]]] = {}
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
            element: Dict[str, Any] = \
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
