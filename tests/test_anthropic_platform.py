"""
The Anthropic request shape, offline. No request is sent: the client is
mocked, and only what would be sent and how the reply is read are checked.
"""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
from utils.llm_platforms import AnthropicPlatform

logger.remove()
HAIKU = "claude-haiku-4-5-20251001"
SCHEMA = {"type": "array", "items": {"type": "object"}}


class TestRequestBody(unittest.TestCase):

    def test_config_pins_a_dated_haiku_snapshot(self):
        self.assertEqual(config.LLM_PLATFORM, "Anthropic")
        self.assertRegex(config.LLM_AI_MODEL, r"^claude-haiku-4-5-\d{8}$")

    def test_haiku_gets_no_thinking_no_effort_and_temperature_zero(self):
        body = AnthropicPlatform(HAIKU, "").get_request_body("p", SCHEMA)
        self.assertNotIn("thinking", body)
        self.assertNotIn("output_config", body)
        self.assertEqual(body["temperature"], 0)

    def test_a_schema_becomes_a_forced_tool_wrapping_it(self):
        body = AnthropicPlatform(HAIKU, "").get_request_body("p", SCHEMA)
        tool = body["tools"][0]
        self.assertEqual(tool["input_schema"]["properties"]["result"], SCHEMA)
        self.assertEqual(body["tool_choice"], {"type": "tool", "name": tool["name"]})

    def test_no_schema_means_no_tool(self):
        self.assertNotIn("tools", AnthropicPlatform(HAIKU, "").get_request_body("p"))

    def test_haiku_with_adaptive_or_effort_is_refused_before_any_call(self):
        for setting in ({"ANTHROPIC_THINKING": "adaptive"}, {"ANTHROPIC_EFFORT": "high"}):
            with patch.multiple(config, **setting):
                with self.assertRaises(ValueError):
                    AnthropicPlatform(HAIKU, "").get_request_body("p", SCHEMA)

    def test_a_thinking_model_gets_thinking_and_no_forced_tool(self):
        with patch.multiple(config, ANTHROPIC_THINKING="adaptive", ANTHROPIC_EFFORT="medium"):
            body = AnthropicPlatform("claude-sonnet-5", "").get_request_body("p", SCHEMA)
        self.assertEqual(body["thinking"], {"type": "adaptive"})
        self.assertEqual(body["output_config"], {"effort": "medium"})
        self.assertNotIn("temperature", body)
        self.assertEqual(body["tool_choice"], {"type": "auto"})


def _reply(content, stop="tool_use"):
    return SimpleNamespace(content=content, stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class TestReplyParsing(unittest.TestCase):

    def _send(self, reply):
        platform = AnthropicPlatform(HAIKU, "")
        platform._client = MagicMock()
        platform._client.messages.create.return_value = reply
        return platform.parse_response(platform.send("p", SCHEMA))

    def test_the_tool_input_is_the_answer(self):
        rows = [{"genomic": {"hugo_symbol": "BRAF", "variant_category": "Mutation"}}]
        reply = _reply([SimpleNamespace(type="tool_use", name="report", input={"result": rows})])
        self.assertEqual(self._send(reply), rows)

    def test_an_empty_tool_result_is_empty_not_none(self):
        reply = _reply([SimpleNamespace(type="tool_use", name="report", input={})])
        self.assertEqual(self._send(reply), {})

    def test_text_replies_still_parse(self):
        reply = _reply([SimpleNamespace(type="text", text=json.dumps({"a": 1}))], stop="end_turn")
        self.assertEqual(self._send(reply), {"a": 1})


if __name__ == "__main__":
    unittest.main()
