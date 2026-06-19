"""Render Emmio UI elements as HTML for the web API.

A third rendering target for the shared `emmio.ui` element tree, alongside the
terminal and rich-console interfaces. All text content is HTML-escaped and only
a fixed set of tags is emitted, so the result is safe to insert into the page.
"""

from html import escape

from emmio.ui import (
    Block,
    Colorized,
    Element,
    Formatted,
    Header,
    Table,
    Text,
    Title,
)

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

_FORMAT_TAGS: dict[str, str] = {"bold": "b", "italic": "i", "underline": "u"}


def to_html(element: Element | str) -> str:
    """Render a single UI element (or string) as HTML."""

    if isinstance(element, str):
        return escape(element)

    if isinstance(element, Text):
        return "".join(to_html(child) for child in element.elements)

    if isinstance(element, Formatted):
        tag: str = _FORMAT_TAGS[element.format_]
        return f"<{tag}>{to_html(element.text)}</{tag}>"

    # Colors are a display concern decided later; render the inner content.
    if isinstance(element, Colorized):
        return to_html(element.text)

    if isinstance(element, Block):
        return f"<div>{to_html(element.text)}</div>"

    if isinstance(element, Header):
        return f"<h3>{to_html(element.text)}</h3>"

    if isinstance(element, Title):
        return f"<h2>{to_html(element.text)}</h2>"

    if isinstance(element, Table):
        head: str = "".join(f"<th>{to_html(c)}</th>" for c in element.columns)
        body: str = "".join(
            "<tr>"
            + "".join(f"<td>{to_html(cell)}</td>" for cell in row)
            + "</tr>"
            for row in element.rows
        )
        return (
            f"<table><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    message: str = f"Cannot render element of type `{type(element)}` as HTML."
    raise ValueError(message)


def elements_to_html(elements: list[Element]) -> str:
    """Render a list of UI elements as an HTML fragment."""
    return "\n".join(to_html(element) for element in elements)
