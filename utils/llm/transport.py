"""
The model transport: the platform config.py selects, send_ai_request (which
records each call inside a run, utils/provenance) and parse_ai_response.

Tests and probes stub the model by replacing transport.send_ai_request, or the
platform as transport._llm_platform; every prompt module calls them through
this module, so one replacement covers all prompts.

Moved from utils/ai_helper.py on 2026-09-29 (step 11, phase 3.1).
"""

import json
import time

import requests
from loguru import logger

import config
from utils import provenance
from utils.llm_platforms import create_llm_platform

# Initialize the LLM platform based on config
_llm_platform = create_llm_platform(
    platform_name=config.LLM_PLATFORM,
    model=config.LLM_AI_MODEL,
    hostname=config.GPU_SERVER_HOSTNAME,
)


def parse_ai_response(ai_response, trial_id=""):
    return _llm_platform.parse_response(ai_response, trial_id)


def send_ai_request(id, prompt, json_schema=None):
    """
    Send AI request using the configured platform. Inside a run
    (utils/provenance.start_run) the call is recorded, answer or error.
    """
    started = time.monotonic()
    try:
        ai_response = _send_ai_request(id, prompt, json_schema)
    except Exception as ex:
        provenance.record_call(
            id,
            prompt,
            json_schema,
            error=f"{type(ex).__name__}: {ex}",
            elapsed=time.monotonic() - started,
        )
        raise
    provenance.record_call(
        id, prompt, json_schema, response=ai_response, elapsed=time.monotonic() - started
    )
    return ai_response


def _send_ai_request(id, prompt, json_schema=None):
    # Hosted platforms (e.g. Anthropic) own their transport and auth via an
    # official SDK, so they expose send() instead of going through the
    # unauthenticated hostname:port POST used by the self-hosted platforms.
    sender = getattr(_llm_platform, "send", None)
    if callable(sender):
        logger.debug(f"AI request | ID:{id} | {prompt[:200]}")
        ai_response = sender(prompt, json_schema)
        logger.debug(f"AI response | ID:{id} | {ai_response}")
        return ai_response

    req_body = _llm_platform.get_request_body(prompt, json_schema)
    req_body_json = json.dumps(req_body)
    logger.debug(f"AI request | ID:{id} | {req_body_json}")
    endpoint_url = _llm_platform.get_endpoint_url()
    print(endpoint_url)

    # Without a timeout a stalled or runaway model blocks the pipeline forever:
    # a local 14B in a constrained-JSON generation loop was observed emitting
    # 30k+ tokens over 3.5 hours on a single call.
    timeout = getattr(config, "LLM_REQUEST_TIMEOUT_SECONDS", 600)
    response = requests.post(
        endpoint_url,
        data=req_body_json,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )

    response.raise_for_status()

    print(response.status_code)
    ai_response = response.json()
    logger.debug(f"AI response | ID:{id} | {ai_response}")
    return ai_response
