#!/usr/bin/python3
import json
import sys
from datetime import datetime, timedelta
from os.path import join
from typing import Dict, List

from emmio.dictionary import Dictionary
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.external.yandex import YandexDictionary
from emmio.frequency import FrequencyDatabase, FrequencyList
from emmio.graph import Visualizer
from emmio.language import Language
from emmio.learning import Learning
from emmio.lexicon import Lexicon
from emmio.sentence import SentenceDatabase
from emmio.teacher import Teacher
from emmio.ui import Logger, header, set_log
from emmio.user_data import UserData
from emmio.util import day_end

"""
<y> or <Enter>  I know at least one meaning of the word
<n>             I don’t know any of meanings of the word
<s>             I know at least one meanings of the word and I’m sure I
                will not forget it, skip this word in the future
<b>             I don’t know any of meanings of the word, but it is a proper
                name too
<->             the word doesn’t exist or is a proper name

<q>             exit
"""


class Emmio:
    def __init__(self, user_data: UserData, path: str):
        self.user_data: UserData = user_data
        self.path: str = path

        self.sentence_db = SentenceDatabase(join(path, "sentence.db"))
        self.frequency_db = FrequencyDatabase(join(path, "frequency.db"))

        with open(join(path, "config.json")) as input_file:
            self.config = json.load(input_file)

        self.frequency_lists: Dict[str, FrequencyList] = {}

    def get_frequency_list(self, frequency_list_id: str) -> FrequencyList:
        if frequency_list_id not in self.frequency_lists:
            frequency_list = FrequencyList()
            frequency_list.read_json(join(
                self.path, "priority",
                self.config["priority"][frequency_list_id]["file_name"]))
            self.frequency_lists[frequency_list_id] = frequency_list
        return self.frequency_lists[frequency_list_id]

    def get_dictionaries(self, language: Language) -> List[Dictionary]:
        dictionaries: List[Dictionary] = []

        wiktionary = EnglishWiktionary("cache", language)
        dictionaries.append(wiktionary)

        return dictionaries

    def run(self):

        print("\nEmmio\n")

        print("""
    Press <Enter> or print "learn" to start learning.
    Print "help" to see commands or "exit" to quit.
""")

        while True:
            command: str = input("> ")
            if command in ["q", "quit", "exit"]:
                return
            if command == "help":
                print("""
    help                print this message
    exit / quit         close Emmio

        Learning

    learn / {Enter}     start learning process
    stat learn          print learning statistics
    depth               show depth graph
    response time       show response time graph
    next question time  show next question time graph
    actions [per day]   show actions graph

        Lexicon

    lexicon             check lexicons
    stat lexicon        print lexicon statistics
    plot lexicon        draw lexicon graph
""")

            if not command or command == "learn":
                self.learn()

            if command == "lexicon":
                for language in sorted(
                        self.user_data.get_lexicon_languages(),
                        key=lambda x:
                        -self.user_data.get_lexicon(x).get_last_rate()):
                    lexicon: Lexicon = self.user_data.get_lexicon(language)
                    now = datetime.now()
                    need: int = lexicon.count_unknowns(
                        "log", now - timedelta(days=7), now)
                    if need >= 5:
                        continue
                    header(f"Lexicon for {language.get_name()}")
                    dictionaries = self.get_dictionaries(language)
                    frequency_list_id: str = (
                        self.user_data.get_frequency_list_id(language))
                    frequency_list = self.get_frequency_list(frequency_list_id)
                    lexicon.check(
                        frequency_list, None, dictionaries, "frequency", False,
                        False, 5 - need)
                    break

            if command == "stat learn":
                stat = {}
                total = 0
                for course_id in self.user_data.course_ids:
                    k = self.user_data.get_course(course_id).knowledges
                    for word in k:
                        if k[word].interval.total_seconds() == 0:
                            continue
                        depth = k[word].get_depth()
                        if depth not in stat:
                            stat[depth] = 0
                        stat[depth] += 1
                        total += 1 / (2 ** depth)

                print()
                for course_id in self.user_data.course_ids:
                    learning = self.user_data.get_course(course_id)
                    print(
                        f"{learning.name:<20} "
                        f"{learning.to_repeat():4d} / {learning.learning():4d} "
                        f"{learning.new_today():2d} / {learning.ratio:2d}")
                print(f"Pressure: {total:.2f}")
                print()

            if command == "stat lexicon":
                from matplotlib import pyplot as plt
                import matplotlib.dates as mdates
                _, ax = plt.subplots()
                locator = mdates.AutoDateLocator()
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(
                    mdates.ConciseDateFormatter(locator))
                print()
                for language in sorted(
                        self.user_data.get_lexicon_languages(),
                        key=lambda x:
                        -self.user_data.get_lexicon(x).get_last_rate()):
                    lexicon = self.user_data.get_lexicon(language)
                    now = datetime.now()
                    rate = lexicon.get_last_rate()
                    rate_string = f"{rate:5.1f}" if rate else "  N/A"
                    last_week_precision: int = lexicon.count_unknowns(
                        "log", now - timedelta(days=7), now)
                    print(
                        f"{language.get_name():<20}  "
                        f"{last_week_precision:3d} "
                        f"{rate_string}")
                print()

            if command == "plot lexicon":
                Visualizer.graph_lexicon([
                    self.user_data.get_lexicon(language) for language
                    in self.user_data.get_lexicon_languages()])

            if command in Visualizer.get_commands():
                ratios = 0
                learning_words = 0
                records = []
                knowledges = {}
                for course_id in self.user_data.course_ids:
                    learning = self.user_data.get_course(course_id)
                    ratios += learning.ratio
                    learning_words += learning.learning()
                    records += learning.records
                    knowledges |= learning.knowledges

                visualizer = Visualizer()
                records = sorted(records, key=lambda x: x.time)

                visualizer.process_command(command, records, knowledges)

    def learn(self):
        for course_id in self.user_data.course_ids:
            learning: Learning = self.user_data.get_course(course_id)
            lexicon: Lexicon = self.user_data.get_lexicon(
                Language(learning.subject))
            if learning.to_repeat() > 0:
                header(f"Repeat learned for {learning.name}")
                learner = Teacher(
                    "tatoeba", self.sentence_db, self.frequency_db, learning,
                    lexicon, get_dictionaries=self.get_dictionaries)
                proceed = learner.repeat()
                if not proceed:
                    return

        sorted_ids = sorted(
            self.user_data.course_ids,
            key=lambda x: (
                self.user_data.get_course(x).learning() /
                self.user_data.get_course(x).ratio))

        for course_id in sorted_ids:  # type: str
            learning = self.user_data.get_course(course_id)
            lexicon: Lexicon = self.user_data.get_lexicon(
                Language(learning.subject))
            if learning.ratio > learning.new_today():
                header(f"Learn new and repeat for {learning.name}")
                learner = Teacher(
                    "tatoeba", self.sentence_db, self.frequency_db, learning,
                    lexicon, get_dictionaries=self.get_dictionaries)
                proceed = learner.start()
                if not proceed:
                    return

        print()
        now = datetime.now()
        time_to_repetition: timedelta = (min(map(
            lambda x: x.get_nearest(), self.user_data.courses)) - now)
        time_to_new: timedelta = day_end(now) - now
        if time_to_repetition < time_to_new:
            print(f"    Repetition in {time_to_repetition}.")
        else:
            print(f"    New question in {time_to_new}.")
        print()


if __name__ == "__main__":
    set_log(Logger)

    data_path: str = sys.argv[1]
    user_id: str = sys.argv[2]

    emmio: Emmio = Emmio(
        UserData.from_directory(join(data_path, user_id)), data_path)
    emmio.run()
