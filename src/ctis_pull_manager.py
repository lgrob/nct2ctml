"""
CTIS Pull Manager

Pulls paediatric trials from the EU Clinical Trials Information System (CTIS),
the register that replaced EudraCT for new EU/EEA trials in January 2023.

This mirrors src/trial_pull_manager.py but talks to a different API and keeps
its records in a separate cache, so the two registers stay independently
syncable and the provenance of every trial is obvious.

The CTIS public API is undocumented but open (no authentication):

    POST {base}/search           paginated summaries; searchCriteria accepts
                                 `containAll` free text and `ageGroupCode`
    GET  {base}/retrieve/{ct}    full protocol record (~30 KB JSON)

Note on scope: Switzerland is not an EU/EEA member and therefore has no
presence in CTIS. These are trials a Swiss patient might travel for, not
trials recruiting in Switzerland.
"""

import csv
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Set

import requests
from loguru import logger

import src.trial_config as config
import src.trial_data_helper as tdh


class CtisPullManager:
    """Manager for pulling and syncing trials from CTIS."""

    # Seconds to wait between full-record retrievals, to stay polite to a
    # public API that publishes no rate limit.
    RETRIEVE_DELAY_SECONDS = 0.2

    STATUS_FIELDNAMES = [
        'ct_number', 'nct_id', 'status', 'countries',
        'trial_last_updated_date', 'entry_last_updated_date',
    ]

    def __init__(self, nct_cache_dir: str = "cache/nct"):
        self.api_base_url = "https://euclinicaltrials.eu/ctis-public-api"
        self.cache_dir = "cache/ctis"
        self.status_file = os.path.join(self.cache_dir, "ctis_status.csv")
        self.nct_cache_dir = nct_cache_dir
        self.conditions = config.ctis_conditions
        self.age_group_codes = config.ctis_age_group_codes
        self.open_statuses = {s.lower() for s in config.ctis_open_statuses}

        os.makedirs(self.cache_dir, exist_ok=True)
        self._ensure_status_file()

    # -- status file ------------------------------------------------------

    def _ensure_status_file(self):
        if not os.path.exists(self.status_file):
            with open(self.status_file, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(self.STATUS_FIELDNAMES)
            logger.info(f"Created new {self.status_file}")

    def get_existing_ct_numbers(self) -> Set[str]:
        found = set()
        if os.path.exists(self.status_file):
            with open(self.status_file, 'r', newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    if row.get('ct_number'):
                        found.add(row['ct_number'])
        return found

    def get_trial_from_status_file(self, ct_number: str) -> Dict:
        if not os.path.exists(self.status_file):
            return None
        with open(self.status_file, 'r', newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('ct_number') == ct_number:
                    return row
        return None

    def modify_status_file(self, ct_number: str, nct_id: str, status: str,
                           countries: str, last_update_date: str, action: str):
        """Insert or update one row in ctis_status.csv."""
        today = datetime.now().strftime('%Y-%m-%d')

        if action == 'insert':
            with open(self.status_file, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(
                    [ct_number, nct_id, status, countries, last_update_date, today]
                )
            logger.info(f"Inserted CTIS trial {ct_number} with status {status}")
            return

        rows, updated = [], False
        with open(self.status_file, 'r', newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['ct_number'] == ct_number:
                    if nct_id:
                        row['nct_id'] = nct_id
                    if status:
                        row['status'] = status
                    if countries:
                        row['countries'] = countries
                    if last_update_date:
                        row['trial_last_updated_date'] = last_update_date
                    row['entry_last_updated_date'] = today
                    updated = True
                rows.append(row)

        if updated:
            with open(self.status_file, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=self.STATUS_FIELDNAMES)
                w.writeheader()
                w.writerows(rows)
            logger.info(f"Updated CTIS trial {ct_number} | status={status}")
        else:
            logger.warning(f"{ct_number} not found in {self.status_file}; nothing updated")

    # -- API --------------------------------------------------------------

    def search_trials(self) -> Dict[str, Dict]:
        """
        Search CTIS for every configured condition term and return the union,
        keyed by CT number.

        CTIS has no structured condition coding, so one request per term is
        the only way to get reasonable recall; overlap between terms is
        expected and de-duplicated here.
        """
        found: Dict[str, Dict] = {}

        for term in self.conditions:
            page = 1
            while True:
                payload = {
                    "pagination": {"page": page, "size": 100},
                    "searchCriteria": {
                        "containAll": term,
                        "ageGroupCode": self.age_group_codes,
                    },
                    "sort": {"property": "decisionDate", "direction": "DESC"},
                }
                try:
                    resp = requests.post(
                        f"{self.api_base_url}/search",
                        json=payload,
                        headers={'Content-Type': 'application/json'},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    body = resp.json()
                except requests.RequestException as e:
                    logger.error(f"CTIS search failed for {term!r} page {page}: {e}")
                    break
                except ValueError as e:
                    logger.error(f"CTIS search returned non-JSON for {term!r}: {e}")
                    break

                batch = body.get('data', []) or []
                for record in batch:
                    ct_number = record.get('ctNumber')
                    if ct_number:
                        found[ct_number] = record

                pagination = body.get('pagination', {}) or {}
                logger.info(
                    f"CTIS search {term!r} page {page}/{pagination.get('totalPages','?')} "
                    f"-> {len(batch)} records ({len(found)} unique so far)"
                )
                if not pagination.get('nextPage'):
                    break
                page += 1

        logger.info(f"CTIS search found {len(found)} unique paediatric trials")
        return found

    def fetch_and_cache_trial(self, ct_number: str) -> Dict:
        """Retrieve the full CTIS record and cache it. Returns the record, or None."""
        try:
            resp = requests.get(
                f"{self.api_base_url}/retrieve/{ct_number}",
                headers={'Accept': 'application/json'},
                timeout=60,
            )
            resp.raise_for_status()
            record = resp.json()
        except requests.RequestException as e:
            logger.error(f"Error retrieving CTIS trial {ct_number}: {e}")
            return None
        except ValueError as e:
            logger.error(f"CTIS returned non-JSON for {ct_number}: {e}")
            return None

        if not record:
            logger.warning(f"No CTIS record for {ct_number}")
            return None

        # CT numbers contain '/' nowhere, but they do contain '-'; safe as a filename.
        tdh.save_to_file(record, self.cache_dir, ct_number, 'json')
        logger.info(f"Cached CTIS trial {ct_number}")
        return record

    # -- record inspection -------------------------------------------------

    @staticmethod
    def get_member_state_infos(record: dict) -> List[dict]:
        """Per-member-state blocks, which carry the authoritative trial status."""
        parts = tdh.safe_get(record, ['authorizedApplication', 'authorizedPartsII'])
        if not isinstance(parts, list):
            return []
        return [p.get('mscInfo', {}) for p in parts if isinstance(p, dict)]

    def get_ctis_local_status(self, record: dict) -> str:
        """
        'open' if any member state reports a status treated as open, else 'closed'.

        The top-level ctStatus string is too coarse for this - codes 2 through 5
        all report "Authorised" - so the per-member-state status is used instead.
        """
        for msc in self.get_member_state_infos(record):
            status = (msc.get('trialStatus') or '').strip().lower()
            if status in self.open_statuses:
                return 'open'
        return 'closed'

    @staticmethod
    def get_recruiting_countries(record: dict) -> List[str]:
        """Member states where recruitment has actually started."""
        countries = []
        for part in tdh.safe_get(record, ['authorizedApplication', 'authorizedPartsII']) or []:
            if not isinstance(part, dict):
                continue
            msc = part.get('mscInfo', {}) or {}
            if msc.get('hasRecruitmentStarted') and msc.get('mscName'):
                countries.append(msc['mscName'])
        return sorted(set(countries))

    @staticmethod
    def get_referenced_nct_ids(record: dict) -> List[str]:
        """
        Any ClinicalTrials.gov ids mentioned anywhere in the CTIS record.

        CTIS has no dedicated NCT field; cross-registration shows up in
        secondary identifiers and free text, so the whole record is scanned.
        """
        import re
        return sorted(set(re.findall(r'NCT\d{8}', json.dumps(record))))

    def get_cached_nct_ids(self) -> Set[str]:
        """NCT ids already pulled by the ClinicalTrials.gov pipeline."""
        if not os.path.isdir(self.nct_cache_dir):
            return set()
        return {
            f[:-5] for f in os.listdir(self.nct_cache_dir)
            if f.startswith('NCT') and f.endswith('.json')
        }

    @staticmethod
    def get_last_updated(summary: dict) -> str:
        """CTIS reports dates as DD/MM/YYYY; normalise to ISO for comparison."""
        raw = (summary.get('lastUpdated') or '').strip()
        if not raw:
            return ''
        try:
            return datetime.strptime(raw, '%d/%m/%Y').strftime('%Y-%m-%d')
        except ValueError:
            logger.debug(f"Unparseable CTIS lastUpdated {raw!r}")
            return ''

    # -- sync --------------------------------------------------------------

    def sync_trials(self) -> Dict:
        """Search CTIS, then retrieve and cache trials that are new or updated."""
        logger.info("Starting CTIS trial synchronization")

        summaries = self.search_trials()
        existing = self.get_existing_ct_numbers()
        already_in_nct = self.get_cached_nct_ids()

        results = {
            'searched': len(summaries),
            'insertions': 0,
            'updates': 0,
            'skipped': 0,
            'failed': 0,
            'duplicates_of_nct': 0,
        }

        for ct_number, summary in summaries.items():
            last_updated = self.get_last_updated(summary)

            if ct_number in existing:
                prior = self.get_trial_from_status_file(ct_number)
                if prior and last_updated and last_updated <= (prior.get('trial_last_updated_date') or ''):
                    results['skipped'] += 1
                    continue
                action = 'update'
            else:
                action = 'insert'

            record = self.fetch_and_cache_trial(ct_number)
            time.sleep(self.RETRIEVE_DELAY_SECONDS)
            if record is None:
                results['failed'] += 1
                continue

            nct_ids = self.get_referenced_nct_ids(record)
            overlap = [n for n in nct_ids if n in already_in_nct]
            if overlap:
                results['duplicates_of_nct'] += 1
                logger.info(f"{ct_number} is also in the NCT cache as {', '.join(overlap)}")

            self.modify_status_file(
                ct_number=ct_number,
                nct_id='|'.join(nct_ids),
                status=self.get_ctis_local_status(record),
                countries='|'.join(self.get_recruiting_countries(record)),
                last_update_date=last_updated,
                action=action,
            )
            results['insertions' if action == 'insert' else 'updates'] += 1

        logger.info(f"CTIS synchronization completed: {results}")
        return results

    def pull_single_trial(self, ct_number: str) -> bool:
        """Retrieve and cache one CTIS trial by CT number."""
        record = self.fetch_and_cache_trial(ct_number)
        if record is None:
            return False

        nct_ids = self.get_referenced_nct_ids(record)
        status = self.get_ctis_local_status(record)
        countries = self.get_recruiting_countries(record)

        action = 'update' if self.get_trial_from_status_file(ct_number) else 'insert'
        self.modify_status_file(
            ct_number=ct_number,
            nct_id='|'.join(nct_ids),
            status=status,
            countries='|'.join(countries),
            last_update_date='',
            action=action,
        )
        print(f"CTIS trial {ct_number} saved at {self.cache_dir}/{ct_number}.json "
              f"| status={status} | recruiting in: {', '.join(countries) or 'none reported'}"
              + (f" | also on ClinicalTrials.gov as {', '.join(nct_ids)}" if nct_ids else ""))
        return True
