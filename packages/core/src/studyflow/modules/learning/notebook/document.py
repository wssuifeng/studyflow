"""Bounded semantic JSON. No HTML, URLs, arbitrary attributes or executable nodes."""
from __future__ import annotations
import copy
import json
import unicodedata
from studyflow.shared.domain import DomainError

MAX_ENTRIES = 1000
MAX_CHARS = 1_000_000
MAX_NODES = 50000
MAX_JSON_BYTES = 8_000_000
BLOCKS = {"paragraph", "heading", "bulletList", "orderedList"}
CONTAINERS = {"paragraph": {"text", "hardBreak"}, "heading": {"text", "hardBreak"},
              "bulletList": {"listItem"}, "orderedList": {"listItem"},
              "listItem": {"paragraph", "bulletList", "orderedList"}}


def invalid(message):
    raise DomainError("INVALID_ARGUMENT", message)


def identity(value, label="ID"):
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        invalid(f"{label}必须是1—64字符文本。")
    return value


def normalize(text):
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def plain(nodes):
    def node_text(node):
        if node["type"] == "text": return node["text"]
        if node["type"] == "hardBreak": return "\n"
        sep = "\n" if node["type"] in {"bulletList", "orderedList", "listItem"} else ""
        return sep.join(node_text(n) for n in node.get("content", []))
    return "\n".join(node_text(n) for n in nodes)


def validate_content(content, source_ids):
    if not isinstance(content, list) or not content: invalid("记录至少需要一个段落。")
    count = 0
    def check(node, allowed, depth=0):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > 12: invalid("笔记节点数量或嵌套超限。")
        if not isinstance(node, dict) or node.get("type") not in allowed: invalid("不支持的笔记节点。")
        kind = node["type"]
        if set(node) - {"type", "text", "attrs", "content", "marks"}: invalid("笔记节点包含未知字段。")
        attrs = node.get("attrs", {})
        if not isinstance(attrs, dict): invalid("节点属性无效。")
        allowed_attrs = {"level"} if kind == "heading" else {"start"} if kind == "orderedList" else set()
        if set(attrs) - allowed_attrs: invalid("笔记节点含非受控属性。")
        if kind == "heading" and (type(attrs.get("level")) is not int or attrs["level"] not in {2, 3}): invalid("小标题只支持两级。")
        if kind == "orderedList" and (type(attrs.get("start", 1)) is not int or not 1 <= attrs.get("start", 1) <= 10000): invalid("列表起始编号无效。")
        if kind == "text":
            if not isinstance(node.get("text"), str) or not node["text"] or "content" in node: invalid("文本节点无效。")
            marks = node.get("marks", [])
            if not isinstance(marks, list) or len(marks) > 4: invalid("文字标记超限。")
            seen = set()
            for mark in marks:
                if not isinstance(mark, dict) or set(mark) - {"type", "attrs"}: invalid("非受控文字标记。")
                m = mark.get("type")
                if m not in {"bold", "italic", "code", "citation"} or m in seen: invalid("文字标记无效或重复。")
                seen.add(m)
                if m == "citation":
                    a = mark.get("attrs", {})
                    if not isinstance(a, dict) or set(a) != {"sourceId", "occurrenceId"}: invalid("出处标记必须明确来源与实例。")
                    identity(a["sourceId"], "出处ID")
                    identity(a["occurrenceId"], "引用实例ID")
                    if a["sourceId"] not in source_ids: invalid("引用出处不存在于当前计划笔记。")
                elif mark.get("attrs"): invalid("普通文字标记不能携带属性。")
        else:
            if "text" in node or node.get("marks"): invalid("容器节点不能附加文字或标记。")
            children = node.get("content", [])
            if not isinstance(children, list): invalid("节点内容必须是列表。")
            if kind in {"bulletList", "orderedList", "listItem"} and not children: invalid("列表容器不能为空。")
            if kind == "listItem" and children and children[0].get("type") != "paragraph": invalid("列表项必须从段落开始。")
            if kind == "hardBreak" and children: invalid("换行节点不能含子节点。")
            for child in children: check(child, CONTAINERS.get(kind, set()), depth + 1)
    for n in content: check(n, BLOCKS)
    if len(plain(content)) > 200000: invalid("单记录文字不能超过20万字符。")
    return copy.deepcopy(content)


def validate_document(entries, sources):
    if len(entries) > MAX_ENTRIES: invalid("计划笔记最多1000条记录。")
    ids = set(); occurrences = {}; total = 0; node_count = 0
    if sum(len(s["original"]) for s in sources.values()) > MAX_CHARS: invalid("出处摘录总长度不能超过100万字符。")
    for entry in entries:
        eid = identity(entry.get("id"), "记录ID")
        if eid in ids: invalid("记录ID重复。")
        ids.add(eid)
        validate_content(entry["content"], sources)
        total += len(plain(entry["content"]))
        last_occurrence = None; completed = set()
        def walk(nodes):
            nonlocal node_count, last_occurrence
            for node in nodes:
                node_count += 1
                if node_count > MAX_NODES: invalid("计划笔记节点总数超过50000。")
                if node["type"] == "text":
                    ref = next((m for m in node.get("marks", []) if m["type"] == "citation"), None)
                    current = ref["attrs"]["occurrenceId"] if ref else None
                    if current != last_occurrence:
                        if last_occurrence is not None: completed.add(last_occurrence)
                        if current is not None and current in completed: invalid("不连续引用区间需要独立实例ID。")
                        last_occurrence = current
                for mark in node.get("marks", []):
                    if mark["type"] == "citation":
                        a = mark["attrs"]; owner = (eid, a["sourceId"])
                        if a["occurrenceId"] in occurrences and occurrences[a["occurrenceId"]] != owner:
                            invalid("跨记录引用实例需要独立ID。")
                        occurrences[a["occurrenceId"]] = owner
                walk(node.get("content", []))
        walk(entry["content"])
    if total > MAX_CHARS: invalid("计划笔记总长度不能超过100万字符。")
    if len(json.dumps(entries, ensure_ascii=False).encode()) > MAX_JSON_BYTES: invalid("笔记JSON超过8MB。")
    return entries


def citations(entries, sources):
    result = []
    for e in entries:
        chunks = {}
        def walk(node):
            for mark in node.get("marks", []):
                if mark["type"] == "citation":
                    a = mark["attrs"]; chunks.setdefault(a["occurrenceId"], {"source_id": a["sourceId"], "text": ""})["text"] += node.get("text", "")
            for child in node.get("content", []): walk(child)
        for n in e["content"]:
            existing = set(chunks)
            # A newline belongs only to an instance spanning the adjacent paragraphs.
            before = {key: value["text"] for key, value in chunks.items()}
            walk(n)
            for key in existing:
                if chunks[key]["text"] != before[key]:
                    chunks[key]["text"] = before[key] + "\n" + chunks[key]["text"][len(before[key]):]
        for oid, chunk in chunks.items():
            source = sources[chunk["source_id"]]
            c, o = normalize(chunk["text"]), normalize(source["original"])
            state = "ORIGINAL" if c == o else "PARTIAL" if c and c in o else "EDITED"
            result.append({"entry_id": e["id"], "occurrence_id": oid, "source_id": chunk["source_id"], "state": state})
    return result
