"""User interface for dictionaries."""

from argparse import Namespace

from emmio.data import Data
from emmio.dictionary.core import DictionaryCollection
from emmio.language import Language, construct_language
from emmio.ui import Interface, TerminalInterface


def start(data: Data, arguments: Namespace):
    """Run dictionary utility."""
    language_1: Language = construct_language(arguments.language_1)
    language_2: Language = construct_language(arguments.language_2)
    construct_language(arguments.language_2),
    dictionaries: DictionaryCollection = (
        data.dictionaries.get_dictionaries_by_language(language_1, language_2)
    )

    for dictionary in dictionaries.dictionaries:
        print(dictionary)

    dictionaries: DictionaryCollection = DictionaryCollection(
        [
            data.get_dictionary(
                {"id": "en_wiktionary", "language": arguments.language_1}
            )
        ]
    )

    interface: Interface = TerminalInterface()
    while True:
        if (word := input("> ")) == "q":
            break
        # TODO: check user input.
        for item in dictionaries.get_items(word):
            print(item.to_str(language_2, interface))
