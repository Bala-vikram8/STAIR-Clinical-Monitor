"""Read the publisher's section XML without dropping its tables or notes."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET


CNXML = "http://cnx.rice.edu/cnxml"
MATHML = "http://www.w3.org/1998/Math/MathML"


@dataclass(frozen=True)
class ParsedModule:
    """One original section title and its readable source text."""

    title: str
    text: str
    warnings: tuple[str, ...]
    tags: tuple[str, ...]


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _fragment(text: str | None) -> str:
    # Collapse XML indentation but keep spaces around inline words and symbols.
    return re.sub(r"\s+", " ", text or "")


def _finish(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _block(text: str) -> str:
    return "\n\n" + text.strip() + "\n\n"


def _alphabetic(number: int) -> str:
    result = ""
    while number > 0:
        number, digit = divmod(number - 1, 26)
        result = chr(97 + digit) + result
    return result


def _roman(number: int) -> str:
    result = ""
    for value, symbol in [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
                          (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                          (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]:
        count, number = divmod(number, value)
        result += symbol * count
    return result


class _Renderer:
    def __init__(self) -> None:
        self.warnings: set[str] = set()

    def children(self, element: ET.Element) -> str:
        text = _fragment(element.text)
        for child in element:
            text += self.render(child) + _fragment(child.tail)
        return text

    def original_markup(self, element: ET.Element, reason: str) -> str:
        self.warnings.add(reason)
        # ElementTree includes the following text in its serialization otherwise.
        standalone = copy(element)
        standalone.tail = None
        return "[Original source markup: " + ET.tostring(standalone, encoding="unicode") + "]"

    def math(self, element: ET.Element) -> str:
        name = _name(element)
        children = [self.render(child).strip() for child in element]
        if name in {"math", "mrow", "mtext", "mn", "mo", "mi", "mstyle", "mtd"}:
            return self.children(element)
        if name == "mfrac" and len(children) == 2:
            return f"({children[0]})/({children[1]})"
        if name == "msup" and len(children) == 2:
            return f"{children[0]}^({children[1]})"
        if name == "msub" and len(children) == 2:
            return f"{children[0]}_({children[1]})"
        if name == "msubsup" and len(children) == 3:
            return f"{children[0]}_({children[1]})^({children[2]})"
        if name == "msqrt":
            return "sqrt(" + self.children(element).strip() + ")"
        if name == "mroot" and len(children) == 2:
            return f"root({children[1]}, {children[0]})"
        if name == "munder" and len(children) == 2:
            return f"{children[0]} [below: {children[1]}]"
        if name == "mover" and len(children) == 2:
            return f"{children[0]} [above: {children[1]}]"
        if name == "mtr":
            return " | ".join(children)
        if name == "mtable":
            return "[" + "; ".join(children) + "]"
        if name == "mfenced":
            return element.get("open", "(") + ", ".join(children) + element.get("close", ")")
        return self.original_markup(element, f"Math element {name} retained as original markup.")

    def listed(self, element: ET.Element) -> str:
        lines = []
        if element.text and element.text.strip():
            lines.append(_fragment(element.text).strip())
        try:
            start = int(element.get("start-value", "1"))
            if not 1 <= start <= 10000:
                raise ValueError
        except ValueError:
            return self.original_markup(element, "A list with an unsupported start value was retained as source markup.")
        enumerated = element.get("list-type") == "enumerated"
        style = element.get("number-style", "arabic")
        count = start
        for child in element:
            if _name(child) != "item":
                lines.append(self.render(child).strip())
                if child.tail and child.tail.strip():
                    lines.append(_fragment(child.tail).strip())
                continue
            if enumerated:
                if style in {"lower-alpha", "upper-alpha"}:
                    marker = _alphabetic(count)
                    if style == "upper-alpha":
                        marker = marker.upper()
                elif style in {"lower-roman", "upper-roman"}:
                    marker = _roman(count)
                    if style == "lower-roman":
                        marker = marker.lower()
                else:
                    marker = str(count)
                marker += "."
            else:
                marker = "-"
            lines.append(marker + " " + self.children(child).strip())
            if child.tail and child.tail.strip():
                lines.append(_fragment(child.tail).strip())
            count += 1
        return _block("\n".join(lines))

    def table_row(self, element: ET.Element) -> str:
        cells = []
        for entry in element:
            if _name(entry) != "entry":
                cells.append(self.render(entry).strip())
                continue
            value = re.sub(r"\s+", " ", self.children(entry)).strip()
            spans = []
            if entry.get("namest") or entry.get("nameend"):
                spans.append("columns " + entry.get("namest", "?") + " to " + entry.get("nameend", "?"))
            if entry.get("colname"):
                spans.append("column " + entry.get("colname", ""))
            if entry.get("morerows"):
                spans.append("additional rows " + entry.get("morerows", ""))
            if entry.get("spanname"):
                spans.append("span " + entry.get("spanname", ""))
            if spans:
                value = "[" + "; ".join(spans) + "] " + value
            cells.append(value)
        return "\n" + " | ".join(cells) + "\n"

    def render(self, element: ET.Element) -> str:
        name = _name(element)
        if element.tag.startswith("{" + MATHML + "}"):
            return self.math(element)
        if name in {"content", "item", "term", "emphasis", "meaning", "tgroup", "entry"}:
            return self.children(element)
        if name in {"para", "section", "title", "caption", "figure", "subfigure", "equation"}:
            return _block(self.children(element))
        if name in {"note", "example", "exercise", "problem", "solution", "glossary"}:
            label = {"problem": "Question", "solution": "Solution", "glossary": "Glossary"}.get(name, name.capitalize())
            return _block(label + ":\n" + self.children(element).strip())
        if name == "list":
            return self.listed(element)
        if name == "link":
            label = self.children(element).strip()
            destination = element.get("url", "")
            if not destination:
                destination = element.get("document", "")
                if element.get("target-id"):
                    destination += "#" + element.get("target-id", "")
                if element.get("resource"):
                    destination += "/" + element.get("resource", "")
            if not destination:
                return label
            return (label + " (" + destination + ")") if label else "[See " + destination + "]"
        if name in {"sup", "sub"}:
            return ("^" if name == "sup" else "_") + "(" + self.children(element).strip() + ")"
        if name == "newline":
            return "\n"
        if name == "space":
            return " "
        if name == "label":
            label = self.children(element).strip()
            return label + ": " if label else ""
        if name == "media":
            alt = element.get("alt", "").strip()
            if not alt:
                self.warnings.add("A source image has no alt text; its visual content is not represented.")
            return _block(("Image description: " + alt + "\n" if alt else "") + self.children(element))
        if name == "image":
            self.warnings.add("Images are referenced, not downloaded; use the original source for visual details.")
            alt = element.get("alt", "").strip()
            return "[Image not rendered; source file: " + element.get("src", "not supplied") + "]" + (" " + alt if alt else "")
        if name in {"table", "informaltable"}:
            summary = element.get("summary", "").strip()
            return _block("Table" + (": " + summary if summary else "") + "\n" + self.children(element))
        if name in {"thead", "tbody", "tfoot"}:
            label = {"thead": "Table headings", "tbody": "Table rows", "tfoot": "Table notes"}[name]
            return _block(label + ":\n" + self.children(element).strip())
        if name == "row":
            return self.table_row(element)
        if name == "colspec":
            return "\n[Column " + element.get("colname", "") + ": position " + element.get("colnum", "not stated") + "]\n"
        if name == "spanspec":
            return "\n[Column span " + element.get("spanname", "") + ": " + element.get("namest", "") + " to " + element.get("nameend", "") + "]\n"
        if name == "footnote":
            return " [Footnote: " + self.children(element).strip() + "] "
        if name == "definition":
            text = _fragment(element.text)
            for child in element:
                text += self.render(child)
                if _name(child) == "term":
                    text += ": "
                text += _fragment(child.tail)
            return _block(text)
        return self.original_markup(element, f"Source element {name} retained as original markup.")


def parse_module(raw: bytes) -> ParsedModule:
    """Read source text only. Do not resolve external entities, links, or images."""
    try:
        decoded = raw.decode("utf-8-sig")
    except (UnicodeDecodeError, AttributeError) as exc:
        raise ValueError("Expected a UTF-8 publisher section file.") from exc
    if "\x00" in decoded or re.search(r"<!\s*(DOCTYPE|ENTITY)\b", decoded, flags=re.IGNORECASE):
        raise ValueError("Section files must not contain DTDs or entity declarations.")
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as exc:
        raise ValueError("The publisher section XML is not well formed.") from exc
    if root.tag != "{" + CNXML + "}document":
        raise ValueError("Expected a publisher section document, not another XML file.")
    title_node = root.find("{" + CNXML + "}title")
    contents = root.findall("{" + CNXML + "}content")
    if title_node is None or not len(contents) == 1:
        raise ValueError("A section needs an original title and a single body.")
    renderer = _Renderer()
    title = _finish(renderer.children(title_node))
    # The publisher places glossary entries after <content>, not inside it.
    # Keep every non-metadata body element in its original document order.
    body = _finish("".join(
        renderer.render(child)
        for child in root
        if _name(child) not in {"title", "metadata"}
    ))
    if not title or not body:
        raise ValueError("A section title and its body must not be empty.")
    metadata = root.find("{" + CNXML + "}metadata")
    if metadata is not None:
        abstract = metadata.find("{http://cnx.rice.edu/mdml}abstract")
        if abstract is not None:
            summary = _finish(renderer.children(abstract))
            if summary and _fragment(summary).strip() not in _fragment(body).strip():
                body = "Publisher summary:\n" + summary + "\n\n" + body
    return ParsedModule(
        title=title,
        text=body,
        warnings=tuple(sorted(renderer.warnings)),
        tags=tuple(sorted({node.tag for node in root.iter()})),
    )
