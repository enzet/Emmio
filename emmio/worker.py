from abc import ABC, abstractmethod

from emmio.ui import Text


class Worker(ABC):
    """Any learning or checking worker."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if worker has the next message to send."""
        raise NotImplementedError()

    @abstractmethod
    def get_next_question(self) -> Text | None:
        """Return next message."""
        raise NotImplementedError()

    @abstractmethod
    def process_answer(self, message) -> str:
        """Process user response."""
        raise NotImplementedError()
