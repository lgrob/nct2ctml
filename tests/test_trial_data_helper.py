import unittest
from unittest.mock import patch
import sys
import os

# Add the src directory to the path so we can import the module
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from trial_data_helper import (remove_unused_keys, get_all_keys, split_with_find,
                               all_tumours, all_solid_tumours)


class TestTrialDataHelper(unittest.TestCase):
    
    def setUp(self):
        """Set up test data before each test method"""
        self.sample_trial_data = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT05894239",
                    "orgStudyIdInfo": {
                        "id": "WO44263"
                    },
                    "secondaryIdInfos": [
                        {
                            "id": "2022-502046-28-00",
                            "type": "REGISTRY",
                            "domain": "EU Clinical Trials"
                        }
                    ],
                    "organization": {
                        "fullName": "Hoffmann-La Roche",
                        "class": "INDUSTRY"
                    },
                    "briefTitle": "A Study to Evaluate the Efficacy and Safety of Inavolisib in Combination With Phesgo Versus Placebo in Combination With Phesgo in Participants With PIK3CA-Mutated HER2-Positive Locally Advanced or Metastatic Breast Cancer",
                    "officialTitle": "A Phase III, Multicenter, Randomized, Double-Blind, Placebo-Controlled Study Evaluating the Efficacy and Safety of Inavolisib in Combination With Phesgo Versus Placebo in Combination With Phesgo As Maintenance Therapy After First Line Induction Therapy in Participants With PIK3CA-Mutated HER2-Positive Locally Advanced or Metastatic Breast Cancer",
                    "acronym": "INAVO122"
                },
                "statusModule": {
                    "statusVerifiedDate": "2025-08",
                    "overallStatus": "RECRUITING",
                    "expandedAccessInfo": {
                        "hasExpandedAccess": False
                    },
                    "startDateStruct": {
                        "date": "2023-09-08",
                        "type": "ACTUAL"
                    },
                    "primaryCompletionDateStruct": {
                        "date": "2026-09-28",
                        "type": "ESTIMATED"
                    },
                    "completionDateStruct": {
                        "date": "2032-12-28",
                        "type": "ESTIMATED"
                    },
                    "studyFirstSubmitDate": "2023-05-24",
                    "studyFirstSubmitQcDate": "2023-06-07",
                    "studyFirstPostDateStruct": {
                        "date": "2023-06-08",
                        "type": "ACTUAL"
                    },
                    "lastUpdateSubmitDate": "2025-08-01",
                    "lastUpdatePostDateStruct": {
                        "date": "2025-08-03",
                        "type": "ACTUAL"
                    }
                },
                "sponsorCollaboratorsModule": {
                    "responsibleParty": {
                        "type": "SPONSOR"
                    },
                    "leadSponsor": {
                        "name": "Hoffmann-La Roche",
                        "class": "INDUSTRY"
                    }
                },
                "oversightModule": {
                    "oversightHasDmc": True,
                    "isFdaRegulatedDrug": True,
                    "isFdaRegulatedDevice": False
                },
                "descriptionModule": {
                    "briefSummary": "This study will evaluate the efficacy and safety of inavolisib in combination with Phesgo (pertuzumab, trastuzumab, and rHuPH20 injection for subcutaneous use) compared with placebo in combination with Phesgo, as maintenance therapy, after induction therapy in participants with previously untreated HER2-positive advanced breast cancer (ABC)."
                },
                "conditionsModule": {
                    "conditions": [
                        "Metastatic Breast Cancer"
                    ]
                },
                "designModule": {
                    "studyType": "INTERVENTIONAL",
                    "phases": [
                        "PHASE3"
                    ],
                    "designInfo": {
                        "allocation": "RANDOMIZED",
                        "interventionModel": "PARALLEL",
                        "primaryPurpose": "TREATMENT",
                        "maskingInfo": {
                            "masking": "DOUBLE",
                            "whoMasked": [
                                "PARTICIPANT",
                                "INVESTIGATOR"
                            ]
                        }
                    },
                    "enrollmentInfo": {
                        "count": 230,
                        "type": "ESTIMATED"
                    }
                },
                "armsInterventionsModule": {
                    "armGroups": [
                        {
                            "label": "Induction Therapy: Phesgo plus Taxane-Based Chemotherapy",
                            "type": "OTHER",
                            "description": "Participants will be administered the treatments as outlined in the interventions section.",
                            "interventionNames": [
                                "Drug: Phesgo",
                                "Drug: Taxane-based Chemotherapy"
                            ]
                        },
                        {
                            "label": "Maintenance Therapy: Inavolisib plus Phesgo",
                            "type": "EXPERIMENTAL",
                            "description": "Participants will be administered the treatments as outlined in the interventions section.",
                            "interventionNames": [
                                "Drug: Inavolisib",
                                "Drug: Phesgo",
                                "Drug: Optional Endocrine Therapy of Investigator's Choice"
                            ]
                        },
                        {
                            "label": "Maintenance Therapy: Placebo plus Phesgo",
                            "type": "ACTIVE_COMPARATOR",
                            "description": "Participants will be administered the treatments as outlined in the interventions section.",
                            "interventionNames": [
                                "Drug: Phesgo",
                                "Drug: Placebo",
                                "Drug: Optional Endocrine Therapy of Investigator's Choice"
                            ]
                        }
                    ],
                    "interventions": [
                        {
                            "type": "DRUG",
                            "name": "Inavolisib",
                            "description": "Participants will receive an inavolisib tablet to be taken orally (PO), once a day (QD), on Days 1-21 of each 21-day cycle, beginning on Day (D) 1 of Cycle (C) 1 of maintenance treatment.",
                            "armGroupLabels": [
                                "Maintenance Therapy: Inavolisib plus Phesgo"
                            ]
                        },
                        {
                            "type": "DRUG",
                            "name": "Phesgo",
                            "description": "Phesgo will be administered to participants subcutaneously every 3 weeks (Q3W) on D1 of each 21-day cycle.",
                            "armGroupLabels": [
                                "Induction Therapy: Phesgo plus Taxane-Based Chemotherapy",
                                "Maintenance Therapy: Inavolisib plus Phesgo",
                                "Maintenance Therapy: Placebo plus Phesgo"
                            ]
                        },
                        {
                            "type": "DRUG",
                            "name": "Placebo",
                            "description": "Inavolisib-matching tablet taken PO QD on Days 1-21 of each 21-day cycle, beginning on D1 C1 of maintenance treatment.",
                            "armGroupLabels": [
                                "Maintenance Therapy: Placebo plus Phesgo"
                            ]
                        },
                        {
                            "type": "DRUG",
                            "name": "Taxane-based Chemotherapy",
                            "description": "During the induction therapy phase, the investigator's choice of taxane-based chemotherapy will be administered after Phesgo.",
                            "armGroupLabels": [
                                "Induction Therapy: Phesgo plus Taxane-Based Chemotherapy"
                            ],
                            "otherNames": [
                                "non-investigational medicinal product (NIMP)"
                            ]
                        },
                        {
                            "type": "DRUG",
                            "name": "Optional Endocrine Therapy of Investigator's Choice",
                            "description": "Optional endocrine therapy (ET) is allowed at the discretion of the investigator, based on the standard of care. Allowed ETs are tamoxifen, or one of the specified third-generation aromatase inhibitor (AI [anastrozole, letrozole, or exemestane]), or fulvestrant. The investigator will determine and supply the appropriate luteinizing hormone-releasing hormone (LHRH) agonist locally approved for use in breast cancer. The LHRH agonist will be administered according to local prescribing information.",
                            "armGroupLabels": [
                                "Maintenance Therapy: Inavolisib plus Phesgo",
                                "Maintenance Therapy: Placebo plus Phesgo"
                            ],
                            "otherNames": [
                                "NIMP"
                            ]
                        }
                    ]
                },
                "outcomesModule": {
                    "primaryOutcomes": [
                        {
                            "measure": "Investigator-Assessed Progression-Free Survival (PFS)",
                            "timeFrame": "Up to approximately 40 months"
                        }
                    ],
                    "secondaryOutcomes": [
                        {
                            "measure": "Overall Survival (OS)",
                            "timeFrame": "Up to approximately 111 months"
                        },
                        {
                            "measure": "Investigator-Assessed Objective Response Rate (ORR)",
                            "timeFrame": "Up to approximately 111 months"
                        },
                        {
                            "measure": "Investigator-Assessed Duration of Response (DOR)",
                            "timeFrame": "Up to approximately 111 months"
                        },
                        {
                            "measure": "Investigator-Assessed Clinical Benefit Rate (CBR)",
                            "timeFrame": "Up to approximately 111 months"
                        },
                        {
                            "measure": "Investigator-Assessed PFS2",
                            "timeFrame": "Up to approximately 111 months"
                        },
                        {
                            "measure": "Mean and Mean Changes from Baseline Score in Function and Health-Related Quality of Life (HRQoL)",
                            "description": "Assessed through the use of the Functional (Role, Physical) and Global Health Status (GHS)/Quality of Life (QoL) scales of the European Organisation for Research and Treatment of Cancer Quality of Life-Core 30 Questionnaire (EORTC QLQ-C30)",
                            "timeFrame": "Day 1 of Cycles 1 and 2 and beyond, 30-day safety follow up visit, post-treatment tumor assessment follow-up with PRO collection and survival follow up visit every 6 months (up to 111 months). Each cycle is 21 days."
                        },
                        {
                            "measure": "Percentage of Participants with Adverse Events",
                            "timeFrame": "Day 1 until 30 days after the final dose of study treatment (up to 111 months). Each cycle is 21 days."
                        },
                        {
                            "measure": "Plasma Concentration of Inavolisib at Specified Timepoints",
                            "timeFrame": "Day 1 of Cycles 1 and 4. Each cycle is 21 days."
                        }
                    ]
                },
                "eligibilityModule": {
                    "eligibilityCriteria": "Inclusion Criteria:\n\n* Eastern Cooperative Oncology Group (ECOG) Performance Status 0 or 1\n* Histologically or cytologically confirmed and documented adenocarcinoma of the breast with metastatic or locally advanced disease not amenable to curative resection\n* Confirmation of HER2 biomarker eligibility based on valid results from central testing of tumor tissue documenting HER2-positivity\n* Confirmation of PIK3CA-mutation biomarker eligibility based on valid results from central testing of tumor tissue documenting PIK3CA-mutated tumor status\n* Disease-free interval from completion of adjuvant or neoadjuvant systemic non-hormonal treatment to recurrence of >= 6 months\n* LVEF (left ventricular ejection fraction) of at least 50% measured by echocardiogram (ECHO) or multiple-gated acquisition scan (MUGA)\n* Adequate hematologic and organ function prior to initiation of study treatment\n\nExclusion Criteria:\n\n* Prior treatment in the locally advanced or metastatic setting with any PI3K, AKT, or mTOR inhibitor or any agent whose mechanism of action is to inhibit the PI3K-AKT-mTOR pathway\n* Any prior systemic non-hormonal anti-cancer therapy for locally advanced or metastatic HER2-positive breast cancer prior to initiation of induction therapy\n* History or active inflammatory bowel disease\n* Disease progression within 6 months of receiving any HER2-targeted therapy\n* Type 2 diabetes requiring ongoing systemic treatment at the time of study entry; or any history of Type 1 diabetes\n* Participants with active HBV infection\n* Clinically significant and active liver disease, including severe liver impairment, viral or other hepatitis, current alcohol abuse, or cirrhosis\n* Symptomatic active lung disease, including pneumonitis or interstitial lung disease\n* Any history of leptomeningeal disease or carcinomatous meningitis\n* Serious infection requiring IV antibiotics within 7 days prior to Day 1 of Cycle 1\n* Any concurrent ocular or intraocular condition that, in the opinion of the investigator, would require medical or surgical intervention during the study period to prevent or treat vision loss that might result from that condition\n* Active inflammatory or infectious conditions in either eye or history of idiopathic or autoimmune-associated uveitis in either eye",
                    "healthyVolunteers": False,
                    "sex": "ALL",
                    "minimumAge": "18 Years",
                    "stdAges": [
                        "ADULT",
                        "OLDER_ADULT"
                    ]
                },
                "contactsLocationsModule": {
                    "centralContacts": [
                        {
                            "name": "Reference Study ID Number: WO44263 https://forpatients.roche.com/",
                            "role": "CONTACT",
                            "phone": "888-662-6728 (U.S. Only)",
                            "email": "global-roche-genentech-trials@gene.com"
                        }
                    ],
                    "overallOfficials": [
                        {
                            "name": "Clinical Trials",
                            "affiliation": "Hoffmann-La Roche",
                            "role": "STUDY_DIRECTOR"
                        }
                    ],
                    "locations": [
                        {
                            "facility": "Queen Mary Hospital",
                            "status": "RECRUITING",
                            "city": "Hong Kong",
                            "country": "Hong Kong",
                            "geoPoint": {
                                "lat": 22.27832,
                                "lon": 114.17469
                            }
                        },
                        {
                            "facility": "Tuen Mun Hospital",
                            "status": "RECRUITING",
                            "city": "Hong Kong",
                            "country": "Hong Kong",
                            "geoPoint": {
                                "lat": 22.27832,
                                "lon": 114.17469
                            }
                        }
                    ]
                },
                "ipdSharingStatementModule": {
                    "ipdSharing": "YES",
                    "description": "For eligible studies, qualified researchers may request access to individual patient level clinical data. See Roche's commitment to transparency of clinical study information here: https://go.roche.com/data_sharing"
                }
            },
            "derivedSection": {
                "miscInfoModule": {
                    "versionHolder": "2025-08-14"
                },
                "conditionBrowseModule": {
                    "meshes": [
                        {
                            "id": "D001943",
                            "term": "Breast Neoplasms"
                        }
                    ],
                    "ancestors": [
                        {
                            "id": "D009371",
                            "term": "Neoplasms by Site"
                        },
                        {
                            "id": "D009369",
                            "term": "Neoplasms"
                        },
                        {
                            "id": "D001941",
                            "term": "Breast Diseases"
                        },
                        {
                            "id": "D012871",
                            "term": "Skin Diseases"
                        }
                    ],
                    "browseLeaves": [
                        {
                            "id": "M5220",
                            "name": "Breast Neoplasms",
                            "asFound": "Breast Cancer",
                            "relevance": "HIGH"
                        },
                        {
                            "id": "M5218",
                            "name": "Breast Diseases",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M15674",
                            "name": "Skin Diseases",
                            "relevance": "LOW"
                        }
                    ],
                    "browseBranches": [
                        {
                            "abbrev": "BC04",
                            "name": "Neoplasms"
                        },
                        {
                            "abbrev": "BC17",
                            "name": "Skin and Connective Tissue Diseases"
                        },
                        {
                            "abbrev": "All",
                            "name": "All Conditions"
                        }
                    ]
                },
                "interventionBrowseModule": {
                    "meshes": [
                        {
                            "id": "C080625",
                            "term": "Taxane"
                        },
                        {
                            "id": "C000723546",
                            "term": "Inavolisib"
                        }
                    ],
                    "ancestors": [
                        {
                            "id": "D000970",
                            "term": "Antineoplastic Agents"
                        },
                        {
                            "id": "D000081082",
                            "term": "Phosphoinositide-3 Kinase Inhibitors"
                        },
                        {
                            "id": "D004791",
                            "term": "Enzyme Inhibitors"
                        },
                        {
                            "id": "D045504",
                            "term": "Molecular Mechanisms of Pharmacological Action"
                        }
                    ],
                    "browseLeaves": [
                        {
                            "id": "M1723",
                            "name": "Fulvestrant",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M9789",
                            "name": "Hormones",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M1743",
                            "name": "Letrozole",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M16403",
                            "name": "Tamoxifen",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M247237",
                            "name": "Exemestane",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M147959",
                            "name": "Taxane",
                            "asFound": "Jet",
                            "relevance": "HIGH"
                        },
                        {
                            "id": "M14260",
                            "name": "Prolactin Release-Inhibiting Factors",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M1781",
                            "name": "Anastrozole",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M350338",
                            "name": "Inavolisib",
                            "asFound": "Intracavitary",
                            "relevance": "HIGH"
                        },
                        {
                            "id": "M25769",
                            "name": "Aromatase Inhibitors",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M2270",
                            "name": "Phosphoinositide-3 Kinase Inhibitors",
                            "relevance": "LOW"
                        },
                        {
                            "id": "M7951",
                            "name": "Enzyme Inhibitors",
                            "relevance": "LOW"
                        }
                    ],
                    "browseBranches": [
                        {
                            "abbrev": "ANeo",
                            "name": "Antineoplastic Agents"
                        },
                        {
                            "abbrev": "All",
                            "name": "All Drugs and Chemicals"
                        },
                        {
                            "abbrev": "BDCA",
                            "name": "Bone Density Conservation Agents"
                        }
                    ]
                }
            },
            "hasResults": False
        }
    
    def test_remove_unused_keys_selectively_removes_status_module_keys(self):
        """Test that statusModule keys are selectively removed while preserving required date structures"""
        result = remove_unused_keys(self.sample_trial_data.copy())
        
        # Check that statusModule still exists
        self.assertIn("statusModule", result["protocolSection"])
        
        # Check that required date structures are preserved
        self.assertIn("studyFirstPostDateStruct", result["protocolSection"]["statusModule"])
        self.assertIn("lastUpdatePostDateStruct", result["protocolSection"]["statusModule"])
        
        # Check that other keys are removed
        self.assertNotIn("statusVerifiedDate", result["protocolSection"]["statusModule"])
        self.assertNotIn("overallStatus", result["protocolSection"]["statusModule"])
        self.assertNotIn("expandedAccessInfo", result["protocolSection"]["statusModule"])
        self.assertNotIn("primaryCompletionDateStruct", result["protocolSection"]["statusModule"])
        self.assertNotIn("studyFirstSubmitDate", result["protocolSection"]["statusModule"])
        self.assertNotIn("studyFirstSubmitQcDate", result["protocolSection"]["statusModule"])
        self.assertNotIn("lastUpdateSubmitDate", result["protocolSection"]["statusModule"])
        
        # Verify the preserved structures contain the expected data
        self.assertEqual(result["protocolSection"]["statusModule"]["studyFirstPostDateStruct"]["date"], "2023-06-08")
        self.assertEqual(result["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"], "2025-08-03")
    
    def test_remove_unused_keys_removes_oversight_module(self):
        """Test that oversightModule is removed from protocolSection"""
        result = remove_unused_keys(self.sample_trial_data.copy())
        self.assertNotIn("oversightModule", result["protocolSection"])
    
    def test_remove_unused_keys_removes_locations_from_contacts_locations_module(self):
        """Test that locations is removed from contactsLocationsModule"""
        result = remove_unused_keys(self.sample_trial_data.copy())
        self.assertNotIn("locations", result["protocolSection"]["contactsLocationsModule"])
    
    def test_remove_unused_keys_removes_outcomes_module(self):
        """Test that outcomesModule is removed from protocolSection"""
        result = remove_unused_keys(self.sample_trial_data.copy())
        self.assertNotIn("outcomesModule", result["protocolSection"])
    
    def test_remove_unused_keys_removes_ipd_sharing_statement_module(self):
        """Test that ipdSharingStatementModule is removed from protocolSection"""
        result = remove_unused_keys(self.sample_trial_data.copy())
        self.assertNotIn("ipdSharingStatementModule", result["protocolSection"])
    
    def test_remove_unused_keys_removes_derived_section(self):
        """Test that derivedSection is removed from the root level"""
        result = remove_unused_keys(self.sample_trial_data.copy())
        self.assertNotIn("derivedSection", result)
    
    def test_remove_unused_keys_preserves_other_keys(self):
        """Test that other important keys are preserved"""
        result = remove_unused_keys(self.sample_trial_data.copy())
        
        # Check that important keys are still present
        self.assertIn("protocolSection", result)
        self.assertIn("identificationModule", result["protocolSection"])
        self.assertIn("contactsLocationsModule", result["protocolSection"])
        self.assertIn("designModule", result["protocolSection"])
        self.assertIn("armsInterventionsModule", result["protocolSection"])
        
        # Check that the contactsLocationsModule still exists but without locations
        self.assertIn("contactsLocationsModule", result["protocolSection"])
        self.assertNotIn("locations", result["protocolSection"]["contactsLocationsModule"])
    
    def test_remove_unused_keys_handles_missing_keys_gracefully(self):
        """Test that the method handles missing keys gracefully using .pop() with None default"""
        # Create trial data with some keys missing
        incomplete_trial_data = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT12345678"},
                "contactsLocationsModule": {},
                "designModule": {"studyType": "Interventional"}
            }
        }
        
        # This should not raise an error
        try:
            result = remove_unused_keys(incomplete_trial_data.copy())
            self.assertIsInstance(result, dict)
        except KeyError:
            self.fail("remove_unused_keys raised KeyError when it should handle missing keys gracefully")
    
    def test_remove_unused_keys_handles_missing_status_module_gracefully(self):
        """Test that the method handles missing statusModule gracefully"""
        # Create trial data without statusModule
        incomplete_trial_data = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT12345678"},
                "contactsLocationsModule": {},
                "designModule": {"studyType": "Interventional"}
            }
        }
        
        # This should not raise an error
        try:
            result = remove_unused_keys(incomplete_trial_data.copy())
            self.assertIsInstance(result, dict)
            # statusModule should not exist in the result
            self.assertNotIn("statusModule", result["protocolSection"])
        except KeyError:
            self.fail("remove_unused_keys raised KeyError when statusModule is missing")
    
    def test_remove_unused_keys_handles_status_module_without_preserved_keys(self):
        """Test that the method handles statusModule that doesn't have the preserved keys"""
        # Create trial data with statusModule but without the preserved keys
        incomplete_trial_data = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT12345678"},
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "startDate": "2023-01-01"
                },
                "contactsLocationsModule": {},
                "designModule": {"studyType": "Interventional"}
            }
        }
        
        # This should not raise an error
        try:
            result = remove_unused_keys(incomplete_trial_data.copy())
            self.assertIsInstance(result, dict)
            # statusModule should exist but be empty (all keys removed)
            self.assertIn("statusModule", result["protocolSection"])
            self.assertEqual(len(result["protocolSection"]["statusModule"]), 0)
        except KeyError:
            self.fail("remove_unused_keys raised KeyError when statusModule lacks preserved keys")
    
    def test_remove_unused_keys_returns_modified_dict(self):
        """Test that the method returns the modified dictionary"""
        result = remove_unused_keys(self.sample_trial_data.copy())
        self.assertIsInstance(result, dict)
        self.assertEqual(result["protocolSection"]["identificationModule"]["nctId"], "NCT05894239")
    
    def test_remove_unused_keys_modifies_original_dict(self):
        """Test that the method modifies the original dictionary (in-place modification)"""
        original_data = self.sample_trial_data.copy()
        original_keys = set(original_data["protocolSection"].keys())
        
        result = remove_unused_keys(original_data)
        
        # Check that the original data was modified
        # statusModule should still exist but with only preserved keys
        self.assertIn("statusModule", original_data["protocolSection"])
        self.assertIn("studyFirstPostDateStruct", original_data["protocolSection"]["statusModule"])
        self.assertIn("lastUpdatePostDateStruct", original_data["protocolSection"]["statusModule"])
        self.assertNotIn("overallStatus", original_data["protocolSection"]["statusModule"])
        
        self.assertNotIn("oversightModule", original_data["protocolSection"])
        self.assertNotIn("outcomesModule", original_data["protocolSection"])
        self.assertNotIn("ipdSharingStatementModule", original_data["protocolSection"])
        self.assertNotIn("derivedSection", original_data)
        
        # Check that the result is the same object as the input
        self.assertIs(result, original_data)

    def test_get_all_keys_returns_all_keys(self):
        """Test that get_all_keys returns all unique keys from a list of dictionaries"""
        list_of_dicts = [{"genomic": {"hugo_symbol": "ROS1", "variant_category": "Structural Variation"}}, {"genomic": {"hugo_symbol": "ALK", "variant_category": "Structural Variation"}}]
        expected_keys = {"genomic", "hugo_symbol", "variant_category"}
        result = get_all_keys(list_of_dicts)
        self.assertEqual(result, expected_keys)

    def test_split_with_find_splits_correctly(self):
        """Test that split_with_find splits a string correctly based on a substring"""
        input_string = "Inclusion criteria:Minimum body weight of 35 kg. Exclusion criteria: HER2 mutation"
        substring = "exclusion criteria"
        expected_output = ("Inclusion criteria:Minimum body weight of 35 kg. ", ": HER2 mutation")
        result = split_with_find(input_string, [substring])
        print(result)
        self.assertEqual(result, expected_output)

    def test_split_with_find_splits_correctly_with_multiple_split_keywords(self):
        """Test that split_with_find splits a string correctly based on a substring"""
        input_string = (
            "Pathologically confirmed, locally advanced or metastatic nonsquamous NSCLC. "
            "Exclusion - Is currently receiving an investigational drug in a clinical trial "
            "or participating in any other type of medical research judged not to be scientifically "
            "or medically compatible with this study.")
        
        substring1 = "exclusion criteria"
        substring2 = "exclusion"
    
        result = split_with_find(input_string, [substring1, substring2])
        
        first_part, second_part = result
        
        # Key assertions based on the function's behavior:
        
        # 1. First part should not contain the keyword
        self.assertNotIn("Exclusion", first_part)
        
        # 2. First part should end right before the keyword
        self.assertTrue(first_part.strip().endswith("NSCLC."))
        
        # 3. Second part should NOT start with the keyword (it's removed)
        self.assertFalse(second_part.startswith("Exclusion"))
        
        # 4. Second part should start with the text after the keyword
        self.assertTrue(second_part.strip().startswith("- Is currently"))
        
        # 5. The keyword should be case-insensitively matched
        # (Test that it works even though we used lowercase "exclusion -")
        self.assertTrue("Exclusion" in input_string)  # Original has capital E

