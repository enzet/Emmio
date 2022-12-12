import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from emmio.lists.core import FrequencyList
from emmio.language import Language
from emmio.learn.core import Learning
from emmio.lexicon.core import Lexicon, LexiconResponse
from emmio.data import Data


@dataclass
class Picture:

    data: Data

    def fill_data(
        self, language: Language, frequency_list: FrequencyList
    ) -> None:

        words = {}
        learn: Learning = self.data.get_course(f"ru_{language.get_code()}")
        for record in learn.records:
            if record.question_id not in words:
                words[record.question_id] = {
                    "word": record.question_id,
                    "language": language.get_code(),
                    "addTime": record.time,
                    "nextQuestionTime": record.time + record.interval,
                    "vector": record.answer.value,
                    "index": frequency_list.get_index(record.question_id),
                }
            elif record.question_id in words:
                words[record.question_id]["nextQuestionTime"] = (
                    record.time + record.interval
                )
                words[record.question_id]["vector"] += record.answer.value

        lexicon: Lexicon = self.data.get_lexicon(language)
        for word in lexicon.words:
            if word not in words:
                words[word] = {
                    "word": word,
                    "language": language.get_code(),
                    "addTime": datetime.now(),
                    "nextQuestionTime": datetime.now(),
                    "vector": "N"
                    if lexicon.words[word].knowing == LexiconResponse.DONT
                    else "Y",
                    "index": frequency_list.get_index(word),
                }

        min_add_time = min(words[x]["addTime"] for x in words)
        max_add_time = max(words[x]["addTime"] for x in words)
        min_next_question_time = min(
            words[x]["nextQuestionTime"] for x in words
        )
        max_next_question_time = max(
            words[x]["nextQuestionTime"] for x in words
        )

        min_time = min(min_add_time, min_next_question_time)
        max_time = max(max_add_time, max_next_question_time)

        for word in words:
            words[word]["addTime"] = (
                words[word]["addTime"] - min_add_time
            ).total_seconds()
            words[word]["nextQuestionTime"] = (
                words[word]["nextQuestionTime"] - min_time
            ).total_seconds()

        w = []

        for word in words:
            w.append(words[word])

        w = list(sorted(w, key=lambda x: x["index"]))

        with (Path("web") / f"{language.get_code()}.js").open(
            "w"
        ) as output_file:
            output_file.write(f"{language.get_code()} = ")
            json.dump(w, output_file)
            output_file.write(";")
