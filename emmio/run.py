"""Emmio entry point."""

import argparse
import logging
import shlex
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from colour import Color

from emmio import inventory, util
from emmio.data import Data
from emmio.graph import Visualizer
from emmio.language import Language, LanguageNotFoundError
from emmio.learn.core import Learning, LearningRecord, Response
from emmio.learn.teacher import Teacher
from emmio.learn.visualizer import LearningVisualizer
from emmio.lexicon.core import (
    RATE_ESTIMATOR_BY_SELECTION,
    Lexicon,
    LexiconChecker,
)
from emmio.lexicon.goal import compute_lexicon_goal_state
from emmio.lexicon.visualizer import LexiconVisualizer
from emmio.listen.listener import Listener
from emmio.lists.frequency_list import FrequencyList
from emmio.paths import DEFAULT_OUTPUT_DIRECTORY
from emmio.text.annotate import TextAnnotator
from emmio.ui import (
    Block,
    Colorized,
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
