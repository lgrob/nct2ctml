"""
Provenance (utils/provenance.py): the _provenance block in every mapped file,
the record of every model call, replaying a run from that record, and what
the index makes of both.
"""

import csv
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import yaml
from loguru import logger

import config
import utils.llm.schema as llm_schema
import utils.llm.transport as transport
from src.trial_map_manager import TrialMapManager
from utils import build_trial_index as bti
from utils import promote as convert
from utils import provenance
from utils.llm_platforms import AnthropicPlatform, ReplayMiss, ReplayPlatform, create_llm_platform

logger.remove()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRIAL = "NCT03643276"
SRC = os.path.join(ROOT, "ctml", "reviewed", f"{TRIAL}.yaml")
SCHEMA = {"type": "object", "properties": {"genes": {"type": "array", "items": {"type": "string"}}}}


class FakeModel(AnthropicPlatform):
    """Answers from a queue, in the shape AnthropicPlatform.send returns."""

    def __init__(self, answers):
        super().__init__(config.LLM_AI_MODEL, "")
        self.answers = list(answers)

    def send(self, prompt, json_schema=None):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"text": json.dumps(answer), "stop_reason": "tool_use", "request_id": "req_1"}


class _Isolated(unittest.TestCase):
    """A temporary runs directory, and no run left open afterwards."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.runs = os.path.join(self.tmp, "runs")
        patches = [
            mock.patch.object(config, "RUNS_PATH", self.runs),
            mock.patch.object(config, "LLM_PLATFORM", "Anthropic"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # Cleanups run last first: close any open run, then remove its directory.
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(provenance.finish_run)

    def use(self, platform):
        p = mock.patch.object(transport, "_llm_platform", platform)
        p.start()
        self.addCleanup(p.stop)
        return platform

    def calls(self):
        run = os.path.join(self.runs, provenance.current_run_id())
        with open(os.path.join(run, provenance.CALLS_FILE)) as handle:
            return [json.loads(line) for line in handle]


class TestStamp(_Isolated):
    def _saved(self, directory, doc, trial="NCT1"):
        TrialMapManager._save(doc, directory, trial)
        with open(os.path.join(directory, f"{trial}.yaml")) as handle:
            return yaml.safe_load(handle)

    def test_every_saved_file_says_what_produced_it(self):
        saved = self._saved(self.tmp, {"nct_id": "NCT1"})
        block = saved["_provenance"]
        self.assertEqual(list(saved)[-1], "_provenance")
        self.assertIsNone(block["run_id"])
        self.assertEqual(block["llm"]["model"], transport._llm_platform.model)
        self.assertEqual(block["llm"]["genomic_prompt"], config.GENOMIC_PROMPT)
        self.assertEqual(block["llm"]["diagnosis_input"], config.DIAGNOSIS_INPUT)
        self.assertEqual(block["llm"]["temperature"], config.ANTHROPIC_TEMPERATURE)
        self.assertRegex(block["mapped_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_every_reference_file_is_hashed(self):
        block = self._saved(self.tmp, {"nct_id": "NCT1"})["_provenance"]
        self.assertEqual(sorted(block["reference_sha256"]), provenance.reference_files())
        for key in provenance._REFERENCE_KEYS:
            self.assertIn(getattr(config, key), block["reference_sha256"])
        self.assertEqual(
            block["reference_sha256"][config.GENE_LIST_FILE_PATH],
            provenance.file_sha256(config.GENE_LIST_FILE_PATH),
        )

    @unittest.skipUnless(os.path.isdir(os.path.join(ROOT, ".git")), "not a git checkout")
    def test_the_commit_is_recorded(self):
        code = self._saved(self.tmp, {"nct_id": "NCT1"})["_provenance"]["code"]
        self.assertRegex(code["commit"], r"^[0-9a-f]{40}$")
        self.assertIsInstance(code["dirty"], bool)

    def test_a_stale_block_is_replaced(self):
        saved = self._saved(self.tmp, {"nct_id": "NCT1", "_provenance": {"run_id": "old"}, "v": 1})
        self.assertEqual(list(saved), ["nct_id", "v", "_provenance"])
        self.assertIsNone(saved["_provenance"]["run_id"])

    def test_a_remap_differing_only_in_provenance_makes_no_backup(self):
        review = os.path.join(self.tmp, "needs-review")
        os.makedirs(review)
        with mock.patch.object(config, "CTML_REVIEW_PATH", review):
            with mock.patch.object(provenance, "_now", return_value="2026-01-01T00:00:00Z"):
                TrialMapManager._save({"nct_id": "NCT1", "v": [1, 2]}, review, "NCT1")
            with mock.patch.object(provenance, "_now", return_value="2026-02-02T00:00:00Z"):
                TrialMapManager._save({"nct_id": "NCT1", "v": [1, 2]}, review, "NCT1")
        self.assertEqual(os.listdir(review), ["NCT1.yaml"])

    def test_a_curator_edit_to_a_stamped_copy_is_still_backed_up(self):
        review = os.path.join(self.tmp, "needs-review")
        os.makedirs(review)
        path = os.path.join(review, "NCT1.yaml")
        with mock.patch.object(config, "CTML_REVIEW_PATH", review):
            TrialMapManager._save({"nct_id": "NCT1", "v": 1}, review, "NCT1")
            with open(path) as handle:
                edited = handle.read().replace("v: 1", "v: 2  # curator")
            with open(path, "w") as handle:
                handle.write(edited)
            TrialMapManager._save({"nct_id": "NCT1", "v": 1}, review, "NCT1")
        self.assertEqual(sorted(os.listdir(review)), ["NCT1.yaml", "NCT1.yaml.prev"])
        with open(path + ".prev") as handle:
            self.assertIn("# curator", handle.read())


class TestRecord(_Isolated):
    def test_nothing_is_recorded_outside_a_run(self):
        self.use(FakeModel([{"genes": ["KRAS"]}]))
        transport.send_ai_request("NCT1", "prompt", SCHEMA)
        self.assertFalse(os.path.exists(self.runs))

    def test_every_call_is_recorded_with_its_raw_answer(self):
        self.use(FakeModel([{"genes": ["KRAS"]}, {"genes": []}]))
        run_id = provenance.start_run("test")
        transport.send_ai_request("NCT1", "first prompt", SCHEMA)
        transport.send_ai_request("NCT2", "second prompt", SCHEMA)
        calls = self.calls()
        self.assertEqual([c["trial_id"] for c in calls], ["NCT1", "NCT2"])
        first = calls[0]
        self.assertEqual(first["run_id"], run_id)
        self.assertEqual(first["prompt"], "first prompt")
        self.assertEqual(first["prompt_sha256"], provenance.sha256_text("first prompt"))
        self.assertEqual(first["response"]["request_id"], "req_1")
        self.assertEqual(json.loads(first["response"]["text"]), {"genes": ["KRAS"]})
        self.assertEqual((first["platform"], first["model"]), ("Anthropic", config.LLM_AI_MODEL))

    def test_a_schema_is_stored_once_exactly_as_sent(self):
        self.use(FakeModel([{}, {}]))
        provenance.start_run("test")
        transport.send_ai_request("NCT1", "a", SCHEMA)
        transport.send_ai_request("NCT1", "b", SCHEMA)
        schemas = os.path.join(self.runs, provenance.current_run_id(), "schemas")
        self.assertEqual(os.listdir(schemas), [f"{provenance.schema_sha256(SCHEMA)}.json"])
        with open(os.path.join(schemas, os.listdir(schemas)[0])) as handle:
            self.assertEqual(handle.read(), json.dumps(SCHEMA, ensure_ascii=False))

    def test_a_failed_call_is_recorded_and_still_raised(self):
        self.use(FakeModel([TimeoutError("slow")]))
        provenance.start_run("test")
        with self.assertRaises(TimeoutError):
            transport.send_ai_request("NCT1", "prompt", SCHEMA)
        self.assertEqual(self.calls()[0]["error"], "TimeoutError: slow")
        self.assertIsNone(self.calls()[0]["response"])

    def test_run_json_closes_with_the_counts(self):
        self.use(FakeModel([{}, TimeoutError("slow")]))
        run_id = provenance.start_run("test")
        transport.send_ai_request("NCT1", "a", SCHEMA)
        with self.assertRaises(TimeoutError):
            transport.send_ai_request("NCT1", "b", SCHEMA)
        self.assertEqual(provenance.for_trial("NCT1")["llm_calls"], 2)
        provenance.finish_run(output="x")
        with open(os.path.join(self.runs, run_id, provenance.RUN_FILE)) as handle:
            info = json.load(handle)
        self.assertEqual(
            (info["llm_calls"], info["llm_call_errors"], info["trials_with_llm_calls"]), (2, 1, 1)
        )
        self.assertEqual(info["summary"], {"output": "x"})
        self.assertIn("finished_at", info)
        self.assertEqual(info["config_overrides"], dict(config.OVERRIDES))
        self.assertEqual(sorted(info["reference_sha256"]), provenance.reference_files())

    def test_a_trial_mapped_in_a_run_points_at_its_calls(self):
        self.use(FakeModel([{}]))
        run_id = provenance.start_run("test")
        transport.send_ai_request("NCT1", "a", SCHEMA)
        block = provenance.for_trial("NCT1")
        self.assertEqual(block["run_id"], run_id)
        self.assertEqual(block["llm_calls"], 1)
        self.assertTrue(block["llm_call_log"].endswith(os.path.join(run_id, provenance.CALLS_FILE)))
        self.assertEqual(provenance.for_trial("NCT2")["llm_calls"], 0)


class _ServedWeights:
    """An Ollama-like platform that reports a digest and is never called."""

    def __init__(self, digest):
        self.model, self._digest = "gpt-oss:120b", digest

    def model_digest(self):
        return self._digest


class TestModelDigest(_Isolated):
    """
    A self-hosted model's tag can be re-published with new weights, so a run
    records the digest it was served, and OLLAMA_MODEL_DIGEST pins it.
    """

    def setUp(self):
        super().setUp()
        for p in (
            mock.patch.object(config, "LLM_PLATFORM", "Ollama"),
            mock.patch.object(config, "OLLAMA_MODEL_DIGESTS", {}),
            mock.patch.object(config, "OLLAMA_MODEL_DIGEST", ""),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_the_run_and_every_file_record_the_served_digest(self):
        self.use(_ServedWeights("sha256:abc"))
        run_id = provenance.start_run("test")
        with open(os.path.join(self.runs, run_id, provenance.RUN_FILE)) as handle:
            self.assertEqual(json.load(handle)["llm"]["model_digest"], "sha256:abc")
        self.assertEqual(provenance.for_trial("NCT1")["llm"]["model_digest"], "sha256:abc")

    def test_a_pinned_digest_that_differs_refuses_the_run(self):
        self.use(_ServedWeights("sha256:new"))
        with mock.patch.object(config, "OLLAMA_MODEL_DIGEST", "sha256:old"):
            with self.assertRaises(RuntimeError):
                provenance.start_run("test")
        self.assertIsNone(provenance.current_run_id())

    def test_a_pin_that_cannot_be_checked_refuses_the_run(self):
        self.use(_ServedWeights(None))
        with mock.patch.object(config, "OLLAMA_MODEL_DIGEST", "sha256:old"):
            with self.assertRaises(RuntimeError):
                provenance.start_run("test")

    def test_the_table_pins_its_model_and_only_that_model(self):
        table = {"gpt-oss:120b": "abc"}
        with mock.patch.object(config, "OLLAMA_MODEL_DIGESTS", table):
            self.use(_ServedWeights("sha256:abc"))  # the prefix does not matter
            self.assertTrue(provenance.start_run("test"))
            provenance.finish_run()
            self.use(_ServedWeights("sha256:other"))
            with self.assertRaises(RuntimeError):
                provenance.start_run("test")
            other = _ServedWeights("sha256:other")
            other.model = "qwen3.6:27b"
            self.use(other)
            self.assertTrue(provenance.start_run("test"))

    def test_off_skips_the_check(self):
        with (
            mock.patch.object(config, "OLLAMA_MODEL_DIGESTS", {"gpt-oss:120b": "abc"}),
            mock.patch.object(config, "OLLAMA_MODEL_DIGEST", "off"),
        ):
            self.use(_ServedWeights("sha256:other"))
            self.assertTrue(provenance.start_run("test"))

    def test_a_matching_pin_runs(self):
        self.use(_ServedWeights("sha256:abc"))
        with mock.patch.object(config, "OLLAMA_MODEL_DIGEST", "sha256:abc"):
            self.assertTrue(provenance.start_run("test"))


class TestPinnedWeights(unittest.TestCase):
    def test_the_benchmarked_weights_are_pinned(self):
        # doc/decisions/2026-10-01-gpt-oss-backend.md
        self.assertEqual(
            config.OLLAMA_MODEL_DIGESTS[config.LLM_AI_MODEL],
            "a951a23b46a1f6093dafee2ea481d634b4e31ac720a8a16f3f91e04f5a40ecd9",
        )


class TestReplay(_Isolated):
    def _record(self, calls):
        """Record (prompt, answer) pairs in a run; returns its llm_calls.jsonl."""
        self.use(FakeModel([answer for _, answer in calls]))
        provenance.start_run("record")
        path = os.path.join(self.runs, provenance.current_run_id(), provenance.CALLS_FILE)
        for prompt, _ in calls:
            try:
                transport.send_ai_request("NCT1", prompt, SCHEMA)
            except Exception:
                pass
        provenance.finish_run()
        return path

    def test_a_replay_gives_back_the_recorded_answers(self):
        path = self._record([("a", {"genes": ["KRAS"]}), ("b", {"genes": ["NRAS"]})])
        replay = self.use(ReplayPlatform("ignored", "", calls_file=path))
        self.assertEqual(replay.model, config.LLM_AI_MODEL)
        self.assertEqual(
            transport.parse_ai_response(transport.send_ai_request("NCT1", "b", SCHEMA), "NCT1"),
            {"genes": ["NRAS"]},
        )
        self.assertEqual(
            transport.parse_ai_response(transport.send_ai_request("NCT1", "a", SCHEMA), "NCT1"),
            {"genes": ["KRAS"]},
        )

    def test_a_repeated_prompt_gets_its_answers_in_order_and_the_last_repeats(self):
        path = self._record([("a", {"n": 1}), ("a", {"n": 2})])
        replay = ReplayPlatform("", "", calls_file=path)
        answers = [replay.parse_response(replay.send("a", SCHEMA))["n"] for _ in range(3)]
        self.assertEqual(answers, [1, 2, 2])

    def test_a_changed_prompt_or_schema_is_a_miss(self):
        path = self._record([("a", {})])
        replay = ReplayPlatform("", "", calls_file=path)
        with self.assertRaises(ReplayMiss):
            replay.send("a changed", SCHEMA)
        with self.assertRaises(ReplayMiss):
            replay.send("a", {"type": "object"})

    def test_a_call_that_failed_is_not_replayed(self):
        path = self._record([("a", TimeoutError("slow"))])
        with self.assertRaises(ReplayMiss):
            ReplayPlatform("", "", calls_file=path).send("a", SCHEMA)

    def test_a_replay_records_no_calls_but_says_what_it_replayed(self):
        path = self._record([("a", {})])
        self.use(ReplayPlatform("", "", calls_file=path))
        with mock.patch.object(config, "LLM_PLATFORM", "Replay"):
            run_id = provenance.start_run("replay")
            transport.send_ai_request("NCT1", "a", SCHEMA)
            block = provenance.for_trial("NCT1")
        self.assertFalse(os.path.exists(os.path.join(self.runs, run_id, provenance.CALLS_FILE)))
        self.assertEqual(block["llm"]["replay_of"], path)
        self.assertEqual(block["llm"]["recorded_platform"], "Anthropic")

    def test_a_replay_caps_schema_enums_as_the_recorded_platform_did(self):
        path = self._record([("a", {})])
        self.use(ReplayPlatform("", "", calls_file=path))
        with (
            mock.patch.object(config, "LLM_PLATFORM", "Replay"),
            mock.patch.object(config, "SCHEMA_ENUM_MAX_VALUES", {"anthropic": None, "replay": 1}),
        ):
            self.assertIsNone(llm_schema.max_enum_values())

    def test_replay_without_a_file_is_refused(self):
        with mock.patch.object(config, "LLM_REPLAY_FILE", None):
            with self.assertRaisesRegex(ValueError, "LLM_REPLAY_FILE"):
                create_llm_platform("Replay", "", "")


@unittest.skipUnless(os.path.exists(SRC), "reviewed trial not present")
class TestIndex(_Isolated):
    def _build(self, docs):
        layer = os.path.join(self.tmp, "mapped")
        os.makedirs(layer)
        for name, doc in docs.items():
            with open(os.path.join(layer, f"{name}.yaml"), "w") as handle:
                yaml.safe_dump(doc, handle, sort_keys=False)
        out = os.path.join(self.tmp, "index")
        manifest = bti.build([(layer, "mapped")], out)
        with open(os.path.join(out, "trials.tsv")) as handle:
            trials = {r["trial_id"]: r for r in csv.DictReader(handle, delimiter="\t")}
        return manifest, trials

    def _trial(self, trial_id, block=None):
        with open(SRC) as handle:
            doc = yaml.safe_load(handle)
        doc["nct_id"] = trial_id
        if block is not None:
            doc["_provenance"] = block
        return doc

    def test_trials_carry_their_provenance_and_the_manifest_counts_drift(self):
        reference = provenance.reference_hashes()
        stale = dict(reference, **{config.GENE_LIST_FILE_PATH: "0" * 64})
        block = {
            "run_id": "20260928T000000Z-abcdef",
            "mapped_at": "2026-09-28T00:00:00Z",
            "code": {"commit": "d61a30c" + "0" * 33, "dirty": True},
            "llm": {
                "model": "claude-haiku-4-5-20251001",
                "genomic_prompt": "roles",
                "diagnosis_input": "labelled",
            },
            "reference_sha256": stale,
        }
        manifest, trials = self._build(
            {"NCT1": self._trial("NCT1", block), "NCT2": self._trial("NCT2")}
        )

        row = trials["NCT1"]
        self.assertEqual(row["mapped_run"], "20260928T000000Z-abcdef")
        self.assertEqual(row["mapped_at"], "2026-09-28T00:00:00Z")
        self.assertEqual(row["mapped_commit"], "d61a30c00000+dirty")
        self.assertEqual(row["llm_model"], "claude-haiku-4-5-20251001")
        self.assertEqual(row["prompt_settings"], "genomic_prompt=roles;diagnosis_input=labelled")
        self.assertEqual(
            {trials["NCT2"][c] for c in ("mapped_run", "mapped_commit", "llm_model")}, {""}
        )

        self.assertEqual(manifest["reference_drift"], {config.GENE_LIST_FILE_PATH: 1})
        self.assertEqual(
            manifest["trials_by_mapping"],
            {
                "claude-haiku-4-5-20251001 genomic_prompt=roles;diagnosis_input=labelled": 1,
                "unrecorded": 1,
            },
        )
        self.assertEqual(manifest["trials_by_commit"], {"d61a30c00000+dirty": 1, "unrecorded": 1})
        self.assertEqual(manifest["reference_sha256"], reference)
        self.assertIn("commit", manifest["code"])

    def test_the_build_is_still_byte_identical(self):
        docs = {"NCT1": self._trial("NCT1", {"run_id": "r", "llm": {"model": "m"}})}

        def build():
            self._build(docs)
            with open(os.path.join(self.tmp, "index", "trials.tsv")) as handle:
                text = handle.read()
            shutil.rmtree(os.path.join(self.tmp, "mapped"))
            shutil.rmtree(os.path.join(self.tmp, "index"))
            return text

        self.assertEqual(build(), build())


class TestConvert(unittest.TestCase):
    def test_the_block_never_reaches_matchminer(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        src, dst = os.path.join(tmp, "reviewed"), os.path.join(tmp, "json")
        os.makedirs(src)
        with open(os.path.join(src, "NCT1.yaml"), "w") as handle:
            yaml.safe_dump({"nct_id": "NCT1", "_provenance": {"run_id": "r"}}, handle)
        with (
            mock.patch.object(convert, "YAML_DIR", src),
            mock.patch.object(convert, "JSON_DIR", dst),
            mock.patch("builtins.print"),
        ):
            convert.convert([])
        with open(os.path.join(dst, "NCT1.json")) as handle:
            self.assertEqual(json.load(handle), {"nct_id": "NCT1"})
        with open(os.path.join(src, "NCT1.yaml")) as handle:
            self.assertIn("_provenance", handle.read())


if __name__ == "__main__":
    unittest.main()
