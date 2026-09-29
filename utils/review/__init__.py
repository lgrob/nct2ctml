"""
The review helper, split by what each part does (improvement plan step 11,
phase 1.2). The command is still `python -m utils.review_helper`.

- common: layer paths, flag keys and advice, Item, finding a trial's layer
- evidence: the trial's text and the passages behind each flag (analyse)
- sheets: the HTML review sheets
- gate: what accept refuses, accept, exclude, the queue and the audit sample
- maintenance: batch commands that re-apply a check to existing output

The rules shared with the mapper are in src/text_rules.py.
"""
