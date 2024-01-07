from emmio.data import Data
from emmio.dictionary.core import Link
from emmio.language import Language, ENGLISH
from emmio.learn.core import Learning
from emmio.lexicon.core import Lexicon
from emmio.listen.core import Listening
from emmio.lists.frequency_list import FrequencyList
from emmio.user.data import UserData


class Analysis:
    def __init__(self, data: Data, user_data: UserData) -> None:
        self.data: Data = data
        self.user_data: UserData = user_data

    def analyze(
        self, language: Language, list_: FrequencyList, max_index: int = 2000
    ) -> None:
        learnings: list[Learning] = [
            x
            for x in self.user_data.get_learnings()
            if x.learning_language == language
        ]
        audio_providers = self.data.get_audio_collection(
            [
                {
                    "id": "wikimedia_commons",
                    "language": language.get_code(),
                },
                {"id": f"lingua_libre_{language.get_code()}"},
                {"id": "armtts"},
                {"id": "narakeet_hy"},
            ]
        )
        index = 0
        for word in list_.get_words():
            if (
                not all(language.has_symbol(x) for x in word)
                or word.lower() != word
            ):
                # NOT A WORD
                print(f"      {word:20s} NOT A WORD")
                continue

            dictionaries = self.data.get_dictionaries(
                [{"id": "en_wiktionary", "language": language.get_code()}]
            )
            items = dictionaries.get_items(word, language)

            links: set[Link] = set()
            has_definition = False
            for item in items:
                links |= item.get_links()
                for form in item.forms:
                    if (
                        ENGLISH in form.definitions
                        and form.definitions[ENGLISH]
                    ):
                        has_definition = True

            if links and not has_definition:
                print(
                    f"      {word:20s} FORM of "
                    + ", ".join([x.link_value for x in links])
                )
                continue

            not_common = False
            for item in items:
                if item.is_not_common(language):
                    not_common = True
                    break

            if not_common:
                print(f"      {word:20s} NOT COMMON")
                continue

            if not has_definition:
                print(f"      {word:20s} NO DEFINITION")
                continue

            line: str = f"{index:5d} {word:20s}"
            index += 1
            if index > max_index:
                break

            paths = audio_providers.get_paths(word)
            line += f" {len(paths)}"

            records = []

            for learning in learnings:
                if learning.has(word):
                    knowledge = learning.get_knowledge(word)
                    records += knowledge.get_records()

            listening: Listening = self.user_data.get_listening(
                language.get_code()
            )
            records += listening.get_records(word)

            lexicon: Lexicon = self.user_data.get_lexicon(language)
            records += lexicon.get_user_records(word)

            records = sorted(records, key=lambda x: x.time)

            line += " " + "".join(x.get_symbol() for x in records)
            print(line)
