"""
Learning process readers and writers.

Versions are:
  - 0.1: old serialization in YAML files.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from emmio.learn.core import Learning, Response
from emmio.serialization import Decoder, DATE_FORMAT, EPOCH, Encoder
from emmio.util import MalformedFile

ANSWERS: list[str] = ["y", "n", "s"]

INTERVALS: list[float] = [
    5.0,
    12.0,
    30.0 * 24.0,
    90.0 * 24.0,
]
"""
Learning intervals in minutes, other intervals are 2.5 times previous interval.
"""


class LearningYAMLDecoder:
    """
    Reader for learning process scheme version 0.1.

    These are YAML files with predefined learning intervals and no precise
    information on each individual learning record.
    """

    @staticmethod
    def decode(
        id_: str, path: Path, structure: dict[str, dict[str, str | int]]
    ) -> Learning:
        """Decode learning process from structure."""

        learning: Learning = Learning(
            path,
            {"frequency_lists": []},
            id_,
        )

        if not structure:
            raise MalformedFile(path)

        for question_id, process in structure.items():
            if (
                "added" not in process
                or "plan" not in process
                or "last" not in process
                or "answers" not in process
            ):
                continue

            added: datetime = EPOCH + timedelta(seconds=process["added"] * 60)
            last: datetime = EPOCH + timedelta(seconds=process["last"] * 60)

            answers: str = process["answers"]
            count: float = 0.0

            # Learning interval in minutes.
            interval: float = INTERVALS[0]

            for answer in answers[:-1]:
                interval = LearningYAMLDecoder.compute_next_interval(
                    answer, interval
                )
                count += interval

            if not count:
                continue

            point: datetime = added
            unit: timedelta = (last - added) / count

            for answer in answers:
                interval = LearningYAMLDecoder.compute_next_interval(
                    answer, interval
                )
                learning.register(
                    Response.RIGHT if answer == "y" else Response.WRONG,
                    0,
                    question_id,
                    time=point,
                )
                point += interval * unit

        return learning

    @staticmethod
    def compute_next_interval(answer: str, interval: float) -> float:
        """
        Compute next learning interval based on the current interval and answer.

        :param answer: "y" for known and "n" for unknown
        :param interval: current learning interval in minutes
        """
        if answer == "n":
            interval = INTERVALS[0]
        elif answer == "y":
            try:
                index = INTERVALS.index(interval)
                interval = INTERVALS[index + 1]
            except (ValueError, IndexError):
                interval *= 2.5
        return interval


class LearningEncoder(Encoder):
    """
    Encoder for learning process log structure.
    """

    MAGIC: bytes = b"EMMLEA"
    VERSION_MAJOR: int = 0
    VERSION_MINOR: int = 1

    def encode(self, structure: list[dict[str, Any]]) -> None:
        """
        Encode learning log structure into the binary format (all integers are
        encoded with big endian). For the input structure description, see
        Decoder.decode_learning method.

        - First date in seconds since epoch (1 January 1970), 8-byte floating
          point.
        """
        self.encode_magic()

        assert len(structure)

        first_time: datetime = datetime.strptime(
            structure[0]["time"][:-7], DATE_FORMAT
        )
        last_time: datetime = first_time
        self.encode_int(int((first_time - EPOCH).total_seconds()), 8)
        self.encode_int(int(structure[0]["time"][-6:]), 4)

        for element in structure:
            time: datetime = datetime.strptime(
                element["time"][:-7], DATE_FORMAT
            )
            self.encode_int(int((time - last_time).total_seconds()), 4)
            self.encode_int(int(element["time"][-6:]), 4)
            self.encode_string(element["word"])
            self.encode_enum(element["answer"], ANSWERS)
            self.encode_int(element["sentence_id"], 4)
            self.encode_int(int(element["interval"]), 4)

            last_time = time


class LearningBinaryDecoder(Decoder):
    """Decoder for learning process log."""

    MAGIC: bytes = b"EMMLEA"
    VERSION_MAJOR: int = 0
    VERSION_MINOR: int = 1

    def decode(self) -> list[dict[str, Any]]:
        """Decode learning process log structure from binary format."""
        self.decode_magic()

        structure: list[dict[str, Any]] = []

        first_time: datetime = EPOCH + timedelta(
            seconds=self.decode_int(8), microseconds=self.decode_int(4)
        )
        last_time: datetime = first_time

        while True:
            try:
                element: dict[str, Any] = {}
                time: datetime = last_time + timedelta(
                    seconds=self.decode_int(4)
                )
                microseconds = self.decode_int(4)
                element["time"] = (
                    time.strftime(DATE_FORMAT) + f".{microseconds:06d}"
                )
                element["word"] = self.decode_string()
                element["answer"] = self.decode_enum(ANSWERS)
                element["sentence_id"] = self.decode_int(4)
                element["interval"] = float(self.decode_int(4))

                structure.append(element)

                last_time = time
            except EOFError:
                break

        return structure


if __name__ == "__main__":
    """
    Arguments:
      - path to learning process YAML file version 0.1,
      - path to directory to store created JSON files.
    """

    path: str = sys.argv[1]
    learning_directory: str = sys.argv[2]

    with Path(path).open() as input_file:
        content: dict[str, dict[str, dict[str, str | int]]] = yaml.load(
            input_file, Loader=yaml.FullLoader
        )

    for course_id, course_content in content.items():
        try:
            print(course_id)
            path: Path = (
                Path(learning_directory) / f"{course_id.replace('/', '_')}.json"
            )
            try:
                path.unlink()
            except Exception:
                pass

            learning: Learning = LearningYAMLDecoder().decode(
                course_id, path, course_content
            )
            learning.write()
        except MalformedFile:
            continue
