"""
Emmio. Simple flashcard learner based on modified Leitner system.

Author: Sergey Vartanov (me@enzet.ru).
"""
import os
import random
import subprocess
import sys
import yaml

from datetime import datetime
from typing import Dict, Optional

from emmio import analysis
from emmio import graph
from emmio import reader
from emmio import ui
from emmio.cards import Cards
from emmio.learning import FullUserData, Responses, Learning
from emmio.frequency import FrequencyList


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


class Teacher:
    """
    Teacher.
    """
    def __init__(self, learning_id: str, directory_name: str, config: Dict,
            options: Dict) -> None:
        """
        :param learning_id: learning process identifier.
        :param directory_name: working directory name.
        :param config: configuration file.
        :param options: dictionary with other options.
        """
        self.learning_id = learning_id
        self.options = options

        if learning_id not in config["learnings"]:
            print("Fatal: no learning with ID " + learning_id + ".")
            sys.exit(1)

        learning_config = config["learnings"][learning_id]

        dictionary_id = learning_config['dictionary']
        user_id = learning_config['user']
        self.learning_name = learning_config['name']

        if dictionary_id not in config['dictionaries']:
            print('Fatal: no dictionary with ID ' + dictionary_id + '.')
            sys.exit(1)

        dictionary_config = config['dictionaries'][dictionary_id]

        if user_id not in config['users']:
            print('Fatal: no user with ID ' + user_id + '.')
            sys.exit(1)

        user_config = config['users'][user_id]

        self.user_file_name = os.path.join(directory_name, user_config["file"])
        full_user_data = FullUserData(self.user_file_name)

        self.learning: Learning
        self.dictionary_user_id: Optional[str] = None

        for dictionary_user_id in full_user_data.get_learning_ids():
            if dictionary_user_id in dictionary_config['user_ids']:
                self.learning = full_user_data.get_learning(dictionary_user_id)
                self.dictionary_user_id = dictionary_user_id
                break

        if not self.dictionary_user_id:
            self.dictionary_user_id = dictionary_id

        self.dictionary: Cards = Cards(
            os.path.join(directory_name, dictionary_config["file"]),
            dictionary_config['format'])

        if "priority" in learning_config:
            priority_list_ids = learning_config["priority"]

            self.priority_list = []

            for priority_list_id in priority_list_ids:
                priority_config = config['priorities'][priority_list_id]
                priority_list = read_priority(
                    os.path.join(directory_name, priority_config["file"]))
                self.priority_list += priority_list
        else:
            self.priority_list = None

        self.schemes = learning_config['scheme']

        self.per_day = None
        if 'per_day' in learning_config:
            self.per_day = learning_config['per_day']

    @staticmethod
    def get_full_status(statistics: dict) -> str:
        return 'Now  ' + str(statistics['to_repeat']) + '    ' + \
            'Learned  ' + str(statistics['learned']) + '    ' \
            'Not  ' + str(statistics['not_learned']) + '    ' \
            'Heaviness  ' + str(int(statistics['heaviness'])) + '    ' \
            'All  ' + str(statistics['learned'] +
                statistics['skipped']) + '    ' \
            'Score  ' + str(statistics['score']) + '    ' \
            'Added today  ' + str(statistics['added_today'])

    @staticmethod
    def get_status(statistics: dict) -> str:
        s = 'Now  %d    Heaviness  %.2f' % \
            (statistics['to_repeat'], statistics['heaviness'])
        s += '    Added today  %d' % statistics['added_today']
        s += ' '
        return s

    def get_next_question(self, now: int):
        """
        Next card for learning.

        :returns: Next question (card ID), is it new.
        """
        minimum_yes = 1000
        next_question = None
        next_scheme_id = None

        scheme_ids = []
        for scheme in self.schemes:
            scheme_ids.append(scheme['id'])

        # Looking for repetition.

        for question_id in self.learning.get_question_ids():  # type: str
            if '#' in question_id:
                question = question_id[:question_id.find('#')]
                scheme_id = question_id[question_id.find('#'):]
            else:
                question = question_id
                scheme_id = ''

            if question not in self.dictionary.get_questions():
                continue
            if scheme_id not in scheme_ids:
                continue

            response: Responses = self.learning.get_responses(question_id)
            if response.plan and response.plan < now and response.answers:
                yes = len(response.answers) - \
                    response.answers.rfind("n") - 1
                if yes < minimum_yes:
                    minimum_yes = yes
                    next_question = question
                    next_scheme_id = scheme_id

        if next_question:
            return next_question, False, next_scheme_id

        # Looking for new word.

        if self.priority_list:
            # Return new question using priority list.
            for q in self.priority_list:
                for scheme in self.schemes:
                    current_scheme_id = scheme['id']
                    question = q[0]
                    if (question in self.dictionary) and \
                            not ((question + current_scheme_id) in
                                self.learning.get_question_ids()):
                        next_question = question
                        scheme_id = current_scheme_id
                        return next_question, True, scheme_id
        else:
            # Return arbitrary question.
            for question in self.dictionary.get_questions():
                for scheme in self.schemes:
                    current_scheme_id = scheme['id']
                    if not ((question + current_scheme_id) in
                            self.learning.get_question_ids()):
                        next_question = question
                        scheme_id = current_scheme_id
                        return next_question, True, scheme_id

    def get_element_text(self, question_id, element):
        if element['source'] == 'key':
            text = question_id
        elif element['source'] == 'value':
            text = self.dictionary.get_answer(question_id)
        elif element['source'] == 'dict_value':
            text = self.dictionary.get_answer_key(question_id, element['field'])
        else:
            text = question_id

        after_text = text

        if 'action' in element:
            if element['action'] == 'remove latin':
                new_text = ''
                for c in text:
                    if 'a' <= c <= 'z' or 'A' <= c <= 'Z' or \
                            c in 'ʃʊɜðɪæɘʌɑʒɛ↗θŋ':
                        new_text += '█'
                    else:
                        new_text += c
                text = new_text

        return text, after_text

    def process_user_response(self, response: bool, question: str, now: int,
            scheme_id: str):
        """
        Process user response.

        :param response: user response: know or don't know.
        :param question: current question.
        :param now: time point integer representation.
        :param scheme_id: current learning scheme identifier.
        """
        self.learning.answer(question + scheme_id, response, now)

    def get_statistics(self):
        return analysis.get_statistics(self.learning, self.dictionary)

    def run(self):
        """
        Run learning process.

        :returns: Nothing.
        """
        per_day = 100
        if 'per_day' in self.options:
            per_day = self.options['per_day']

        heaviness = None
        if 'heaviness' in self.options:
            heaviness = self.options['heaviness']

        # now = int((datetime.now() -
        #     datetime(1970, 1, 1)).total_seconds() / 60)
        # begin_statistics = analysis.get_statistics(self.user_data,
        #     self.dictionary, now, postfix)

        while True:
            now = int((datetime.now() -
                datetime(1970, 1, 1)).total_seconds() / 60)

            # Get current statistics

            statistics = analysis.get_statistics(self.learning,
                self.dictionary, now, '')

            # if statistics['to_repeat'] <= 0 and \
            #        statistics['to_learn'] <= 0 and \
            #        statistics['added_last_24_hours'] >= 24:
            #    break

            # Get next card

            next_question, is_new_card, scheme_id = \
                self.get_next_question(now)

            if is_new_card:
                if per_day and statistics['added_today'] >= per_day:
                    break
                if heaviness and statistics['heaviness'] >= heaviness:
                    break

            if next_question is None:
                break

            status = self.get_status(statistics)

            question, answer = None, None

            scheme = None
            for current_scheme in self.schemes:
                if current_scheme['id'] == scheme_id:
                    scheme = current_scheme
                    break

            question, after_question = \
                self.get_element_text(next_question, scheme['question'])

            answer = ''
            for answer_element in scheme['answer']:
                text, _ = self.get_element_text(next_question, answer_element)
                answer += text

            # Show question

            ui.show(question, status, 31 if is_new_card else None)

            result = 'wrong'

            if 'check' in scheme and scheme['check'] == 'type':
                result = ui.get_word(answer)
            else:
                a = ui.get_char()
                while a in 's':
                    if a == 's':
                        try:
                            print('Dumping statistics...')
                            graph.dump_times('times.dat', self.user_data)
                            graph.dump_times('times_24.dat', self.user_data,
                                scale=24)
                            graph.dump_quality('quality.dat', self.user_data)
                            graph.dump_quality('quality_sum.dat', self.user_data,
                                is_sum=True)
                            subprocess.check_output(['gnuplot',
                                'statistics.gnuplot'])
                            print('Done.')
                        except Exception as e:
                            print(e)
                    a = ui.get_char()

                if a == 'q':  # Quit
                    break

            # Show answer

            if 'м. р.' in answer and 'ж. р.' not in answer:
                ui.show(question + '\n' + answer, status, 31)
            elif 'ж. р.' in answer and 'м. р.' not in answer:
                ui.show(question + '\n' + answer, status, 34)
            else:
                ui.show(after_question + '\n' + answer, status)

            if 'check' in scheme and scheme['check'] == 'type':
                if result == 'quit':
                    break
                elif result == 'skip':
                    self.process_user_response(True, next_question, now,
                        scheme_id)
                elif result == 'right':
                    self.process_user_response(True, next_question, now,
                        scheme_id)
                elif result == 'wrong':
                    self.process_user_response(False, next_question, now,
                        scheme_id)
            else:
                a = ui.get_char()
                while not (a in 'qynjkfd,.'):
                    a = ui.get_char()
                if a == 'q':  # Quit
                    break
                elif a in 'ynjkfd,.':  # Answer
                    response = a in 'yjf,'
                    self.process_user_response(response, question, now, scheme_id)

        sys.stdout.write('\nWriting results... ')
        sys.stdout.flush()

        self.write_data()

    def write_data(self):
        """
        Write changed user data and archive it.
        """
        now: int = \
            int((datetime.now() - datetime(1970, 1, 1)).total_seconds() / 60)

        # obj = yaml.safe_dump(full_user_data, allow_unicode=True, width=200)

        full_user_data = reader.read_answers_fast(self.user_file_name)
        full_user_data[self.dictionary_user_id] = self.user_data

        obj = ""
        for dictionary_name in sorted(full_user_data.keys()):
            obj += dictionary_name + ':\n'
            for key in sorted(full_user_data[dictionary_name].keys()):
                answer = full_user_data[dictionary_name][key]
                if key in ['on', 'off', 'yes', 'no', 'null', 'true', 'false']:
                    obj += "  '" + key + "': {"
                else:
                    obj += '  ' + key + ': {'
                for field in ['added', 'answers', 'last', 'plan']:
                    if field in answer:
                        obj += field + ': ' + str(answer[field]) + ', '
                obj = obj[:-2]
                obj += '}\n'

        open(self.user_file_name, 'w+').write(obj)
