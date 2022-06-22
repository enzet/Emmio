from emmio.serialization import Encoder


class LinksEncoder(Encoder):
    """Encoder for links between Tatoeba sentences."""

    MAGIC: bytes = b"EMMLNK"
    VERSION_MAJOR: int = 0
    VERSION_MINOR: int = 1

    def encode(self, links: dict[int, int]) -> None:
        """Encode links between Tatoeba sentences into a binary format."""
        for key, value in links.items():
            self.encode_int(key, 4)
            self.encode_int(value, 4)
