# Backend: Claude Haiku 4.5 through the Anthropic API

- **Date:** 2026-09-24
- **Roadmap:** D1
- **Outcome:** adopted: Claude Haiku 4.5 (claude-haiku-4-5-20251001) through the Anthropic API
- Moved from CHANGES.md on 2026-09-28 (improvement plan step 13); the text is unchanged.

Decided 2026-09-24 (roadmap D1). `config.py` now selects `Anthropic` with
`claude-haiku-4-5-20251001`, pinned to the dated snapshot so a run can be
reproduced. Every prompt measurement since 2026-09-23 was made on it, and it
is the cheapest current Claude model.

The platform as written would have failed on the first call. It always sent
`thinking: adaptive` and `output_config.effort`, and Haiku 4.5 supports
neither. It also sent schemas as `output_config.format`, a path its own
comment called untested. `AnthropicPlatform` now:

- sends thinking and effort only when `config.ANTHROPIC_THINKING` /
  `ANTHROPIC_EFFORT` ask for them, and refuses either with Haiku 4.5 before
  any call is made;
- runs at `ANTHROPIC_TEMPERATURE` (0) when thinking is off;
- enforces a prompt's schema through a forced tool call whose input wraps
  it as `{"result": ...}` (several prompts return a top-level array, and a
  tool input must be an object). This is the request shape all the Haiku
  measurements used, so production and benchmark now send the same request.

`scripts/run_ollama_mapping.sh` refuses to run unless `LLM_PLATFORM` is
`Ollama`, since it reads the model id from `config.py`.
`tests/test_anthropic_platform.py` covers the request body and the reply
parsing offline. Not yet done: a live call through this code path (roadmap
0.4).
