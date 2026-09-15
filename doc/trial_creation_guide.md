## Guide for creation of trial documents

This document outlines the rules for manual creation of CTML documents that adhere to MatchMiner schema

The CTML trial documents are YAML files containing trial information.

#### Reference Schema
The schema for a trial document — including all **allowed values** for match fields — is defined in the MatchMiner API:

[matchminer/data_model.py](https://github.com/sumedhasaxena/matchminer-api/blob/master/matchminer/data_model.py)

Please refer to these schema objects in that file:
- `parent_schema` — top-level trial document
- `yaml_clinical_schema` — clinical match criteria
- `yaml_genomic_schema` — genomic match criteria
- `yaml_match_schema` — `and` / `or` match structure

For how NCT data maps into CTML, see [nct_to_ctml_mapping_guide.md](nct_to_ctml_mapping_guide.md).

------------


#### Directory Structure

nct2ctml/

├── ctml/

│   ├── json/

│   ├── pending/

│   └── reviewed/

The CTML directory on root level contains the trial CTML files. The sub-directories and their purpose is as follows:

**pending**: Newly curated CTML trial files go here.

**reviewed**: Once the trials under 'pending' folder are reviewed, they are moved to this folder

**json**: When trial files are ready to be picked up by [matchminer-admin](http://https://github.com/sumedhasaxena/matchminer-admin "matchminer-admin"), they are converted to JSON format and moved here. matchminer-admin repo will remove files from here, once it finishes processing them.

------------
#### Rules for assigning values to various CTML fields

1. Oncotree diagnosis — see [nct_to_ctml_mapping_guide.md § Diagnosis](nct_to_ctml_mapping_guide.md#diagnosis-oncotree); uses [OncoTree `oncotree_2025_10_03`](https://oncotree.mskcc.org/?version=oncotree_2025_10_03&field=NAME) (`ref/oncotree_file.txt`); allowed diagnosis strings are OncoTree names (not enumerated in `data_model.py`)
2. Genes / genomic criteria — see mapping guide § Genomic match; allowed values in `yaml_genomic_schema`
3. General fields — see mapping guide § Part 1; trial-level fields in `parent_schema`
4. `protocol_id` and `protocol_no` — leave empty/`0` in CTML; MatchMiner assigns unique auto-incremented values on database insert (see [mapping guide § protocol_id and protocol_no](nct_to_ctml_mapping_guide.md#protocol_id-and-protocol_no-intentionally-empty)). Use `protocol_ids` for local IDs from `local_trial_info.csv`.
5. Match criteria — allowed values in `yaml_clinical_schema` and `yaml_genomic_schema`; structure in `yaml_match_schema`

------------

#### Manual curation of trial a file (CTML):

Please follow the 'Manual workflow' section in doc/clinical_trial_management_workflow.pdf to understand if a trial needs to be created manually.
Essentially, a trial file needs to be prepared manually only if it cannot be created via automated workflow or if its not present on clinical_trials.gov.

In such case, as presented in the workflow, one needs to do the following:

1. Prepare a CTML file for the trial manually, using the CTML schema mentioned in the section above.
Make sure to set the following fields as:

- nct_id: Set as 'NA'
- protocol_ids: Append the local protocol id to the protocol_ids list.

2. Make an entry for the manually curated trial file in local_trial_info.csv and push the the updated content to git.


