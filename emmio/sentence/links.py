from emmio.serialization import Decoder, Encoder


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


class LinksDecoder(Decoder):
    """Decoder for links between Tatoeba sentences."""

    MAGIC: bytes = b"EMMLNK"
    VERSION_MAJOR: int = 0
    VERSION_MINOR: int = 1

    def decode(self) -> dict[int, int]:
        """Decode links between Tatoeba sentences from the binary format."""
        links: dict[int, int] = {}

        while True:
            try:
                links[self.decode_int(4)] = self.decode_int(4)
            except EOFError:
                break

        return links
