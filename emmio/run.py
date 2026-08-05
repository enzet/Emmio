"""Emmio entry point."""

import argparse
import logging
import random
import shlex
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from colour import Color

from emmio import inventory, postgres, util
from emmio.catalog import NON_PROPER_NOUNS
from emmio.data import Data
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.dictionary.core import DictionaryCollection
from emmio.graph import Visualizer
from emmio.language import KnownLanguages, Language, LanguageNotFoundError
from emmio.learn.core import Learning, LearningRecord, Response
from emmio.learn.teacher import Teacher
from emmio.learn.visualizer import LearningVisualizer
from emmio.lexicon.core import (
    NOT_TO_CHECK_CATEGORIES,
    NOT_TO_CHECK_CATEGORY_CODES,
    RATE_ESTIMATOR_BY_SELECTION,
    AnswerType,
    Lexicon,
    LexiconChecker,
    LexiconResponse,
)
from emmio.lexicon.curation import (
    DEFAULT_N_C,
    DEFAULT_N_STRATA,
    CuratedPanelError,
    CuratedPanelResult,
    build_or_extend_curated_panel,
    classify_automatically,
)
from emmio.lexicon.goal import compute_lexicon_goal_state
from emmio.lexicon.visualizer import LexiconVisualizer
from emmio.listen.listener import Listener
from emmio.lists.config import parse_frequency_list_identifier
from emmio.lists.frequency_list import FrequencyList
from emmio.paths import DEFAULT_OUTPUT_DIRECTORY
from emmio.sentence.config import SentencesUsageConfig
from emmio.sentence.core import SentenceElement
from emmio.sentence.data import SentencesData
from emmio.text.annotate import TextAnnotator
from emmio.ui import (
    Block,
    Colorized,
    Element,
    Formatted,
    Header,
    InlineElement,
    Interface,
    Table,
    Text,
    Title,
    progress,
)
from emmio.user.data import UserData

logger: logging.Logger = logging.getLogger(__name__)

# Category choices offered by `Emmio.curate`, and their single-letter
# storage codes (see `scripts/schema.sql`, `curated_words.category`).
# Group (1) is `Real word` alone (words to check); everything from
# `NOT_TO_CHECK_CATEGORIES` on is group (2) (words not to check, broken
# down by why) — see `emmio.lexicon.core` for the taxonomy this shares
# with `LexiconChecker.ask`'s "Not to check" submenu.
CURATION_CATEGORIES: list[tuple[str, str]] = [
    ("Real word", "w"),
    *NOT_TO_CHECK_CATEGORIES,
    ("Unsure", "u"),
    ("Quit", "q"),
]
CURATION_CATEGORY_CODES: dict[str, str] = {
    "Real word": "W",
    **NOT_TO_CHECK_CATEGORY_CODES,
    "Unsure": "U",
}

# How a past `emmio lexicon` answer maps to a curation category, for
# `Emmio.import_lexicon_curation_votes`. Per the user: "know" and "don't
# know" both mean the word is real; "don't but proper noun too" and "not a
# word" are legacy-only response types (no longer produced by `ask`, which
# now writes a category (2) vote directly instead — see
# `LexiconChecker._record_not_to_check_vote`) but old records using them
# still carry real signal, so they import as "proper noun" and "not a
# word" respectively. `KNOW_SEMANTIC_CLASS` is treated the same as `KNOW`
# for the same reason it means the word is real. `KNOW_OR_NOT_A_WORD` is
# deliberately absent — it is genuinely ambiguous between "real" and "not
# a word", so it is left for a human curator rather than guessed.
LEXICON_RESPONSE_TO_CURATION_CATEGORY: dict[LexiconResponse, str] = {
    LexiconResponse.KNOW: "W",
    LexiconResponse.KNOW_SEMANTIC_CLASS: "W",
    LexiconResponse.DONT: "W",
    LexiconResponse.DONT_BUT_PROPER_NOUN_TOO: "P",
    LexiconResponse.NOT_A_WORD: "N",
}


