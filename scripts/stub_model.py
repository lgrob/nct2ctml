"""
A schema-driven stand-in for the model, shared by the probes: for each JSON
schema it returns the same answer every time, the first enum value(s) in
sorted order, empty strings and lists, False. Deterministic, so what the
probes hash depends only on the prompts and the code around them.
"""


def fake(node):
    t = node.get("type") if isinstance(node, dict) else None
    if isinstance(node, dict) and "enum" in node:
        return sorted(node["enum"], key=str)[0]
    if t == "object":
        return {k: fake(v) for k, v in (node.get("properties") or {}).items()}
    if t == "array":
        it = node.get("items") or {}
        if isinstance(it, dict) and "enum" in it:
            return sorted(it["enum"], key=str)[:2]
        return [fake(it)] if isinstance(it, dict) and it.get("type") == "object" else []
    if t == "string":
        return ""
    if t == "boolean":
        return False
    return None


class _Refuse:
    def __init__(self, real):
        self.model = getattr(real, "model", None)

    def send(self, *args, **kwargs):
        raise RuntimeError("a probe reached the real LLM platform; its stub did not take effect")

    parse_response = get_request_body = send


def refuse_real_platform(transport):
    """
    Replace the model platform with one that raises, so a probe never calls a
    model. Pass utils.llm.transport, where the platform lives.
    """
    transport._llm_platform = _Refuse(transport._llm_platform)
