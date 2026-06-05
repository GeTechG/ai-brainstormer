#!/usr/bin/env python3
"""Tests for run_round.py ledger detection and validation.

Standard library only (unittest). Focus: the symmetric_deliberation composite
ledger added alongside the existing objection/response ledgers, plus a
regression check that the original adversarial-review ledgers still validate.

Run:  python3 test_run_round.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_round as rr  # noqa: E402


def _fenced(obj):
    return "Some prose.\n\n```json\n%s\n```\n" % json.dumps(obj, indent=2)


VALID_DELIBERATION = {
    "options": [
        {"id": "OPT-A", "summary": "Stay asymmetric.", "proposed_by": "claude"},
        {"id": "OPT-B", "summary": "Add symmetric mode.", "proposed_by": "codex"},
    ],
    "claims": [
        {
            "id": "C1",
            "claim": "Convergence stays measurable with a claims ledger.",
            "supports": "OPT-B",
            "decision_critical": True,
            "evidence": "run_round.py:173 validates ledger structure.",
            "challenged_by": [],
            "status": "accepted",
            "resolution_evidence": "codex dropped challenge in round 4.",
        }
    ],
    "positions": [
        {
            "agent": "claude",
            "current_option": "OPT-B",
            "changed_from": "OPT-A",
            "change_evidence": "C1 resolved with evidence.",
            "suspect_flip": False,
        }
    ],
}


class ExpectedKind(unittest.TestCase):
    def test_deliberation_heading(self):
        prompt = "## Deliberation ledger\n\nemit the block"
        self.assertEqual(rr._expected_ledger_kind(prompt), "deliberation")

    def test_deliberation_json_marker(self):
        prompt = 'schema: {\n  "claims": [\n  ]\n}'
        self.assertEqual(rr._expected_ledger_kind(prompt), "deliberation")

    def test_objections_still_detected(self):
        prompt = '## Objection ledger\n\n"objections": ['
        self.assertEqual(rr._expected_ledger_kind(prompt), "objections")

    def test_responses_still_detected(self):
        prompt = '## Objection ledger response\n\n"responses": ['
        self.assertEqual(rr._expected_ledger_kind(prompt), "responses")

    def test_none_when_no_ledger(self):
        self.assertIsNone(rr._expected_ledger_kind("just prose, no ledger"))


class DeliberationValidation(unittest.TestCase):
    def test_valid_block_passes(self):
        verdict = _fenced(VALID_DELIBERATION)
        self.assertIsNone(rr._validate_ledger_block(verdict, "deliberation"))

    def test_missing_array_fails(self):
        bad = {k: v for k, v in VALID_DELIBERATION.items() if k != "positions"}
        err = rr._validate_ledger_block(_fenced(bad), "deliberation")
        self.assertIsNotNone(err)
        self.assertIn("options", err)
        self.assertIn("positions", err)

    def test_non_array_value_fails(self):
        bad = dict(VALID_DELIBERATION, claims={"id": "C1"})
        err = rr._validate_ledger_block(_fenced(bad), "deliberation")
        self.assertEqual(err, "`claims` is not an array")

    def test_item_not_object_fails(self):
        bad = dict(VALID_DELIBERATION, options=["not-an-object"])
        err = rr._validate_ledger_block(_fenced(bad), "deliberation")
        self.assertEqual(err, "options[0] is not an object")

    def test_missing_required_key_fails(self):
        bad_claim = dict(VALID_DELIBERATION["claims"][0])
        del bad_claim["resolution_evidence"]
        bad = dict(VALID_DELIBERATION, claims=[bad_claim])
        err = rr._validate_ledger_block(_fenced(bad), "deliberation")
        self.assertEqual(err, "claims[0] missing resolution_evidence")

    def test_no_fenced_block_fails(self):
        err = rr._validate_ledger_block("prose with no JSON", "deliberation")
        self.assertIn("missing fenced JSON block", err)

    def test_empty_arrays_pass(self):
        verdict = _fenced({"options": [], "claims": [], "positions": []})
        self.assertIsNone(rr._validate_ledger_block(verdict, "deliberation"))


class RetryPrompt(unittest.TestCase):
    def test_deliberation_schema_in_retry(self):
        prompt = rr._ledger_retry_prompt("old", "missing positions", "deliberation")
        self.assertIn('"options"', prompt)
        self.assertIn('"claims"', prompt)
        self.assertIn('"positions"', prompt)
        self.assertIn("missing positions", prompt)

    def test_objections_retry_unchanged(self):
        prompt = rr._ledger_retry_prompt("old", "err", "objections")
        self.assertIn('"objections"', prompt)
        self.assertNotIn('"positions"', prompt)


class AdversarialRegression(unittest.TestCase):
    def test_objections_valid(self):
        block = _fenced({"objections": [{
            "id": "J1-O1", "claim": "x", "required_evidence": "y",
            "severity": "high", "status": "open"}]})
        self.assertIsNone(rr._validate_ledger_block(block, "objections"))

    def test_responses_valid(self):
        block = _fenced({"responses": [{
            "id": "J1-O1", "response": "conceded", "evidence": "e",
            "answer_change": "c"}]})
        self.assertIsNone(rr._validate_ledger_block(block, "responses"))


if __name__ == "__main__":
    unittest.main()
