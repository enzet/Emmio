from emmio.dictionary import hide


def check(sentence: str, hidden: str, words_to_hide: list[str]) -> None:
    assert hidden == hide(sentence, words_to_hide)


def test_word() -> None:
    check(
        "I want an apple.",
        "I want an _____.",
        ["apple"],
    )


def test_two_words() -> None:
    check(
        "I want an apple, and he wants an apple.",
        "I want an _____, and he wants an _____.",
        ["apple"],
    )
