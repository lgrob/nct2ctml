# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

'''
The CTML trial skeleton every mapper starts from.

The `age` default is "All", not upstream's "Adults". It is the value a
trial keeps when its registry gives no age band, and in a paediatric corpus
"Adults" is the one answer guaranteed to be wrong. "All" is also what
src/ctis.map_age_group already returns in the same situation, so both
registries now fall back to the same, deliberately wide, label.
'''

def get_ctml_schema():
    return {
  'nct_id': '',
  'age': 'All',
  'cancer_center_accrual_goal_upper': 0,
  'curated_on': '',
  'study_start_date':'',
  'study_completion_date':'',
  'data_table4': 'Interventional',
  'drug_list': {
    'drug': []
  },
  'long_title': '',
  'last_updated': '',
  'management_group_list': {
    'management_group': [
      {
        'is_primary': 'Y',
        'management_group_name': 'Group1'
      }
    ]
  },
  'oncology_group_list': {
    'oncology_group': [
      {
        'group_name': 'Group1',
        'is_primary': 'N'
      }
    ]
  },
  'phase': '',
  'principal_investigator': '',
  'principal_investigator_institution': '',
  'program_area_list': {
    'program_area': [
      {
        'is_primary': 'Y',
        'program_area_name': 'Program1'
      }
    ]
  },
  'protocol_id': 0,
  'protocol_ids': [], # list of local protocol IDs
  'protocol_no': '',
  'protocol_target_accrual': 0,
  'protocol_type': 'INTERVENTIONAL',
  'prior_treatment_requirements': [],
  'short_title': '',
  'site_list': {
    'site': []
  },
  'sponsor_list': {
    'sponsor': []
  },
  'staff_list': {
    'protocol_staff': []
  },
  'status': 'open to accrual',
  'summary': '',
  'treatment_list': {
    'step': [
      {
        'step_internal_id': 111,
        'step_code': '1',
        'step_type': 'Registration',
        'arm': [],
        'match': []
      }
    ]
  }
}