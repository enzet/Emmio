#!/usr/bin/python3

import argparse
import json
import os
import sys

from datetime import timedelta
from typing import List

from emmio.teacher import Teacher

from emmio.lexicon import Lexicon
from emmio.language import languages
from emmio.util import first_day_of_week, first_day_of_month, plus_month
from emmio.frequency import FrequencyList
from emmio.dictionary import SimpleDictionary, Dictionary
from emmio.ui import set_log, VerboseLogger
from emmio.text import Text


def teacher(args: List[str]):
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-l",
        dest="learning_id")

    parser.add_argument(
        "-d",
        dest="directory_name")

    arguments = parser.parse_args(args)

    directory_name = "."
    if arguments.directory_name:
        directory_name = arguments.directory_name
    config_file_name = os.path.join(arguments.directory_name, "config.json")

    config = json.load(open(config_file_name))

    current_teacher = Teacher(arguments.learning_id, directory_name, config,
        options=vars(arguments))
    current_teacher.run()


def lexicon(args: List[str]):
    import argparse

    # Arguments.

    parser = argparse.ArgumentParser()

    parser.add_argument("--lexicon",
        dest="lexicon_file_name",
        metavar="<name>",
        help="user lexicon file name")

    parser.add_argument("--language",
        dest="language")

    parser.add_argument("--input-directory",
        dest="input_directory")

    parser.add_argument("--output-directory",
        dest="output_directory")

    parser.add_argument("--log",
        dest="log",
        default="frequency")

    parser.add_argument("--skip-known",
        dest="skip_known",
        action="store_true",
        help="skip all words marked in that session as known in the future")

    parser.add_argument("--skip-unknown",
        dest="skip_unknown",
        action="store_true",
        help="skip all words marked in that session as unknown in the future")

    parser.add_argument("--command",
        dest="command",
        default="check")

    parser.add_argument("-f", "--frequency",
        dest="frequency_file_name")

    parser.add_argument("-ff",
        dest="frequency_file_format")

    parser.add_argument("-d", "--dictionary",
        dest="dictionary_file_name")

    parser.add_argument("-df",
        dest="dictionary_file_format")

    parser.add_argument("--stop-at",
        dest="stop_at")

    parser.add_argument("--update-dictionary",
        dest="update_dictionary",
        action="store_true")

    arguments = parser.parse_args(args)

    if arguments.command not in ["check", "compute", "unknown"]:
        print("Error: unknown command " + arguments.command)
        return

    if arguments.command == "compute":
        current_percent = {}
        for file_name in os.listdir(arguments.input_directory):
            language = file_name[-7:-5]
            user_lexicon = Lexicon(language,
                os.path.join(arguments.input_directory, file_name))

            # first = first_day_of_month
            # next_ = plus_month
            first = first_day_of_week
            next_ = lambda x: x + timedelta(days=7)
            # first = lambda x: datetime.combine(x, datetime.min.time())
            # next_ = lambda x: x + timedelta(days=1)

            print(language)
            r = user_lexicon.construct(100, first, next_)
            file_name = os.path.join(arguments.output_directory,
                "lexicon_" + language + "_time.dat")
            with open(file_name, "w+") as output_file:
                for date in r:
                    output_file.write(
                        f"    {date.strftime('%Y.%m.%d')} {r[date]:f}\n")

            file_name = os.path.join(arguments.output_directory,
                "lexicon_" + language + "_time_precise.dat")
            r = user_lexicon.construct_precise()
            with open(file_name, "w+") as output_file:
                for date in r:
                    output_file.write(
                        f"    {date.strftime('%Y.%m.%d')} {r[date]:f}\n")
                    current_percent[language] = r[date]

        for language in sorted(
                current_percent, key=lambda x: current_percent[x]):
            print("%s %5.2f %%" % (language, current_percent[language]))
        return

    if not arguments.frequency_file_format:
        if arguments.frequency_file_name.endswith(".yml"):
            arguments.frequency_file_format = "yaml"
        elif arguments.frequency_file_name.endswith(".txt"):
            arguments.frequency_file_format = "text"
        elif arguments.frequency_file_name.endswith(".json"):
            arguments.frequency_file_format = "json"
        else:
            print("Unknown frequency file format.")
            return

    frequency_list = FrequencyList()
    frequency_list.read(
        arguments.frequency_file_name, arguments.frequency_file_format)

    file_name = arguments.lexicon_file_name

    user_lexicon = Lexicon(arguments.language, file_name)

    if arguments.command == "unknown":
        top: List[str] = user_lexicon.get_top_unknown(frequency_list)
        print("%-20s %-10s" % ("word", "occurrences"))
        print(20 * "-" + " " + 10 * "-")
        for word in top[:50]:
            print("%-20s %10d" % (word, frequency_list.get_occurrences(word)))
        return

    stop_at = None
    if arguments.stop_at:
        stop_at = int(arguments.stop_at)

    dictionaries: List[Dictionary] = []
    if arguments.dictionary_file_name:
        dictionaries.append(SimpleDictionary(
            arguments.language, arguments.dictionary_file_name,
            arguments.dictionary_file_format))

    print("""
    <y> or <Enter>  I know at least one meaning of the word
    <n>             I don’t know any of meanings of the word
    <s>             I know at least one meanings of the word and I’m sure I
                    will not forget it, skip this word in the future
    <b>             I don’t know any of meanings of the word, but it is a proper
                    name too
    <->             the word doesn’t exist or is a proper name

    <q>             exit
""")

    user_lexicon.check(frequency_list, stop_at, dictionaries,
        arguments.log, arguments.skip_known, arguments.skip_unknown, None)


def do_text(arguments: List[str]):
    parser = argparse.ArgumentParser()

    parser.add_argument("-i", "--input",
        help="input file with the text",
        dest="input_file_name",
        metavar="<path>",
        required=True)

    parser.add_argument("-o", "--output",
        help="output file for the frequency list",
        dest="output_file_name",
        metavar="<path>",
        required=True)

    parser.add_argument("-l", "--language",
        help="text language",
        dest="language",
        metavar="<2-letters ISO 639-1 language code>",
        required=True)

    options = parser.parse_args(arguments)

    # Options check

    if not (options.language in languages):
        print(
            f"Unknown language: {options.language}. "
            f"Known languages: {', '.join(languages)}.")
        return

    content = open(options.input_file_name, "r").read()

    text = Text(content, options.language)
    frequency_list: FrequencyList = text.get_frequency_list()
    frequency_list.write_json(options.output_file_name)


if __name__ == "__main__":
    command = sys.argv[1]

    if command == "teacher":
        print("\nEmmio. Teacher.\n")
        set_log(VerboseLogger)
        teacher(sys.argv[2:])
    elif command == "lexicon":
        print("\nEmmio. Lexicon.\n")
        set_log(VerboseLogger)
        lexicon(sys.argv[2:])
    elif command == "text":
        print("\nEmmio. Text\n")
        set_log(VerboseLogger)
        do_text(sys.argv[2:])
    else:
        print(f"Unknown command: {command}.")
