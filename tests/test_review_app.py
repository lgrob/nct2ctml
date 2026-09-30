"""
The local review interface (utils/review/app.py): the queue, the per-trial page,
and the three actions.

No sockets. Every test drives the request handlers' logic directly, because the
value is in what save / accept / exclude do to the layers, and because a test
that binds a port fails in a sandbox and in some CI runners.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import utils.review.app as app
import utils.review.common as common
from tests.support import temporary_layers

CTML = """nct_id: NCT0TEST
short_title: A test trial
treatment_list:
  step:
  - match:
    - and:
      - clinical:
          oncotree_primary_diagnosis: Neuroblastoma
          age_numerical: '>=1'
"""

FLAGGED = CTML + "gene_unsupported: ALK\n"


class _Layers(unittest.TestCase):
    def setUp(self):
        self.layers = temporary_layers().__enter__()
        self.addCleanup(self.layers.__exit__, None, None, None)

    def put(self, text, layer="review"):
        directory = {
            "mapped": self.layers.mapped,
            "review": self.layers.review,
            "reviewed": self.layers.reviewed,
        }[layer]
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "NCT0TEST.yaml")
        with open(path, "w") as handle:
            handle.write(text)
        return path


class TestQueue(_Layers):
    def test_a_flagged_trial_is_listed_with_its_flag_and_objection(self):
        self.put(FLAGGED)
        rows = app.queue_rows()
        self.assertEqual([r["trial_id"] for r in rows], ["NCT0TEST"])
        self.assertEqual(rows[0]["flags"], ["gene_unsupported"])
        self.assertIn("still flagged: gene_unsupported", rows[0]["problems"])
        self.assertEqual(rows[0]["title"], "A test trial")

    def test_the_index_page_renders_every_row(self):
        self.put(FLAGGED)
        page = app._index_html(app.queue_rows())
        self.assertIn("NCT0TEST", page)
        self.assertIn("gene_unsupported", page)

    def test_unreadable_yaml_is_listed_rather_than_crashing_the_queue(self):
        self.put("[not: a mapping")
        rows = app.queue_rows()
        self.assertEqual(rows[0]["flags"], ["unreadable YAML"])


class TestTrialPage(_Layers):
    def test_the_page_carries_the_editor_and_both_decisions(self):
        self.put(FLAGGED)
        page = app._trial_html("NCT0TEST")
        self.assertIn("<textarea", page)
        self.assertIn("gene_unsupported: ALK", page)  # the file itself, escaped into the editor
        self.assertIn('value="accept"', page.replace("'", '"'))
        self.assertIn('value="exclude"', page.replace("'", '"'))

    def test_a_sheet_that_cannot_render_still_leaves_the_editor(self):
        # No cached registry record in a temporary layer, so evidence.analyse raises.
        self.put(FLAGGED)
        page = app._trial_html("NCT0TEST")
        self.assertIn("<textarea", page)


class TestSave(_Layers):
    def test_a_valid_edit_is_written_and_the_previous_version_kept(self):
        path = self.put(FLAGGED)
        ok, message = app.save_trial("NCT0TEST", CTML)
        self.assertTrue(ok)
        self.assertIn(".prev", message)
        self.assertNotIn("gene_unsupported", open(path).read())
        self.assertIn("gene_unsupported", open(path + ".prev").read())

    def test_the_message_says_what_accept_would_still_refuse(self):
        self.put(FLAGGED)
        ok, message = app.save_trial(
            "NCT0TEST", FLAGGED.replace("Neuroblastoma", "Not A Diagnosis")
        )
        self.assertTrue(ok)
        self.assertIn("still flagged: gene_unsupported", message)
        self.assertIn("not an OncoTree name", message)

    def test_a_clean_save_says_nothing_is_left(self):
        self.put(FLAGGED)
        ok, message = app.save_trial("NCT0TEST", CTML)
        self.assertTrue(ok)
        self.assertIn("Nothing left", message)

    def test_broken_yaml_is_refused_and_the_file_untouched(self):
        path = self.put(FLAGGED)
        ok, message = app.save_trial("NCT0TEST", "key: [unclosed\n")
        self.assertFalse(ok)
        self.assertIn("not valid YAML", message)
        self.assertEqual(open(path).read(), FLAGGED)

    def test_a_non_mapping_is_refused(self):
        path = self.put(FLAGGED)
        ok, message = app.save_trial("NCT0TEST", "- just\n- a list\n")
        self.assertFalse(ok)
        self.assertIn("YAML mapping", message)
        self.assertEqual(open(path).read(), FLAGGED)

    def test_a_second_save_does_not_overwrite_the_first_backup(self):
        path = self.put(FLAGGED)
        app.save_trial("NCT0TEST", CTML)
        app.save_trial("NCT0TEST", CTML + "phase: II\n")
        self.assertTrue(os.path.exists(path + ".prev"))
        self.assertTrue(os.path.exists(path + ".prev.1"))


class TestActions(_Layers):
    def test_accept_refuses_a_flagged_file_and_says_why(self):
        self.put(FLAGGED)
        ok, message = app.accept_trial("NCT0TEST", "lgrob")
        self.assertFalse(ok)
        self.assertIn("still flagged: gene_unsupported", message)
        self.assertFalse(os.path.exists(os.path.join(self.layers.reviewed, "NCT0TEST.yaml")))

    def test_accept_moves_a_clean_file_and_logs_it(self):
        self.put(CTML)
        ok, message = app.accept_trial("NCT0TEST", "lgrob", "checked against the protocol")
        self.assertTrue(ok, message)
        self.assertTrue(os.path.exists(os.path.join(self.layers.reviewed, "NCT0TEST.yaml")))
        log = open(common.LOG_FILE).read()
        self.assertIn("lgrob", log)
        self.assertIn("checked against the protocol", log)

    def test_accept_without_a_reviewer_is_refused_before_the_gate(self):
        self.put(CTML)
        ok, message = app.accept_trial("NCT0TEST", "  ")
        self.assertFalse(ok)
        self.assertIn("reviewer name is required", message)
        self.assertFalse(os.path.exists(os.path.join(self.layers.reviewed, "NCT0TEST.yaml")))

    def test_exclude_needs_a_reason(self):
        self.put(CTML)
        ok, message = app.exclude_trial("NCT0TEST", "lgrob", "")
        self.assertFalse(ok)
        self.assertIn("reason", message.lower())

    def test_the_save_then_accept_path_works_end_to_end(self):
        self.put(FLAGGED)
        self.assertFalse(app.accept_trial("NCT0TEST", "lgrob")[0])
        self.assertTrue(app.save_trial("NCT0TEST", CTML)[0])
        ok, message = app.accept_trial("NCT0TEST", "lgrob")
        self.assertTrue(ok, message)
        self.assertTrue(os.path.exists(os.path.join(self.layers.reviewed, "NCT0TEST.yaml")))


if __name__ == "__main__":
    unittest.main()
