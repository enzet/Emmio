"""Annotate text with word translations."""

from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from emmio.data import Data
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.language import Language
from emmio.lexicon.core import LexiconResponse
from emmio.sentence.core import SentenceElement, split_sentence
from emmio.user.data import UserData


@dataclass
class TextAnnotator:
    """Annotate text with word translations."""

    data: Data
    user_data: UserData
    from_language: Language
    to_language: Language

    async def annotate(self, input_path: Path, output_path: Path) -> None:
        """Annotate text with word translations."""
        dictionaries = self.data.get_dictionaries(
            [
                DictionaryUsageConfig(
                    id="kaikki", from_language=self.from_language.code
                )
            ]
        )
        lexicon = self.user_data.get_lexicon_by_id(self.from_language.code)
        header_count: int = 0
        metadata: dict[str, str] = {}
        with (
            input_path.open() as input_file,
            output_path.open("w") as output_file,
        ):
            for line in tqdm(input_file.readlines()):
                if line.strip() == "---":
                    header_count += 1
                    if header_count == 2:
                        output_file.write(
                            f"""
<?xml version='1.0' encoding='utf-8'?>
<html>
    <link rel="stylesheet" href="/Users/enzet/program/Reading/style.css">
    <script src="/Users/enzet/program/Reading/reading.js"></script>
    <title>{metadata["title"]}</title>
    <body>
        <div class=main id="main" data-pages="{metadata["pages"]}">

    <h1>{metadata["title"]}</h1><p>
                            """
                        )
                    continue
                if header_count < 2:
                    key, value = line.split(": ")
                    metadata[key] = value
                    continue
                if line.startswith("# "):
                    output_file.write(f"<h2>{line.removeprefix('# ')}</h2>")
                    continue
                if not line.strip():
                    output_file.write("</p><p>")
                    continue
                split_ = split_sentence(line, self.from_language)
                new_line = ""
                for word, type_ in split_:
                    if len(word) == 1 or word in [
                        "style",
                        "class",
                        "margin",
                        "bottom",
                        "de",
                        "et",
                        "ni",
                        "où",
                        "qu",
                    ]:
                        new_line += word
                        continue
                    answer = lexicon.get_last_answer(word.lower())
                    if answer and answer.response != LexiconResponse.DONT:
                        new_line += word
                        continue
                    items = await dictionaries.get_items(
                        word, language=self.from_language
                    )
                    translation = []
                    for item in items:
                        _, text = item.get_short(self.to_language, 1000)
                        translation.append(text)
                    if translation and type_ == SentenceElement.WORD:
                        new_line += (
                            f'<span class="noted">{word}'
                            f'<span class="note">'
                            f"{'; '.join(translation)}</span></span>"
                        )
                    else:
                        new_line += word
                output_file.write(new_line)
