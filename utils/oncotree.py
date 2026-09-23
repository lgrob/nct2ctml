import sys
import os

sys.path.append(os.path.abspath('../'))

import csv
import re
from collections import defaultdict
import config

# "Acute Myeloid Leukemia (AML)" -> the display name, dropping the trailing
# Oncotree code. Anchored at the end because a display name may contain
# brackets of its own, and the same pattern is used by
# utils/reference_validation so the two parsers cannot diverge again.
_LEVEL_VALUE = re.compile(r"\s+\([A-Z0-9_./-]+\)$")


def _get_level_columns(fieldnames):
    return sorted(
        (f for f in fieldnames if f.startswith('level_')),
        key=lambda name: int(name.split('_')[1]),
    )


def _parse_level_value(value):
    """
    The Oncotree display name, with its code removed.

    This used to split on the first "(", which silently truncated the twenty
    nodes whose display name contains a parenthesis - and merged them, since
    the five B-Lymphoblastic Leukemia/Lymphoma translocation subtypes all
    became "B-Lymphoblastic Leukemia/Lymphoma with t". The model was then
    offered a name no patient record can carry, answered with it faithfully,
    and had the answer rejected by the validator, which parses the same file
    correctly. Fifteen of the twenty are haematological - ETV6-RUNX1,
    TCF3-PBX1, BCR-ABL1, KMT2A-rearranged, RUNX1-RUNX1T1, CBFB-MYH11.
    """
    return _LEVEL_VALUE.sub("", value.strip()).strip()


def _read_oncotree_rows():
    with open(config.ONCOTREE_TXT_FILE_PATH) as f:
        reader = csv.DictReader(f, delimiter='\t')
        level_columns = _get_level_columns(reader.fieldnames)
        rows = list(reader)
    return rows, level_columns


def get_all_oncotree_data():
    rows, level_columns = _read_oncotree_rows()

    level_1_list = set()
    mapping_l1_all = defaultdict(set)

    for row in rows:
        level_1 = _parse_level_value(row[level_columns[0]])
        level_1_list.add(level_1)
        mapping_l1_all[level_1].update(
            _parse_level_value(row[col]) for col in level_columns[1:]
        )

    for s in mapping_l1_all.values():
        if '' in s:
            s.remove('')
    return level_1_list, mapping_l1_all


def get_l1_l2_oncotree_data():
    print(config.ONCOTREE_TXT_FILE_PATH)
    rows, level_columns = _read_oncotree_rows()

    level_1_list = set()
    mapping_11_l2 = defaultdict(set)

    for row in rows:
        level_1 = _parse_level_value(row[level_columns[0]])
        level_1_list.add(level_1)
        if len(level_columns) > 1:
            level_2 = _parse_level_value(row[level_columns[1]])
            mapping_11_l2[level_1].update({level_2})

    for s in mapping_11_l2.values():
        if '' in s:
            s.remove('')

    return level_1_list, mapping_11_l2


def get_lineage():
    """
    (parent, level_1_names, descendants) for every Oncotree node.

    `parent` maps a display name to the node above it, `descendants` maps a
    name to itself plus everything below it, and `level_1_names` is the set of
    organ-system roots.

    `descendants` is the same relation MatchMiner's oncotree_mapping.json
    encodes: the matchengine expands a trial's diagnosis to every descendant
    before querying, so a parent matches every patient its children do.
    Computing it here rather than reading the deployed file keeps mapping
    independent of a running MatchMiner; checked against the live instance on
    2026-09-21, the two agree on 852 of 861 shared names, and all nine
    differences are nodes our newer Oncotree has and the deployed table does
    not.
    """
    rows, level_columns = _read_oncotree_rows()

    parent = {}
    level_1_names = set()
    descendants = defaultdict(set)

    for row in rows:
        path = [_parse_level_value(row[col]) for col in level_columns]
        path = [node for node in path if node]
        if not path:
            continue
        level_1_names.add(path[0])
        for depth, node in enumerate(path):
            descendants[node].update(path[depth:])
            if depth:
                parent[node] = path[depth - 1]

    return parent, level_1_names, dict(descendants)
