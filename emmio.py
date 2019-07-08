#!/usr/bin/python3

import os
import sys

from datetime import timedelta

from engine.lexicon import Lexicon, first_day_of_week
from engine.frequency_list import FrequencyList
from engine.dictionary import Dictionary
from engine.ui import set_log, VerboseLogger


def lexicon(args):
    import argparse

    # Arguments.

    parser = argparse.ArgumentParser()
    parser.add_argument("--lexicon", dest="lexicon_file_name", metavar="<name>",
        help="user lexicon file name")
    parser.add_argument("--language", dest="language")
    parser.add_argument("--output-directory", dest="output_directory")
    parser.add_argument("--log", dest="log", default="frequency")
    parser.add_argument("--skip-known", dest="skip_known", action="store_true",
        help="skip all words marked in that session as known in the future")
    parser.add_argument("--skip-unknown", dest="skip_unknown",
        action="store_true",
        help="skip all words marked in that session as unknown in the future")

    parser.add_argument("--command", dest="command", default="check")

    parser.add_argument("-f", "--frequency", dest="frequency_file_name")
    parser.add_argument("-ff", dest="frequency_file_format")
    parser.add_argument("-d", "--dictionary", dest="dictionary_file_name")
    parser.add_argument("-df", dest="dictionary_file_format")

    parser.add_argument("--stop-at", dest="stop_at")

    arguments = parser.parse_args(args)

    if arguments.command not in ["check", "compute", "unknown"]:
        print("Error: unknown command " + arguments.command)
        return

    if arguments.command == "compute":
        for file_name in os.listdir("lexicon"):
            language = file_name[6:8]
            user_lexicon = Lexicon(language,
                                   os.path.join("lexicon", file_name))
            user_lexicon.read_fast()

            # first = first_day_of_month,
            # next_ = plus_month
            first = first_day_of_week
            next_ = lambda x: x + timedelta(days=7)
            # first = lambda x: datetime.combine(x, datetime.min.time())
            # next_ = lambda x: x + timedelta(days=1)

            user_lexicon.construct(os.path.join(arguments.output_directory,
                "lexicon_" + language + "_time.dat"), 100, first, next_)
        return

    if not arguments.frequency_file_format:
        if arguments.frequency_file_name.endswith(".yml"):
            arguments.frequency_file_format = "yaml"
        elif arguments.frequency_file_name.endswith(".txt"):
            arguments.frequency_file_format = "text"
        else:
            print("Unknown frequency file format.")
            return

    frequency_list = FrequencyList()
    frequency_list.read(
        arguments.frequency_file_name, arguments.frequency_file_format)

    file_name = arguments.lexicon_file_name

    if not os.path.isfile(file_name):
        print("Create new user file " + file_name)
        open(file_name, "w+").write("log:\nwords:\n")

    user_lexicon = Lexicon(arguments.language, file_name)
    user_lexicon.read_fast()

    if arguments.command == "unknown":
        top = user_lexicon.get_top_unknown()
        print("%-20s %-10s" % ("word", "occurrences"))
        print(20 * "-" + " " + 10 * "-")
        for word, word_knowledge in top[:50]:
            print("%-20s %10d" % (word, word_knowledge.occurrences))
        return

    stop_at = None
    if arguments.stop_at:
        stop_at = int(arguments.stop_at)

    dictionary = None
    if arguments.dictionary_file_name:
        dictionary = Dictionary(arguments.dictionary_file_name,
            arguments.dictionary_file_format)

    print("""
    <y> or <Enter>  you know at least one meaning of the word
    <n>             you don't know any of meanings of the word
    <->             the word doesn't exist or is a proper name

    <q>             exit lexicon test
""")

    user_lexicon.check(frequency_list, stop_at, dictionary,
        arguments.log, arguments.skip_known, arguments.skip_unknown)


if __name__ == "__main__":
    command = sys.argv[1]

    if command == "lexicon":
        print("\nEmmio. Lexicon.\n")
        set_log(VerboseLogger)
        lexicon(sys.argv[2:])
    else:
        print("Unknown command: " + command + ".")
