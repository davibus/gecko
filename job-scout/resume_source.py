"""Read the Word master directly, preserving paragraph and table order."""

from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_master_text(path: str | Path) -> str:
    """Read a fresh DOCX; never substitute an older master or cached export."""
    path = Path(path)
    try:
        if path.suffix.lower() != ".docx":
            raise ValueError("The canonical master must be a Word DOCX document")
        with ZipFile(path) as package:
            document = ET.fromstring(package.read("word/document.xml"))
            styles = (ET.fromstring(package.read("word/styles.xml"))
                      if "word/styles.xml" in package.namelist() else None)
        style_lists = {}
        style_parents = {}
        if styles is not None:
            for style in styles.findall(W + "style"):
                identifier = style.get(W + "styleId")
                style_lists[identifier] = style.find(W + "pPr/" + W + "numPr")
                parent = style.find(W + "basedOn")
                style_parents[identifier] = parent.get(W + "val") if parent is not None else None
        lines = []
        for paragraph in document.iter(W + "p"):
            text = "".join(
                node.text or "" if node.tag == W + "t" else
                "\t" if node.tag == W + "tab" else "\n"
                for node in paragraph.iter()
                if node.tag in {W + "t", W + "tab", W + "br", W + "cr"}
            )
            number = paragraph.find(W + "pPr/" + W + "numPr")
            style = paragraph.find(W + "pPr/" + W + "pStyle")
            identifier = style.get(W + "val") if style is not None else None
            visited = set()
            while number is None and identifier and identifier not in visited:
                visited.add(identifier)
                number = style_lists.get(identifier)
                identifier = style_parents.get(identifier)
            number_id = number.find(W + "numId") if number is not None else None
            is_list = number is not None and (number_id is None or number_id.get(W + "val") != "0")
            if is_list and text.strip() and not re.match(r"^[\u2022\ufffd*-]\s", text.lstrip()):
                text = "\u2022 " + text
            lines.extend(text.splitlines() or [""])
    except (OSError, ValueError, KeyError, BadZipFile, ET.ParseError) as error:
        raise OSError(f"Required Gecko master resume is missing or unreadable: {path}") from error
    content = "\n".join(lines)
    if not content.strip():
        raise ValueError(f"Required Gecko master resume is empty: {path}")
    return content
