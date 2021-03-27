from emmio.language import Language
from emmio.learning import Learning
from emmio.lexicon import Lexicon, LexiconResponse
from emmio.sentence import SentenceDatabase
from emmio.text import Text
from emmio.frequency import FrequencyList, FrequencyDatabase


def check(lexicon: Lexicon) -> None:
    assert lexicon.has("книга")
    assert lexicon.has("письмо")
    assert lexicon.has("Иван")

    assert lexicon.get("книга") == LexiconResponse.KNOW
    assert lexicon.get("письмо") == LexiconResponse.DO_NOT_KNOW
    assert lexicon.get("Иван") == LexiconResponse.NOT_A_WORD


def do_lexicon(language: Language, lexicon_file_name: str) -> None:
    lexicon = Lexicon(language, lexicon_file_name)
    check(lexicon)
    lexicon.write()

    lexicon = Lexicon(language, lexicon_file_name)
    check(lexicon)


def test_lexicon() -> None:
    do_lexicon(Language("ru"), "test/lexicon.json")


def test_text() -> None:
    text = Text(
        "It’s not the history of man… that’s the history of Gods.", "en")
    frequency_list: FrequencyList = text.get_frequency_list()

    assert frequency_list.get_occurrences("it") == 1
    assert frequency_list.get_occurrences("it’s") == 0
    assert frequency_list.get_occurrences("It") == 0
    assert frequency_list.get_occurrences("the") == 2
    assert frequency_list.get_occurrences("s") == 2
    assert len(frequency_list) == 9


def test_teacher() -> None:
    learning = Learning("test/learning.json", "test_course")
    sentence_db = SentenceDatabase("test/sentence.db")
    frequency_db = FrequencyDatabase("test/frequency.db")