class Emmio:
    """Emmio entry point."""

    path: Path
    """Path to the data directory, `~/.emmio` by default."""

    interface: Interface
    """Interface to interact with the user."""

    data: Data
    """Data to store user data."""

    user_id: str
    """User ID."""

    user_data: UserData
    """User data."""

    def __init__(
        self, path: Path, interface: Interface, data: Data, user_id: str
    ) -> None:
        self.path: Path = path
        self.output_path: Path = path / DEFAULT_OUTPUT_DIRECTORY
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.interface: Interface = interface
        self.data: Data = data

        if not data.has_user(user_id):
            answer: str = self.interface.choice(
                [("Yes", "y"), ("No", "n")],
                f"User with id `{user_id}` does not exist. Do you want to "
                "create new user?",
            )
            if answer == "Yes":
                user_name = self.interface.input("Enter user name: ")
            else:
                return
            data.create_user(user_id, user_name)
            self.interface.print(
                f"User `{user_id}` with name `{user_name}` created."
            )

        self.user_data: UserData = data.users_data[user_id]
        self.user_data.verify()

        self.user_id: str = user_id

    async def run(self) -> None:
        """Run the main loop."""

        self.interface.print(Title("Emmio"))

        self.interface.print(
            Block(
                'Press <Enter> or print "learn" to start learning.\n'
                'Print "help" to see commands or "exit" to quit.',
                (1, 4, 1, 4),
            )
        )

        while True:
            command: str = self.interface.input("Emmio > ")

            if command in ("q", "quit", "exit"):
                return

            await self.process_command(command)

    async def process_command(
        self, command: str, *, interactive: bool = True
    ) -> None:
        """Process the user command."""

        parser: argparse.ArgumentParser = argparse.ArgumentParser(
            exit_on_error=False, add_help=False
        )
        subparsers = parser.add_subparsers(dest="command")

        help_parser = subparsers.add_parser("help", help="print help message")
        help_parser.add_argument("subcommand", nargs="?")

        learn_parser = subparsers.add_parser("learn", help="learn topics")
        learn_parser.add_argument("topic", nargs="?")

        lexicon_parser = subparsers.add_parser("lexicon", help="check lexicon")
        lexicon_parser.add_argument("id", nargs="?")
        lexicon_parser.add_argument(
            "--type",
            default="frequency",
            choices=["frequency", "random", "most frequent"],
        )

        curate_parser = subparsers.add_parser(
            "curate", help="curate a frequency list's SFWR panel"
        )
        curate_parser.add_argument(
            "language", help="language code of the curated list, e.g. `de`"
        )
        curate_parser.add_argument(
            "frequency_list_id",
            help=(
                "source frequency list identifier, e.g. `de_opensubtitles_2024`"
            ),
        )
        curate_parser.add_argument(
            "--stratum", type=int, help="restrict to one stratum"
        )
        curate_parser.add_argument(
            "--from-lexicon-history",
            action="store_true",
            help=(
                "instead of asking interactively, vote using this user's "
                "own past `emmio lexicon` answers, for panel words that "
                "already have such an answer and that this curator has not "
                "already voted on; words the panel does not have yet are "
                "never added (only `emmio data build-panel` grows the "
                "panel)"
            ),
        )

        stat_parser = subparsers.add_parser("stat", help="show statistics")
        stat_parser.add_argument(
            "process",
            choices=["actions", "learn", "lexicon"],
            default="learn",
            help="what print statistics for",
        )

        plot_parser = subparsers.add_parser("plot", help="plot a graph")
        plot_subparsers = plot_parser.add_subparsers(dest="process")

        plot_lexicon_parser = plot_subparsers.add_parser(
            "lexicon",
            help="plot lexicon rate",
            description="""
                Plot lexicon rate. Lexicon rate is `-log_2(x)`, where `x` is a
                number of words the user don't know in a random text.
            """,
        )
        plot_lexicon_parser.add_argument(
            "--legend",
            choices=["list", "text"],
            default="list",
            help=(
                "show legend, `list` shows simple legend, `text` shows labels "
                "at the right side of the graphs"
            ),
        )
        plot_lexicon_parser.add_argument(
            "--interval",
            "-i",
            default="year",
            choices=["day", "week", "month", "year"],
            help="interval of X axis",
        )
        plot_lexicon_parser.add_argument(
            "--margin", "-m", default=None, type=float, help="minimum Y value"
        )
        plot_lexicon_parser.add_argument(
            "--type", choices=["svg", "matplot", "tikz"]
        )
        plot_lexicon_parser.add_argument(
            "--languages",
            "-l",
            type=str,
            help="list of language codes",
            nargs="+",
        )
        plot_lexicon_parser.add_argument(
            "--exclude",
            "-e",
            type=str,
            help="list of lexicon identifiers to exclude",
            nargs="+",
            default=[],
        )
        plot_lexicon_parser.add_argument(
            "--precision",
            "-p",
            type=int,
            default=100,
            help="lexicon rate precision (default is 100)",
        )
        plot_lexicon_parser.add_argument(
            "--background-color", "-bc", type=str, default="white"
        )
        plot_lexicon_parser.add_argument(
            "--grid-color", "-gc", type=str, default="#888888"
        )
        plot_lexicon_parser.add_argument(
            "--color",
            "-c",
            type=str,
            nargs="+",
            help=(
                "color of the line, it may specify a single color (e.g. `red` "
                "or `#FF0000`) or a gradient by specifying gradient anchor "
                "colors (e.g. `red yellow green`)"
            ),
        )
        plot_lexicon_parser.add_argument(
            "--show-main",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="plot main average line",
        )
        plot_lexicon_parser.add_argument(
            "--show-averages",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="fill between average lines",
        )
        plot_lexicon_parser.add_argument(
            "--show-precise-values",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="show precise values",
        )
        plot_lexicon_parser.add_argument(
            "--show-precision-interval",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="show precision interval",
        )

        # Arguments for `plot learn` command.
        plot_learn_parser = plot_subparsers.add_parser(
            "learn", help="plot learning questions"
        )
        plot_learn_parser.add_argument(
            "--interactive",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="show interactive Matplotlib window",
        )
        plot_learn_parser.add_argument(
            "--actions",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="use number of actions for the X axis instead of time",
        )
        plot_learn_parser.add_argument(
            "--depth",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="group by question depth instead of learning topic",
        )
        plot_learn_parser.add_argument(
            "--pressure",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="count pressure instead of question number",
        )

        plot_actions_parser = plot_subparsers.add_parser(
            "actions", help="plot number of user actions"
        )
        plot_actions_parser.add_argument("--interval", default="year")
        plot_actions_parser.add_argument(
            "--depth",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="group by question depth instead of learning topic",
        )
        plot_actions_parser.add_argument(
            "--moving",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="use moving average",
        )

        plot_subparsers.add_parser(
            "knowing", help="plot cumulative amount of learned questions"
        )

        plot_subparsers.add_parser(
            "schedule", help="plot scheduled question time"
        )

        plot_history_parser = plot_subparsers.add_parser(
            "history", help="plot history"
        )
        plot_history_parser.add_argument(
            "--size", "-s", help="marker size", type=float, default=0.5
        )

        listen_parser = subparsers.add_parser(
            "listen", help="play audio learning"
        )
        listen_parser.add_argument("id", help="listening process identifier")
        listen_parser.add_argument(
            "--start-from",
            help="start from the word in the list with that index",
            type=int,
            default=0,
        )
        listen_parser.add_argument("--repeat", type=int, default=1)

        analyze_parser = subparsers.add_parser("analyze")
        analyze_parser.add_argument("language")

        text_parser = subparsers.add_parser("text")
        text_parser.add_argument("action")
        text_parser.add_argument("--input", type=Path)
        text_parser.add_argument("--output", type=Path)
        text_parser.add_argument("--from-language")
        text_parser.add_argument("--to-language")

        # Shared data artifact management.
        data_parser = subparsers.add_parser(
            "data", help="manage shared data artifacts"
        )
        data_subparsers = data_parser.add_subparsers(dest="data_command")
        data_list_parser = data_subparsers.add_parser(
            "list", help="show downloaded and available artifacts"
        )
        data_list_parser.add_argument(
            "type",
            nargs="?",
            choices=["dictionaries", "sentences", "lists"],
            help="only show artifacts of this type",
        )
        data_list_parser.add_argument(
            "--language", help="filter by language code, e.g. `fr`"
        )

        data_download_parser = data_subparsers.add_parser(
            "download", help="download an on-demand artifact now"
        )
        data_download_parser.add_argument(
            "kind", choices=["kaikki", "tatoeba", "frequency_words"]
        )
        data_download_parser.add_argument(
            "language", help="language code, e.g. `fr`"
        )
        data_download_parser.add_argument(
            "--year",
            type=int,
            help=(
                f"FrequencyWords release year (default "
                f"{inventory.DEFAULT_FREQUENCY_WORDS_YEAR})"
            ),
        )

        data_delete_parser = data_subparsers.add_parser(
            "delete", help="delete an artifact from disk"
        )
        data_delete_parser.add_argument(
            "kind", choices=["kaikki", "tatoeba", "frequency_words", "file"]
        )
        data_delete_parser.add_argument(
            "target",
            help="language code, or configuration identifier for `file`",
        )
        data_delete_parser.add_argument(
            "--year", type=int, help="FrequencyWords release year"
        )
        data_delete_parser.add_argument(
            "--type",
            choices=list(inventory.ARTIFACT_TYPES),
            help="artifact type, when a `file` identifier is ambiguous",
        )

        data_add_parser = data_subparsers.add_parser(
            "add",
            help="register an artifact configuration (without downloading)",
        )
        add_subparsers = data_add_parser.add_subparsers(dest="add_type")

        add_list_parser = add_subparsers.add_parser(
            "list", help="frequency list from a local file"
        )
        add_list_parser.add_argument("--id", required=True)
        add_list_parser.add_argument(
            "--language", required=True, help="language code, e.g. `eo`"
        )
        add_list_parser.add_argument(
            "--path", required=True, help="file name inside `lists`"
        )
        add_list_parser.add_argument(
            "--format", default="list", choices=["list", "csv", "json"]
        )
        add_list_parser.add_argument("--name")
        add_list_parser.add_argument("--source")
        add_list_parser.add_argument(
            "--url", help="URL the file can be downloaded from"
        )
        add_list_parser.add_argument(
            "--stripped",
            action="store_true",
            help="the list does not cover its whole corpus",
        )

        add_word_list_parser = add_subparsers.add_parser(
            "word-list", help="word list from a local file"
        )
        add_word_list_parser.add_argument("--id", required=True)
        add_word_list_parser.add_argument(
            "--language", required=True, help="language code, e.g. `eo`"
        )
        add_word_list_parser.add_argument(
            "--path", required=True, help="file name inside `lists`"
        )
        add_word_list_parser.add_argument("--name")
        add_word_list_parser.add_argument(
            "--source", help='origin of the list, e.g. "personal knowledge"'
        )

        add_dictionary_parser = add_subparsers.add_parser(
            "dictionary", help="dictionary from a local file"
        )
        add_dictionary_parser.add_argument("--id", required=True)
        add_dictionary_parser.add_argument(
            "--path", required=True, help="file name inside `dictionaries`"
        )
        add_dictionary_parser.add_argument(
            "--from",
            dest="from_language",
            required=True,
            help="language of words being defined",
        )
        add_dictionary_parser.add_argument(
            "--to",
            dest="to_language",
            required=True,
            help="language of definitions",
        )
        add_dictionary_parser.add_argument("--name")

        add_sentences_parser = add_subparsers.add_parser(
            "sentences", help="sentence collection from a local file"
        )
        add_sentences_parser.add_argument("--id", required=True)
        add_sentences_parser.add_argument(
            "--path", required=True, help="file name inside `sentences`"
        )
        add_sentences_parser.add_argument(
            "--languages",
            required=True,
            help="comma-separated language codes, e.g. `de,ru`",
        )
        add_sentences_parser.add_argument(
            "--sentence-type",
            default="simple_two_languages",
            choices=["simple_one_language", "simple_two_languages"],
        )
        add_sentences_parser.add_argument("--name")

        data_build_panel_parser = data_subparsers.add_parser(
            "build-panel",
            help="build or extend an SFWR curated panel from a frequency list",
        )
        data_build_panel_parser.add_argument(
            "kind", choices=["opensubtitles", "frequency_words"]
        )
        data_build_panel_parser.add_argument(
            "language", help="language code, e.g. `de`"
        )
        data_build_panel_parser.add_argument(
            "--year",
            type=int,
            help=(
                "release/generation year; required for `opensubtitles` "
                "(no catalog to default from), defaults to the best "
                "FrequencyWords year for `frequency_words`"
            ),
        )
        data_build_panel_parser.add_argument(
            "--name", help="display name (default: derived)"
        )
        data_build_panel_parser.add_argument(
            "--n-strata",
            type=int,
            default=DEFAULT_N_STRATA,
            help=f"number of log-uniform strata (default {DEFAULT_N_STRATA})",
        )
        data_build_panel_parser.add_argument(
            "--n-c",
            type=int,
            default=DEFAULT_N_C,
            help=f"target words per stratum (default {DEFAULT_N_C})",
        )
        data_build_panel_parser.add_argument(
            "--seed", type=int, help="random seed (default: none)"
        )

        arguments: argparse.Namespace
        if command:
            try:
                # `shlex` keeps quoted arguments (e.g. `--name "Esperanto
                # 2011"`) together.
                arguments = parser.parse_args(shlex.split(command))
            except argparse.ArgumentError:
                logger.exception("Error parsing command.")
                return
            except SystemExit:
                return
        else:
            arguments = argparse.Namespace(command="learn", topic=None)

        # Command `help`.
        if arguments.command == "help":
            if arguments.subcommand == "learn":
                learn_parser.print_help()
            else:
                parser.print_help()

        # Command `learn`.
        elif arguments.command == "learn":
            # We cannot use iterators here!
            learnings: list[Learning]
            if arguments.topic:
                try:
                    learnings = [
                        self.data.get_learning(self.user_id, arguments.topic)
                    ]
                except ValueError:
                    self.interface.print(
                        f"No learning found for `{arguments.topic}`."
                    )
                    return
            else:
                learnings = list(self.data.get_active_learnings(self.user_id))

            await self.learn(learnings)

        # Command `lexicon`.
        elif arguments.command == "lexicon":
            lexicons: list[Lexicon] = [
                x
                for x in self.user_data.get_lexicons()
                if RATE_ESTIMATOR_BY_SELECTION.get(x.config.selection)
                and (not arguments.id or x.id_ == arguments.id)
            ]
            if not lexicons:
                self.interface.print(
                    f"No `{arguments.language}` lexicon found."
                )
                return
            await self.run_lexicon(
                sorted(
                    lexicons,
                    key=lambda lexicon: -lexicon.get_last_rate_number(),
                ),
                arguments.type,
            )

        # Command `curate`.
        elif arguments.command == "curate":
            if arguments.from_lexicon_history:
                self.import_lexicon_curation_votes(
                    arguments.language,
                    arguments.frequency_list_id,
                    arguments.stratum,
                )
            else:
                await self.curate(
                    arguments.language,
                    arguments.frequency_list_id,
                    arguments.stratum,
                )

        # Command `stat`.
        elif arguments.command == "stat":
            # Command `stat actions`.
            if arguments.process == "actions":
                stat_actions: dict[Language, int] = defaultdict(int)
                stat_time: dict[Language, timedelta] = defaultdict(timedelta)

                for learning in self.data.get_learnings(self.user_id):
                    stat_actions[learning.learning_language] += (
                        learning.count_actions()
                    )
                    stat_time[learning.learning_language] += (
                        learning.compute_average_action_time()
                    )

                self.interface.print(
                    Table(
                        [
                            "Language",
                            "Actions",
                            "Average action time",
                            "Approximated time",
                        ],
                        [
                            [x.get_name(), str(y), str(z), str(y * z)]
                            for x, y, z in sorted(
                                zip(
                                    stat_actions.keys(),
                                    stat_actions.values(),
                                    stat_time.values(),
                                    strict=False,
                                ),
                                key=lambda x: -x[1],
                            )
                        ],
                    )
                )

            # Command `stat learn`.
            elif arguments.process == "learn":
                self.data.print_learning_statistics(
                    self.interface, self.user_id
                )

            # Command `stat lexicon`.
            elif arguments.process == "lexicon":
                await self.stat_lexicon()

        elif arguments.command == "plot":
            # Command `plot lexicon`.
            if arguments.process == "lexicon":
                self.plot_lexicon(arguments, interactive=interactive)

            # Command `plot learn`.
            elif arguments.process == "learn":
                records: list[tuple[LearningRecord, Learning]] = []
                for learning in self.user_data.get_active_learnings():
                    records += [(x, learning) for x in learning.process.records]
                records = sorted(records, key=lambda record: record[0].time)
                LearningVisualizer(
                    records,
                    interactive=arguments.interactive,
                    is_time=not arguments.actions,
                    count_by_depth=arguments.pressure,
                    by_language=not arguments.depth,
                ).draw()

            # Command `plot knowing`.
            elif arguments.process == "knowing":
                Visualizer().knowing(
                    list(self.user_data.get_active_learnings())
                )

            # Command `plot schedule`.
            elif arguments.process == "schedule":
                Visualizer().next_question_time(
                    self.user_data.get_active_learnings()
                )

            # Command `plot history`.
            elif arguments.process == "history":
                Visualizer().history(
                    self.user_data.get_active_learnings(), arguments.size
                )

            # Command `plot actions`.
            elif arguments.process == "actions":
                self.plot_actions(arguments)

        # Command `listen`.
        elif arguments.command == "listen":
            await self.listen(
                arguments.id, arguments.start_from, arguments.repeat
            )

        # Command `to learn`.
        elif command == "to learn":
            await self.to_learn()

        # Command `schedule`.
        elif command == "schedule":
            await self.schedule()

        # Command `text annotate`.
        elif arguments.command == "text" and arguments.action == "annotate":
            await TextAnnotator(
                self.data,
                self.user_data,
                Language.from_code(arguments.from_language),
                Language.from_code(arguments.to_language),
            ).annotate(arguments.input, arguments.output)

        # Command `data`.
        elif arguments.command == "data":
            match arguments.data_command:
                case "list":
                    types: list[str] = (
                        [arguments.type]
                        if arguments.type
                        else ["dictionaries", "sentences", "lists"]
                    )
                    for type_ in types:
                        if len(types) > 1:
                            self.interface.print(type_.capitalize())
                        self.print_artifacts(type_, arguments.language)
                case "download":
                    self.download_artifact(arguments)
                case "delete":
                    self.delete_artifact(arguments)
                case "add":
                    if arguments.add_type:
                        self.add_artifact(arguments)
                    else:
                        data_add_parser.print_help()
                case "build-panel":
                    self.build_curated_panel(arguments)
                case _:
                    data_parser.print_help()

    def print_artifacts(self, type_: str, language: str | None) -> None:
        """Print the inventory of shared data artifacts of one type.

        Shows what is downloaded (with its size on disk) and what could be
        downloaded, sorted largest first, with a total row at the bottom.

        :param type_: artifact type: `dictionaries`, `sentences`, or `lists`
        :param language: only show artifacts for this language code
        """
        artifacts: list[inventory.Artifact] = {
            "dictionaries": inventory.dictionary_artifacts,
            "sentences": inventory.sentence_artifacts,
            "lists": inventory.list_artifacts,
        }[type_](self.data.path)
        if language:
            artifacts = [x for x in artifacts if x.language == language]
        if not artifacts:
            self.interface.print("No artifacts found.")
            return

        def language_name(code: str | None) -> str:
            if code is None:
                return ""
            try:
                return Language.from_code(code).get_name()
            except LanguageNotFoundError:
                return code

        # Lists come in several kinds (word list, frequency list, cropped
        # frequency list), so their table gets an extra "Type" column.
        with_list_type: bool = type_ == "lists"

        def row(artifact: inventory.Artifact) -> list[InlineElement | str]:
            values: list[InlineElement | str] = [
                language_name(artifact.language),
                artifact.name,
            ]
            if with_list_type:
                values.append(artifact.list_type or "")
            values += [
                "downloaded" if artifact.downloaded else "available",
                inventory.format_size(artifact.size),
                artifact.path or "",
            ]
            return values

        rows: list[list[InlineElement | str]] = [
            row(artifact) for artifact in artifacts
        ]
        downloaded: list[inventory.Artifact] = [
            x for x in artifacts if x.downloaded
        ]
        total_row: list[InlineElement | str] = ["Total", ""]
        if with_list_type:
            total_row.append("")
        total_row += [
            f"{len(downloaded)} of {len(artifacts)} downloaded",
            inventory.format_size(
                sum(artifact.size or 0 for artifact in downloaded)
            ),
            "",
        ]
        rows.append(total_row)
        columns: list[InlineElement | str] = ["Language", "Name"]
        if with_list_type:
            columns.append("Type")
        columns += ["Status", "Size", "Path"]
        self.interface.print(Table(columns, rows))

    def _artifact_language(self, code: str) -> Language | None:
        """Parse a language code argument, printing an error if unknown."""
        try:
            return Language.from_code(code)
        except LanguageNotFoundError:
            self.interface.print(f"Unknown language code `{code}`.")
            return None

    def download_artifact(self, arguments: argparse.Namespace) -> None:
        """Download an on-demand artifact (command `data download`)."""

        language: Language | None = self._artifact_language(arguments.language)
        if language is None:
            return
        path: Path
        fetched: bool
        try:
            match arguments.kind:
                case "kaikki":
                    path, fetched = inventory.download_kaikki(
                        self.data.path, language
                    )
                case "tatoeba":
                    path, fetched = inventory.download_tatoeba(
                        self.data.path, language
                    )
                case "frequency_words":
                    path, fetched = inventory.download_frequency_words(
                        self.data.path,
                        language,
                        arguments.year
                        or inventory.frequency_words_year(language),
                    )
                case _:
                    return  # Unreachable: `argparse` restricts the choices.
        except inventory.InventoryError as error:
            self.interface.print(str(error))
            return
        size: str = inventory.format_size(inventory.tree_size(path))
        location: Path = path.relative_to(self.data.path)
        if fetched:
            self.interface.print(f"Downloaded `{location}` ({size}).")
        else:
            self.interface.print(f"Already downloaded: `{location}` ({size}).")

    def delete_artifact(self, arguments: argparse.Namespace) -> None:
        """Delete an artifact from disk (command `data delete`)."""

        removed: list[Path]
        size: int
        try:
            if arguments.kind == "file":
                removed, size = inventory.delete_configured(
                    self.data.path, arguments.target, arguments.type
                )
                if not removed:
                    self.interface.print(
                        f"Removed configuration entry `{arguments.target}` "
                        f"(its file was already absent)."
                    )
                    return
            else:
                language: Language | None = self._artifact_language(
                    arguments.target
                )
                if language is None:
                    return
                match arguments.kind:
                    case "kaikki":
                        removed, size = inventory.delete_kaikki(
                            self.data.path, language
                        )
                    case "tatoeba":
                        removed, size = inventory.delete_tatoeba(
                            self.data.path, language
                        )
                    case "frequency_words":
                        removed, size = inventory.delete_frequency_words(
                            self.data.path, language, arguments.year
                        )
                    case _:
                        return  # Unreachable: `argparse` restricts choices.
        except inventory.InventoryError as error:
            self.interface.print(str(error))
            return
        locations: str = ", ".join(
            f"`{path.relative_to(self.data.path)}`" for path in removed
        )
        self.interface.print(
            f"Removed {locations} ({inventory.format_size(size)})."
        )

    def add_artifact(self, arguments: argparse.Namespace) -> None:
        """Register an artifact configuration (command `data add`).

        Only the configuration entry is written; the file it points at is
        expected to be put in place separately.
        """
        type_: str
        entry: dict
        match arguments.add_type:
            case "list":
                type_ = "lists"
                entry = {
                    "type": "frequency_list",
                    "language": arguments.language,
                    "path": arguments.path,
                    "file_format": arguments.format,
                    "is_stripped": arguments.stripped,
                }
                if arguments.name:
                    entry["name"] = arguments.name
                if arguments.source:
                    entry["source"] = arguments.source
                if arguments.url:
                    entry["url"] = arguments.url
            case "word-list":
                type_ = "lists"
                entry = {
                    "type": "word_list",
                    "language": arguments.language,
                    "path": arguments.path,
                    "name": arguments.name or arguments.id,
                    "source": arguments.source or "unknown",
                }
            case "dictionary":
                type_ = "dictionaries"
                entry = {
                    "file_name": arguments.path,
                    "name": arguments.name or arguments.id,
                    "from_language": arguments.from_language,
                    "to_language": arguments.to_language,
                }
            case "sentences":
                type_ = "sentences"
                entry = {
                    "file_name": arguments.path,
                    "type": arguments.sentence_type,
                    "name": arguments.name or arguments.id,
                    "languages": arguments.languages.split(","),
                }
            case _:
                return  # Unreachable: `argparse` restricts the choices.

        try:
            file_path, exists = inventory.add_configured(
                self.data.path, type_, arguments.id, entry
            )
        except inventory.InventoryError as error:
            self.interface.print(str(error))
            return
        self.interface.print(
            f"Added `{arguments.id}` to `{type_}/config.json`."
        )
        if not exists:
            self.interface.print(
                f"Note: `{file_path.relative_to(self.data.path)}` does not "
                f"exist yet; put the file there to complete the artifact."
            )

    async def stat_lexicon(self) -> None:
        """Print lexicon statistics."""

        rows: list[list[InlineElement | str]] = []

        lexicons: list[Lexicon] = []
        for language, language_lexicons in self.data.get_frequency_lexicons(
            self.user_id
        ).items():
            lexicons_to_check = [
                x
                for x in language_lexicons
                if RATE_ESTIMATOR_BY_SELECTION.get(x.config.selection)
            ]
            if len(lexicons_to_check) == 1:
                lexicons.append(lexicons_to_check[0])
            else:
                logger.fatal("More than one lexicon to check for %s.", language)

        for lexicon in sorted(
            lexicons, key=lambda lexicon: -lexicon.get_last_rate_number()
        ):
            now: datetime = datetime.now(UTC)
            rate: float | None = lexicon.get_last_rate()
            rate_year_before: float | None = lexicon.get_last_rate(
                before=now - timedelta(days=365.25)
            )
            frequency_list: FrequencyList | None = None
            if lexicon.config.frequency_list:
                frequency_list = self.data.get_frequency_list(
                    lexicon.config.frequency_list
                )
            records: list[tuple[datetime, str, str]] = [
                (record.time, record.word, record.response.to_code())
                for record in lexicon.log.records
            ]
            achieved: bool = compute_lexicon_goal_state(
                lexicon.config.selection, frequency_list, records, now
            ).achieved
            change: float = (
                abs(rate) - abs(rate_year_before)
                if rate_year_before is not None and rate is not None
                else 0.0
            )
            change_text: InlineElement
            match change:
                case float() as change if change >= 0.1:
                    change_text = Colorized(f"▲ +{change:.1f}", color="green")
                case float() as change if change <= -0.1:
                    change_text = Colorized(f"▼ {change:.1f}", color="red")
                case _:
                    change_text = Text("")
            if not rate:
                continue
            code: Formatted = Formatted(
                lexicon.language.get_code(), format_="bold"
            )
            row: list[InlineElement | str] = [
                Text().add(code).add(" " + lexicon.language.get_name()),
                (
                    Colorized("achieved", color="green")
                    if achieved
                    else Text("checking")
                ),
                (
                    f"{abs(rate):.1f}  " + progress(int(rate * 10))
                    if rate is not None
                    else "N/A"
                ),
                change_text,
            ]
            rows.append(row)

        self.interface.print(
            Table(["Language", "Status", "Rate", "Year change"], rows)
        )

    def build_curated_panel(self, arguments: argparse.Namespace) -> None:
        """Build or extend an SFWR curated panel (command `data build-panel`).

        `--n-c` is a per-stratum target, not a per-call draw count: if the
        list already exists, only enough new words are drawn to bring each
        stratum up to `--n-c` (a stratum already at or past target is left
        alone), so running the same command again with the same `--n-c` is
        a no-op, and a larger `--n-c` tops every stratum up to the new
        target instead of redrawing it from scratch.

        Draws the frequency list via the normal discovery mechanism
        (`ListsData.get_frequency_list`, the same one `emmio lexicon` uses),
        so the source file must already be in the recognized
        `<language>_opensubtitles_<year>.txt` /
        `<language>_frequency_words_<year>.txt` location and naming — no
        raw file path is accepted here. See `emmio.lexicon.curation` for the
        stratified draw itself.
        """
        language: Language | None = self._artifact_language(arguments.language)
        if language is None:
            return

        year: int | None = arguments.year
        if year is None:
            if arguments.kind == "frequency_words":
                year = inventory.frequency_words_year(language)
            else:
                self.interface.print(
                    "`--year` is required for `opensubtitles` (there is no "
                    "catalog to default it from, unlike `frequency_words`)."
                )
                return

        try:
            result: CuratedPanelResult = build_or_extend_curated_panel(
                self.data,
                language,
                arguments.kind,
                year,
                arguments.name,
                arguments.n_strata,
                arguments.n_c,
                arguments.seed,
            )
        except CuratedPanelError as error:
            self.interface.print(str(error))
            return

        if result.strata_mismatch:
            self.interface.print(
                f"Curated list `{result.name}` already exists with "
                f"{result.n_strata} strata; ignoring `--n-strata "
                f"{arguments.n_strata}` to keep stratum boundaries "
                "consistent with words already curated."
            )
        self.interface.print(
            f"Curated list `{result.name}` (id {result.list_id}): "
            f"{result.new_words} new word(s) added, topping every stratum "
            f"up to {arguments.n_c} words (already-curated words were left "
            "untouched)."
        )

    async def run_lexicon(
        self, lexicons: list[Lexicon], lexicon_type: str
    ) -> None:
        """Check user vocabulary."""

        for lexicon in lexicons:
            language: Language = lexicon.language
            now: datetime = datetime.now(UTC)
            need: int = 5 - lexicon.count_unknowns(now - timedelta(days=7), now)
            need = max(need, 101 - lexicon.count_unknowns())
            if need <= 0:
                continue

            self.interface.print(Header(f"Lexicon for {language.get_name()}"))

            frequency_list: FrequencyList | None = None
            if lexicon.config.frequency_list:
                frequency_list = self.data.get_frequency_list(
                    lexicon.config.frequency_list
                )
            if frequency_list is None:
                logger.error(
                    "Frequency list with config `%s` cannot be loaded.",
                    lexicon.config.frequency_list,
                )
                continue

            other_lexicons: list[Lexicon] = (
                self.user_data.get_lexicons_by_language(language)
            )
            checker: LexiconChecker = LexiconChecker(
                self.interface,
                lexicon,
                self.data.get_dictionaries(lexicon.config.dictionaries or []),
                self.data.get_sentences_data(),
                lexicon.config.sentences or [],
            )
            if lexicon_type == "random":
                await checker.check_random(
                    other_lexicons, frequency_list, None, need
                )
            elif lexicon_type == "most frequent":
                await checker.check_top(
                    other_lexicons, frequency_list, None, need
                )
            else:
                await checker.check_frequency(
                    other_lexicons, frequency_list, None, need
                )
            break

    async def curate(
        self, language: str, frequency_list_id: str, stratum: int | None
    ) -> None:
        """Interactively curate a frequency list's SFWR curated panel.

        Draws the next word this user has not yet voted on — coverage
        first, so the least-voted word wins — and records their category
        choice, looping until nothing is left in scope or the user quits.
        Curation is a property of the list, not the learner (see
        `research/metric.tex` §"Curation is a property of the list, not the
        learner"), so this reads/writes the shared `curated_words` table,
        not anything scoped to this user alone; `self.user_id` is recorded
        only as the vote's `curator_id`, for attribution and consensus.

        Before each vote, a dictionary entry and (if available) a Tatoeba
        example sentence are shown, exactly as `emmio lexicon` would, so the
        curator does not have to look the word up elsewhere to decide.

        Words with a clear-cut automatic answer are never shown at all: a
        word outside the language's alphabet, an all-junk dictionary result,
        or a `cap_ratio` past the proper-noun threshold are all assumed
        "not a word" or "proper noun" the same way raw (uncurated) lexicon
        checking already assumes them (see `LexiconChecker.do_skip`); a word
        with at least one non-junk dictionary entry is assumed "real word".
        None of this is written to the database — the whole point of
        curation is to save human judgment for words the automatic checks
        cannot resolve — so it is simply recomputed each time the list is
        used, here and later when it feeds a learner's lexicon check.

        :param language: language code of the curated list, e.g. `de`
        :param frequency_list_id: source frequency list identifier, e.g.
            `de_opensubtitles_2024` (see `emmio data build-panel`)
        :param stratum: restrict to one stratum, or `None` for the whole
            list
        """
        list_id: int | None = postgres.get_curated_list_id(
            language, frequency_list_id
        )
        if list_id is None:
            self.interface.print(
                f"No curated list for `{language}`/`{frequency_list_id}`. "
                "Build one first with `emmio data build-panel`."
            )
            return

        word_language: Language = Language.from_code(language)
        alphabet: str | None = word_language.get_symbols()
        non_proper_nouns: frozenset[str] = NON_PROPER_NOUNS.get(
            language, frozenset()
        )
        frequency_list: FrequencyList | None = self.data.get_frequency_list(
            parse_frequency_list_identifier(frequency_list_id, language)
        )

        dictionaries: DictionaryCollection = self.data.get_dictionaries(
            [
                DictionaryUsageConfig(
                    id="kaikki",
                    from_language=language,
                    name=word_language.get_name(),
                )
            ]
        )
        # TODO(enzet): get definitions languages from user settings.
        definitions_languages: list[Language] = [
            KnownLanguages.ENGLISH,
            KnownLanguages.RUSSIAN,
        ]
        sentences_data: SentencesData = self.data.get_sentences_data()
        sentences_usage_configs: list[SentencesUsageConfig] = [
            SentencesUsageConfig(id="tatoeba", language=language)
        ]

        curated_count: int = 0
        auto_resolved_count: int = 0
        skipped_this_run: set[str] = set()
        while True:
            word: str | None = postgres.get_next_curation_candidate(
                list_id, self.user_id, stratum, exclude=skipped_this_run
            )
            if word is None:
                self.interface.print("Nothing left to curate. Well done!")
                break

            if (
                await classify_automatically(
                    word,
                    word_language,
                    alphabet,
                    frequency_list,
                    non_proper_nouns,
                    dictionaries,
                )
                is not None
            ):
                skipped_this_run.add(word)
                auto_resolved_count += 1
                continue

            self.interface.print(Header(word))

            # Only look up an example if Tatoeba sentences are already
            # cached locally: building that cache means downloading
            # Tatoeba's full links export, which would stall this
            # word-by-word loop on whichever word happens to go first.
            sentence_and_translations = (
                sentences_data.get(word, sentences_usage_configs, max_number=50)
                if sentences_data.has_tatoeba_word_cache(word_language)
                else []
            )
            if sentence_and_translations:
                sentence = random.choice(sentence_and_translations).sentence
                text: Text = Text()
                for part, element_type in sentence.get_words(word_language):
                    if (
                        element_type == SentenceElement.WORD
                        and word_language.normalize(part) == word
                    ):
                        text.add(Formatted(part, "bold"))
                    else:
                        text.add(part)
                self.interface.print(
                    Text().add(Colorized("Example: ", "#AAAAAA")).add(text)
                )

            translation: list[Element] | None = await dictionaries.to_text(
                word, word_language, definitions_languages
            )
            if translation:
                for element in translation:
                    self.interface.print(element)

            answer: str = self.interface.choice(
                CURATION_CATEGORIES, "Category?"
            )
            if answer == "Quit":
                break

            postgres.record_curation_vote(
                list_id, word, CURATION_CATEGORY_CODES[answer], self.user_id
            )
            curated_count += 1

        self.interface.print(
            f"Curated {curated_count} word(s), {auto_resolved_count} "
            "auto-resolved and left unrecorded."
        )

    def import_lexicon_curation_votes(
        self, language: str, frequency_list_id: str, stratum: int | None
    ) -> None:
        """Vote on curated-panel words using this user's lexicon history.

        `emmio lexicon` answers already encode a curation judgment: `KNOW`,
        `KNOW_SEMANTIC_CLASS` and `DONT` (recognizing a word without
        knowing it is still recognizing it as a word) confirm the word is
        real (group (1)); `DONT_BUT_PROPER_NOUN_TOO` and `NOT_A_WORD` are
        legacy-only response types (`ask` now writes a category (2) vote
        directly instead of using them, see
        `LexiconChecker._record_not_to_check_vote`), but old records using
        them still carry real signal, so they import as `Proper noun` and
        `Not a word` respectively (see
        `LEXICON_RESPONSE_TO_CURATION_CATEGORY`). This reuses that history
        as curator votes instead of asking the same question again in
        `emmio curate`.

        Scope is deliberately narrow: only panel words this curator has
        not already voted on are considered (an earlier explicit
        `emmio curate` vote is never overwritten), and only the panel's
        existing words are touched — a word missing from the panel is
        never added here, whatever its history; growing the panel is
        `emmio data build-panel`'s job alone. `--stratum` narrows further,
        the same as it does for `emmio curate`.

        Only genuine `AnswerType.USER_ANSWER` records count — propagated
        and automatically-assumed answers are excluded, for the same
        reason `curate` never auto-votes: only human decisions belong in
        `curated_words`/`curated_word_records`.

        :param language: language code of the curated list, e.g. `de`
        :param frequency_list_id: source frequency list identifier, e.g.
            `de_opensubtitles_2024` (see `emmio data build-panel`)
        :param stratum: restrict to one stratum, or `None` for the whole
            list
        """
        list_id: int | None = postgres.get_curated_list_id(
            language, frequency_list_id
        )
        if list_id is None:
            self.interface.print(
                f"No curated list for `{language}`/`{frequency_list_id}`. "
                "Build one first with `emmio data build-panel`."
            )
            return

        unvoted: set[str] = postgres.get_curator_unvoted_words(
            list_id, self.user_id, stratum
        )
        if not unvoted:
            self.interface.print(
                "Nothing to import: you have already voted on every panel "
                "word in scope."
            )
            return

        word_language: Language = Language.from_code(language)
        latest_response: dict[str, LexiconResponse] = {}
        latest_time: dict[str, datetime] = {}
        for lexicon in self.user_data.get_lexicons_by_language(word_language):
            for record in lexicon.log.records:
                if record.answer_type != AnswerType.USER_ANSWER:
                    continue
                if (
                    record.word not in latest_time
                    or record.time > latest_time[record.word]
                ):
                    latest_time[record.word] = record.time
                    latest_response[record.word] = record.response

        voted_count: int = 0
        ambiguous_count: int = 0
        for word in unvoted:
            response: LexiconResponse | None = latest_response.get(word)
            if response is None:
                continue
            category: str | None = LEXICON_RESPONSE_TO_CURATION_CATEGORY.get(
                response
            )
            if category is None:
                ambiguous_count += 1
                continue
            postgres.record_curation_vote(list_id, word, category, self.user_id)
            voted_count += 1

        no_history_count: int = len(unvoted) - voted_count - ambiguous_count
        self.interface.print(
            f"Imported {voted_count} vote(s) from lexicon-check history "
            f"({ambiguous_count} skipped as ambiguous, {no_history_count} "
            "had no matching history)."
        )

    async def learn(self, learnings: list[Learning]) -> None:
        """Start learning process."""

        reply: str
        do_continue: bool
        teacher: Teacher
        learning: Learning

        while True:
            learnings = sorted(
                learnings, key=lambda learning: learning.compare_by_old()
            )
            learning = learnings[0]
            if learning.count_questions_to_repeat() > 0:
                teacher = Teacher(
                    self.interface,
                    self.data,
                    self.user_data,
                    learning,
                    stop_after_answer=True,
                )
                self.interface.print(
                    Header(
                        "Repeat questions for "
                        + learning.learning_language.get_name()
                    )
                )
                do_continue = await teacher.repeat(max_actions=10)
                reply = self.interface.choice(
                    [("Yes", "y"), ("No", "n")], "Continue?"
                )
                if reply == "No" or not do_continue:
                    return
            else:
                learnings = sorted(
                    learnings, key=lambda learning: learning.compare_by_new()
                )
                learning = learnings[0]
                if learning.count_questions_to_add() > 0:
                    teacher = Teacher(
                        self.interface,
                        self.data,
                        self.user_data,
                        learning,
                        stop_after_answer=True,
                    )
                    self.interface.print(
                        Header(
                            "Learn new words for "
                            + learning.learning_language.get_name()
                        )
                    )
                    do_continue = await teacher.learn_new()
                    self.interface.print("All new words added")
                    reply = self.interface.choice(
                        [("Yes", "y"), ("No", "n")], "Continue?"
                    )
                    if reply == "No" or not do_continue:
                        return
                else:
                    break

        now: datetime = datetime.now(UTC)
        total_nearest: datetime = now

        for learning in self.user_data.get_learn_data().learnings.values():
            if not learning.config.is_active:
                continue
            nearest: datetime | None = learning.get_nearest()
            if nearest is None or nearest <= now:
                continue
            total_nearest = min(total_nearest, nearest)

        time_to_repetition: timedelta = total_nearest - now
        time_to_new: timedelta = util.day_end(now) - now

        if time_to_repetition < time_to_new:
            self.interface.print(
                Block(f"Repetition in {time_to_repetition}.", (1, 4, 1, 4))
            )

        else:
            self.interface.print(
                Block(f"New question in {time_to_new}.", (1, 4, 1, 4))
            )

    async def listen(
        self, listening_id: str, start_from: int, repeat: int
    ) -> None:
        """Listen to the audio."""

        listener: Listener = Listener(
            self.user_data.get_listening(listening_id),
            self.data,
            self.user_data,
            self.interface,
        )
        await listener.listen(start_from, repeat)

    def plot_lexicon(
        self, arguments: argparse.Namespace, *, interactive: bool
    ) -> None:
        """Plot lexicon."""

        languages: list[Language] | None = (
            [Language.from_code(x) for x in arguments.languages]
            if arguments.languages
            else None
        )
        first_point: Callable[[datetime], datetime]
        next_point: Callable[[datetime], datetime]

        if arguments.interval == "year":
            first_point = util.year_start
            next_point = util.plus_year
        elif arguments.interval == "week":
            first_point = util.week_start
            next_point = util.plus_week
        elif arguments.interval == "month":
            first_point = util.month_start
            next_point = util.plus_month
        else:
            message = f"Unknown interval: `{arguments.interval}`."
            raise ValueError(message)

        lexicons: dict[Language, list[Lexicon]] = {
            language: [
                lexicon
                for lexicon in lexicons
                if lexicon.id_ not in arguments.exclude
            ]
            for language, lexicons in self.user_data.get_frequency_lexicons(
                languages
            ).items()
        }
        lexicon_visualizer: LexiconVisualizer = LexiconVisualizer(
            self.interface,
            self.output_path,
            plot_main=arguments.show_main,
            plot_averages=arguments.show_averages,
            plot_precise_values=arguments.show_precise_values,
            plot_precision_interval=arguments.show_precision_interval,
            precision=arguments.precision,
            interactive=interactive,
            first_point=first_point,
            next_point=next_point,
        )
        colors: list[Color] | None = None
        if arguments.color:
            colors = [Color(color) for color in arguments.color]

        match arguments.type:
            case "tikz":
                lexicon_visualizer.graph_with_tikz(
                    lexicons, margin=arguments.margin
                )
            case "matplot":
                lexicon_visualizer.graph_with_matplot(
                    lexicons, legend=arguments.legend, margin=arguments.margin
                )
            case _:
                lexicon_visualizer.graph_with_svg(
                    lexicons,
                    arguments.margin,
                    colors,
                    Color(arguments.background_color),
                    Color(arguments.grid_color),
                )

    def plot_actions(self, arguments: argparse.Namespace) -> None:
        """Plot actions."""

        records: list[tuple[LearningRecord, Learning]] = []
        for learning in self.user_data.get_active_learnings():
            records += [(x, learning) for x in learning.process.records]
        records = sorted(records, key=lambda record: record[0].time)

        days: float

        if arguments.moving:
            match arguments.interval:
                case "week":
                    days = 7
                case "month":
                    days = 30
                case "year":
                    days = 365
                case _:
                    days = 10

            Visualizer().cumulative_actions_moving(records, days=days)
        else:
            locator, days = util.day_start, 1
            if arguments.interval == "week":
                locator, days = util.week_start, 7
            elif arguments.interval == "month":
                locator, days = util.month_start, 31
            elif arguments.interval == "year":
                locator, days = util.year_start, 365 * 0.6

            Visualizer().cumulative_actions(
                records,
                list(self.user_data.get_lexicons()),
                point=locator,
                width=days,
                by_language=not arguments.depth,
            )

    async def to_learn(self) -> None:
        """Print words to learn."""

        rows: list[list[InlineElement | str]] = []
        for learning in self.user_data.get_active_learnings():
            rows.append([f"== {learning.config.name} =="])
            for word, knowledge in learning.knowledge.items():
                if knowledge.get_last_response() != Response.WRONG:
                    continue
                items = await self.data.dictionaries.get_dictionaries(
                    learning.config.dictionaries
                ).get_items(word, learning.learning_language)

                if not items:
                    rows.append([word])
                    continue

                transcription, text = items[0].get_short(
                    learning.base_languages[0]
                )
                if transcription:
                    text = f"[yellow]{transcription} [black]{text}"
                rows.append([word, text])

        self.interface.print(Table(["Word", "Translation"], rows))

    async def schedule(self) -> None:
        """Print schedule of questions to repeat."""

        now: datetime = datetime.now(UTC)

        interval: str = "month"
        points: int
        schedule: list[int]
        delta: timedelta
        start: datetime
        from_seconds: int

        match interval:
            case "day":
                points = 24
                schedule = [0] * points
                delta = timedelta(days=1)
                start = datetime(
                    year=now.year,
                    month=now.month,
                    day=now.day,
                    hour=now.hour,
                    tzinfo=UTC,
                )
                from_seconds = 60 * 60
            case "month":
                points = 30
                schedule = [0] * points
                delta = timedelta(days=30)
                start = datetime(
                    year=now.year, month=now.month, day=now.day, tzinfo=UTC
                )
                from_seconds = 60 * 60 * 24
            case _:
                return

        rows: list[list[InlineElement | str]] = []
        for learning in self.user_data.get_active_learnings():
            for knowledge in learning.knowledge.values():
                if not knowledge.is_learning():
                    continue
                if start <= learning.get_next_time(knowledge) < start + delta:
                    seconds: timedelta = (
                        learning.get_next_time(knowledge) - start
                    )
                    schedule[int(seconds.total_seconds() // from_seconds)] += 1
                elif learning.get_next_time(knowledge) < now:
                    schedule[0] += 1

        for point in range(points):
            time: datetime = start + delta * point
            rows.append(
                [
                    f"{time.day:2}",
                    f"{time.hour:2}:00",
                    f"{schedule[point]:2} {progress(schedule[point])}",
                ]
            )
        self.interface.print(Table(["Day", "Time", "To repeat"], rows))
