"""
The HTML review sheets: one page per trial with every flag, its evidence and
the edit that resolves it, and an index page. They only read; the curator
edits the YAML and runs accept.
"""

import datetime
import html
import os

import src.text_rules as text_rules
import utils.review.common as common
import utils.review.evidence as evidence

CSS = """
body{font:14px/1.45 -apple-system,Helvetica,Arial,sans-serif;margin:24px;max-width:1200px;color:#222}
h1{font-size:19px;margin:0 0 4px} h2{font-size:15px;margin:22px 0 6px;border-bottom:1px solid #ddd}
.flag{background:#fdecea;border-left:4px solid #c0392b;padding:6px 10px;margin:6px 0}
.ok{color:#1e7e34} .warn{color:#b35900} .bad{color:#c0392b;font-weight:600}
table{border-collapse:collapse;width:100%} td,th{border-bottom:1px solid #eee;padding:4px 6px;vertical-align:top;text-align:left}
th{background:#f6f6f6} mark{background:#fff2a8} mark.hit{background:#ffd6d6}
.ev{font-size:12.5px;color:#444} .text{white-space:pre-wrap;background:#fafafa;border:1px solid #eee;padding:10px;font-size:13px}
code{background:#f3f3f3;padding:1px 4px} .muted{color:#888}
"""


def _note_class(note):
    if (
        note.startswith("named")
        or note.startswith("verified")
        or note.startswith("alias of")
        and "wrong" not in note
    ):
        return "ok"
    if note.startswith(("parent", "registry", "only")) or note == "basket wildcard":
        return "warn"
    return "bad" if note else ""


def _highlight(text, terms):
    out, last = [], 0
    for s, e, _ in text_rules.find_mentions(text, terms):
        out.append(html.escape(text[last:s]) + "<mark>" + html.escape(text[s:e]) + "</mark>")
        last = e
    return "".join(out) + html.escape(text[last:])


def render(a):
    tid = a["trial_id"]
    link = (
        f"https://clinicaltrials.gov/study/{tid}"
        if tid.startswith("NCT")
        else f"https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT={tid}"
    )
    h = [
        f"<!doctype html><meta charset='utf-8'><title>{tid}</title><style>{CSS}</style>",
        "<p class='muted'><a href='index.html'>&larr; queue</a></p>",
        f"<h1>{tid} <span class='muted'>({a['layer']})</span></h1>",
        f"<div>{html.escape(a['title'])}</div><div class='muted'><a href='{link}'>registry record</a>"
        f" &middot; file: <code>{html.escape(a['path'])}</code></div>",
    ]
    if a["conditions"]:
        h.append(
            f"<div class='muted'>registry conditions: {html.escape('; '.join(a['conditions']))}</div>"
        )

    h.append("<h2>Flags to resolve</h2>")
    flagged = [i for i in a["items"] if i.flag]
    if not flagged:
        h.append("<p class='ok'>No flags. Check the items below against the text.</p>")
    for i in flagged:
        h.append(
            f"<div class='flag'><b>{html.escape(i.flag)}</b>: {html.escape(i.value)}"
            + (
                f" <span class='{_note_class(i.note)}'>({html.escape(i.note)})</span>"
                if i.note
                else ""
            )
            + f"<div class='ev'>{html.escape(common.ADVICE.get(i.flag, ''))}</div>"
            + "".join(f"<div class='ev'>[{n}] {s}</div>" for n, s in i.evidence[:4])
            + ("" if i.evidence else "<div class='ev bad'>no supporting passage found</div>")
            + "</div>"
        )

    for kind, heading in (
        ("diagnosis", "Diagnoses"),
        ("gene", "Genomic criteria"),
        ("partner", "Fusion partners"),
        ("protein", "Protein changes"),
        ("age", "Age"),
    ):
        rows = [i for i in a["items"] if i.kind == kind]
        if not rows:
            continue
        h.append(
            f"<h2>{heading} ({len(rows)})</h2><table><tr><th>item</th><th>side</th><th>check</th><th>evidence</th></tr>"
        )
        for i in rows:
            ev = "".join(f"<div class='ev'>[{n}] {s}</div>" for n, s in i.evidence[:2])
            h.append(
                f"<tr><td>{'<b>&#9873;</b> ' if i.flag else ''}{html.escape(i.value)}</td>"
                f"<td>{i.side}</td><td class='{_note_class(i.note)}'>{html.escape(i.note)}</td><td>{ev}</td></tr>"
            )
        h.append("</table>")

    for name, text in a["sections"]:
        h.append(
            f"<h2>Eligibility: {name}</h2><div class='text'>{_highlight(text, a['mentions']) or '<i>empty</i>'}</div>"
        )
    h.append(
        f"<h2>To finish</h2><p>Edit <code>{html.escape(a['path'])}</code>, then run "
        f"<code>python -m utils.review_helper accept {tid} --reviewer YOU</code>. "
        f"<code>check {tid}</code> shows what would still be refused.</p>"
    )
    return "\n".join(h)


def render_index(rows, heading):
    h = [
        f"<!doctype html><meta charset='utf-8'><title>{heading}</title><style>{CSS}</style>",
        f"<h1>{html.escape(heading)}</h1><p class='muted'>generated {datetime.datetime.now():%Y-%m-%d %H:%M}; "
        f"{len(rows)} trials</p><table><tr><th>trial</th><th>flags</th><th>unnamed diagnoses</th><th>title</th></tr>",
    ]
    for a in rows:
        dx = [i for i in a["items"] if i.kind == "diagnosis" and i.note == "not named in text"]
        h.append(
            f"<tr><td><a href='{a['trial_id']}.html'>{a['trial_id']}</a></td>"
            f"<td class='bad'>{html.escape(', '.join(a['flags']))}</td><td>{len(dx)}</td>"
            f"<td>{html.escape(a['title'][:110])}</td></tr>"
        )
    return "\n".join(h + ["</table>"])


def write_sheets(trial_ids, heading, out_dir=common.SHEET_DIR):
    ref = text_rules.Reference()
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for tid in trial_ids:
        a = evidence.analyse(tid, ref)
        open(os.path.join(out_dir, f"{tid}.html"), "w").write(render(a))
        rows.append(a)
    rows.sort(key=lambda a: (-len(a["flags"]), a["trial_id"]))
    open(os.path.join(out_dir, "index.html"), "w").write(render_index(rows, heading))
    return rows
