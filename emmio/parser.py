import sys
from pathlib import Path

from emmio.dictionary.core import Dictionary, DictionaryItem, Form, Definition
from emmio.language import Language, ARMENIAN
from emmio.ui import Interface, RichInterface


def main(input_path: Path) -> None:
    word: str | None = None
    etymology: int = 0

    item: DictionaryItem | None = None

    titles: list[str | None] = []

    dictionary: Dictionary = Dictionary()

    with input_path.open() as input_file:
        while line := input_file.readline():
            line = line[:-1].strip()
            if len(line) > 3 and line[0] == "=":
                if line[1] != "=":
                    # Header 1.
                    if line.endswith("="):
                        line = line[:-1]
                    word = line[1:].strip()
                    item: DictionaryItem = DictionaryItem(word)
                    dictionary.add(word, item)
                elif line[2] != "=":
                    # Header 2.
                    if line.endswith("=="):
                        line = line[:-2]
                    titles = titles[:1] + [line[2:].strip(), None, None]
                elif line[3] != "=":
                    # Header 3.
                    if line.endswith("==="):
                        line = line[:-3]
                    titles = titles[:2] + [line[3:].strip(), None]
                elif line[4] != "=":
                    # Header 4.
                    if line.endswith("===="):
                        line = line[:-4]
                    titles = titles[:3] + [line[4:].strip()]
            else:
                if titles[1] == "Pronoun":
                    if line == "{{hy-personal pronoun}}":
                        pass
                    if line.startswith("#"):
                        form: Form = Form(
                            title,
                            part_of_speech=subsubtitle,
                        )
                        item.add_form(form)

    for word, item in dictionary.get_items().items():
        print(item.to_str([ARMENIAN], RichInterface()))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
