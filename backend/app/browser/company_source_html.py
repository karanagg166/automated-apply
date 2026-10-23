"""Bounded, nonexecuting public-description extraction. No full HTML reaches models."""

import re
from html.parser import HTMLParser

from backend.app.core.text import normalize, phrase_in

SKIP = {
    "label",
    "form",
    "input",
    "textarea",
    "select",
    "button",
    "script",
    "style",
    "noscript",
    "template",
    "nav",
    "header",
    "footer",
    "iframe",
    "object",
    "dialog",
}
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = [{"tag": "root", "attrs": {}, "children": [], "hidden": False}]
        self.stack = [0]

    def handle_starttag(self, tag, attributes):
        if len(self.nodes) >= 8192 or len(self.stack) > 128:
            raise ValueError("Unsupported company document")
        attrs = dict(attributes)
        style = re.sub(r"\s+", "", attrs.get("style") or "").casefold()
        hidden = (
            self.nodes[self.stack[-1]]["hidden"]
            or tag in SKIP
            or "hidden" in attrs
            or "inert" in attrs
            or "contenteditable" in attrs
            or attrs.get("aria-hidden", "").casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or bool(
                set((attrs.get("class") or "").split())
                & {"hidden", "sr-only", "visually-hidden"}
            )
        )
        index = len(self.nodes)
        self.nodes.append(
            {"tag": tag, "attrs": attrs, "children": [], "hidden": hidden}
        )
        self.nodes[self.stack[-1]]["children"].append(index)
        if tag not in VOID:
            self.stack.append(index)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for offset in range(len(self.stack) - 1, 0, -1):
            if self.nodes[self.stack[offset]]["tag"] == tag:
                del self.stack[offset:]
                return

    def handle_data(self, data):
        if not self.nodes[self.stack[-1]]["hidden"]:
            self.nodes[self.stack[-1]]["children"].append(data)

    def text(self, index):
        node = self.nodes[index]
        if node["hidden"]:
            return ""
        return " ".join(
            " ".join(
                self.text(child) if isinstance(child, int) else child
                for child in node["children"]
            ).split()
        )


def extract(html, company_name):
    document = Document()
    document.feed(html)
    nodes = document.nodes
    titles = [
        document.text(i)
        for i, n in enumerate(nodes)
        if n["tag"] in {"title", "h1"} and not n["hidden"]
    ]
    if not any(phrase_in(company_name, title) for title in titles):
        raise ValueError("Company identity not established by public title/heading")
    explicit = []
    for index, node in enumerate(nodes):
        attrs = node["attrs"]
        if not node["hidden"] and (
            "data-company-description" in attrs
            or attrs.get("id") == "company-description"
            or "company-description" in (attrs.get("class") or "").split()
        ):
            value = document.text(index)
            if value and value not in explicit:
                explicit.append(value)
    if len(explicit) > 1:
        raise ValueError("Ambiguous company descriptions")
    if explicit:
        result = explicit[0]
    else:
        headings = {
            "about us",
            "who we are",
            "our company",
            "our mission",
            "what we do",
            "company overview",
            "about " + normalize(company_name),
        }
        parts = []
        for index, node in enumerate(nodes):
            if (
                node["hidden"]
                or node["tag"] not in {"h1", "h2", "h3"}
                or normalize(document.text(index)) not in headings
            ):
                continue
            level = int(node["tag"][1])
            for following in range(index + 1, len(nodes)):
                item = nodes[following]
                if (
                    not item["hidden"]
                    and item["tag"] in {"h1", "h2", "h3", "h4", "h5", "h6"}
                    and int(item["tag"][1]) <= level
                ):
                    break
                if item["tag"] in {"p", "li"}:
                    value = document.text(following)
                    if value and value not in parts:
                        parts.append(value)
        result = "\n".join(parts)
    if not result:
        raise ValueError("No supported public company description; read manually")
    return {
        "company_text": result[:4000],
        "source_title": next(t for t in titles if phrase_in(company_name, t))[:300],
    }
