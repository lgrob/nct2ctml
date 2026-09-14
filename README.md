# nct2ctml

The **nct2ctml** repository is a specialized ETL (Extract, Transform, Load) application for clinical trial data. It provides a CLI interface for pulling and mapping trial data from [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api#extapi) to the Clinical Trial Markup Language ([CTML](https://matchminer.gitbook.io/matchminer/deployment/ctml-and-trial-curation)) schema format.

---

## Workflow
- For the trials present on clinicaltrials.gov:
  1. The trials are pulled and synced automatically via 'pull' command. The trials are saved in `cache\nct` directory.
  2. Once pulled, they are converted to CTML format via 'map' command. The CTML files are saved in `cache\ctml` directory.
  3. Once mapped, manual review is encouraged to verify that the AI generated diagnosis and match criteria is correct. Once reviewed, the files are saved in `ctml\reviewed` directory.
  4. Further, they are converted to json and placed under `ctml/json` directory for matchminer-admin workflow to pick up and inserted to matchminer DB.

- For local trials, not present on any international trial repository,
  1. A CTML file is generated manually and placed in `ctml/pending` directory.
  2. A manual review is done to make sure that the captured information is correct and post-verification, file is saved in `ctml\reviewed` directory.
  3. Further, they are converted to json and placed under `ctml/json` directory for matchminer-admin workflow to pick up and inserted to matchminer DB.
  4. For manual creation or editing of CTML files, please refer to the guide at [`doc/trial_creation_guide.md`](doc/trial_creation_guide.md).

> **Detailed workflows:**
> For detailed steps please visit https://miro.com/app/board/uXjVJcuSvUY=/, and follow the steps under 'Manual workflow' section and 'Automated Workflow' section.
---

For detailed information about the system architecture and component relationships, see:
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/sumedhasaxena/nct2ctml)

---

## Quick Start

### Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/sumedhasaxena/nct2ctml.git
   cd nct2ctml
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Usage

Run the CLI from the project root:

```bash
python main.py [-h] {pull,map} ...
```

### Commands

#### Pull NCT study data
- Pull all studies:
  ```bash
  python main.py pull --all
  ```
- Pull a specific study:
  ```bash
  python main.py pull --nct_id NCT_ID
  ```

#### Map NCT IDs to CTML
- Map all NCT files (uses config default cutoff):
  ```bash
  python main.py map --all
  ```
- Map all NCT files with custom cutoff days:
  ```bash
  python main.py map --all --cutoff-days 14
  ```
- Map a specific NCT ID:
  ```bash
  python main.py map --nct_id NCT_ID
  ```

### Configuration

The mapping cutoff is configurable in `config.py`:
```python
MAPPING_CUTOFF_DAYS = 1  # Default: 1 day
```

This determines how far back to look for updated trials when using `map --all`. Trials with `entry_last_updated_date` within the cutoff period will be processed.

---

## Shell script

Instead of running individual commands, sync_trials.sh can be used for running the full automated workflow.
The script will:
1. Ensure correct conda environment is created with required dependencies. 
2. Run `python main.py pull --all`
3. Run `python main.py map --all`

```bash
# Make executable
chmod +x sync_trials.sh

./sync_trials.sh

```

## Running Tests

- **Run all tests:**
  ```bash
  python -m unittest discover -s tests -v
  ```
- **Run a specific test:**
  ```bash
  python -m unittest tests.test_ai_helper.TestAITasks.test_get_genomic_criteria -v
  ```

## Citation

If you use nct2ctml, please cite:

Sumedha Saxena, Edmond S K Ma, Aya El Helali, David J H Shih. AI-assisted patient matching for
personalized cancer medicine. Briefings in Bioinformatics.
2025;26(Supplement_1):i12–i14. https://doi.org/10.1093/bib/bbaf631.013

```bibtex
@article{saxena2025nct2ctml,
  title   = {AI-assisted patient matching for personalized cancer medicine},
  author  = {Saxena, Sumedha and Ma, Edmond S K and El Helali, Aya and Shih, David J H},
  journal = {Briefings in Bioinformatics},
  volume  = {26},
  number  = {Supplement_1},
  pages   = {i12--i14},
  year    = {2025},
  doi     = {10.1093/bib/bbaf631.013},
  url     = {https://academic.oup.com/bib/article/26/Supplement_1/i12/8378037}
}
```

## License
This project's source code is licensed under the Apache License 2.0.
See [LICENSE](LICENSE).


## Resources
- [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api#extapi)
- [MatchMiner CTML](https://matchminer.gitbook.io/matchminer/deployment/ctml-and-trial-curation)
- [Oncotree (oncotree_2021_11_02)](https://oncotree.mskcc.org/?version=oncotree_2021_11_02&field=NAME)
- [COSMIC Cancer Gene Census](https://cancer.sanger.ac.uk/census)
- [Manual CTML Curation Guide](doc/trial_creation_guide.md)
