from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from emmio.dictionary.core import DictionaryCollection
from emmio.language import construct_language, Language, ENGLISH
from emmio.read.config import ReadConfig
from emmio.sentence.core import split_sentence
from emmio.text.core import Texts
from emmio.ui import Interface


@dataclass
class Read:
    """Reading process."""

    path: Path
    """Path to file with reading process."""

    config: ReadConfig
    """Reading process configuration."""

    from_language: Language
    to_language: Language

    def print_words(
        self, interface: Interface, user_data, dictionaries, words
    ) -> None:
        result = []
        for word, type_ in words:
            if type_ == "word" and not user_data.is_known_or_not_a_word(
                word.lower(), self.from_language
            ):
                translations = []
                items = dictionaries.get_items(word, self.from_language)
                if items:
                    for item in items:
                        _, word_translation = item.get_short(ENGLISH)
                        translations.append(word_translation)
                translations = [x for x in translations if x]
                result.append([word, translations[0] if translations else ""])
        interface.table(["Word", "Translation"], result)

    def read(
        self,
        interface: Interface,
        user_data: "UserData",
        dictionaries: DictionaryCollection,
        texts: Texts,
    ) -> None:
        text: list[str] = texts.data[self.from_language]
        translation: list[str] = texts.data[self.to_language]
        for index, line in enumerate(text):
            words: list[tuple[str, Literal["word", "symbol"]]] = split_sentence(
                line, self.from_language
            )
            sentence: str = ""
            for word, type_ in words:
                if user_data.is_known_or_not_a_word(
                    word.lower(), self.from_language
                ):
                    sentence += f"\033[32m{word}\033[0m"
                else:
                    sentence += word
            print(sentence)
            self.print_words(interface, user_data, dictionaries, words)
            command: str = input("[READ]> ")
            if command == "/stop":
                break
            print(translation[index])
            command: str = input("[READ]> ")

    @classmethod
    def from_config(cls, path: Path, config: ReadConfig):
        from_language = construct_language(config.from_language)
        to_language = construct_language(config.to_language)

        return cls(path / config.file_name, config, from_language, to_language)
