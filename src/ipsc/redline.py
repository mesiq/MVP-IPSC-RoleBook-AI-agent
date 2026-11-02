"""Build a PDF of the newer edition of a rulebook with every difference to an older edition marked.

Added wording is bold green, removed wording is bold red and struck through, and a renumbered rule shows the
old number struck through next to the new one. The rule text comes from the database (the same text the
answers quote); only the layout is new. Appendices are not compared, so they are left out.
"""
import html
import io
import re
from collections import defaultdict

import pymupdf

from . import changes
from .settings import IMAGE_MAX_PAGES, IMAGE_MAX_WIDTH, IMAGE_MIN_SIZE

INTERNAL_REF = re.compile(r"^(p\d+)+$")
RED, GREEN = "#b91c1c", "#15803d"
CSS = f"""
body {{ font-family: sans-serif; font-size: 9.5pt; }}
h1 {{ font-size: 18pt; margin: 0 0 4pt; }}
h2 {{ font-size: 13pt; margin: 14pt 0 3pt; color: #14532d; }}
h3 {{ font-size: 11pt; margin: 10pt 0 2pt; color: #14532d; }}
h4 {{ font-size: 10pt; margin: 8pt 0 2pt; }}
p {{ margin: 0 0 5pt; }}
.ref {{ font-weight: bold; }}
.legend {{ margin: 6pt 0 12pt; }}
.add {{ color: {GREEN}; font-weight: bold; }}
.del {{ color: {RED}; font-weight: bold; text-decoration: line-through; }}
"""


def _mark(kind: str, text: str) -> str:
    text = html.escape(text)
    return f'<span class="{kind}">{text}</span>' if kind in ("add", "del") else text


def _ref_html(old_ref: str, new_ref: str) -> str:
    """The rule number; a renumbered rule shows the old number struck through and the new one in green."""
    if INTERNAL_REF.match(old_ref + new_ref):
        return ""  # unnumbered passages carry an internal "p7" label that is not a rule number
    if old_ref and new_ref and old_ref != new_ref:
        return f'{_mark("del", old_ref)} {_mark("add", new_ref)}'
    if not new_ref:
        return _mark("del", old_ref)
    return html.escape(new_ref) if old_ref else _mark("add", new_ref)


def _joined(chunks: list) -> tuple:
    refs = " + ".join(dict.fromkeys(c["ref"] for c in chunks))
    return refs, " ".join(" ".join(c["text"].split()) for c in chunks)


def rule_block(old_chunks: list, new_chunks: list) -> str:
    """One rule (or a group of split/merged pieces) as an HTML paragraph with the changes marked."""
    old_ref, old_text = _joined(old_chunks)
    new_ref, new_text = _joined(new_chunks)
    if not old_chunks:
        body = _mark("add", new_text)
    elif not new_chunks:
        body = _mark("del", old_text)
    else:
        body = " ".join(_mark(kind, text) for kind, text in changes.diff_words(old_text, new_text))
    return f'<p><span class="ref">{_ref_html(old_ref, new_ref)}</span> {body}</p>'


def _headings(context: str, previous: list) -> tuple:
    """Heading tags for the levels of the breadcrumb that differ from the previous rule's."""
    levels = [part.strip() for part in context.split(">") if part.strip()]
    shared = 0
    while shared < min(len(levels), len(previous)) and levels[shared] == previous[shared]:
        shared += 1
    tags = "".join(f"<h{min(depth + 2, 4)}>{html.escape(level)}</h{min(depth + 2, 4)}>"
                   for depth, level in enumerate(levels) if depth >= shared)
    return tags, levels


