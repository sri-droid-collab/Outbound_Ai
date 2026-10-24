"""Reduce an HTML page to the title, description, readable text and links the
research agent needs. Stdlib parser only - tolerant of broken markup."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin

MAX_TEXT_CHARS = 6000
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}
_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "tr",
    "section",
    "article",
    "header",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
}


@dataclass
class ExtractedPage:
    title: str = ""
    description: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)


class _Extractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base = base_url
        self._skip_depth = 0
        self._in_title = False
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.description = ""
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (attr.get("name") or attr.get("property") or "").lower()
            if key in ("description", "og:description") and not self.description:
                self.description = (attr.get("content") or "").strip()
        elif tag == "a" and attr.get("href"):
            self._anchor_href = attr["href"]
            self._anchor_text = []
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._anchor_href is not None:
            url, _ = urldefrag(urljoin(self._base, self._anchor_href))
            self.links.append((url, " ".join("".join(self._anchor_text).split())))
            self._anchor_href = None
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        self.text_parts.append(data)
        if self._anchor_href is not None:
            self._anchor_text.append(data)


def extract_page(html: str, base_url: str) -> ExtractedPage:
    parser = _Extractor(base_url)
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.text_parts).split("\n"))
    text = "\n".join(line for line in lines if line)
    text = re.sub(r"\n{3,}", "\n\n", text)[:MAX_TEXT_CHARS]
    return ExtractedPage(
        title=" ".join("".join(parser.title_parts).split()),
        description=parser.description,
        text=text,
        links=parser.links,
    )
