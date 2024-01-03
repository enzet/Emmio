"""Teacher."""
import logging
from datetime import datetime

from emmio.audio.core import AudioCollection
from emmio.data import Data
from emmio.dictionary.core import (
    DictionaryItem,
    DictionaryCollection,
    Dictionary,
    SimpleDictionary,
)
from emmio.language import construct_language
from emmio.learn.core import Learning, Response, Knowledge, LearningSession
from emmio.lexicon.core import (
    LexiconLog,
    LexiconResponse,
    WordSelection,
    Lexicon,
    AnswerType,
)
from emmio.lists.core import List
from emmio.sentence.core import SentenceTranslations, SentencesCollection
from emmio.ui import Interface
from emmio.user.data import UserData

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

ESCAPE_CHARACTER: str = "_"  # "░"


class Teacher:
    def __init__(
        self,
        interface: Interface,
        data: Data,
        user_data: UserData,
        learning: Learning,
        stop_after_answer: bool = False,
    ) -> None:
        self.interface: Interface = interface
        self.data: Data = data
        self.user_data: UserData = user_data

        self.learning: Learning = learning
        self.lexicon: Lexicon = user_data.get_lexicon(
            self.learning.learning_language
        )
        self.word_index: int = 0
        self.words: list[tuple[str, List, int]] = []
        for list_id in self.learning.config.lists:
            list_ = data.get_list(list_id)
            for index, word in enumerate(list_.get_words()):
                self.words.append((word, list_, index))

        self.stop_after_answer: bool = stop_after_answer

        self.dictionaries: DictionaryCollection = data.get_dictionaries(
            self.learning.config.dictionaries
        )
        self.sentences: SentencesCollection = data.get_sentences_collection(
            self.learning.config.sentences
        )
        self.audio: AudioCollection = data.get_audio_collection(
            self.learning.config.audio
        )
        self.max_for_day: int = self.learning.config.max_for_day

    @staticmethod
    def get_smallest_interval() -> timedelta:
        return timedelta(minutes=5)

    @staticmethod
    def increase_interval(interval: timedelta) -> timedelta:
        if interval == timedelta(minutes=5):
            return timedelta(hours=8)
        elif interval == timedelta(hours=8):
            return timedelta(days=1)
        return interval * 2

    def get_new_question(self) -> str | None:
        for question_id, list_, index in self.words[self.word_index :]:
            logging.info(f"{index}th word from {list_.get_name()}")

            self.word_index += 1

            # Check whether the learning process already has the word: whether
            # it was initially known or it is learning.
            if self.learning.has(question_id):
                if self.learning.is_initially_known(question_id):
                    logging.info("Was initially known")
                else:
                    logging.info("Already learning")
                continue

            # Check user lexicon. Skip the word if it was mark as known by user
            # while checking lexicon.
            if (
                self.learning.config.check_lexicon
                and self.lexicon
                and self.lexicon.has(question_id)
            ):
                if self.lexicon.get(question_id) != LexiconResponse.DONT:
                    logging.info("Known in lexicon")
                    continue

            # Request word definition in the dictionary.
            items: list[DictionaryItem] = self.dictionaries.get_items(
                question_id, self.learning.learning_language
            )

            # Skip word if current dictionaries has no definitions for it.
            if not items:
                logging.info("No definition")
                continue

            # Skip word if it is known that it is solely a form of other words.
            items_no_links: list[DictionaryItem] = self.dictionaries.get_items(
                question_id, self.learning.learning_language, follow_links=False
            )

            not_common = False
            for item in items_no_links:
                for language in self.learning.base_languages:
                    if item.has_definitions() and item.is_not_common(language):
                        not_common = True
                        break
            if not_common:
                logging.info("Not common")
                continue

            # Check user lexicon. Skip the word if it was mark as known by user
            # while checking lexicon. This should be done after checking
            # definitions in dictionary, because if user answer is "no", the
            # learning process starts immediately.
            if (
                self.learning.config.check_lexicon
                and self.lexicon
                and self.lexicon.has(question_id)
            ):
                if self.lexicon.get(question_id) != LexiconResponse.DONT:
                    logging.info("Known in lexicon")
                    continue
                else:
                    logging.info("Lexicon response was DONT KNOW")
                    # FIXME: user response may be DONT KNOW, but the word is
                    #        still may be just a form or not common, so we don't
                    #        want to learn it.
                    return question_id

            # If `ask_lexicon` option is enabled, show the word to user before
            # testing.
            if self.learning.config.ask_lexicon and not self.lexicon.has(
                question_id
            ):
                if not self.lexicon.has_log("log_ex"):
                    self.lexicon.add_log(
                        LexiconLog("log_ex", WordSelection("top"))
                    )
                self.lexicon.write()

                _, response, _ = self.lexicon.ask(
                    self.interface,
                    question_id,
                    [],
                    self.dictionaries,
                    log_name="log_ex",
                )
                if response is None:
                    return None

                if response == LexiconResponse.DONT:
                    logging.info("Lexicon response was DONT KNOW")
                    return question_id
                else:
                    logging.info("Lexicon response was KNOW")
                    continue

            logging.info("Nothing is known about the word")
            return question_id

        return None

    def __start(self) -> bool:
        """Start the learning process: repeat old questions and learn new ones.

        :return: true if the learning process was finished, false if the
            learning process was interrupted by the user.
        """
        while True:
            # Learn new questions.

            if (
                self.learning.count_questions_added_today() < self.max_for_day
                and (question_id := self.get_new_question()) is not None
            ):
                code: str = self.learn(question_id, timedelta())
                if code == "stop":
                    return False
                continue

            # Repeat old questions.

            if (question_id := self.learning.get_next_question()) is not None:
                code: str = self.learn(
                    question_id, self.learning.knowledge[question_id].interval
                )
                if code == "stop":
                    return False

        return True

    def repeat(self, max_actions: int | None = None) -> bool:
        actions: int = 0
        to_continue: bool
        session: LearningSession = LearningSession(
            type="repeat", start=datetime.now()
        )
        while True:
            if word := self.learning.get_next_question():
                code: str = self.learn(word, self.learning.knowledge[word])
                if code != "bad question":
                    self.learning.write()
                if code == "stop":
                    to_continue = False
                    break
                actions += 1
                if max_actions is not None and actions >= max_actions:
                    to_continue = True
                    break
            else:
                to_continue = True
                break

        if actions:
            session.end_session(datetime.now(), actions)
            self.learning.process.sessions.append(session)
            self.learning.write()
            self.interface.box(f"{actions} actions made")

        return to_continue

    def learn_new(self, max_actions: int | None = None) -> bool:
        actions: int = 0
        to_continue: bool
        session: LearningSession = LearningSession(
            type="learn_new", start=datetime.now()
        )
        while True:
            if (
                self.learning.count_questions_added_today() < self.max_for_day
                and (question_id := self.get_new_question()) is not None
            ):
                code: str = self.learn(question_id, None)
                if code != "bad question":
                    self.learning.write()
                if code == "stop":
                    to_continue = False
                    break
                actions += 1
                if max_actions is not None and actions >= max_actions:
                    to_continue = True
                    break
            else:
                to_continue = True
                break

        if actions:
            session.end_session(datetime.now(), actions)
            self.learning.process.sessions.append(session)
            self.learning.write()
            self.interface.box(f"{actions} actions made")

        return to_continue

    def play(self, word: str):
        self.audio.play(word, self.learning.learning_language)

    def print_sentence(
        self,
        word: str,
        rated_sentences: list[tuple[float, SentenceTranslations]],
        index,
        show_index: bool = False,
        max_translations: int = 3,
    ):
        """Print sentence and its translations.

        :param word: learning word that should be hidden
        :param rated_sentences: example sentences with the learning word
        :param index: current index in rated sentences
        :param show_index: show current sentence index
        :param max_translations: maximum number of translations to show
        """
        rating, sentence_translations = rated_sentences[index]
        text: str = sentence_translations.sentence.text
        if show_index:
            text += f" ({index + 1}/{len(rated_sentences)})"

        result: str = ""

        sentence_translations: SentenceTranslations
        words: list[tuple[str, str]] = sentence_translations.sentence.get_words(
            self.learning.learning_language
        )
        all_known: bool = True

        for current_word, type_ in words:
            if type_ == "symbol":
                result += current_word
            elif current_word.lower() == word:
                result += ESCAPE_CHARACTER * len(current_word)
            elif self.user_data.is_known_or_not_a_word(
                current_word.lower(), self.learning.learning_language
            ):
                result += "\033[32m" + current_word + "\033[0m"
            else:
                result += "\033[2m" + current_word + "\033[0m"
                all_known = False

        self.interface.print(result)

        translations: list[text] = [
            x.text
            for x in sentence_translations.translations[:max_translations]
        ]
        if all_known:
            input("[reveal translations]")
        print("\n".join(translations))

    def learn(self, word: str, knowledge: Knowledge | None) -> str:
        ids_to_skip: set[int] = set()
        # if word in self.data.exclude_sentences:
        #     ids_to_skip = set(self.data.exclude_sentences[word])

        statistics: str = ""
        if knowledge:
            statistics += (
                "".join(x.get_symbol() for x in knowledge.get_responses())
                + "\n"
            )
        else:
            statistics = "New question  "

        statistics += (
            f"skipped: {self.learning.get_skipping_counter(word)}  "
            f"added today: {self.learning.count_questions_added_today()}  "
            f"to repeat: {self.learning.count_questions_to_repeat()}"
        )

        alternative_forms: set[str] = set()
        exclude_translations: set[str] = set()

        # if word in self.data.exclude_translations:
        #     exclude_translations = set(self.data.exclude_translations[word])

        items: list[DictionaryItem] = self.dictionaries.get_items(
            word, self.learning.learning_language
        )

        words_to_hide: set[str] = set()
        for item in items:
            words_to_hide.add(item.word)
            for link in item.get_links():
                words_to_hide.add(link.link_value)

        if items:
            translation_list = [
                x.to_str(
                    self.learning.base_languages,
                    self.interface,
                    False,
                    words_to_hide=words_to_hide | exclude_translations,
                    hide_translations=exclude_translations,
                    only_common=False,
                )
                for x in items
            ]
            self.interface.print(
                statistics + "\n" + "\n".join(translation_list)
            )
            alternative_forms: set[str] = set(
                x.link_value for x in items[0].get_links()
            )
        else:
            self.interface.print(statistics + "\n" + "No translations.")

        if index < len(rated_sentences):
            self.print_sentence(word, rated_sentences, index)

        while True:
            answer: str = self.interface.get_word(
                word, alternative_forms, self.learning.learning_language
            )
            sentence_id: int = (
                rated_sentences[index][1].sentence.id_
                if index < len(rated_sentences)
                else 0
            )

            # Preprocess answer.
            answer: str = self.learning.learning_language.decode_text(answer)

            if answer == word:
                self.learning.register(Response.RIGHT, sentence_id, word)
                if items:
                    string_items: list[str] = [
                        x.to_str(self.learning.base_languages, self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))

                self.play(word)

                if self.stop_after_answer:
                    new_answer = self.interface.input("> ")
                    while new_answer:
                        self.process_command(new_answer, word, sentence_id)
                        new_answer = self.interface.input("> ")

                self.learning.write()

                return "continue"

            if answer in ["p", "/postpone"]:
                self.learning.postpone(word)
                return "continue"

            if answer == "/skip":
                self.learning.register(Response.SKIP, 0, word)
                self.learning.write()
                print(f"Word is no longer in the learning process.")
                return "continue"

            if answer.startswith("/skip "):
                _, word_to_skip = answer.split(" ")
                self.learning.register(Response.SKIP, 0, word_to_skip)
                self.learning.write()
                return "continue"

            if answer == "/stop":
                return "stop"

            if answer == "/exclude":
                self.data.exclude_sentence(word, sentence_id)
                self.learning.postpone(word)
                return "continue"

            if answer.startswith("/hide "):
                self.data.exclude_translation(
                    word, " ".join(answer.split(" ")[1:])
                )
                self.learning.postpone(word)
                return "continue"

            if answer.startswith("/btt "):
                _, w, t = answer.split(" ")
                self.data.exclude_translation(w, t)
                continue

            if answer.startswith("/know "):
                command, command_word = answer.split(" ")
                lexicon: Lexicon = self.user_data.get_lexicon(
                    self.learning.learning_language
                )
                if not self.lexicon.has_log("log_ex"):
                    self.lexicon.add_log(
                        LexiconLog("log_ex", WordSelection("top"))
                    )
                lexicon.register(
                    command_word,
                    LexiconResponse.KNOW,
                    to_skip=False,
                    log_name="log_ex",
                    answer_type=AnswerType.USER_ANSWER,
                )
                lexicon.write()

            if answer.startswith("/not_a_word "):
                command, command_word = answer.split(" ")
                lexicon: Lexicon = self.user_data.get_lexicon(
                    self.learning.learning_language
                )
                lexicon.register(
                    command_word,
                    LexiconResponse.NOT_A_WORD,
                    to_skip=False,
                    log_name="log_ex",
                    answer_type=AnswerType.USER_ANSWER,
                )
                lexicon.write()

            if answer in [
                "/no",
                "n",  # Short for no, non, nein.
                "н",  # Short for нет.
                "ո",  # Short for ոչ.
            ]:
                self.interface.box(word)
                if items:
                    string_items: list[str] = [
                        x.to_str(self.learning.base_languages, self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))
                self.interface.box(word)
                self.play(word)

                self.learning.register(Response.WRONG, sentence_id, word)
                new_answer = self.interface.input("> ")
                while new_answer:
                    if new_answer in ["s", "skip"]:
                        self.learning.register(Response.SKIP, sentence_id, word)
                        break
                    self.process_command(new_answer, word, sentence_id)
                    new_answer = self.interface.input("> ")

                self.learning.write()

                return "continue"

            if answer == "":
                index += 1
                if index < len(rated_sentences):
                    self.print_sentence(word, rated_sentences, index)
                elif index == len(rated_sentences):
                    self.interface.print("No more sentences.")

    def process_command(self, command: str, word: str, sentence_id: int):
        if command in ["s", "/skip"]:
            self.learning.register(Response.SKIP, sentence_id, word)
            print(f'Word "{word}" is no longer in the learning process.')
        elif command.startswith("/hint "):
            _, language, definition = command.split(" ", maxsplit=2)
            dictionary_id: str = (
                f"{self.learning.learning_language}_{language}_"
                f"{self.user_data.user_id}"
            )
            dictionary: Dictionary | None = self.dictionaries.get_dictionary(
                dictionary_id
            )
            if dictionary and isinstance(dictionary, SimpleDictionary):
                dictionary.add_simple(word, definition)
                dictionary.write()
                print(f"Hint written to `{dictionary_id}`.")
            else:
                print(f"No personal dictionary `{dictionary_id}` found.")
        elif command.startswith("/define "):
            _, language_code, word_to_define = command.split(" ", maxsplit=2)
            language = construct_language(language_code)
            items = self.dictionaries.get_items(word_to_define, language)
            for item in items:
                item.to_str([language], self.interface)
