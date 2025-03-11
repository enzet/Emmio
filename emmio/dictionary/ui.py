"""User interface for dictionaries."""

from argparse import Namespace

from emmio.data import Data
from emmio.dictionary.core import DictionaryCollection
from emmio.language import Language
from emmio.ui import Interface, Text


async def start(data: Data, interface: Interface, arguments: Namespace):
    """Run dictionary utility."""

    language_1: Language = Language.from_code(arguments.language_1)
    language_2: Language = Language.from_code(arguments.language_2)

    dictionaries: DictionaryCollection = (
        data.dictionaries.get_dictionaries_by_language(language_1, language_2)
    )

    while True:
        if (word := interface.input("> ")) == "q":
            break
        # TODO: check user input.
        text: Text = Text()
        for item in await dictionaries.get_items(word, language_2):
            text.add(item.to_text([language_2]))
        interface.print(text)
