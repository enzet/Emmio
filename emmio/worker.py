class Worker:
    """Any learning or checking worker."""

    def __lt__(self, other: "Worker") -> bool:
        raise NotImplementedError()

    def is_ready(self) -> bool:
        """Check if worker has next message to send."""
        pass

    @staticmethod
    def get_greetings() -> str:
        """Return greetings to tell that worker is ready."""
        return "Hello."

    def get_next_question(self) -> list[str]:
        """Return list of next messages."""
        pass

    def process_answer(self, message) -> str:
        """Process user response."""
        pass
