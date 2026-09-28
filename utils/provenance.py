"""
What produced a mapped CTML file, and a record of every model call.

Why this exists
---------------
A mapped trial used to say nothing about how it was made. The model, the
prompt variants (GENOMIC_PROMPT, DIAGNOSIS_INPUT, both overridable from the
environment), the code and the reference files all change what the mapper
writes, so two files that look alike could come from different pipelines,
and a file could not be traced back to the answer the model actually gave.
Temperature 0 does not make a hosted model deterministic, so re-running the
mapping does not reproduce it either.

Three things fix that:

- `for_trial()` is stamped into every mapped CTML file as `_provenance`
  (by TrialMapManager._save): run id, time, git commit and dirty flag, LLM
  platform, model and settings, and the SHA-256 of every reference file.
  `bulk_convert_yaml_to_json.py` strips it, because MatchMiner's trial
  resource rejects unknown fields; the reviewed YAML keeps it.
- A run (`start_run()`, called by `main.py map` and the benchmark) writes
  `runs/<run_id>/run.json` with the same facts plus the command, Python and
  package versions, and appends every model call to
  `runs/<run_id>/llm_calls.jsonl`: trial, prompt, the SHA-256 of the prompt
  and of the schema, the raw response, the time taken, or the error. Each
  distinct schema is written once to `runs/<run_id>/schemas/<sha256>.json`.
- `LLM_PLATFORM = "Replay"` (utils/llm_platforms.ReplayPlatform) answers from
  such a file instead of a model, so a run can be rebuilt offline and a
  change to the deterministic code measured without a model in the loop.

`runs/` is not regenerable, unlike `cache/`: it is the only copy of what the
model said. Keep it with the outputs a result was based on.

Nothing is recorded without a started run, so tests and one-off imports
never write to `runs/`. "dirty" ignores untracked files.
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata

from loguru import logger

import config

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Every reference file the mapper reads at run time, by its config name.
# ref/local_trial_info.csv has no config entry; TrialMapManager hard-codes it.
_REFERENCE_KEYS = (
    "ONCOTREE_TXT_FILE_PATH",
    "GENE_LIST_FILE_PATH",
    "LEGACY_GENE_LIST_FILE_PATH",
    "GENE_SYNONYM_FILE_PATH",
    "GENE_SYNONYM_ADDENDUM_FILE_PATH",
    "GENE_REWRITE_EXCLUSION_FILE_PATH",
    "PROTEIN_REFERENCE_FILE_PATH",
    "DIAGNOSIS_TEXT_TERMS_FILE_PATH",
    "TRANSLOCATION_TABLE_FILE_PATH",
    "MANE_GENES_FILE_PATH",
    "DIAGNOSIS_SYNONYM_FILE_PATH",
    "SCOPE_OVERRIDES_FILE_PATH",
)
LOCAL_TRIAL_INFO_FILE_PATH = "ref/local_trial_info.csv"

# Packages whose version can change an output; recorded in run.json.
_PACKAGES = ("anthropic", "PyYAML", "pyahocorasick", "requests", "loguru")

CALLS_FILE = "llm_calls.jsonl"
RUN_FILE = "run.json"

_run = None
_git = None
_hashes = {}


def _now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def schema_text(schema):
    """The schema as sent, in its own key order: order is part of the request."""
    return None if schema is None else json.dumps(schema, ensure_ascii=False)


def schema_sha256(schema):
    text = schema_text(schema)
    return None if text is None else sha256_text(text)


def file_sha256(path):
    """SHA-256 of a file, None if it does not exist. Cached on size and mtime."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    key = (path, st.st_size, st.st_mtime_ns)
    if key not in _hashes:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        _hashes[key] = digest.hexdigest()
    return _hashes[key]


def reference_files():
    paths = {getattr(config, k) for k in _REFERENCE_KEYS if getattr(config, k, None)}
    return sorted(paths | {LOCAL_TRIAL_INFO_FILE_PATH})


def reference_hashes():
    return {path: file_sha256(path) for path in reference_files()}


def code_version():
    """{"commit", "dirty"} of the checkout; both None outside a git checkout."""
    global _git
    if _git is None:
        try:

            def git(*args):
                return subprocess.run(
                    ["git", *args],
                    cwd=_ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                ).stdout

            _git = {
                "commit": git("rev-parse", "HEAD").strip(),
                "dirty": bool(git("status", "--porcelain", "--untracked-files=no").strip()),
            }
        except (OSError, subprocess.SubprocessError):
            _git = {"commit": None, "dirty": None}
    return dict(_git)


def short_commit(code):
    """The commit's first 12 characters, with "+dirty" when the tree had local changes."""
    commit = (code or {}).get("commit")
    if not commit:
        return ""
    return commit[:12] + ("+dirty" if code.get("dirty") else "")


