"""
Static audit of gui/web/index.html.

Catches common UI drift issues without needing a running browser:

  * Every getElementById('X') / querySelector('#X') reference must point at
    an id that actually exists in the HTML. Typos here produce silent
    "nothing happens when I click X" bugs.

  * Every interactive <button> with a fixed id must be referenced somewhere
    in the page's JS. Dangling buttons (no onclick, no listener, no
    referenced id) are dead UI — exactly the "Reset Zoom" class of bug.

Intentionally conservative: buttons without an id aren't checked, since they
can legitimately be wired via event delegation on a parent container. The
goal is high-signal regressions, not exhaustive lint.
"""

import re
import sys
from pathlib import Path

INDEX_HTML = (
    Path(__file__).resolve().parent.parent / "gui" / "web" / "index.html"
)


def _read_html():
    return INDEX_HTML.read_text(encoding="utf-8")


# Buttons with an id="..." attribute. Scope: only the opening <button ...> tag.
_BUTTON_WITH_ID_RE = re.compile(
    r'<button\b[^>]*\bid\s*=\s*"([A-Za-z_][\w-]*)"[^>]*>',
    re.IGNORECASE,
)

# All id="..." attributes anywhere in the document (HTML form).
_ID_ATTR_RE = re.compile(r'\bid\s*=\s*"([A-Za-z_][\w-]*)"')

# Ids assigned dynamically in JS, e.g. `el.id = 'foo'` or `id: 'foo'`.
_DYNAMIC_ID_RE = re.compile(
    r"""(?:\.\s*id\s*=\s*|[\{,]\s*id\s*:\s*)['"]([A-Za-z_][\w-]*)['"]"""
)

# JS lookups that target an id.
_GET_BY_ID_RE = re.compile(r"""getElementById\(\s*['"]([A-Za-z_][\w-]*)['"]\s*\)""")
_QS_ID_RE = re.compile(
    r"""querySelector(?:All)?\(\s*['"]#([A-Za-z_][\w-]*)\b['"]?""",
)


def _all_ids(html: str) -> set:
    ids = set(_ID_ATTR_RE.findall(html))
    ids.update(_DYNAMIC_ID_RE.findall(html))
    return ids


def _js_id_refs(html: str) -> set:
    refs = set(_GET_BY_ID_RE.findall(html))
    refs.update(_QS_ID_RE.findall(html))
    return refs


def test_every_getElementById_reference_has_matching_dom_id():
    """No JS id lookup should be typo'd or point at a removed element."""
    html = _read_html()
    dom_ids = _all_ids(html)
    refs = set(_GET_BY_ID_RE.findall(html))

    orphans = sorted(r for r in refs if r not in dom_ids)
    assert not orphans, (
        f"JS calls getElementById() for ids with no matching DOM element: "
        f"{orphans}"
    )


def test_every_queryselector_id_reference_has_matching_dom_id():
    html = _read_html()
    dom_ids = _all_ids(html)
    refs = set(_QS_ID_RE.findall(html))

    orphans = sorted(r for r in refs if r not in dom_ids)
    assert not orphans, (
        f"querySelector('#X') references ids with no matching DOM element: "
        f"{orphans}"
    )


def test_every_button_with_id_is_referenced_somewhere():
    """
    A <button id="X"> that nothing in the JS references is almost always dead.
    (Buttons without an id may be wired via delegation - those are not checked.)
    """
    html = _read_html()
    button_ids = set(_BUTTON_WITH_ID_RE.findall(html))

    # Collect anywhere the id name appears outside the HTML attribute itself:
    # JS string literals, CSS selectors, etc. We use a simple textual search
    # since the JS and CSS live in the same file.
    unreferenced = []
    for bid in sorted(button_ids):
        # Count occurrences: we expect at least the id="..." declaration plus
        # one other mention (JS handler, listener attachment, etc.).
        hits = html.count(bid)
        if hits < 2:
            unreferenced.append(bid)

    assert not unreferenced, (
        f"<button id=X> elements that are never referenced in JS/CSS: "
        f"{unreferenced}"
    )
