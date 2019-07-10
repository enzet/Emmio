from engine.dictionary import Dictionary
from engine.lexicon import Lexicon, LexiconResponse


class Test:
    def __init__(self, name: str):
        self.name = name
        self.assert_count = 0
        self.passed = True

    def assert_(self, condition: bool):
        if condition:
            print(" OK ")
        else:
            print("FAIL")
            self.passed = False

    def get_name(self):
        return self.name


class DictionaryTest(Test):
    def __init__(self, name: str, file_name: str, format_: str):
        super().__init__(name)
        self.file_name = file_name
        self.format_ = format_

    def run(self) -> bool:
        dictionary = Dictionary(self.file_name, self.format_)
        self.assert_(dictionary.has("книга"))
        self.assert_(dictionary.has("письмо"))
        self.assert_(not dictionary.has("other"))
        self.assert_(dictionary.get("книга") == "    book\n")
        self.assert_(dictionary.get("письмо") == "    letter\n")
        return self.passed


class LexiconTest(Test):
    def __init__(self, name: str, language: str, lexicon_file_name: str,
            fast: bool):
        super().__init__(name)
        self.language = language
        self.lexicon_file_name = lexicon_file_name
        self.fast = fast

    def run(self) -> bool:
        lexicon = Lexicon(self.language, self.lexicon_file_name)
        if self.fast:
            lexicon.read_fast()
        else:
            lexicon.read()
        self.assert_(lexicon.has("книга"))
        self.assert_(lexicon.has("письмо"))
        self.assert_(lexicon.has("Иван"))
        self.assert_(lexicon.get("книга") == LexiconResponse.KNOW)
        self.assert_(lexicon.get("письмо") == LexiconResponse.DO_NOT_KNOW)
        self.assert_(lexicon.get("Иван") == LexiconResponse.NOT_A_WORD)
        return self.passed


def run_tests():

    tests = [
        DictionaryTest("Dictionary .dict", "test/simple.dict", "dict"),
        LexiconTest("Lexicon fast", "ru", "test/lexicon.yml", True),
        LexiconTest("Lexicon slow", "ru", "test/lexicon.yml", False),
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            result = test.run()
        except AssertionError:
            result = False
        if result:
            print(" OK  " + test.get_name())
            passed += 1
        else:
            print("FAIL " + test.get_name())
            failed += 1

    print("Passed: " + str(passed))
    print("Failed: " + str(failed))


if __name__ == "__main__":
    run_tests()
