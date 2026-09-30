"""
A local review interface: the sheets a curator already reads, with the edits and
the decision in the same page.

    python -m utils.review.app            # then open http://127.0.0.1:8765

Why a server at all. The static sheets (utils/review/sheets.py) show every flag
with its evidence but only read, so resolving one meant editing YAML in another
window and running `accept` in a third. This serves the same sheet, adds an
editor for the trial's CTML, and re-runs the review gate on every save, so the
curator sees what `accept` would still refuse before pressing it.

What it does not do. It never bypasses the gate: Accept is
utils.review.gate.accept and Exclude is gate.exclude, the same code paths the CLI
uses, so `ctml/review_log.tsv` and the SHA-256 of every accepted file are written
exactly as before. A save keeps the previous version as `<trial>.yaml.prev`, the
convention the mapper already uses, and refuses anything that is not a YAML
mapping. Nothing is deleted.

Standard library only (http.server), bound to 127.0.0.1: the queue holds
unpublished clinical mapping output, so it is not served off this machine, and
there is no authentication because there is no network exposure. One request at a
time, deliberately - two curators editing one file would need locking this does
not have.
"""

import argparse
import html
import http.server
import os
import shutil
import urllib.parse

try:
    import yaml

    import src.text_rules as text_rules
    import utils.review.common as common
    import utils.review.evidence as evidence
    import utils.review.gate as gate
    import utils.review.sheets as sheets
except ModuleNotFoundError as missing:  # a curator starts this by hand
    raise SystemExit(
        f"{missing.name} is missing, so this is not the repository's environment.\n"
        "Run it from the repo root with the repo's Python:\n"
        "    ./.venv/bin/python -m utils.review.app\n"
        "or activate the environment first (source .venv/bin/activate). Build it once with\n"
        "    python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.lock"
    ) from missing

HOST, PORT = "127.0.0.1", 8765

_PAGE_CSS = (
    sheets.CSS
    + """
.bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:10px 0;margin-bottom:12px;z-index:5}
.bar input[type=text]{padding:4px 6px;border:1px solid #ccc;width:150px}
button{padding:5px 12px;margin-right:6px;border:1px solid #bbb;background:#f6f6f6;cursor:pointer;border-radius:3px}
button.go{background:#1e7e34;color:#fff;border-color:#1a6b2c} button.warn{background:#b35900;color:#fff;border-color:#9a4c00}
textarea{width:100%;height:420px;font:12.5px/1.4 ui-monospace,Menlo,monospace;border:1px solid #ccc;padding:8px}
.msg{padding:8px 10px;margin:8px 0;border-left:4px solid #888;background:#f6f6f6;white-space:pre-wrap}
.msg.bad{border-color:#c0392b;background:#fdecea} .msg.good{border-color:#1e7e34;background:#eaf6ec}
"""
)


def queue_rows():
    """One row per queued trial: id, flags present, and the gate's objections."""
    rows = []
    for trial_id in gate._queue_ids():
        path, layer = common._layer_of(trial_id)
        raw = open(path).read()
        # A curator may be mid-edit, so a file that does not parse is a row to
        # show, not an exception that empties the queue page.
        try:
            ctml = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            rows.append(
                {
                    "trial_id": trial_id,
                    "layer": layer,
                    "flags": ["unreadable YAML"],
                    "problems": [str(e).splitlines()[0]],
                    "title": "",
                }
            )
            continue
        if not isinstance(ctml, dict):
            rows.append(
                {
                    "trial_id": trial_id,
                    "layer": layer,
                    "flags": ["unreadable YAML"],
                    "problems": ["file is not a YAML mapping"],
                    "title": "",
                }
            )
            continue
        rows.append(
            {
                "trial_id": trial_id,
                "layer": layer,
                "flags": [k for k in common.FLAG_KEYS if k in ctml],
                "problems": gate.problems(ctml, raw),
                "title": str(ctml.get("short_title") or ctml.get("long_title") or ""),
            }
        )
    return rows


def read_trial(trial_id):
    """(raw text, layer, path) for a trial in any layer."""
    path, layer = common._layer_of(trial_id)
    return open(path).read(), layer, path


def save_trial(trial_id, text):
    """
    Write edited CTML, keeping the previous version as .prev. Returns (ok, message).
    Refuses anything that does not parse as a YAML mapping, so a broken paste
    cannot replace a mapped trial.
    """
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return False, f"not valid YAML, nothing written:\n{e}"
    if not isinstance(parsed, dict):
        return False, "the file must be a YAML mapping (a top-level key: value document)"
    path, _ = common._layer_of(trial_id)
    backup = f"{path}.prev"
    suffix = 0
    while os.path.exists(backup):
        suffix += 1
        backup = f"{path}.prev.{suffix}"
    shutil.copy2(path, backup)
    with open(path, "w") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")
    left = gate.problems(parsed, text)
    if left:
        return True, f"saved (previous version kept as {os.path.basename(backup)}).\n" + (
            "accept would still refuse:\n  - " + "\n  - ".join(left)
        )
    return True, (
        f"saved (previous version kept as {os.path.basename(backup)}). "
        "Nothing left for accept to refuse."
    )


