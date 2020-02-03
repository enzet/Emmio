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
        assert dictionary.get("other") == None
        assert dictionary.get("книга") == "    book\n"
        assert dictionary.get("письмо") == "    letter\n"


def check(lexicon: Lexicon) -> None:
    assert lexicon.has("книга")
    assert lexicon.has("письмо")
    assert lexicon.has("Иван")

    assert lexicon.get("книга") == LexiconResponse.KNOW
    assert lexicon.get("письмо") == LexiconResponse.DO_NOT_KNOW
    assert lexicon.get("Иван") == LexiconResponse.NOT_A_WORD


class LexiconTest:
    def __init__(self, language: str, lexicon_file_name: str) -> None:
        self.language = language
        self.lexicon_file_name = lexicon_file_name
        lexicon = Lexicon(self.language, self.lexicon_file_name)

        lexicon.read()
        check(lexicon)

        lexicon.file_name = "test/temp_lexicon.json"
        lexicon.write()
        lexicon.read()
        check(lexicon)


def test_dict() -> None:
    DictionaryTest("test/simple.dict", "dict").test_run()


def test_lexicon() -> None:
    LexiconTest("ru", "test/lexicon.json")
