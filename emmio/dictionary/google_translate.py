"""An interface to Google Translate dictionary.

See https://translate.google.com/
"""

from pathlib import Path
from typing import override

import httpx
from googletrans import Translator

from emmio.dictionary.core import Dictionary, DictionaryItem
from emmio.language import Language

# Cap how long a single live translation may take. Without a bound, a slow or
# rate-limited Google response blocks the whole lookup for many seconds; we
# would rather fail fast (return `None`) and serve the rest of the result.
_TIMEOUT_SECONDS: float = 5.0


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
            self.cache_directory.mkdir(parents=True)

        self.from_language: Language = from_language
        self.to_language: Language = to_language
        self.is_machine: bool = True

        # A single client is reused across lookups so repeated network calls
        # share the connection (keepalive), avoiding a fresh TLS handshake per
        # uncached word. The instance itself is cached in `DictionaryData`.
        self.translator: Translator = Translator(
            timeout=httpx.Timeout(_TIMEOUT_SECONDS)
        )

        self.items: dict[str, DictionaryItem] = {}

    @override
    def get_name(self) -> str:
        return (
            f"Google Translate {self.from_language.get_name()} to "
            f"{self.to_language.get_name()}"
        )

    @override
    async def get_item(
        self, word: str, *, cache_only: bool = False
    ) -> DictionaryItem | None:
        # Return already loaded item.
        if word in self.items:
            return self.items[word]

        # Try to read cached file.
        cache_path: Path = self.cache_directory / word
        if cache_path.exists():
            with cache_path.open(encoding="utf-8") as input_file:
                item: DictionaryItem = DictionaryItem.from_simple_translation(
                    word, self.to_language, input_file.read()
                )
            self.items[word] = item
            return item

        if cache_only:
            return None

        try:
            translation = await self.translator.translate(
                word,
                src=self.from_language.get_code(),
                dest=self.to_language.get_code(),
            )
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.TimeoutException,
        ):
            return None

        with (self.cache_directory / word).open(
            "w", encoding="utf-8"
        ) as output_file:
            output_file.write(translation.text)

        item = DictionaryItem.from_simple_translation(
            word, self.to_language, translation.text
        )
        self.items[word] = item
        return item

    @override
    def check_from_language(self, language: Language) -> bool:
        return language == self.from_language

    @override
    def check_to_language(self, language: Language) -> bool:
        return language == self.to_language

    @override
    def check_is_machine(self) -> bool:
        return True