def accept_trial(trial_id, reviewer, note=""):
    """gate.accept, with its refusal turned into a message instead of an exit."""
    if not (reviewer or "").strip():
        return False, "a reviewer name is required; accept writes it to the review log"
    try:
        gate.accept(trial_id, reviewer, note)
    except SystemExit as e:
        return False, str(e)
    return True, f"{trial_id} accepted into {common.REVIEWED_DIR} and logged"


def exclude_trial(trial_id, reviewer, reason):
    """gate.exclude, same treatment."""
    try:
        layers = gate.exclude(trial_id, reviewer, reason)
    except SystemExit as e:
        return False, str(e)
    return True, (
        f"{trial_id} excluded from scope (ref/scope_overrides.tsv); its copies in "
        f"{', '.join(layers) or 'no layer'} stay in place and drop out at the next index build"
    )


def _index_html(rows, message=""):
    body = [
        f"<!doctype html><meta charset='utf-8'><title>review queue</title><style>{_PAGE_CSS}</style>",
        f"<h1>Review queue <span class='muted'>({len(rows)} trials)</span></h1>",
        "<div class='muted'>Every action runs the same checks as the command line. "
        "Accept refuses a file that still carries a flag.</div>",
    ]
    if message:
        body.append(f"<div class='msg'>{html.escape(message)}</div>")
    body.append(
        "<table><tr><th>trial</th><th>layer</th><th>flags</th><th>accept would refuse</th></tr>"
    )
    for r in rows:
        flags = ", ".join(r["flags"]) or "<span class='muted'>none</span>"
        problems = (
            "<br>".join(html.escape(p) for p in r["problems"]) or "<span class='ok'>nothing</span>"
        )
        body.append(
            f"<tr><td><a href='/trial/{r['trial_id']}'>{r['trial_id']}</a><div class='muted'>"
            f"{html.escape(r['title'][:70])}</div></td><td>{r['layer']}</td>"
            f"<td class='ev'>{flags}</td><td class='ev'>{problems}</td></tr>"
        )
    body.append("</table>")
    return "".join(body)


def _trial_html(trial_id, message="", ok=None):
    raw, layer, path = read_trial(trial_id)
    try:
        analysis = evidence.analyse(trial_id, text_rules._shared_reference())
        sheet = sheets.render(analysis).replace("index.html", "/")
        sheet = sheet[sheet.index("<p class='muted'>") :]
    except Exception as e:  # a sheet that cannot render must not hide the editor
        sheet = f"<div class='msg bad'>evidence sheet unavailable: {html.escape(str(e))}</div>"
    css_class = "" if ok is None else (" good" if ok else " bad")
    banner = f"<div class='msg{css_class}'>{html.escape(message)}</div>" if message else ""
    return (
        f"<!doctype html><meta charset='utf-8'><title>{trial_id}</title><style>{_PAGE_CSS}</style>"
        f"<div class='bar'><a href='/'>&larr; queue</a> &nbsp; <b>{trial_id}</b> "
        f"<span class='muted'>({layer})</span>"
        f"<form method='post' action='/action' style='display:inline'>"
        f"<input type='hidden' name='trial' value='{trial_id}'>"
        f" reviewer <input type='text' name='reviewer' required>"
        f" note <input type='text' name='note'>"
        f"<button class='go' name='do' value='accept'>Accept</button>"
        f"<button class='warn' name='do' value='exclude'>Exclude (needs a note as the reason)</button>"
        f"</form></div>"
        f"{banner}{sheet}"
        f"<h2>CTML <span class='muted'>{html.escape(path)}</span></h2>"
        f"<form method='post' action='/action'>"
        f"<input type='hidden' name='trial' value='{trial_id}'>"
        f"<textarea name='text' spellcheck='false'>{html.escape(raw)}</textarea>"
        f"<p><button name='do' value='save'>Save and re-check</button>"
        f"<span class='muted'>the previous version is kept as .prev</span></p></form>"
    )


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "nct2ctml-review"

    def log_message(self, fmt, *args):  # one line per action, not per asset
        if self.command == "POST":
            super().log_message(fmt, *args)

    def _send(self, body, status=200):
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = urllib.parse.urlparse(self.path).path
        if route == "/":
            self._send(_index_html(queue_rows()))
        elif route.startswith("/trial/"):
            trial_id = route[len("/trial/") :]
            try:
                self._send(_trial_html(trial_id))
            except SystemExit as e:
                self._send(_index_html(queue_rows(), str(e)), 404)
        else:
            self._send("<p>not found — <a href='/'>queue</a></p>", 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        trial_id = (form.get("trial") or [""])[0]
        action = (form.get("do") or [""])[0]
        reviewer = (form.get("reviewer") or [""])[0]
        note = (form.get("note") or [""])[0]
        if action == "save":
            ok, message = save_trial(trial_id, (form.get("text") or [""])[0])
        elif action == "accept":
            ok, message = accept_trial(trial_id, reviewer, note)
        elif action == "exclude":
            ok, message = exclude_trial(trial_id, reviewer, note)
        else:
            ok, message = False, f"unknown action {action!r}"
        if ok and action in ("accept", "exclude"):
            self._send(_index_html(queue_rows(), message))
            return
        self._send(_trial_html(trial_id, message, ok))


def serve(host=HOST, port=PORT):
    server = http.server.HTTPServer((host, port), Handler)
    print(f"review interface on http://{host}:{server.server_port} (ctrl-c to stop)")
    print(f"layers: {common.MAPPED_DIR}, {common.REVIEW_DIR}, {common.REVIEWED_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
