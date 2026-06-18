"""Yuque Lake HTML to readable Markdown conversion helpers."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import zlib
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Doctype, NavigableString, Tag


def _collapse_ws(value: str) -> str:
    value = value.replace("\u200b", "")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def _escape_table(value: str) -> str:
    value = value.replace("\\", "\\\\").replace("|", "\\|")
    value = re.sub(r"\n+", "<br>", value)
    return value.strip() or " "


def _lakesheet_bytes(value: str) -> bytes:
    try:
        return value.encode("latin-1")
    except UnicodeEncodeError:
        return bytes(ord(char) & 0xFF for char in value)


def _lakesheet_cell_value(cell: Any) -> str:
    if not isinstance(cell, dict):
        return ""
    value = cell.get("v")
    if value is None:
        value = cell.get("m")
    if value is None:
        value = cell.get("f")
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _decode_card_value(value: str | None) -> Any:
    if not value:
        return {}
    raw = value[5:] if value.startswith("data:") else value
    raw = urllib.parse.unquote(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _first(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return None


def _text_from_html(fragment: str | None) -> str:
    if not fragment:
        return ""
    soup = BeautifulSoup(fragment, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return _collapse_ws(html.unescape(soup.get_text("\n")))


@dataclass
class MarkdownConversionStats:
    cards_total: int = 0
    diagram_plantuml: int = 0
    diagram_mermaid: int = 0
    boards: int = 0
    boards_as_mermaid: int = 0
    codeblocks: int = 0
    images: int = 0
    links: int = 0
    unknown_cards: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cards_total": self.cards_total,
            "diagram_plantuml": self.diagram_plantuml,
            "diagram_mermaid": self.diagram_mermaid,
            "boards": self.boards,
            "boards_as_mermaid": self.boards_as_mermaid,
            "codeblocks": self.codeblocks,
            "images": self.images,
            "links": self.links,
            "unknown_cards": dict(sorted(self.unknown_cards.items())),
        }


class LakeMarkdownConverter:
    def __init__(self) -> None:
        self.stats = MarkdownConversionStats()

    def convert(self, content: str) -> str:
        soup = BeautifulSoup(content or "", "html.parser")
        parts = [self.block(child).rstrip() for child in soup.contents]
        md = "\n\n".join(part for part in parts if part)
        return re.sub(r"\n{4,}", "\n\n\n", md).strip()

    def children_blocks(self, node: Tag) -> str:
        parts = [self.block(child).rstrip() for child in node.children]
        return "\n\n".join(part for part in parts if part).strip()

    def block(self, node: Any) -> str:
        if isinstance(node, Doctype):
            return ""
        if isinstance(node, NavigableString):
            return _collapse_ws(str(node))
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()
        if name in {"meta", "colgroup", "style", "script"}:
            return ""
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = self.inline(node)
            return f"{'#' * int(name[1])} {text}" if text else ""
        if name == "p":
            return self.inline(node)
        if name == "table":
            return self.table(node)
        if name in {"ul", "ol"}:
            return self.list_block(node, ordered=(name == "ol"))
        if name == "pre":
            return self.pre(node)
        if name == "blockquote":
            inner = self.children_blocks(node) or self.inline(node)
            return "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())
        if name == "card":
            return self.card(node)
        if name == "img":
            return self.image(node)
        if name in {"div", "section", "article", "body"}:
            return self.children_blocks(node)
        return self.inline(node)

    def inline(self, node: Any) -> str:
        if isinstance(node, Doctype):
            return ""
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()
        if name == "br":
            return "\n"
        if name == "card":
            return "\n\n" + self.card(node) + "\n\n"
        if name == "img":
            return self.image(node)
        text = _collapse_ws("".join(self.inline(child) for child in node.children))
        if not text:
            return ""
        if name in {"strong", "b"}:
            return f"**{text}**"
        if name in {"em", "i"}:
            return f"*{text}*"
        if name == "code":
            return f"`{text.replace('`', '\\`')}`"
        if name == "a" and node.get("href"):
            return f"[{text}]({node.get('href')})"
        return text

    def pre(self, node: Tag) -> str:
        code_node = node.find("code")
        code = code_node.get_text("\n") if code_node else node.get_text("\n")
        classes = " ".join(code_node.get("class", []) if code_node else node.get("class", []))
        match = re.search(r"language-([A-Za-z0-9_+-]+)", classes)
        language = match.group(1) if match else ""
        return f"```{language}\n{code.strip()}\n```"

    def list_block(self, node: Tag, ordered: bool) -> str:
        lines: list[str] = []
        for index, li in enumerate(node.find_all("li", recursive=False), start=1):
            marker = f"{index}." if ordered else "-"
            lines.append(f"{marker} {self.inline(li)}".rstrip())
        return "\n".join(lines)

    def table(self, node: Tag) -> str:
        rows: list[list[str]] = []
        for tr in node.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            row = [_escape_table(self.cell(cell)) for cell in cells]
            if row and any(cell.strip() for cell in row):
                rows.append(row)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [" "] * (width - len(row)) for row in rows]
        lines = [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    def cell(self, node: Tag) -> str:
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, Tag) and child.name and child.name.lower() in {"p", "div", "ul", "ol", "table", "card"}:
                parts.append(self.block(child))
            else:
                parts.append(self.inline(child))
        return _collapse_ws("\n".join(part for part in parts if part))

    def image(self, node: Tag) -> str:
        src = node.get("src") or node.get("data-src") or ""
        alt = _collapse_ws(node.get("alt") or node.get("title") or "image")
        return f"![{alt}]({src})" if src else ""

    def card(self, node: Tag) -> str:
        self.stats.cards_total += 1
        name = (node.get("name") or node.get("data-card-name") or "unknown").strip()
        key = name.lower()
        payload = _decode_card_value(node.get("value"))
        if key in {"diagram", "textdiagram"}:
            return self.diagram_card(payload)
        if key == "board":
            return self.board_card(payload)
        if key == "codeblock":
            return self.codeblock_card(payload)
        if key == "image":
            return self.image_card(payload)
        if key in {"yuque", "yuqueinline", "localdoc", "link", "bookmark", "bookmarkinline", "bookmarklink"}:
            return self.link_card(payload)
        if key in {"file", "video"}:
            return self.file_card(key, payload)
        if key in {"calendar", "datecard", "label", "mention"}:
            return self.text_card(payload)
        if key == "lockedtext":
            return self.text_card(payload) or "_Locked text is not readable from the Yuque API._"
        if key == "checkbox":
            return self.checkbox_card(payload)
        if key == "hr":
            return "---"
        self.stats.unknown_cards[name] = self.stats.unknown_cards.get(name, 0) + 1
        return self.text_card(payload)

    def diagram_card(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        diagram_type = str(_first(payload, ["type", "diagramType", "language"]) or "").lower()
        code = _first(payload, ["code", "source", "content"]) or ""
        url = _first(payload, ["url", "src", "renderUrl"])
        if diagram_type in {"puml", "plantuml", "uml"}:
            language = "plantuml"
            self.stats.diagram_plantuml += 1
        elif diagram_type in {"mermaid", "mmd"}:
            language = "mermaid"
            self.stats.diagram_mermaid += 1
        else:
            language = diagram_type or "text"
        parts = [f"```{language}\n{str(code).strip()}\n```"] if code else []
        if url:
            parts.append(f"> Diagram source: [{url}]({url})")
        return "\n\n".join(parts)

    def codeblock_card(self, payload: Any) -> str:
        self.stats.codeblocks += 1
        if not isinstance(payload, dict):
            return ""
        language = _first(payload, ["language", "lang", "mode"]) or ""
        code = _first(payload, ["code", "content", "text", "source"]) or ""
        return f"```{language}\n{str(code).strip()}\n```"

    def image_card(self, payload: Any) -> str:
        self.stats.images += 1
        if not isinstance(payload, dict):
            return ""
        src = _first(payload, ["src", "url", "originUrl", "downloadUrl"])
        if isinstance(payload.get("image"), dict):
            src = src or _first(payload["image"], ["src", "url", "originUrl"])
        alt = _first(payload, ["name", "title", "alt"]) or "image"
        text = _first(payload, ["ocr", "text", "description"])
        parts = [f"![{alt}]({src})"] if src else []
        if text:
            parts.append(f"> Image text: {_collapse_ws(str(text))}")
        return "\n\n".join(parts)

    def link_card(self, payload: Any) -> str:
        self.stats.links += 1
        if not isinstance(payload, dict):
            return ""
        title = _first(payload, ["title", "name", "text", "docTitle"]) or "Yuque link"
        url = _first(payload, ["url", "href", "link", "src"])
        if isinstance(payload.get("data"), dict):
            title = _first(payload["data"], ["title", "name", "text", "docTitle"]) or title
            url = _first(payload["data"], ["url", "href", "link", "src"]) or url
        return f"[{title}]({url})" if url else str(title)

    def file_card(self, card_type: str, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        title = _first(payload, ["name", "title", "fileName", "filename"]) or card_type
        url = _first(payload, ["url", "href", "src", "downloadUrl", "previewUrl"])
        if isinstance(payload.get("file"), dict):
            title = _first(payload["file"], ["name", "title", "fileName", "filename"]) or title
            url = _first(payload["file"], ["url", "href", "src", "downloadUrl", "previewUrl"]) or url
        label = "Video" if card_type == "video" else "File"
        return f"> {label}: [{title}]({url})" if url else f"> {label}: {title}"

    def text_card(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        text = _first(payload, ["text", "title", "name", "value", "date", "label"])
        if isinstance(payload.get("data"), dict):
            text = _first(payload["data"], ["text", "title", "name", "value", "date", "label"]) or text
        return str(text) if text else ""

    def checkbox_card(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return "- [ ]"
        checked = bool(_first(payload, ["checked", "value", "status"]))
        text = _first(payload, ["text", "title", "name"]) or ""
        return f"- [{'x' if checked else ' '}] {text}".rstrip()

    def board_card(self, payload: Any) -> str:
        self.stats.boards += 1
        if not isinstance(payload, dict):
            return ""
        body = payload.get("diagramData", {}).get("body", [])
        if not isinstance(body, list):
            return ""
        labels_by_id: dict[str, str] = {}
        parent_label_by_child: dict[str, str] = {}
        rows: list[tuple[str, str]] = []
        edges: list[tuple[str, str, str]] = []

        def item_label(item: dict[str, Any]) -> str:
            for key in ("text", "label", "title", "name"):
                if isinstance(item.get(key), str):
                    text = _text_from_html(item.get(key))
                    if text:
                        return text
            return _text_from_html(item.get("html")) if isinstance(item.get("html"), str) else ""

        def visit(item: dict[str, Any], parent_label: str | None = None) -> None:
            item_id = str(item.get("id") or "")
            item_type = str(item.get("type") or "item")
            own_label = item_label(item)
            children = item.get("children") if isinstance(item.get("children"), list) else []
            child_labels = [item_label(child) for child in children if isinstance(child, dict) and item_label(child)]
            group_label = own_label or " / ".join(child_labels[:3])
            if item_id and group_label:
                labels_by_id[item_id] = group_label
                rows.append((item_type, group_label))
            if parent_label and item_id:
                parent_label_by_child[item_id] = parent_label
            for child in children:
                if isinstance(child, dict):
                    child_id = str(child.get("id") or "")
                    if child_id and group_label:
                        parent_label_by_child[child_id] = group_label
                    visit(child, group_label or parent_label)

        for item in body:
            if isinstance(item, dict):
                visit(item)

        def endpoint_label(endpoint: Any) -> str:
            if not isinstance(endpoint, dict):
                return ""
            endpoint_id = str(endpoint.get("id") or "")
            return labels_by_id.get(endpoint_id) or parent_label_by_child.get(endpoint_id) or ""

        for item in body:
            if not isinstance(item, dict) or item.get("type") != "line":
                continue
            source = endpoint_label(item.get("source"))
            target = endpoint_label(item.get("target"))
            label = item_label(item)
            if source and target and source != target:
                edges.append((source, target, label))

        parts = ["> Yuque board card converted from source JSON."]
        mermaid = self.board_mermaid(edges)
        if mermaid:
            self.stats.boards_as_mermaid += 1
            parts.append(mermaid)
        seen: set[tuple[str, str]] = set()
        table = ["| Type | Text |", "| --- | --- |"]
        for item_type, label in rows:
            key = (item_type, label)
            if label and key not in seen:
                table.append(f"| {_escape_table(item_type)} | {_escape_table(label)} |")
                seen.add(key)
            if len(table) >= 122:
                table.append("| ... | More board items omitted. |")
                break
        if len(table) > 2:
            parts.append("\n".join(table))
        src = payload.get("src")
        if src:
            parts.append(f"> Board source: [{src}]({src})")
        return "\n\n".join(parts)

    def board_mermaid(self, edges: list[tuple[str, str, str]]) -> str:
        if not edges or len(edges) > 80:
            return ""
        ids: dict[str, str] = {}

        def node_id(label: str) -> str:
            if label not in ids:
                ids[label] = f"n{len(ids) + 1}"
            return ids[label]

        lines = ["```mermaid", "flowchart LR"]
        for source, target, label in edges:
            sid = node_id(source)
            tid = node_id(target)
            lines.append(f'  {sid}["{source.replace(chr(34), chr(92) + chr(34))}"]')
            lines.append(f'  {tid}["{target.replace(chr(34), chr(92) + chr(34))}"]')
            if label:
                lines.append(f'  {sid} -->|"{label.replace(chr(34), chr(92) + chr(34))}"| {tid}')
            else:
                lines.append(f"  {sid} --> {tid}")
        lines.append("```")
        return "\n".join(lines)


def _decode_lakesheet(content: str) -> list[dict[str, Any]]:
    payload = json.loads(content)
    if not isinstance(payload, dict) or payload.get("format") != "lakesheet":
        raise ValueError("not a lakesheet payload")
    sheet_blob = payload.get("sheet")
    if not isinstance(sheet_blob, str) or not sheet_blob:
        raise ValueError("lakesheet payload does not contain sheet data")
    decompressed = zlib.decompress(_lakesheet_bytes(sheet_blob))
    sheets = json.loads(decompressed.decode("utf-8"))
    if not isinstance(sheets, list):
        raise ValueError("lakesheet data is not a sheet list")
    return [sheet for sheet in sheets if isinstance(sheet, dict)]


def _lakesheet_sheet_to_markdown(sheet: dict[str, Any]) -> str:
    data = sheet.get("data")
    if not isinstance(data, dict) or not data:
        return ""

    row_map: dict[int, dict[int, str]] = {}
    max_col = -1
    for row_key, columns in data.items():
        if not isinstance(columns, dict):
            continue
        try:
            row_index = int(row_key)
        except (TypeError, ValueError):
            continue
        row_values: dict[int, str] = {}
        for col_key, cell in columns.items():
            try:
                col_index = int(col_key)
            except (TypeError, ValueError):
                continue
            value = _lakesheet_cell_value(cell)
            row_values[col_index] = value
            if value:
                max_col = max(max_col, col_index)
        if row_values:
            row_map[row_index] = row_values

    if max_col < 0:
        return ""

    rows: list[list[str]] = []
    for row_index in sorted(row_map):
        row = [row_map[row_index].get(col_index, "") for col_index in range(max_col + 1)]
        if any(cell.strip() for cell in row):
            rows.append(row)
    if not rows:
        return ""

    header = [cell if cell.strip() else f"Column {index + 1}" for index, cell in enumerate(rows[0])]
    body = rows[1:] or [["" for _ in header]]
    lines = [
        "| " + " | ".join(_escape_table(cell) for cell in header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(_escape_table(cell) for cell in row) + " |")
    return "\n".join(lines)


def lakesheet_to_markdown(content: str) -> tuple[str, dict[str, Any]]:
    sheets = _decode_lakesheet(content)
    parts: list[str] = []
    rows_total = 0
    for index, sheet in enumerate(sheets, start=1):
        table = _lakesheet_sheet_to_markdown(sheet)
        if not table:
            continue
        data = sheet.get("data") if isinstance(sheet.get("data"), dict) else {}
        rows_total += len(data)
        name = sheet.get("name") or sheet.get("id") or f"Sheet{index}"
        parts.append(f"## {name}\n\n{table}")
    return "\n\n".join(parts).strip(), {
        "source": "lakesheet",
        "sheets_total": len(sheets),
        "sheets_rendered": len(parts),
        "rows_total": rows_total,
    }


def lake_to_markdown(content: str) -> tuple[str, dict[str, Any]]:
    if content.lstrip().startswith("{"):
        try:
            return lakesheet_to_markdown(content)
        except Exception:
            pass

    converter = LakeMarkdownConverter()
    markdown = converter.convert(content)
    return markdown, converter.stats.as_dict()
