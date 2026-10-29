"""A small, deterministic Markdown subset for stored model answers.

The answers the ask page stores are markdown (``## Verdict``, ``- bullets``,
``**bold**``, ``` `code` ```). The web frontend used to print them inside a
``<pre>``, which on a phone reads as a text file with asterisks in it. This
module renders the subset the model actually emits, and nothing else:

    headings ``#``..``######``, paragraphs, unordered and ordered lists,
    blockquotes, fenced code, horizontal rules, GitHub-style tables,
    ``**bold**``, ``*italic*`` / ``_italic_``, ``~~strike~~``, ``` `code` ```,
    ``[text](url)``.

Deliberately **not** here: nested lists, reference links, footnotes, raw HTML,
images, autolinks, setext headings. There is no extension hook, no plugin, and
no dependency — the renderer is a pure function over a string, so the CLI can
use it later and the web extra stays the only thing that needs Jinja.

Safety: the input is escaped first and every rule rewrites escaped text, so raw
HTML in a model answer is shown, never executed. Link targets are limited to
http(s), mailto and relative paths; anything else (``javascript:``) is left as
literal text. A renderer that trusts the model is how a local tool becomes a
remote one.

Output is HTML as a plain ``str``; templates must mark it safe explicitly
(``{{ body | md | safe }}``) so the decision stays visible where it is made.
"""
from __future__ import annotations

import html
import re

__all__ = ["render", "inline"]

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,}|(?:-\s){2,}-)$")
_UL = re.compile(r"^[-*+]\s+(.*)$")
_OL = re.compile(r"^\d{1,9}[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_FENCE = re.compile(r"^(```|~~~)\s*([\w+-]*)\s*$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)+\|?$")

_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_BOLD_U = re.compile(r"__(?=\S)(.+?)(?<=\S)__")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])")
_ITALIC_U = re.compile(r"(?<![A-Za-z0-9_])_(?=\S)([^_\n]+?)(?<=\S)_(?![A-Za-z0-9_])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^()\s]+)\)")

_SAFE_SCHEME = re.compile(r"^(?:https?:|mailto:|/|#|\.{0,2}/)", re.I)


def _link(match: re.Match[str]) -> str:
    label, target = match.group(1), match.group(2)
    # html.escape() turned ``&`` into ``&amp;``; unescape only for the scheme test
    raw = html.unescape(target)
    if not _SAFE_SCHEME.match(raw):
        return match.group(0)
    return (f'<a href="{html.escape(raw, quote=True)}" '
            f'rel="noopener noreferrer">{label}</a>')


def inline(text: str) -> str:
    """Escape one line of text, then render its inline markup."""
    if not text:
        return ""
    text = html.escape(text, quote=False)
    # code spans are literal: park them so bold/italic/link rules cannot reach in
    parked: list[str] = []

    def park(match: re.Match[str]) -> str:
        parked.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(parked) - 1}\x00"

    text = _CODE_SPAN.sub(park, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _BOLD_U.sub(r"<strong>\1</strong>", text)
    text = _STRIKE.sub(r"<del>\1</del>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = _ITALIC_U.sub(r"<em>\1</em>", text)
    text = _LINK.sub(_link, text)
    # a placeholder surrounded by markup can end up inside an attribute-free
    # text node only, so a plain restore is enough
    return re.sub(r"\x00(\d+)\x00", lambda m: parked[int(m.group(1))], text)


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def _is_block_start(line: str) -> bool:
    return bool(
        not line.strip()
        or _HEADING.match(line)
        or _HR.match(line)
        or _UL.match(line)
        or _OL.match(line)
        or _QUOTE.match(line)
        or _FENCE.match(line)
        or line.lstrip().startswith("|")
    )


def render(text: str) -> str:
    """Render a markdown-subset string to an HTML fragment."""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + inline(" ".join(para).strip()) + "</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ---- fenced code ----
        fence = _FENCE.match(stripped)
        if fence:
            flush_para()
            marker, lang = fence.group(1), fence.group(2)
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != marker:
                body.append(lines[i])
                i += 1
            i += 1  # closing fence (or EOF)
            cls = f' class="language-{lang}"' if lang else ""
            out.append('<pre class="md-code"><code' + cls + ">"
                       + html.escape("\n".join(body), quote=False)
                       + "</code></pre>")
            continue

        # ---- blank ----
        if not stripped:
            flush_para()
            i += 1
            continue

        # ---- heading ----
        match = _HEADING.match(stripped)
        if match:
            flush_para()
            level = len(match.group(1))
            out.append(f"<h{level}>{inline(match.group(2))}</h{level}>")
            i += 1
            continue

        # ---- horizontal rule ----
        if _HR.match(stripped):
            flush_para()
            out.append("<hr>")
            i += 1
            continue

        # ---- table ----
        if (stripped.startswith("|") and i + 1 < len(lines)
                and _TABLE_SEP.match(lines[i + 1].strip())):
            flush_para()
            head = _cells(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append('<div class="md-table"><table class="data tight"><thead><tr>'
                       + "".join(f"<th>{inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>")
            for row in rows:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row)
                           + "</tr>")
            out.append("</tbody></table></div>")
            continue

        # ---- blockquote ----
        if _QUOTE.match(stripped):
            flush_para()
            inner: list[str] = []
            while i < len(lines):
                q = _QUOTE.match(lines[i].strip())
                if q:
                    inner.append(q.group(1))
                elif lines[i].strip() and not _is_block_start(lines[i].strip()):
                    inner.append(lines[i].strip())   # lazy continuation
                else:
                    break
                i += 1
            out.append("<blockquote>" + render("\n".join(inner))
                       + "</blockquote>")
            continue

        # ---- lists ----
        ul, ol = _UL.match(line.strip()), _OL.match(line.strip())
        if ul or ol:
            flush_para()
            ordered = bool(ol)
            items: list[str] = []
            pattern = _OL if ordered else _UL
            while i < len(lines):
                m = pattern.match(lines[i].strip())
                if m:
                    items.append(m.group(1))
                elif lines[i].strip() and not _is_block_start(lines[i].strip()):
                    items[-1] += " " + lines[i].strip()   # continuation line
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(item)}</li>"
                                            for item in items) + f"</{tag}>")
            continue

        # ---- paragraph ----
        para.append(stripped)
        i += 1

    flush_para()
    return "\n".join(out)
