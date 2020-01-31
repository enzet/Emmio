from emmio.dictionary import Dictionary
from emmio.lexicon import Lexicon, LexiconResponse


class DictionaryTest:
    def __init__(self, file_name: str, format_: str) -> None:
        """
        :param file_name: dictionary file path.
        :param format_: dictionary format: `dict`, `json`, or `yaml`.
        """
        self.file_name = file_name
        self.format_ = format_

    def test_run(self) -> None:
        dictionary = Dictionary(self.file_name, self.format_)
        assert dictionary.has("книга")
        assert dictionary.has("письмо")
        assert not dictionary.has("other")
        assert dictionary.get("книга") == "    book\n"
        assert dictionary.get("письмо") == "    letter\n"


class LexiconTest:
    def __init__(self, language: str, lexicon_file_name: str) -> None:
        self.language = language
        self.lexicon_file_name = lexicon_file_name
        self.lexicon = Lexicon(self.language, self.lexicon_file_name)

        self.lexicon.read()
        self.check()

        self.lexicon.write()
        self.lexicon.read()
        self.check()

    def check(self) -> None:
        assert self.lexicon.has("книга")
        assert self.lexicon.has("письмо")
        assert self.lexicon.has("Иван")

        assert self.lexicon.get("книга") == LexiconResponse.KNOW
        assert self.lexicon.get("письмо") == LexiconResponse.DO_NOT_KNOW
        assert self.lexicon.get("Иван") == LexiconResponse.NOT_A_WORD


def test_dict() -> None:
    DictionaryTest("test/simple.dict", "dict").test_run()


def test_lexicon() -> None:
    LexiconTest("ru", "test/lexicon.json")
