"""An interface to Google Translate dictionary.

See https://translate.google.com/
"""

import os
from pathlib import Path
from typing import override

import httpx
from googletrans import Translator

from emmio.dictionary.core import Dictionary, DictionaryItem
from emmio.language import Language


class GoogleTranslate(Dictionary):
    """Google Translate dictionary."""

    def __init__(
        self,
        path: Path,
        cache_directory: Path,
        from_language: Language,
        to_language: Language,
    ) -> None:
        """Initialize Google Translate dictionary.

        :param path: path to the dictionary
        :param cache_directory: path to the cache directory
        :param from_language: language of requests
        :param to_language: language of translations
        """
        super().__init__("google_translate")
        self.path: Path = path
        self.cache_directory: Path = (
            cache_directory
            / "google_translate"
            / from_language.get_code()
            / to_language.get_code()
        )
        if not self.cache_directory.exists():
            os.makedirs(self.cache_directory)

        self.from_language: Language = from_language
        self.to_language: Language = to_language
        self.is_machine: bool = True

        self.translator: Translator = Translator()

        self.items: dict[str, DictionaryItem] = {}

    @override
    def get_name(self) -> str:
        return (
            f"Google Translate {self.from_language.get_name()} to "
            f"{self.to_language.get_name()}"
        )

    @override
    async def get_item(
        self, word: str, cache_only: bool = False
    ) -> DictionaryItem | None:

        # Return already loaded item.
        if word in self.items:
            return self.items[word]

        # Try to read cached file.
        cache_path: Path = self.cache_directory / word
        if cache_path.exists():
            with cache_path.open(encoding="utf-8") as input_file:
                return DictionaryItem.from_simple_translation(
                    word, self.to_language, input_file.read()
                )

        if cache_only:
            return None

        try:
            translation = await self.translator.translate(
                word,
                src=self.from_language.get_code(),
                dest=self.to_language.get_code(),
            )
        except httpx.ConnectError:
            return None
        except httpx.ConnectTimeout:
            return None

        with (self.cache_directory / word).open(
            "w", encoding="utf-8"
        ) as output_file:
            output_file.write(translation.text)

        return DictionaryItem.from_simple_translation(
            word, self.to_language, translation.text
        )

    @override
    def check_from_language(self, language: Language) -> bool:
        return language == self.from_language

    @override
    def check_to_language(self, language: Language) -> bool:
        return language == self.to_language

    @override
    def check_is_machine(self) -> bool:
        return True
