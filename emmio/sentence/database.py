import bz2
import logging
from pathlib import Path

from emmio.database import Database
from emmio.language import Language
from emmio.sentence.core import Sentence
from emmio.util import download


class SentenceDatabase(Database):
    """Database with tables:

    Tables <language>_sentences:
        ID: INTEGER, SENTENCE: TEXT
    """

    def create(self, language: Language, cache_path: Path) -> None:
        """Create table for sentences written in the specified language.

        :param language: language of the sentences
        :param cache_path: path to the cache directory
        """

        table_id: str = f"{language.get_code()}_sentences"
        file_path = cache_path / f"{language.get_part3()}_sentences.tsv"

        if not file_path.exists():
            zip_path: Path = (
                cache_path / f"{language.get_part3()}_sentences.tsv.bz2"
            )

            # Tatoeba uses ISO 639-3 codes, but for some languages it uses
            # individual codes, instead of inclusive ones. E.g. `nob` (individual
            # code for Norwegian Bokmål) instead of `nor` (inclusive code for
            # Norwegian).
            if not zip_path.is_file():
                download(
                    f"https://downloads.tatoeba.org/exports/per_language/"
                    f"{language.get_part3()}/{language.get_part3()}"
                    f"_sentences.tsv.bz2",
                    zip_path,
                )

                # Check if file has appropriate size.
                if zip_path.stat().st_size < 1000:
                    logging.error(
                        "File `%s` seems to be empty. Removing it.", zip_path
                    )
                    # Remove zip file.
                    zip_path.unlink()
                    return

                with bz2.open(zip_path) as zip_file:
                    with file_path.open("wb+") as cache_file:
                        logging.info(
                            "Unzipping sentences for `%s` from `%s` to `%s`.",
                            language.get_name(),
                            zip_path,
                            file_path,
                        )
                        cache_file.write(zip_file.read())

        self.cursor.execute(
            f"CREATE TABLE {table_id} (id integer primary key, sentence text)"
        )
        logging.info("Reading table `%s`...", table_id)
        with file_path.open(encoding="utf-8") as input_file:
            for line in input_file.readlines():
                id_, _, sentence = line[:-1].split("\t")
                self.cursor.execute(
                    f"INSERT INTO {table_id} VALUES (?,?)", (id_, sentence)
                )
        self.connection.commit()

    def get_sentence(self, language: Language, sentence_id: int) -> Sentence:
        """Get sentence by identifier.

        :param language: language of the sentence
        :param sentence_id: sentence unique integer identifier
        """
        table_id: str = f"{language.get_code()}_sentences"
        id_, text = self.cursor.execute(
            f"SELECT * FROM {table_id} WHERE id=?", (sentence_id,)
        ).fetchone()
        return Sentence(id_, text)

    def get_sentences(
        self, language: Language, cache_path: Path
    ) -> dict[int, Sentence]:
        """Get all sentences written in the specified language.

        :param language: language of the sentences
        :param cache_path: path to the cache directory
        :returns: a mapping from sentence identifiers to sentences
        """
        table_id: str = f"{language.get_code()}_sentences"

        # Check if table exists.
        if not self.has_table(table_id):
            logging.error("Table `%s` does not exist.", table_id)
            return {}

        result: dict[int, Sentence] = {}
        if not self.has_table(table_id):
            self.create(language, cache_path)
        for row in self.cursor.execute(f"SELECT * FROM {table_id}"):
            id_, text = row
            result[id_] = Sentence(id_, text)
        return result
