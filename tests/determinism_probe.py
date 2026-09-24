"""Probe for tests/test_prompt_determinism.py: map trials with a schema-driven stub model and record a hash of every prompt, schema and output. Run as a script under a given PYTHONHASHSEED."""
import sys, os, json, hashlib
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from loguru import logger; logger.remove()
import utils.ai_helper as ai
import utils.reference_validation as rv
import src.clinical_trials_gov as ctg, src.ctis as ctis

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
    if t == "string": return ""
    if t == "boolean": return False
    return None

CALLS = []
def send(id, prompt, json_schema=None):
    CALLS.append({"id": id, "prompt": prompt, "schema": json.dumps(json_schema, sort_keys=True)})
    return fake(json_schema or {})
ai.send_ai_request = send
ai.parse_ai_response = lambda r, trial_id="": r

from src.trial_map_manager import TrialMapManager
syn = TrialMapManager.get_gene_synonym_mapping(None)
out = {}
for tid in sys.argv[2].split(","):
    n0 = len(CALLS)
    reg = "nct" if tid.startswith("NCT") else "ctis"
    d = json.load(open(f"cache/{reg}/{tid}.json"))
    try:
        ctml = (ctg.map_nct_to_ctml if reg == "nct" else ctis.map_ctis_to_ctml)(d, syn)
        c = json.dumps(ctml, sort_keys=True, default=str, indent=1)
    except Exception as e:
        c = f"ERROR {type(e).__name__}: {e}"
    n1 = len(CALLS)
    try:
        inc, exc = (ctg if reg == "nct" else ctis).split_inclusion_exclusion_criteria(d)
        g = ctg.map_ctml_match_genomic_criteria(tid, syn, inc, exc)
        c += "|G|" + json.dumps(g, sort_keys=True, default=str)
    except Exception as e:
        c += f"|G ERROR {type(e).__name__}: {e}"
    out.setdefault("_genomic_calls", 0); out["_genomic_calls"] += len(CALLS) - n1
    out[tid] = {"calls": [{"id": x["id"], "first": x["prompt"][:90].replace("\n", " "),
                           "p": hashlib.md5(x["prompt"].encode()).hexdigest()[:10],
                           "s": hashlib.md5(x["schema"].encode()).hexdigest()[:10]} for x in CALLS[n0:]],
                "ctml": hashlib.md5(c.encode()).hexdigest()[:10], "ctml_err": c[:200] if c.startswith("ERROR") else ""}
json.dump(out, open(sys.argv[1], "w"), indent=0)
print(len(CALLS), "calls")
