from engine.dictionary import Dictionary
from engine.lexicon import Lexicon, LexiconResponse


class DictionaryTest:
    def __init__(self, file_name: str, format_: str) -> None:
        self.file_name = file_name
        self.format_ = format_

    def test_run(self) -> None:
        dictionary = Dictionary(self.file_name, self.format_)
        assert(dictionary.has("книга"))
        assert(dictionary.has("письмо"))
        assert(not dictionary.has("other"))
        assert(dictionary.get("книга") == "    book\n")
        assert(dictionary.get("письмо") == "    letter\n")


class LexiconTest:
    def __init__(self, language: str, lexicon_file_name: str, fast: bool) \
            -> None:
        self.language = language
        self.lexicon_file_name = lexicon_file_name
        self.fast = fast

    def test_run(self) -> None:
        lexicon = Lexicon(self.language, self.lexicon_file_name)
        if self.fast:
            lexicon.read_fast()
        else:
            lexicon.read()

        assert(lexicon.has("книга"))
        assert(lexicon.has("письмо"))
        assert(lexicon.has("Иван"))
        assert(lexicon.get("книга") == LexiconResponse.KNOW)
        assert(lexicon.get("письмо") == LexiconResponse.DO_NOT_KNOW)
        assert(lexicon.get("Иван") == LexiconResponse.NOT_A_WORD)


def test_dict():
    DictionaryTest("test/simple.dict", "dict").test_run()


def test_lexicon_1():
    LexiconTest("ru", "test/lexicon.yml", True).test_run()


def test_lexicon_2():
    LexiconTest("ru", "test/lexicon.yml", False).test_run()
