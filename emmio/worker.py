from abc import ABC, abstractmethod


class Worker(ABC):
    """Any learning or checking worker."""

    @abstractmethod
    def __lt__(self, other: "Worker") -> bool:
        raise NotImplementedError()

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if worker has the next message to send."""
        raise NotImplementedError()

    @abstractmethod
    def get_next_question(self) -> list[str]:
        """Return list of next messages."""
        raise NotImplementedError()

    @abstractmethod
    def process_answer(self, message) -> str:
        """Process user response."""
        raise NotImplementedError()