def llm_settings():
    """The platform, model and every setting that changes what the model is asked or answers."""
    import utils.ai_helper as ai

    platform = ai._llm_platform
    name = str(config.LLM_PLATFORM)
    settings = {
        "platform": name,
        "model": platform.model,
        "genomic_prompt": config.GENOMIC_PROMPT,
        "diagnosis_input": config.DIAGNOSIS_INPUT,
    }
    kind = name.lower()
    if kind == "anthropic":
        settings.update(
            temperature=getattr(config, "ANTHROPIC_TEMPERATURE", None),
            thinking=getattr(config, "ANTHROPIC_THINKING", None),
            effort=getattr(config, "ANTHROPIC_EFFORT", None),
            max_tokens=getattr(config, "ANTHROPIC_MAX_TOKENS", None),
        )
    elif kind == "ollama":
        settings.update(
            num_ctx=getattr(config, "OLLAMA_NUM_CTX", None),
            num_predict=getattr(config, "OLLAMA_NUM_PREDICT", None),
        )
    elif kind == "replay":
        settings.update(recorded_platform=platform.recorded_platform, replay_of=platform.source)
    return settings


def _package_versions():
    versions = {}
    for name in _PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    os.replace(tmp, path)


def start_run(command, directory=None):
    """
    Start a run: write run.json and record every model call from here on.
    `directory` defaults to config.RUNS_PATH; None there turns both off, and
    the run id is still stamped into the CTML. Returns the run id.
    """
    global _run
    directory = getattr(config, "RUNS_PATH", "runs") if directory is None else directory
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    llm = llm_settings()
    info = {
        "run_id": run_id,
        "command": command,
        "argv": sys.argv,
        "started_at": _now(),
        "code": code_version(),
        "llm": llm,
        "reference_sha256": reference_hashes(),
        "python": sys.version.split()[0],
        "packages": _package_versions(),
    }
    run_dir = calls_path = None
    if directory:
        run_dir = os.path.join(directory, run_id)
        os.makedirs(os.path.join(run_dir, "schemas"), exist_ok=True)
        _write_json(os.path.join(run_dir, RUN_FILE), info)
        # A replay asks no model, so there is nothing new to record.
        if llm["platform"].lower() != "replay":
            calls_path = os.path.join(run_dir, CALLS_FILE)
    _run = {
        "id": run_id,
        "dir": run_dir,
        "calls_path": calls_path,
        "info": info,
        "calls": Counter(),
        "errors": 0,
        "record_failures": 0,
        "schemas": set(),
    }
    where = (
        calls_path
        or (run_dir and f"{run_dir} (replay: calls not recorded)")
        or "nowhere (RUNS_PATH is None)"
    )
    logger.info(
        f"Run {run_id} | {llm['platform']} {llm['model']} | model calls recorded in {where}"
    )
    return run_id


def finish_run(**summary):
    """Close the run: add the end time and call counts to run.json."""
    global _run
    if _run is None:
        return None
    run, _run = _run, None
    info = dict(
        run["info"],
        finished_at=_now(),
        llm_calls=sum(run["calls"].values()),
        llm_call_errors=run["errors"],
        trials_with_llm_calls=len(run["calls"]),
        record_failures=run["record_failures"],
        summary=summary,
    )
    if run["dir"]:
        _write_json(os.path.join(run["dir"], RUN_FILE), info)
    if run["record_failures"]:
        logger.error(
            f"Run {run['id']} | {run['record_failures']} model calls could not be recorded"
        )
    return info


def current_run_id():
    return _run["id"] if _run else None


def record_call(trial_id, prompt, schema, response=None, error=None, elapsed=None):
    """Append one model call to the run's llm_calls.jsonl. Never raises."""
    if _run is None or not _run["calls_path"]:
        return
    try:
        s_text = schema_text(schema)
        s_sha = None if s_text is None else sha256_text(s_text)
        if s_sha and s_sha not in _run["schemas"]:
            path = os.path.join(_run["dir"], "schemas", f"{s_sha}.json")
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(s_text)
            _run["schemas"].add(s_sha)
        llm = _run["info"]["llm"]
        line = {
            "ts": _now(),
            "run_id": _run["id"],
            "trial_id": trial_id,
            "platform": llm["platform"],
            "model": llm["model"],
            "prompt_sha256": sha256_text(prompt),
            "schema_sha256": s_sha,
            "elapsed_s": None if elapsed is None else round(elapsed, 3),
            "prompt": prompt,
            "response": response,
            "error": error,
        }
        # Opened per call and flushed on close, so a crash loses at most the call in flight.
        with open(_run["calls_path"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        _run["calls"][trial_id] += 1
        if error:
            _run["errors"] += 1
    except Exception as ex:
        _run["record_failures"] += 1
        logger.error(f"{trial_id} | model call not recorded: {type(ex).__name__}: {ex}")


def for_trial(trial_id):
    """The `_provenance` block for one mapped trial."""
    block = {
        "run_id": current_run_id(),
        "mapped_at": _now(),
        "code": code_version(),
        "llm": llm_settings(),
        "reference_sha256": reference_hashes(),
    }
    if _run and _run["calls_path"]:
        block["llm_calls"] = _run["calls"].get(trial_id, 0)
        block["llm_call_log"] = _run["calls_path"]
    return block
