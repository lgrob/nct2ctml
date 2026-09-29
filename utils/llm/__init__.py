"""
Everything that talks to the model (improvement plan step 11, phase 3).

- transport: the configured platform, sending a request (and recording it
  inside a run), parsing the answer. Stub the model by replacing
  transport.send_ai_request; every prompt calls it through the module.
- schema: the JSON-schema machinery shared by the prompts: the enum cap,
  candidate checks, and prompt list ordering.
- prompts/: one module per prompt family, each with its text, schema and
  the function that sends it.
"""