def _images(pdf_path: str, last_page: int) -> tuple:
    """Pictures of the newer PDF as ({page: [file names]}, Archive). Logos repeated on many pages are skipped."""
    archive = pymupdf.Archive()
    by_page = defaultdict(list)
    seen = defaultdict(list)
    with pymupdf.open(pdf_path) as pdf:
        for number in range(1, min(last_page, len(pdf)) + 1):
            for info in pdf[number - 1].get_image_info(xrefs=True):
                xref = info.get("xref")
                width, height = info["width"], info["height"]
                if xref and min(width, height) >= IMAGE_MIN_SIZE:
                    seen[xref].append((number, info["bbox"]))
        for xref, places in seen.items():
            if len({page for page, _ in places}) > IMAGE_MAX_PAGES:
                continue
            try:
                pixmap = pymupdf.Pixmap(pdf, xref)
                if pixmap.n - pixmap.alpha >= 4:
                    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
                name = f"img{xref}.png"
                archive.add(pixmap.tobytes("png"), name)
            except (RuntimeError, ValueError):
                continue
            page, bbox = places[0]
            shown = min(bbox[2] - bbox[0], IMAGE_MAX_WIDTH)
            by_page[page].append(f'<p><img src="{name}" width="{shown:.0f}"></p>')
    return by_page, archive


def build_html(con, old_doc: dict, new_doc: dict) -> tuple:
    """The marked-up newer edition as (html, image archive)."""
    old = changes.load_chunks(con, old_doc["id"])
    new = changes.load_chunks(con, new_doc["id"])
    groups = changes.align(old, new)
    group_of_old = {i: g for g, (o, _) in enumerate(groups) for i in o}
    group_of_new = {j: g for g, (_, n) in enumerate(groups) for j in n}

    # removed rules are shown right after the rule that preceded them in the old edition
    removed_after = defaultdict(list)
    for g, (o, n) in enumerate(groups):
        if n:
            continue
        for i in o:
            k = i - 1
            while k >= 0 and not groups[group_of_old[k]][1]:
                k -= 1
            removed_after[group_of_old[k] if k >= 0 else -1].append(i)

    pictures, archive = ({}, pymupdf.Archive())
    if new:
        pictures, archive = _images(new_doc["path"], max(c["page_pdf"] for c in new))
    picture_for_group = defaultdict(list)
    for page, tags in pictures.items():
        anchor = max((j for j, c in enumerate(new) if c["page_pdf"] <= page), default=0)
        picture_for_group[group_of_new[anchor]].extend(tags)

    def removed(g: int) -> list:
        return [rule_block([old[i]], []) for i in removed_after.get(g, [])]

    parts = [f"<h1>IPSC rulebook {html.escape(new_doc['edition_label'])}: changes since "
             f"{html.escape(old_doc['edition_label'])}</h1>",
             f'<p class="legend">{_mark("add", "Added or changed wording")} &nbsp; '
             f'{_mark("del", "Removed wording")} &nbsp; {_ref_html("old no.", "new no.")} = renumbered rule. '
             f'Appendices are not compared and are not included. Unmarked text is unchanged.</p>'] + removed(-1)
    done, previous = set(), []
    for j in range(len(new)):
        g = group_of_new[j]
        if g in done:
            continue
        done.add(g)
        o, n = groups[g]
        tags, previous = _headings(new[n[0]]["context"], previous)
        parts.append(tags + rule_block([old[i] for i in o], [new[k] for k in n]))
        parts += picture_for_group.get(g, [])
        parts += removed(g)
    return f"<html><head><style>{CSS}</style></head><body>{''.join(parts)}</body></html>", archive


def build_redline_pdf(con, old_doc: dict, new_doc: dict) -> bytes:
    """The whole marked-up PDF as bytes."""
    html_text, archive = build_html(con, old_doc, new_doc)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    story = pymupdf.Story(html=html_text, archive=archive)
    mediabox = pymupdf.paper_rect("a4")
    area = mediabox + (48, 48, -48, -56)
    more = 1
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
    writer.close()

    with pymupdf.open(stream=buffer.getvalue(), filetype="pdf") as pdf:
        footer = f"{new_doc['edition_label']} vs {old_doc['edition_label']}"
        for number, page in enumerate(pdf, 1):
            page.insert_text((48, mediabox.height - 30), f"{footer}   |   page {number} of {len(pdf)}",
                             fontsize=8, color=(0.4, 0.4, 0.4))
        return pdf.tobytes(garbage=3, deflate=True)
