# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

"""
Trial Map Manager

This module handles the mapping of NCT trial data to CTML format.
"""

import csv
import os
from datetime import datetime
from typing import Dict, List
from loguru import logger
import src.clinical_trials_gov as ctg
import src.ctis as ctis
import src.trial_data_helper as tdh
import utils.reference_validation as rv
import utils.oncology_scope as scope
import config


class TrialMapManager:
    """Manager for trial data mapping to CTML format"""
    
    def __init__(self):
        self.local_trial_file = 'ref/local_trial_info.csv'
        self.trial_status_file = 'cache/nct/trial_status.csv'
       
    
    def get_gene_synonym_mapping(self) -> Dict[str, List[str]]:
        """
        alias -> [official symbols] for finding genes named in criteria text.

        Delegates to utils.reference_validation, which is the single reader of
        the gene reference files. This method used to open and parse them a
        second time with its own blocklist handling, which is how the "!"
        convention came to be honoured on this path and ignored on the
        validation one.
        """
        return rv.gene_synonym_mapping()

    def load_trial_status_dict(self) -> Dict[str, Dict]:
        """Load trial status information into a dictionary"""
        trial_status_dict = {}
        if os.path.exists(self.trial_status_file):
            with open(self.trial_status_file, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    trial_status_dict[row['nct_id']] = row
        return trial_status_dict
    
    def load_local_trial_dict(self) -> Dict[str, Dict]:
        """Load local trial info into a consolidated dictionary with key as nct_id"""
        local_trial_dict = {}
        if os.path.exists(self.local_trial_file):
            with open(self.local_trial_file, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    nct_id = row['nct_id']
                    local_protocol_id = row['local_protocol_ids'].strip()
                    pi_name = row['pi_name'].strip()
                    pi_institution = row['pi_institution'].strip()
                    
                    # Only process trials with valid NCT IDs (skip 'NA' entries)
                    if nct_id != 'NA':
                        if nct_id not in local_trial_dict:
                            local_trial_dict[nct_id] = {
                                'nct_id': nct_id,
                                'local_protocol_ids': local_protocol_id,
                                'pi_names': pi_name,
                                'pi_institutions': pi_institution
                            }
                        else:
                            # Append multiple local_protocol_ids with pipe separator
                            existing_protocols = local_trial_dict[nct_id]['local_protocol_ids']
                            if local_protocol_id not in existing_protocols:
                                local_trial_dict[nct_id]['local_protocol_ids'] = f"{existing_protocols}|{local_protocol_id}"
                            
                            # Append multiple pi_names with pipe separator
                            existing_pi_names = local_trial_dict[nct_id]['pi_names']
                            if pi_name not in existing_pi_names:
                                local_trial_dict[nct_id]['pi_names'] = f"{existing_pi_names}|{pi_name}"
                            
                            # Append multiple pi_institutions with pipe separator
                            existing_pi_institutions = local_trial_dict[nct_id]['pi_institutions']
                            if pi_institution not in existing_pi_institutions:
                                local_trial_dict[nct_id]['pi_institutions'] = f"{existing_pi_institutions}|{pi_institution}"
        
        return local_trial_dict
    
    def _add_local_trial_info(self, mapped_ctml: dict, nct_id: str) -> None:
        """
        Add local trial information to the mapped CTML data.
        This method handles the common logic for both map_all_trials and map_single_trial.
        
        Parameters
        ----------
        mapped_ctml : dict
            The CTML data to be updated with local trial info
        nct_id : str
            The NCT ID to look up in local trial info
        """
        if os.path.exists(self.local_trial_file):
            with open(self.local_trial_file, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                local_protocol_ids_list = []
                local_pi_names_list = []
                local_pi_institutions_list = []
                
                for row in reader:
                    if row['nct_id'] == nct_id:
                        local_protocol_ids_list.append(row['local_protocol_ids'].strip())
                        local_pi_names_list.append(row['pi_name'].strip())
                        local_pi_institutions_list.append(row['pi_institution'].strip())
                
                if local_protocol_ids_list:
                    # Convert protocol IDs to list (handle any existing pipe separators)
                    local_protocol_ids_str = '|'.join(local_protocol_ids_list)
                    local_protocol_ids_list_final = tdh.convert_protocol_ids_to_list(local_protocol_ids_str)
                    mapped_ctml['protocol_ids'] = local_protocol_ids_list_final
                    logger.info(f"Added local protocol IDs: {local_protocol_ids_list_final}")
                    
                    # Handle PI names - convert pipe to comma and append to existing if present
                    local_pi_names = ', '.join(local_pi_names_list)
                    if mapped_ctml['principal_investigator']:
                        mapped_ctml['principal_investigator'] = f"{mapped_ctml['principal_investigator']}, {local_pi_names}"
                    else:
                        mapped_ctml['principal_investigator'] = local_pi_names
                    logger.info(f"Added local PI names: {local_pi_names}")
                    
                    # Handle PI institutions - convert pipe to comma and append to existing if present
                    local_pi_institutions = ', '.join(local_pi_institutions_list)
                    if mapped_ctml['principal_investigator_institution']:
                        mapped_ctml['principal_investigator_institution'] = f"{mapped_ctml['principal_investigator_institution']}, {local_pi_institutions}"
                    else:
                        mapped_ctml['principal_investigator_institution'] = local_pi_institutions
                    logger.info(f"Added local PI institutions: {local_pi_institutions}")
                    
                else:
                    mapped_ctml['protocol_ids'] = []
                    logger.info("No local trial info found")
        else:
            mapped_ctml['protocol_ids'] = []
            logger.info("Local trial info file not found")
    
    def _get_cutoff_date(self, cutoff_days: int = None) -> datetime:
        """
        Get the cutoff date for mapping trials.
        
        Parameters
        ----------
        cutoff_days : int, optional
            Number of days back to consider. If None, uses config default.
            
        Returns
        -------
        datetime
            Cutoff date
        """
        import config
        from datetime import datetime, timedelta
        
        if cutoff_days is None:
            cutoff_days = config.MAPPING_CUTOFF_DAYS
        
        cutoff_date = datetime.now() - timedelta(days=cutoff_days)
        return cutoff_date
    
    def map_all_trials(self, nct_files_path: str, ctml_files_path: str, cutoff_days: int = None) -> Dict[str, int]:
        """Map all NCT files to CTML format with local trial info integration"""
        logger.info("Using ctml_files_path: {}".format(ctml_files_path))
        cutoff_date = self._get_cutoff_date(cutoff_days)
        gene_synonym_mapping = self.get_gene_synonym_mapping()
        
        # Load data dictionaries
        trial_status_dict = self.load_trial_status_dict()
        local_trial_dict = self.load_local_trial_dict()
        
        logger.info(f"Loaded {len(trial_status_dict)} trial status records")
        logger.info(f"Loaded {len(local_trial_dict)} local trial records")
        logger.info(f"Using cutoff date: {cutoff_date.strftime('%Y-%m-%d')} (trials updated within last {cutoff_days or 'config default'} days)")
        
        processed_count = 0
        skipped_count = 0
        out_of_scope = []
        scope_overrides = scope.load_overrides() if config.SKIP_OUT_OF_SCOPE_AT_MAP else {}
        
        for file_name in os.listdir(nct_files_path):
            if os.path.isfile(os.path.join(nct_files_path, file_name)) and file_name.endswith('.json'):
                nct_id = file_name.split('.')[0]
                
                # Check if this trial was updated within the cutoff period in trial_status.csv
                if nct_id in trial_status_dict:
                    entry_last_updated_date_str = trial_status_dict[nct_id]['entry_last_updated_date']
                    
                    # Convert string date to datetime object for comparison                    
                    entry_last_updated_date = datetime.strptime(entry_last_updated_date_str, '%Y-%m-%d')
                    if entry_last_updated_date < cutoff_date:
                        logger.info(f"Skipping NCT ID: {nct_id} - last updated: {entry_last_updated_date_str}, cutoff: {cutoff_date.strftime('%Y-%m-%d')}")
                        skipped_count += 1
                        continue
                else:
                    logger.info(f"Skipping NCT ID: {nct_id} - not found in trial_status.csv")
                    skipped_count += 1
                    continue
                
                try:
                    trial_data = tdh.read_from_file(nct_files_path, nct_id, 'json')
                    if config.SKIP_OUT_OF_SCOPE_AT_MAP:
                        in_scope, why = scope.assess(nct_id, trial_data, "nct", scope_overrides)
                        if not in_scope:
                            logger.info(f"Skipping NCT ID: {nct_id} - out of scope: {why}")
                            out_of_scope.append((nct_id, "nct", why))
                            skipped_count += 1
                            continue

                    logger.info(f"Mapping NCT ID: {nct_id}")   
                    logger.info("-----------------------")
                    
                    # Map to CTML format
                    mapped_ctml = ctg.map_nct_to_ctml(trial_data, gene_synonym_mapping)
                    
                    # Add local trial info if available
                    if nct_id in local_trial_dict:
                        local_info = local_trial_dict[nct_id]
                        
                        # Add local protocol IDs - convert to list
                        local_protocol_ids_str = local_info['local_protocol_ids']
                        local_protocol_ids_list = tdh.convert_protocol_ids_to_list(local_protocol_ids_str)
                        mapped_ctml['protocol_ids'] = local_protocol_ids_list
                        logger.info(f"Added local protocol IDs: {local_protocol_ids_list}")
                        
                        # Handle PI names - convert pipe to comma and append to existing if present
                        local_pi_names = local_info['pi_names'].replace('|', ', ')
                        if mapped_ctml['principal_investigator']:
                            mapped_ctml['principal_investigator'] = f"{mapped_ctml['principal_investigator']}, {local_pi_names}"
                        else:
                            mapped_ctml['principal_investigator'] = local_pi_names
                        logger.info(f"Added local PI names: {local_pi_names}")
                        
                        # Handle PI institutions - convert pipe to comma and append to existing if present
                        local_pi_institutions = local_info['pi_institutions'].replace('|', ', ')
                        if mapped_ctml['principal_investigator_institution']:
                            mapped_ctml['principal_investigator_institution'] = f"{mapped_ctml['principal_investigator_institution']}, {local_pi_institutions}"
                        else:
                            mapped_ctml['principal_investigator_institution'] = local_pi_institutions
                        logger.info(f"Added local PI institutions: {local_pi_institutions}")

                        # Handle case when we need to explicity record status as closed
                        # This will be needed if we are inserting an already closed trial, which has a local trial too, just to record it
                        if trial_status_dict[nct_id]['status'].lower() == 'closed':
                            mapped_ctml['status'] = 'closed'
                            logger.info(f"nct_id: {nct_id} | Set trial status to closed  based on trial_status.csv")
                        
                    else:
                        # Fall back to reading from file for this specific trial
                        self._add_local_trial_info(mapped_ctml, nct_id)
                    
                    # Save CTML files
                    tdh.save_to_file(mapped_ctml, ctml_files_path, nct_id, 'yaml')
                    #tdh.save_to_file(mapped_ctml, ctml_files_path, nct_id, 'json')
                    
                    processed_count += 1
                    logger.info(f"Successfully mapped and saved {nct_id}")
                    
                except Exception as ex:
                    logger.error(f"nct_id: {nct_id} | Unexpected {ex=}, {type(ex)=}")
        
        if config.SKIP_OUT_OF_SCOPE_AT_MAP:
            scope.write_report(out_of_scope, config.SCOPE_REPORT_FILE_PATH, registry="nct")
            logger.info(f"{len(out_of_scope)} trials out of scope, listed in "
                        f"{config.SCOPE_REPORT_FILE_PATH}")
        logger.info(f"Mapping completed. Processed: {processed_count}, Skipped: {skipped_count}")
        
        return {
            'processed': processed_count,
            'skipped': skipped_count
        }
    
    def map_all_ctis_trials(self, ctis_files_path: str, ctml_files_path: str) -> Dict[str, int]:
        """Map every cached CTIS trial, skipping out-of-scope ones as for NCT."""
        numbers = sorted(f[:-5] for f in os.listdir(ctis_files_path) if f.endswith('.json'))
        overrides = scope.load_overrides() if config.SKIP_OUT_OF_SCOPE_AT_MAP else {}
        out_of_scope, done, failed = [], 0, 0
        for n, ct in enumerate(numbers, 1):
            if config.SKIP_OUT_OF_SCOPE_AT_MAP:
                try:
                    trial_data = tdh.read_from_file(ctis_files_path, ct, 'json')
                except Exception as e:
                    logger.error(f"CTIS: {ct} | could not read cached record: {e}")
                    failed += 1
                    continue
                in_scope, why = scope.assess(ct, trial_data, "ctis", overrides)
                if not in_scope:
                    logger.info(f"CTIS: {ct} | Skipping - out of scope: {why}")
                    out_of_scope.append((ct, "ctis", why))
                    continue
            ok = self.map_single_ctis_trial(ct, ctis_files_path, ctml_files_path)
            done, failed = done + bool(ok), failed + (not ok)
            print(f"  [{n}/{len(numbers)}] {ct}: {'ok' if ok else 'FAILED'}")
        if config.SKIP_OUT_OF_SCOPE_AT_MAP:
            scope.write_report(out_of_scope, config.SCOPE_REPORT_FILE_PATH, registry="ctis")
        return {'processed': done, 'failed': failed, 'skipped': len(out_of_scope)}

    def map_single_ctis_trial(self, ct_number: str, ctis_files_path: str, ctml_files_path: str) -> bool:
        """
        Map one CTIS record to CTML.

        Separate entry point rather than a branch inside map_single_trial:
        the two registries publish different documents, and local trial info
        is keyed on NCT ids so it does not apply here.
        """
        try:
            logger.info(f"Mapping CTIS number: {ct_number}")
            trial_data = tdh.read_from_file(ctis_files_path, ct_number, 'json')
        except FileNotFoundError:
            logger.error(f'File {ct_number}.json not found at {ctis_files_path}')
            return False
        except Exception as e:
            logger.exception(f'Error reading file {ct_number}.json: {e}')
            return False

        gene_synonym_mapping = self.get_gene_synonym_mapping()
        try:
            mapped_ctml = ctis.map_ctis_to_ctml(trial_data, gene_synonym_mapping)
            # CTIS bypassed the review queue entirely until 2026-09-21: it saved
            # straight to the output directory, so a CTIS trial whose diagnosis
            # could not be determined reached MatchMiner and matched every
            # patient in the database. The safety net was only ever wired to the
            # ClinicalTrials.gov path.
            destination = self._destination_for(mapped_ctml, ctml_files_path, ct_number)
            tdh.save_to_file(mapped_ctml, destination, ct_number, 'yaml')
            logger.info(f"Successfully mapped and saved {ct_number}")
            return True
        except Exception as ex:
            logger.exception(f"ct_number: {ct_number} | Unexpected error while mapping: {ex}")
            return False

    @staticmethod
    def _destination_for(mapped_ctml: dict, ctml_files_path: str, trial_id: str) -> str:
        """
        Where this trial should be written: the normal output, or the review
        queue when it is not usable as it stands.

        Two cases send a trial to review:

        - No oncotree_primary_diagnosis anywhere in its match tree. That trial
          would match on its remaining criteria alone, which for a basket
          trial is every patient in the database.
        - A protein change that failed the reference check
          (protein_change_unverified, see
          match_criteria_mapper._clean_protein_change_fields). The criterion
          is gene-level until a curator resolves it, so the trial matches
          every variant in that gene.

        Discarding either is worse than queueing it: a trial that is not there
        is a trial nobody can be matched to and nobody can see is missing.
        """
        keys = tdh.get_all_keys(mapped_ctml)
        reasons = []
        if 'oncotree_primary_diagnosis' not in keys:
            reasons.append("no diagnosis criterion, so as it stands it would match every patient")
        if 'protein_change_unverified' in keys:
            reasons.append("a protein change did not match its reference protein")
        if not reasons:
            return ctml_files_path
        import config  # imported here, as elsewhere in this module
        review_path = getattr(config, 'CTML_REVIEW_PATH', 'ctml/needs-review')
        os.makedirs(review_path, exist_ok=True)
        logger.warning(
            f"{trial_id} | Writing to {review_path} instead of {ctml_files_path}: "
            f"{'; '.join(reasons)}."
        )
        return review_path

    def map_single_trial(self, nct_id: str, nct_files_path: str, ctml_files_path: str) -> bool:
        """Map a specific NCT ID to CTML format with local trial info integration"""
        logger.info("Using ctml_files_path: {}".format(ctml_files_path))
        try:
            logger.info(f"Mapping NCT ID: {nct_id}")   
            logger.info("-----------------------")                 
            trial_data = tdh.read_from_file(nct_files_path, nct_id, 'json')
        except FileNotFoundError:
            logger.error(f'File {nct_id}.json not found at {nct_files_path}')
            return False
        except Exception as e:
            # Log full traceback so we get file/line information
            logger.exception(f'Error reading file {nct_id}.json: {e}')
            return False
        
        gene_synonym_mapping = self.get_gene_synonym_mapping()
        try:
            # Map to CTML format
            mapped_ctml = ctg.map_nct_to_ctml(trial_data, gene_synonym_mapping)
            
            # Add local trial info if available
            self._add_local_trial_info(mapped_ctml, nct_id)

            # Save CTML file
            destination = self._destination_for(mapped_ctml, ctml_files_path, nct_id)
            tdh.save_to_file(mapped_ctml, destination, nct_id, 'yaml')

            logger.info(f"Successfully mapped and saved {nct_id} to {destination}")
            return True
            
        except Exception as ex:
            logger.exception(f"nct_id: {nct_id} | Unexpected error while mapping: {ex}")
            return False


def main():
    """Simple entry point for testing"""
    manager = TrialMapManager()
    
    # Test mapping all trials
    nct_files_path = 'cache/nct'
    ctml_files_path = config.CTML_MAPPED_PATH
        
    # Ensure directories exist
    os.makedirs(ctml_files_path, exist_ok=True)
    
    if os.path.exists(nct_files_path):
        results = manager.map_all_trials(nct_files_path, ctml_files_path)
        print(f"Mapping completed. Processed: {results['processed']}, Skipped: {results['skipped']}")
    else:
        print(f"NCT files directory not found: {nct_files_path}")


if __name__ == "__main__":
    main()