class TestBroadBasketDetection(unittest.TestCase):
    """
    A trial whose conditions say "any cancer" gets MatchMiner's _SOLID_ /
    _LIQUID_ wildcards instead of an enumerated diagnosis list. A paediatric
    registry usually phrases those broad terms with a qualifier, and the
    detectors only matched the bare forms, so "Pediatric Cancer" fell through
    to a hard mapping failure.
    """

    def test_bare_broad_terms(self):
        self.assertTrue(all_tumours(["Cancer"]))
        self.assertTrue(all_solid_tumours(["Solid Tumor"]))

    def test_qualified_broad_terms(self):
        for condition in ("Pediatric Cancer", "Childhood Cancer", "Advanced Cancer"):
            self.assertTrue(all_tumours([condition]), condition)
        for condition in ("Pediatric Solid Tumor", "Recurrent Solid Tumor"):
            self.assertTrue(all_solid_tumours([condition]), condition)

    def test_stripping_is_additive(self):
        # "Malignant Neoplasm" is matched by an exact comparison, and stripping
        # leaves "Neoplasm", which is not. Both forms have to be tested.
        self.assertTrue(all_solid_tumours(["Malignant Neoplasm"]))

    def test_a_specific_diagnosis_is_not_a_basket(self):
        for condition in ("Neuroblastoma", "Acute Myeloid Leukemia",
                          "Ewing Sarcoma", "Hepatoblastoma"):
            self.assertFalse(all_tumours([condition]), condition)
            self.assertFalse(all_solid_tumours([condition]), condition)

    def test_empty_and_none(self):
        for value in ([], None):
            self.assertFalse(all_tumours(value))
            self.assertFalse(all_solid_tumours(value))


if __name__ == '__main__':
    unittest.main()
