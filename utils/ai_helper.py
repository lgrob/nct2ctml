# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.


# a lot of trial criteria mention exclusion too in inclusion criteria hence the prompt supplies both inclusion and exclusion instructions
# Shape that _enrich_genomic_criteria expects. Supplied to Ollama as
# "format", which constrains decoding rather than merely asking for JSON.
# Without it a model will happily echo the prompt's own input labels back as
# keys - gemma3:27b returned {"EligibilityCriteria": ..., "Possible GeneList":
# [], "Output": []} on 8 of 12 benchmark trials, treating the prompt as a
# template to fill in.
# Structured output for everything the model is asked for, not just genomic
# criteria. Without it Ollama is free to return prose or malformed JSON, and
# parse_response logs a JSONDecodeError and hands back an empty dict - so the
# whole answer is discarded as if the model had found nothing. Observed twice
# on a single trial: "Expecting ',' delimiter: line 68 column 1 (char 514)",
# which is 68 lines in 514 characters, i.e. a list of diagnoses one per line
# with the commas missing.
#
# Where the prompt already restricts the answer to a list of candidates, the
# schema restricts it too, which on a grammar-compiling backend makes an
# off-list answer impossible to emit rather than merely discouraged.
# "Lymphoma" is not an Oncotree display name and cannot be produced there.
# On Anthropic the tool call is not `strict`, so the enum is guidance: the
# cached Haiku answers to the 50-trial benchmark contain "Lymphoma" once per
# replicate (NCT02332668, 1 of 440 and 1 of 426 answers) under a 283-value
# enum. That one is caught - filter_diagnoses drops terms that are not
# Oncotree names when the CTML is built - but an Oncotree name from outside
# the candidate branch would pass. MatchMiner's _SOLID_ and
# _LIQUID_ wildcards are deliberately absent too: the pipeline derives those
# from the trial's conditions, and a model should not be invited to guess them.


def safe_get(dict_data, keys):
    for key in keys:
        dict_data = dict_data.get(key, {})
    return dict_data
