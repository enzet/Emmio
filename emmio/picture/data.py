# type: ignore
"""Data for the picture."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from emmio.learn.core import Learning
from emmio.lexicon.core import Lexicon, LexiconResponse
from emmio.lists.frequency_list import FrequencyList


def fill_data(
    learning: Learning, lexicon: Lexicon, frequency_list: FrequencyList
) -> None:
    """Write the JSON file describing current learning process."""

    words: dict[str, dict[str, Any]] = {}
    for record in learning.process.records:
        if record.question_id not in words:
            words[record.question_id] = {
                "word": record.question_id,
                "language": learning.learning_language.get_code(),
                "addTime": record.time,
                "nextQuestionTime": record.time + record.interval,
                "vector": record.response.value,
                "index": frequency_list.get_index(record.question_id),
            }
        elif record.question_id in words:
            words[record.question_id]["nextQuestionTime"] = (
                record.time + record.interval
            )
            words[record.question_id]["vector"] += record.response.value

    for word in lexicon.words:
        if word in words:
            continue
        words[word] = {
            "word": word,
            "language": lexicon.language.get_code(),
            "addTime": datetime.now(),
            "nextQuestionTime": datetime.now(),
            "vector": (
                "N"
                if lexicon.words[word].knowing == LexiconResponse.DONT
                else "Y"
            ),
            "index": frequency_list.get_index(word),
        }

    min_add_time = min(structure["addTime"] for structure in words.values())
    min_next_question_time = min(
        structure["nextQuestionTime"] for structure in words.values()
    )
    min_time = min(min_add_time, min_next_question_time)

    for word, structure in words.items():
        structure["addTime"] = (
            structure["addTime"] - min_add_time
        ).total_seconds()
        structure["nextQuestionTime"] = (
            structure["nextQuestionTime"] - min_time
        ).total_seconds()

    result: list = []

    for word, structure in words.items():
        result.append(structure)

    result = list(sorted(result, key=lambda structure: structure["index"]))

    with (Path("web") / f"{lexicon.language.get_code()}.js").open(
        "w", encoding="utf-8"
    ) as output_file:
        output_file.write(f"{lexicon.language.get_code()} = ")
        json.dump(result, output_file)
        output_file.write(";")
