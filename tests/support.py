"""
Shared test support. `tests/__init__.py` installs the offline guard, so it
applies when the suite runs as a package:

    python -m unittest discover -s tests -t .

tests/test_offline_guard.py fails when the guard is missing, which is what
happens with the older command without `-t .`.
"""

import os

import utils.llm.transport as transport

LIVE = os.environ.get("RUN_LIVE_LLM_TESTS") == "1"
MESSAGE = (
    "a test reached the LLM platform. Tests must stub the model (patch "
    "utils.llm.transport.send_ai_request or use a fake platform); a patch on a name that "
    "no longer exists does nothing. Live tests need RUN_LIVE_LLM_TESTS=1."
)


class OfflinePlatform:
    """
    Wraps the configured LLM platform for the offline suite: building and
    parsing requests work as usual, sending raises. Defining send() also
    covers the self-hosted platforms, since utils.llm.transport uses send()
    whenever a platform has one.
    """

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def send(self, *args, **kwargs):
        raise RuntimeError(MESSAGE)


def install_offline_guard():
    """Wrap utils.llm.transport's platform unless live tests were asked for. Idempotent."""
    if LIVE:
        return

    if not isinstance(transport._llm_platform, OfflinePlatform):
        transport._llm_platform = OfflinePlatform(transport._llm_platform)


# ------------------------------------------------------------ directories

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Where the review layer paths live; tests redirect them only through
# temporary_layers(), so a move of these constants changes this one line.
REVIEW_PATHS_MODULE = "utils.review.common"
# What no test may change. Checked by tests/test_zz_no_writes.py, which runs
# last, against the state recorded when the tests package was imported.
PROTECTED = ("ctml", "cache/ctml", "ref", "index", "runs", "review_sheets")


class temporary_layers:
    """
    Temporary mapped/review/reviewed directories and review log, with the
    review helper pointed at them for the duration:

        with temporary_layers() as layers:
            open(os.path.join(layers.review, "NCT0.yaml"), "w") ...

    Use the attributes (mapped, review, reviewed, log, sheets, root), not the
    module constants, so tests do not depend on where those constants live.
    """

    NAMES = {
        "mapped": "MAPPED_DIR",
        "review": "REVIEW_DIR",
        "reviewed": "REVIEWED_DIR",
        "log": "LOG_FILE",
        "sheets": "SHEET_DIR",
    }

    def __enter__(self):
        import importlib
        import tempfile

        self._module = importlib.import_module(REVIEW_PATHS_MODULE)
        self.root = tempfile.mkdtemp()
        self.mapped = os.path.join(self.root, "mapped")
        self.review = os.path.join(self.root, "review")
        self.reviewed = os.path.join(self.root, "reviewed")
        self.log = os.path.join(self.root, "review_log.tsv")
        self.sheets = os.path.join(self.root, "review_sheets")
        for d in (self.mapped, self.review):
            os.makedirs(d)
        self._saved = {c: getattr(self._module, c) for c in self.NAMES.values()}
        for attr, constant in self.NAMES.items():
            setattr(self._module, constant, getattr(self, attr))
        return self

    def __exit__(self, *exc):
        import shutil

        for constant, value in self._saved.items():
            setattr(self._module, constant, value)
        shutil.rmtree(self.root, True)
        return False


def protected_state():
    """(size, mtime) of every file under PROTECTED, keyed by path."""
    out = {}
    for top in PROTECTED:
        for d, _, files in os.walk(os.path.join(ROOT, top)):
            for f in files:
                p = os.path.join(d, f)
                try:
                    st = os.stat(p)
                except FileNotFoundError:
                    continue
                out[os.path.relpath(p, ROOT)] = (st.st_size, st.st_mtime_ns)
    return out


STATE_AT_START = None


def record_state():
    global STATE_AT_START
    if STATE_AT_START is None:
        STATE_AT_START = protected_state()
