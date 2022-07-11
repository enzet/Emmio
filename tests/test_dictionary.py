from emmio.dictionary import sanitize


def check(sentence: str, hidden: str, words_to_hide: list[str]) -> None:
    assert sanitize(sentence, words_to_hide) == hidden


def test_word() -> None:
    check("I want an apple.", "I want an _____.", ["apple"])


def test_two_words() -> None:
    check(
        "I want an apple, and he wants an apple.",
        "I want an _____, and he wants an _____.",
        ["apple"],
    )


def test_uppercase() -> None:
    check("I want an Apple.", "I want an _____.", ["apple"])


def test_russian() -> None:
    check("зима́ – холодное время года", "____ – холодное время года", ["зима"])


def test_russian_middle_accent() -> None:
    check("ма́рт – третий месяц", "____ – третий месяц", ["март"])


def test_ukrainian() -> None:
    check("яки́й", "____", ["який"])
