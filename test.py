import unittest

from engine.dictionary import DictionaryTest
from engine.lexicon import LexiconTest


def run_tests():

    tests = [
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
    unittest.main(verbosity=2)
