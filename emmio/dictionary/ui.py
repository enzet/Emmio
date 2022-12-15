from argparse import Namespace

from emmio.data import Data
from emmio.dictionary.core import DictionaryCollection
from emmio.language import construct_language, Language
from emmio.ui import TerminalInterface


def start(data: Data, arguments: Namespace):
    language_1: Language = construct_language(arguments.language_1)
    language_2: Language = construct_language(arguments.language_2)
    construct_language(arguments.language_2),
    dictionaries: DictionaryCollection = (
        data.dictionaries.get_dictionaries_by_language(language_1, language_2)
    )

    for dictionary in dictionaries.dictionaries:
        print(dictionary)

    dictionaries = DictionaryCollection(
        [
            data.get_dictionary(
                {"id": "en_wiktionary", "language": arguments.language_1}
            )
        ]
    )

    interface = TerminalInterface()
    while True:
        word: str = input("> ")
        if word == "q":
            break
        for item in dictionaries.get_items(word):
            print(item.to_str(language_2, interface))
