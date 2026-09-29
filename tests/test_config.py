"""
config.py: every tunable setting can be overridden as NCT2CTML_<NAME>, the
overrides are collected in config.OVERRIDES, a bad value stops at import, and
the defaults are what they were. Each case imports config in a fresh
interpreter with a controlled environment.
"""

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

PROBE = (
    "import json, config; print(json.dumps({'overrides': config.OVERRIDES, "
    "'values': {k: getattr(config, k) for k in %r}}))"
)


def load(env=None, names=()):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("NCT2CTML_")}
    result = subprocess.run(
        [sys.executable, "-c", PROBE % (list(names),)],
        cwd=ROOT,
        env={**clean, **(env or {})},
        capture_output=True,
        text=True,
    )
    return result, (json.loads(result.stdout) if result.returncode == 0 else None)


class TestConfig(unittest.TestCase):
    def test_defaults_without_overrides(self):
        _, out = load(names=["LLM_PLATFORM", "LLM_AI_MODEL", "GENOMIC_PROMPT", "RUNS_PATH"])
        self.assertEqual(out["overrides"], {})
        self.assertEqual(
            out["values"],
            {
                "LLM_PLATFORM": "Anthropic",
                "LLM_AI_MODEL": "claude-haiku-4-5-20251001",
                "GENOMIC_PROMPT": "roles",
                "RUNS_PATH": "runs",
            },
        )

    def test_each_kind_of_override_is_parsed_and_recorded(self):
        env = {
            "NCT2CTML_LLM_AI_MODEL": "llama3.3:70b",
            "NCT2CTML_OLLAMA_NUM_CTX": "8192",
            "NCT2CTML_ANTHROPIC_TEMPERATURE": "0.5",
            "NCT2CTML_SKIP_OUT_OF_SCOPE_AT_MAP": "false",
            "NCT2CTML_RUNS_PATH": "none",
        }
        names = list(k[len("NCT2CTML_") :] for k in env)
        _, out = load(env, names)
        expected = {
            "LLM_AI_MODEL": "llama3.3:70b",
            "OLLAMA_NUM_CTX": 8192,
            "ANTHROPIC_TEMPERATURE": 0.5,
            "SKIP_OUT_OF_SCOPE_AT_MAP": False,
            "RUNS_PATH": None,
        }
        self.assertEqual(out["values"], expected)
        self.assertEqual(out["overrides"], expected)

    def test_the_replay_file_keeps_its_old_variable_name(self):
        _, out = load({"NCT2CTML_REPLAY_FILE": "runs/x/llm_calls.jsonl"}, ["LLM_REPLAY_FILE"])
        self.assertEqual(out["values"]["LLM_REPLAY_FILE"], "runs/x/llm_calls.jsonl")

    def test_a_bad_value_stops_at_import_and_names_the_variable(self):
        result, _ = load({"NCT2CTML_OLLAMA_NUM_CTX": "big"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NCT2CTML_OLLAMA_NUM_CTX='big'", result.stderr)
        result, _ = load({"NCT2CTML_SKIP_OUT_OF_SCOPE_AT_MAP": "maybe"})
        self.assertIn("NCT2CTML_SKIP_OUT_OF_SCOPE_AT_MAP", result.stderr)

    def test_paths_are_not_overridable(self):
        _, out = load({"NCT2CTML_GENE_LIST_FILE_PATH": "/tmp/other.txt"}, ["GENE_LIST_FILE_PATH"])
        import config

        self.assertEqual(out["values"]["GENE_LIST_FILE_PATH"], config.GENE_LIST_FILE_PATH)
        self.assertEqual(out["overrides"], {})

    def test_the_model_catalogue_lives_in_the_docs_not_in_config(self):
        with open(os.path.join(ROOT, "config.py")) as handle:
            text = handle.read()
        self.assertNotIn("# LLM_AI_MODEL =", text)
        with open(os.path.join(ROOT, "doc", "llm_backends.md")) as handle:
            self.assertIn('# LLM_AI_MODEL = "llama3.3:70b"', handle.read())


if __name__ == "__main__":
    unittest.main()
