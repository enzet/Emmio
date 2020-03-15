from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Optional

from emmio.ui import log


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.in_td = False

    def error(self, message: str) -> None:
        log.error(message)

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "td":
            self.in_td = True

    def handle_endtag(self, tag) -> None:
        if tag == "td":
            self.in_td = False
        elif tag == "table":
            if self.current_table:
                self.tables.append(self.current_table)
                self.current_table = []
        elif tag == "tr":
            if self.current_row:
                self.current_table.append(self.current_row)
                self.current_row = []

    def handle_data(self, data) -> None:
        if self.in_td:
            self.current_row.append(data.strip())


def parse_date(date_string: str) -> Optional[datetime]:
    for date_format in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(date_string, date_format)
        except ValueError:
            pass

    return None


class MemriseDataRecord:
    def __init__(
            self, course_name: str, date_from: datetime, date_to: datetime,
            num_tests: int, score: float):

        self.course_name = course_name
        self.date_from = date_from
        self.date_to = date_to
        self.num_tests = num_tests
        self.score = score


class MemriseData:
    def __init__(self, file_name: str):
        with open(file_name, "r") as input_file:
            content = input_file.read()

        parser = TableParser()
        parser.feed(content)

        self.all_tests = 0
        self.data = []

        for row in parser.tables[4]:
            course_name, _, from_date, to_date, num_tests, score = row

            if num_tests:
                self.all_tests += int(num_tests)

            if to_date:
                f = parse_date(from_date)
                t = parse_date(to_date)

                self.data.append(MemriseDataRecord(
                    course_name, f, t, int(num_tests), float(score)))
