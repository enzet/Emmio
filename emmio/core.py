from datetime import datetime


class Record:
    """"""

    def get_time(self) -> datetime:
        raise NotImplementedError()


class Session:
    """"""

    def end_session(self, time: datetime, actions: int) -> None:
        raise NotImplementedError()

    def get_start(self) -> datetime:
        raise NotImplementedError()

    def get_end(self) -> datetime:
        raise NotImplementedError()
