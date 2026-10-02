"""
disease_status is neither asked nor published unless
config.PUBLISH_DISEASE_STATUS (doc/decisions/2026-10-02-no-disease-status.md).
"""

import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import src.clinical_trials_gov as ctg
import src.mapping.biomarkers as biomarkers

logger.remove()

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "registry", "nct")


def _has_status(node):
    if isinstance(node, dict):
        return "disease_status" in node or any(_has_status(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_status(v) for v in node)
    return False


_SYNONYMS = {}


def _synonyms():
    if not _SYNONYMS:
        from src.trial_map_manager import TrialMapManager

        _SYNONYMS.update(TrialMapManager().get_gene_synonym_mapping())
    return _SYNONYMS


class TestNoDiseaseStatus(unittest.TestCase):
    def _map(self, publish):
        import json

        name = sorted(f for f in os.listdir(FIXTURE) if f.endswith(".json"))[0]
        trial = json.load(open(os.path.join(FIXTURE, name)))
        asked = mock.Mock(return_value={"disease_status": ["Recurrent"]})
        with (
            mock.patch.object(config, "PUBLISH_DISEASE_STATUS", publish),
            mock.patch.object(biomarkers, "map_disease_status", asked),
            # Everything else the mapper asks a model is answered empty.
            mock.patch("utils.llm.transport.send_ai_request", return_value={}),
            mock.patch("utils.llm.transport.parse_ai_response", return_value={}),
        ):
            ctml = ctg.map_nct_to_ctml(trial, _synonyms())
        return ctml, asked

    def test_off_neither_asks_nor_publishes(self):
        ctml, asked = self._map(False)
        asked.assert_not_called()
        self.assertFalse(_has_status(ctml.get("treatment_list")))

    def test_on_restores_the_old_behaviour(self):
        ctml, asked = self._map(True)
        asked.assert_called_once()
        self.assertTrue(_has_status(ctml.get("treatment_list")))

    def test_the_default_is_off(self):
        self.assertFalse(config.PUBLISH_DISEASE_STATUS)


if __name__ == "__main__":
    unittest.main()
