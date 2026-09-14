# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

from loguru import logger
import argparse

def main():
    parser = argparse.ArgumentParser(
        description="NCT to CTML: Pull and map clinical trial data from ClinicalTrials.gov to CTML format.",
        epilog="""
Examples:
  # Pull all updated trials from ClinicalTrials.gov, update trial_status.csv and save trial files to cache/nct
  python main.py pull --all
  
  # Pull a specific trial
  python main.py pull --nct_id NCT03997435
  
  # Map all trials updated within cutoff period (uses config default)
  python main.py map --all
  
  # Map all trials updated in last 14 days
  python main.py map --all --cutoff-days 14
  
  # Map a specific trial
  python main.py map --nct_id NCT03997435
  
  # For continuous automation, use sync_trials.sh
  ./sync_trials.sh
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', required=True, metavar='COMMAND')

    # Subparser for 'pull'
    pull_parser = subparsers.add_parser(
        'pull', 
        help='Pull NCT study data from ClinicalTrials.gov',
        description='Download clinical trial data from ClinicalTrials.gov API and cache locally.',
        epilog="""
Examples:
  python main.py pull --all                          # Pull all eligible ClinicalTrials.gov trials
  python main.py pull --all --source ctis            # Pull paediatric trials from EU CTIS
  python main.py pull --all --source all             # Pull from both registries
  python main.py pull --nct_id NCT03997435           # Pull specific ClinicalTrials.gov trial
  python main.py pull --ct_number 2025-522006-21-00  # Pull specific CTIS trial
        """
    )
    pull_group = pull_parser.add_mutually_exclusive_group(required=True)
    
    pull_group.add_argument(
        '--all', 
        action='store_true', 
        help='Pull all eligible trials after comparing status and last updated date as stored in trial_status.csv'
    )    
    pull_group.add_argument(
        '--nct_id', 
        type=str, 
        metavar='NCT_ID',
        help='Pull study data for a specific NCT ID (e.g., NCT03997435)'
    )
    pull_group.add_argument(
        '--ct_number',
        type=str,
        metavar='CT_NUMBER',
        help='Pull a specific CTIS trial by EU CT number (e.g., 2025-522006-21-00). Implies --source ctis.'
    )

    pull_parser.add_argument(
        '--source',
        choices=['nct', 'ctis', 'all'],
        default='nct',
        help="Registry to pull from with --all: 'nct' (ClinicalTrials.gov, default), "
             "'ctis' (EU Clinical Trials Information System), or 'all' for both."
    )

    # Subparser for 'map'
    map_parser = subparsers.add_parser(
        'map', 
        help='Map NCT trial data to CTML schema format, including local trial infomation, if any',
        description='Convert downloaded NCT trial data to Clinical Trial Markup Language (CTML) format for MatchMiner.',
        epilog="""
Examples:
  python main.py map --all                           # Map all eligible trials (uses config default)
  python main.py map --all --cutoff-days 14          # Map trials updated in last 14 days
  python main.py map --nct_id NCT03997435            # Map specific trial
        """
    )
    map_group = map_parser.add_mutually_exclusive_group(required=True)
    
    map_group.add_argument(
        '--all', 
        action='store_true', 
        help='Map all eligible NCT files based on last update date in trial_status.csv'
    )
    map_group.add_argument(
        '--nct_id', 
        type=str, 
        metavar='NCT_ID',
        help='Map a specific NCT ID to CTML format'
    )
    map_group.add_argument(
        '--ct_number',
        type=str,
        metavar='CT_NUMBER',
        help='Map a specific CTIS trial number (EU registry) to CTML format'
    )
    
    map_parser.add_argument(
        '--test_mode',
        nargs='?',
        const=True,
        default=False,
        metavar='TEST_MODE',
        help='Enable test mode for mapping (e.g., map a small subset of trials for testing purposes). Use --test_mode or --test_mode true/false.'
    )
    
    map_parser.add_argument(
        '--source',
        choices=['nct', 'ctis'],
        default='nct',
        help="Which registry to map from when using --all (default: nct)."
    )

    # Add cutoff days option for map --all
    map_parser.add_argument(
        '--cutoff-days', 
        type=int, 
        metavar='DAYS',
        help='Only with --all. Map trials updated in the last DAYS; overrides MAPPING_CUTOFF_DAYS in the config.'
    )

    args = parser.parse_args()

    nct_files_path = 'cache/nct'
    ctis_files_path = 'cache/ctis'    

    if args.command == 'pull':
        if args.all:
            if args.source in ('nct', 'all'):
                pull_all()
            if args.source in ('ctis', 'all'):
                pull_all_ctis()
        elif args.ct_number:
            pull_ctis(args.ct_number)
        else:
            pull_nct(args.nct_id)

    elif args.command == 'map':
        # Handle test_mode: convert string to bool if needed
        test_mode = args.test_mode
        if isinstance(test_mode, str):
            test_mode = test_mode.lower() in ('true', '1', 'yes')
        
        if test_mode:
            ctml_files_path = "cache/ctml_test/20260428/gemma4_31B"
        else:
            ctml_files_path = "cache/ctml/"
        if args.all:
            if args.source == 'ctis':
                map_all_ctis(ctis_files_path, ctml_files_path, args)
            else:
                map_all(nct_files_path, ctml_files_path, args)
        elif args.ct_number:
            map_ctis(args.ct_number, ctis_files_path, ctml_files_path)
        else:
            map_nct(args.nct_id, nct_files_path, ctml_files_path)

def map_ctis(ct_number, ctis_files_path, ctml_files_path):
    """Map one CTIS trial to CTML."""
    from src.trial_map_manager import TrialMapManager
    manager = TrialMapManager()
    ok = manager.map_single_ctis_trial(ct_number, ctis_files_path, ctml_files_path)
    print(f"{ct_number}: {'mapped' if ok else 'FAILED'}")


def map_all_ctis(ctis_files_path, ctml_files_path, args):
    """Map every cached CTIS trial to CTML."""
    import os
    from src.trial_map_manager import TrialMapManager
    manager = TrialMapManager()
    numbers = sorted(f[:-5] for f in os.listdir(ctis_files_path) if f.endswith('.json'))
    done = failed = 0
    for n, ct in enumerate(numbers, 1):
        ok = manager.map_single_ctis_trial(ct, ctis_files_path, ctml_files_path)
        done, failed = done + bool(ok), failed + (not ok)
        print(f"  [{n}/{len(numbers)}] {ct}: {'ok' if ok else 'FAILED'}")
    print(f"\nmapped {done}, failed {failed}")


def pull_all():
    """Trial synchronization implementation"""
    from src.trial_pull_manager import TrialPullManager
    
    try:
        sync = TrialPullManager()
        results = sync.sync_trials()
        print("Trial synchronization completed successfully!")
        print(f"Processed {results['api_trials_processed']} trials from API")
        print(f"Inserted {results['insertions']} new trials")
        print(f"Updated {results['updates']} existing trials")
        print(f"Closed {results['closures']} trials")
        print(f"Merged {results['local_trials_merged']} local trials")
    except Exception as e:
        logger.error(f"Error in pull_all: {e}")
        raise

def pull_nct(nct_id):
    from src.trial_pull_manager import TrialPullManager
    sync = TrialPullManager()
    sync.pull_single_trial(nct_id)

def pull_all_ctis():
    """Pull paediatric trials from the EU CTIS register"""
    from src.ctis_pull_manager import CtisPullManager

    try:
        sync = CtisPullManager()
        results = sync.sync_trials()
        print("CTIS synchronization completed successfully!")
        print(f"Searched {results['searched']} unique trials from CTIS")
        print(f"Inserted {results['insertions']} new trials")
        print(f"Updated {results['updates']} existing trials")
        print(f"Skipped {results['skipped']} unchanged trials")
        print(f"Failed {results['failed']} retrievals")
        print(f"Of these, {results['duplicates_of_nct']} are also in the ClinicalTrials.gov cache")
    except Exception as e:
        logger.error(f"Error in pull_all_ctis: {e}")
        raise

def pull_ctis(ct_number):
    from src.ctis_pull_manager import CtisPullManager
    CtisPullManager().pull_single_trial(ct_number)

def map_all(nct_files_path, ctml_files_path, args):
    """Map all NCT files to CTML format"""
    from src.trial_map_manager import TrialMapManager
    
    try:
        manager = TrialMapManager()
        # Get cutoff_days from command line args if provided
        cutoff_days = getattr(args, 'cutoff_days', None)
        results = manager.map_all_trials(nct_files_path, ctml_files_path, cutoff_days)
        logger.info(f"Mapping completed. Processed: {results['processed']}, Skipped: {results['skipped']}")
    except Exception as e:
        logger.error(f"Error in map_all: {e}")
        raise

def map_nct(nct_id, nct_files_path, ctml_files_path):
    """Map a specific NCT ID to CTML format"""
    from src.trial_map_manager import TrialMapManager
    
    try:
        manager = TrialMapManager()
        success = manager.map_single_trial(nct_id, nct_files_path, ctml_files_path)
        if success:
            logger.info(f"Successfully mapped {nct_id}")
        else:
            logger.error(f"Failed to map {nct_id}")
    except Exception as e:
        logger.error(f"Error in map_nct: {e}")
        raise

if __name__ == "__main__":
    logger.add('logs/nct2ctml.log', rotation = '1 MB', encoding="utf-8", format="{time} {level} - Line: {line} - {message}", level="INFO")
    main()