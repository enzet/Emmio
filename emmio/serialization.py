import io
from typing import Optional


ENDIAN: str = "little"


class Encoder:
    """Encoding lexicon structure."""

    MAGIC: bytes = b"XXXXXX"
    VERSION_MAJOR: int = 0
    VERSION_MINOR: int = 0

    def __init__(self, code: io.BytesIO) -> None:
        self.code: io.BytesIO = code

    def encode_magic(self) -> None:
        self.code.write(self.MAGIC)
        self.encode_int(self.VERSION_MAJOR, 1)
        self.encode_int(self.VERSION_MINOR, 1)

    def encode_string(self, text: str) -> None:
        """
        Encode string value into 4-bytes integer of the length and UTF-8 value.
        """
        text_code: bytes = text.encode()
        self.code.write(
            len(text_code).to_bytes(2, ENDIAN, signed=False) + text_code
        )

    def encode_int(self, value: int, size: int) -> None:
        """Encode integer value."""
        self.code.write(value.to_bytes(size, ENDIAN, signed=False))

    def encode_float(self, value: float, size: int) -> None:
        """Encode integer value."""
        integer_part: int = int(value)
        self.encode_int(integer_part, size)
        self.encode_int(int((value - integer_part) * 1_000_000), 2)

    def encode_boolean(self, value: bool) -> None:
        """Encode Boolean value."""
        self.code.write(b"\x01" if value else b"\x00")

    def encode_ternary(self, value: Optional[bool]) -> None:
        """Encode optional Boolean value."""
        if value is None:
            self.code.write(b"\x02")
        else:
            self.encode_boolean(value)

    def encode_enum(self, value: str, values: list[str]) -> None:
        """
        Encode value of an enum.

        Store number of the entry in the entry list starting with 1 (0 is used
        if value is not specified).
        """
        self.code.write(
            (values.index(value) + 1).to_bytes(1, ENDIAN, signed=False)
        )
