import unittest

import utils.reference_validation as rv
from utils.ai_helper import get_child_level_diagnoses_from_condition, get_inclusion_genomic_criteria, get_exclusion_genomic_criteria

class TestAITasks(unittest.TestCase):

    def setUp(self):
        self.nct_condition = 'Colorectal Cancer'
        self.child_nodes_oncotree_list = ['Signet Ring Cell Adenocarcinoma of the Colon and Rectum', 'Colon Adenocarcinoma In Situ', 'Small Bowel Well-Differentiated Neuroendocrine Tumor', 'Gastrointestinal Neuroendocrine Tumors', 'Well-Differentiated Neuroendocrine Tumor of the Rectum', 'Small Bowel Cancer', 'Anal Squamous Cell Carcinoma', 'Anorectal Mucosal Melanoma', 'Low-grade Appendiceal Mucinous Neoplasm', 'Medullary Carcinoma of the Colon', 'Goblet Cell Adenocarcinoma of the Appendix', 'Mucinous Adenocarcinoma of the Appendix', 'Appendiceal Adenocarcinoma', 'Small Intestinal Carcinoma', 'Well-Differentiated Neuroendocrine Tumor of the Appendix', 'Signet Ring Cell Type of the Appendix', 'Colorectal Adenocarcinoma', 'High-Grade Neuroendocrine Carcinoma of the Colon and Rectum', 'Colonic Type Adenocarcinoma of the Appendix', 'Anal Gland Adenocarcinoma', 'Rectal Adenocarcinoma', 'Mucinous Adenocarcinoma of the Colon and Rectum', 'Duodenal Adenocarcinoma', 'Colon Adenocarcinoma', 'Tubular Adenoma of the Colon']
        self.genes = sorted(rv.gene_symbols())

   
    def test_get_child_level_diagnoses_from_condition(self):
        oncotree_diagnoses_dict = get_child_level_diagnoses_from_condition("", set(self.child_nodes_oncotree_list), self.nct_condition)
        self.assertIsNotNone(oncotree_diagnoses_dict, msg="faield to get child level diagnoses")
    
    def test_get_genomic_criteria(self):
        text = """Cohort A: ROS1 Fusion-positive tumors (excluding NSCLC),
        Cohort B: NTRK1/2/3 fusion-positive tumors,
        Cohort C: ALK fusion-positive tumors (excluding NSCLC),
        Cohort E: AKT1/2/3 mutant-positive tumors,
        Cohort F: HER2 mutant-positive tumors,
        Cohort G: MDM2-amplified, TP53 wild-type tumors,
        Cohort H: PIK3CA multiple mutant-positive tumors,
        Cohort I: BRAF class II mutant or fusion-positive tumors,
        Cohort J: BRAF class III mutant-positive tumors,
        Cohort K: RET fusion-positive tumors (excluding NSCLC),
        Cohort L: KRAS G12C-positive tumors (excluding NSCLC and CRC),
        Cohort M: ATM Loss of Function tumors,
        Cohort N: SETD2 Loss of Function tumors"""
        result = get_inclusion_genomic_criteria('', self.genes, text)
        self.assertIsNotNone(result, msg="failed to get genomic criteria")

        # Extract all gene names mentioned in the test text
        expected_genes = {
            'ROS1', 'NTRK1', 'NTRK2', 'NTRK3', 'ALK', 'AKT1', 'AKT2', 'AKT3', 
            'HER2', 'MDM2', 'TP53', 'PIK3CA', 'BRAF', 'RET', 'KRAS', 'ATM', 'SETD2'
        }
        
        # Convert result to string to search for gene names
        result_str = str(result)
        
        # Check that all expected genes are present in the response
        for gene in expected_genes:
            self.assertIn(gene, result_str, msg=f"Gene {gene} not found in genomic criteria response")

        print(result)

if __name__ == "__main__":
    unittest.main()