"""Database with sentences from Tatoeba."""

import bz2
import logging
from pathlib import Path

from emmio.database import Database
from emmio.language import Language
from emmio.sentence.core import Sentence
from emmio.util import download

logger: logging.Logger = logging.getLogger(__name__)


class TatoebaDatabase(Database):
    """Database for sentences.

    Database schema is as follows.

    Tables <language>_sentences:
        ID: INTEGER, SENTENCE: TEXT

    Table links:
        ID_1: INTEGER, ID_2: INTEGER
    """

    def __init__(self, database_file_path: Path, cache_path: Path) -> None:
        """Initialize the database.

        :param database_file_path: path to the database file
        :param cache_path: path to the cache directory
        """
        super().__init__(database_file_path)
        self.cache_path: Path = cache_path

    def load_links(self) -> None:
        """Load links from cache."""
        links_csv_path: Path = self.cache_path / "links.csv"

        # If links file doesn't exist in cache, download and unzip it.
        if not links_csv_path.exists():
            # Download zipped links file if it doesn't exist in cache.
            links_zip_path: Path = self.cache_path / "links.tar.bz2"
            if not links_zip_path.exists():
                download(
                    "https://downloads.tatoeba.org/exports/links.tar.bz2",
                    links_zip_path,
                )

            # Unzip links file to `links.csv`.
            if links_zip_path.exists():
                with (
                    bz2.open(links_zip_path) as zip_file,
                    links_csv_path.open("wb+") as cache_file,
                ):
                    logger.info("Unzipping links file...")
                    cache_file.write(zip_file.read())
            else:
                message = "Failed to download links file."
                raise ValueError(message)

            # Remove zipped links file.
            links_zip_path.unlink()

        self.cursor.execute("CREATE TABLE links (id_1 integer, id_2 integer)")

        with links_csv_path.open(encoding="utf-8") as input_csv:
            lines = input_csv.readlines()

        for line in lines:
            id_1, id_2 = map(int, line[:-1].split("\t"))
            self.cursor.execute("INSERT INTO links VALUES (?, ?)", (id_1, id_2))
        self.connection.commit()

    def load_language(self, language: Language, cache_path: Path) -> None:
        """Create table for sentences written in the specified language.

        :param language: language of the sentences
        :param cache_path: path to the cache directory
        """
        table_id: str = f"{language.get_code()}_sentences"
        file_path: Path = cache_path / f"{language.get_part3()}_sentences.tsv"

        if not file_path.exists():
            zip_path: Path = (
                cache_path / f"{language.get_part3()}_sentences.tsv.bz2"
            )

            # Tatoeba uses ISO 639-3 codes, but for some languages it uses
            # individual codes, instead of inclusive ones. E.g. `nob`
            # (individual code for Norwegian Bokmål) instead of `nor` (inclusive
            # code for Norwegian).
            if not zip_path.is_file():
                download(
                    f"https://downloads.tatoeba.org/exports/per_language/"
                    f"{language.get_part3()}/{language.get_part3()}"
                    f"_sentences.tsv.bz2",
                    zip_path,
                )

                # Check if file has appropriate size.
                if zip_path.stat().st_size < 1000:  # noqa: PLR2004
                    logger.error(
                        "File `%s` seems to be empty. Removing it.", zip_path
                    )
                    # Remove zip file.
                    zip_path.unlink()
                    return

                with (
                    bz2.open(zip_path) as zip_file,
                    file_path.open("wb+") as cache_file,
                ):
                    logger.info(
                        "Unzipping sentences for `%s` from `%s` to `%s`.",
                        language.get_name(),
                        zip_path,
                        file_path,
                    )
                    cache_file.write(zip_file.read())

        self.cursor.execute(
            f"CREATE VIRTUAL TABLE {table_id} USING fts5(sentence)"
        )
        logger.info("Reading table `%s`...", table_id)
        with file_path.open(encoding="utf-8") as input_file:
            for line in input_file.readlines():
                id_, _, sentence = line[:-1].split("\t")
                self.cursor.execute(
                    f"INSERT INTO {table_id}(rowid, sentence) VALUES (?,?)",  # noqa: S608
                    (int(id_), sentence),
                )
        self.connection.commit()

    def get_sentence(
        self, language: Language, sentence_id: int
    ) -> Sentence | None:
        """Get sentence by identifier.

        :param language: language of the sentence
        :param sentence_id: sentence unique integer identifier
        """
        table_id: str = f"{language.get_code()}_sentences"

        # If table doesn't exist, load it.
        if not self.has_table(table_id):
            self.load_language(language, self.cache_path)

        result = self.cursor.execute(
            f"SELECT rowid, sentence FROM {table_id} WHERE rowid=?",  # noqa: S608
            (sentence_id,),
        ).fetchone()
        if result:
            id_, text = result
            return Sentence(id_, text)
        logger.warning("No sentence with id %d in %s.", sentence_id, table_id)
        return None

    def get_sentences(self, language: Language) -> dict[int, Sentence]:
        """Get all sentences written in the specified language.

        :param language: language of the sentences
        :return: a mapping from sentence identifiers to sentences
        """
        table_id: str = f"{language.get_code()}_sentences"

        # If table doesn't exist, load it.
        if not self.has_table(table_id):
            self.load_language(language, self.cache_path)

        result: dict[int, Sentence] = {}
        for id_, text in self.cursor.execute(
            f"SELECT rowid, sentence FROM {table_id}"  # noqa: S608
        ):
            result[id_] = Sentence(id_, text)
        return result

    # def get_sentence_by_word(self, word: str, language: Language) -> Sentence:
    #     """Get sentence by word.

    #     :param word: word to search for
    #     :param language: language of the sentence
    #     """
