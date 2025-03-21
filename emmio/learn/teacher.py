"""Teacher."""

import logging
from datetime import datetime

from emmio.audio.core import AudioCollection
from emmio.data import Data
from emmio.dictionary.core import (
    Dictionary,
    DictionaryCollection,
    DictionaryItem,
    SimpleDictionary,
)
from emmio.language import Language
from emmio.learn.config import Scheme
from emmio.learn.core import Knowledge, Learning, LearningSession, Response
from emmio.lexicon.core import AnswerType, Lexicon, LexiconResponse
from emmio.lists.core import List
from emmio.sentence.core import (
    SentenceElement,
    SentencesCollection,
    SentenceTranslations,
)
from emmio.ui import Element, Interface
from emmio.user.data import UserData

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

ESCAPE_CHARACTER: str = "_"  # "░"


class Teacher:
    """Teacher: manager for the learning process."""

    def __init__(
        self,
        interface: Interface,
        data: Data,
        user_data: UserData,
        learning: Learning,
        stop_after_answer: bool = False,
    ) -> None:
        self.interface: Interface = interface
        """User interface for learning."""

        self.data: Data = data
        """Data storage: dictionaries, sentences, audio."""

        self.user_data: UserData = user_data
        """User data storage: user responses."""

        self.learning: Learning = learning
        """Learning data."""

        self.scheme: Scheme | None = self.learning.config.scheme
        """Learning scheme: how to learn."""

        if not self.scheme:
            raise ValueError("No scheme found.")
        if not self.scheme.new_question:
            raise ValueError("No new question scheme found.")
        if not self.scheme.new_question.pick_from:
            raise ValueError("No question lists found.")

        # Load lexicons.
        self.check_lexicons: list[Lexicon] | None = None
        if self.scheme.new_question.check_lexicons:
            self.check_lexicons = [
                user_data.get_lexicon_by_id(x["id"])
                for x in self.scheme.new_question.check_lexicons
            ]
        self.ask_lexicon: Lexicon | None = None
        if self.scheme.new_question.ask_lexicon:
            self.ask_lexicon = user_data.get_lexicon_by_id(
                self.scheme.new_question.ask_lexicon["id"]
            )
        self.learning_lexicon: Lexicon | None = None
        if self.scheme.learning_lexicon:
            self.learning_lexicon = user_data.get_lexicon_by_id(
                self.scheme.learning_lexicon["id"]
            )

        # Load question lists.
        self.question_index: int = 0
        self.question_ids: list[tuple[str, List, int]] = []
        for list_config in self.scheme.new_question.pick_from:
            list_: List | None = data.get_list(list_config)
            if list_ is None:
                raise ValueError(
                    f'No list with id `{list_config["id"]}` found.'
                )
            for index, word in enumerate(list_.get_words()):
                self.question_ids.append((word, list_, index))

        # Load dictionaries for checking questions.
        self.dictionaries_to_check: DictionaryCollection
        if self.scheme.new_question.ignore_not_common:
            self.dictionaries_to_check = data.get_dictionaries(
                self.scheme.new_question.ignore_not_common
            )
        else:
            self.dictionaries_to_check = DictionaryCollection([])

        self.stop_after_answer: bool = stop_after_answer

        # TODO: remove.
        self.dictionaries: DictionaryCollection = data.get_dictionaries(
            self.learning.config.dictionaries
        )
        self.sentences: SentencesCollection
        if self.learning.config.sentences:
            self.sentences = data.get_sentences_collection(
                self.learning.config.sentences
            )
        else:
            self.sentences = SentencesCollection([])
        self.audio: AudioCollection = data.get_audio_collection(
            self.learning.config.audio
        )
        self.max_for_day: int = self.learning.config.max_for_day

    async def get_new_question(self) -> str | None:
        """Get new question to learn."""

        for question_id, list_, index in self.question_ids[
            self.question_index :
        ]:
            logging.info("%dth word from `%s`.", index, list_.get_name())
            self.question_index += 1

            good_question_id: bool = await self.check_question_id(question_id)
            if good_question_id:
                return question_id

        return None

    async def check_question_id(self, question_id: str) -> bool:
        """Check whether the learning process already has the word.

        Whether it was initially known or it is learning.

        :param question_id: question identifier
        :return: whether the word is known
        """
        if self.learning.has(question_id):
            if self.learning.is_initially_known(question_id):
                logging.info("Was initially known")
            else:
                logging.info("Already learning")
            return False

        if self.check_lexicons:
            for check_lexicon in self.check_lexicons:
                if (
                    check_lexicon.has(question_id)
                    and check_lexicon.get(question_id) != LexiconResponse.DONT
                ):
                    logging.info("Known in lexicon")
                    return False

        if self.dictionaries_to_check.dictionaries:
            if not self.check_common(question_id):
                return False

        return await self.check2(question_id)

    async def check2(self, question_id: str) -> bool:
        """Check whether the word should be asked.

        :param question_id: question identifier
        """
        # TODO: rename.
        # Check user lexicon. Skip the word if it was mark as known by user
        # while checking lexicon. This should be done after checking
        # definitions in dictionary, because if user answer is "no", the
        # learning process starts immediately.
        if self.check_lexicons:
            for check_lexicon in self.check_lexicons:
                if not check_lexicon.has(question_id):
                    continue

                if check_lexicon.get(question_id) != LexiconResponse.DONT:
                    logging.info("Known in lexicon")
                    return False

                logging.info("Lexicon response was DONT KNOW")
                # FIXME: user response may be DONT KNOW, but the word is
                #     still may be just a form or not common, so we don't
                #     want to learn it.
                return True

        # If `ask_lexicon` option is enabled, show the word to user before
        # testing.
        if self.ask_lexicon and not self.ask_lexicon.has(question_id):
            self.ask_lexicon.write()

            _, response, _ = await self.ask_lexicon.ask(
                self.interface,
                question_id,
                self.dictionaries,
                self.sentences,
            )
            if response is None:
                return False

            if response == LexiconResponse.DONT:
                logging.info("Lexicon response was DONT KNOW")
                return True

            logging.info("Lexicon response was KNOW")
            return False

        logging.info("Nothing is known about the word")
        return True

    async def check_common(self, question_id: str) -> bool:
        """Check whether the word is common.

        :param question_id: question identifier
        """
        # Request word definition in the dictionary.
        items: list[DictionaryItem] = (
            await self.dictionaries_to_check.get_items(
                question_id, self.learning.learning_language
            )
        )

        # Skip word if current dictionaries has no definitions for it.
        if not items:
            logging.info("No definition")
            return False

        # Skip word if it is known that it is solely a form of other words.
        items_no_links: list[DictionaryItem] = (
            await self.dictionaries_to_check.get_items(
                question_id, self.learning.learning_language, follow_links=False
            )
        )
        not_common: bool = False
        for item in items_no_links:
            for language in self.learning.base_languages:
                if item.has_definitions() and item.is_not_common(language):
                    not_common = True
                    break
        if not_common:
            logging.info("Not common")
            return False

        return True

    async def repeat(self, max_actions: int | None = None) -> bool:
        """Start repeating process.

        :param max_actions: maximum number of actions
        :return: whether to continue
        """
        actions: int = 0
        to_continue: bool
        session: LearningSession = LearningSession(
            type="repeat", start=datetime.now()
        )
        while True:
            if word := self.learning.get_next_question():
                code: str = await self.learn(
                    word, self.learning.knowledge[word]
                )
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
            self.interface.print(
                f"{actions} actions made in {session.get_time()}"
            )

        return to_continue

    async def learn_new(self, max_actions: int | None = None) -> bool:
        """Start learning new words.

        :param max_actions: maximum number of actions
        :return: whether to continue
        """
        actions: int = 0
        to_continue: bool
        session: LearningSession = LearningSession(
            type="learn_new", start=datetime.now()
        )
        while True:
            if (
                self.learning.count_questions_added_today() < self.max_for_day
                and (question_id := await self.get_new_question()) is not None
            ):
                code: str = await self.learn(question_id, None)
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
            self.interface.print(f"{actions} actions made")

        return to_continue

    async def repeat_and_learn_new(
        self, max_actions: int | None = None
    ) -> bool:
        """Start repeating and learning new words.

        :param max_actions: maximum number of actions
        :return: whether to continue
        """
        actions: int = 0
        to_continue: bool
        session: LearningSession = LearningSession(
            type="repeat_and_learn_new", start=datetime.now()
        )
        code: str

        while True:
            # Repeat words.
            if word := self.learning.get_next_question():
                code = await self.learn(word, self.learning.knowledge[word])
                if code != "bad question":
                    self.learning.write()
                if code == "stop":
                    to_continue = False
                    break
                actions += 1
                if max_actions is not None and actions >= max_actions:
                    to_continue = True
                    break

            # Learn new words.
            elif (
                self.learning.count_questions_added_today() < self.max_for_day
                and (question_id := await self.get_new_question()) is not None
            ):
                code = await self.learn(question_id, None)
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
            self.interface.print(f"{actions} actions made")

        return to_continue

    def play(self, word: str) -> None:
        """Play the audio pronunciation of the word.

        :param word: word to play
        """
        self.audio.play(word)

    def print_sentence(
        self,
        word: str,
        rated_sentences: list[tuple[float, SentenceTranslations]],
        index: int,
        show_index: bool = False,
        max_translations: int = 3,
    ) -> None:
        """Print sentence and its translations.

        :param word: learning word that should be hidden
        :param rated_sentences: example sentences with the learning word
        :param index: current index in rated sentences
        :param show_index: show current sentence index
        :param max_translations: maximum number of translations to show
        """
        _, sentence_translations = rated_sentences[index]
        text: str = sentence_translations.sentence.text
        if show_index:
            text += f" ({index + 1}/{len(rated_sentences)})"

        result: str = ""

        words: list[tuple[str, SentenceElement]] = (
            sentence_translations.sentence.get_words(
                self.learning.learning_language
            )
        )
        all_known: bool = True

        for current_word, type_ in words:
            if type_ == SentenceElement.SYMBOL:
                result += current_word
            elif current_word.lower() == word:
                result += ESCAPE_CHARACTER * len(current_word)
            elif self.user_data.is_known_or_not_a_word(
                current_word.lower(), self.learning.learning_language
            ):
                result += "[green]" + current_word + "[/green]"
            else:
                result += "[grey]" + current_word + "[/grey]"
                all_known = False

        self.interface.print(result)

        translations: list[str] = [
            x.text
            for x in sentence_translations.translations[:max_translations]
        ]
        if all_known:
            self.interface.button("Reveal translations")
        self.interface.print("\n".join(translations))

    async def learn(self, word: str, knowledge: Knowledge | None) -> str:
        """Start learning the word.

        :param word: word to learn
        :param knowledge: knowledge of the word
        """
        ids_to_skip: set[int] = set()
        translation: list[Element] = []

        if knowledge:
            self.interface.print(
                "".join(x.get_symbol() for x in knowledge.get_responses())
            )
        else:
            self.interface.print("New question.")

        alternative_forms: set[str] = set()

        if self.scheme and self.scheme.actions:
            for action in self.scheme.actions:
                if action["type"] == "show_question_id":
                    self.interface.print(word)
                elif action["type"] == "check_translation":
                    pass
                    # TODO: implement.
            return "continue"  # FIXME

        items: list[DictionaryItem] = await self.dictionaries.get_items(
            word, self.learning.learning_language
        )

        words_to_hide: set[str] = set()
        for item in items:
            words_to_hide.add(item.word)
            for link in item.get_links():
                words_to_hide.add(link.link_value)

        if items:
            for item in items:
                translation = item.to_text(
                    self.learning.base_languages,
                    False,
                    words_to_hide=words_to_hide,
                    only_common=False,
                )
                for element in translation:
                    self.interface.print(element)
            alternative_forms = set(x.link_value for x in items[0].get_links())
        else:
            self.interface.print("No translations.")
            self.interface.print("")

        index: int = 0
        rated_sentences: list[tuple[float, SentenceTranslations]] = (
            self.sentences.filter_by_word_and_rate(
                word, self.user_data.is_known, ids_to_skip, 120
            )
        )
        if index < len(rated_sentences):
            self.print_sentence(word, rated_sentences, index)

        request_time: datetime = datetime.now()
        answer: str

        while True:
            answer = self.interface.get_word(
                word, alternative_forms, self.learning.learning_language
            )
            sentence_id: int = (
                rated_sentences[index][1].sentence.id_
                if index < len(rated_sentences)
                else 0
            )

            # Preprocess answer.
            answer = self.learning.learning_language.decode_text(answer)

            if answer == word:
                self.learning.register(
                    Response.RIGHT, sentence_id, word, request_time=request_time
                )
                if items:
                    for item in items:
                        translation = item.to_text(self.learning.base_languages)
                        for element in translation:
                            self.interface.print(element)

                self.play(word)

                if self.stop_after_answer:
                    new_answer = self.interface.input("> ")
                    while new_answer:
                        await self.process_command(
                            new_answer, word, sentence_id
                        )
                        new_answer = self.interface.input("> ")

                self.learning.write()

                return "continue"

            if answer in ["p", "/postpone"]:
                self.learning.postpone(word)
                return "continue"

            if answer == "/skip":
                self.learning.register(Response.SKIP, 0, word)
                self.learning.write()
                print("Word is no longer in the learning process.")
                return "continue"

            if answer.startswith("/skip "):
                _, word_to_skip = answer.split(" ")
                self.learning.register(Response.SKIP, 0, word_to_skip)
                self.learning.write()
                return "continue"

            if answer == "/stop":
                return "stop"

            if answer.startswith("/know "):
                _, command_word = answer.split(" ")
                # TODO: sanitize user input.
                if self.learning_lexicon:
                    self.learning_lexicon.register(
                        command_word,
                        LexiconResponse.KNOW,
                        to_skip=False,
                        request_time=None,
                        answer_type=AnswerType.USER_ANSWER,
                    )
                    self.learning_lexicon.write()
                else:
                    self.interface.print("No lexicon specified.")

            if answer.startswith("/not_a_word "):
                _, command_word = answer.split(" ")
                # TODO: sanitize user input.
                if self.learning_lexicon:
                    self.learning_lexicon.register(
                        command_word,
                        LexiconResponse.NOT_A_WORD,
                        to_skip=False,
                        request_time=None,
                        answer_type=AnswerType.USER_ANSWER,
                    )
                    self.learning_lexicon.write()
                else:
                    self.interface.print("No lexicon specified.")

            if answer in [
                "/no",
                "n",  # Short for no, non, nein.
                "н",  # Short for нет.
                "ո",  # Short for ոչ.
            ]:
                self.interface.print(word)
                if items:
                    for item in items:
                        translation = item.to_text(self.learning.base_languages)
                        for element in translation:
                            self.interface.print(element)
                self.interface.print(word)
                self.play(word)

                self.learning.register(
                    Response.WRONG, sentence_id, word, request_time=request_time
                )
                new_answer = self.interface.input("> ")
                while new_answer:
                    if new_answer in ["s", "skip"]:
                        self.learning.register(Response.SKIP, sentence_id, word)
                        break
                    await self.process_command(new_answer, word, sentence_id)
                    new_answer = self.interface.input("> ")

                self.learning.write()

                return "continue"

            if answer == "":
                index += 1
                if index < len(rated_sentences):
                    self.print_sentence(word, rated_sentences, index)
                elif index == len(rated_sentences):
                    self.interface.print("No more sentences.")

    async def process_command(
        self, command: str, word: str, sentence_id: int
    ) -> None:
        """Process the command.

        :param command: user command
        :param word: current learning word
        :param sentence_id: sentence identifier
        """
        if command in ["s", "/skip"]:
            self.learning.register(Response.SKIP, sentence_id, word)
            print(f'Word "{word}" is no longer in the learning process.')
        elif command.startswith("/hint "):
            _, language_code, definition = command.split(" ", maxsplit=2)
            dictionary_id: str = (
                f"{self.learning.learning_language}_{language_code}_"
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
            language: Language = Language.from_code(language_code)
            items: list[DictionaryItem] = await self.dictionaries.get_items(
                word_to_define, language
            )
            for item in items:
                for element in item.to_text([language]):
                    self.interface.print(element)
