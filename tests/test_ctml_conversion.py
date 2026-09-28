import subprocess

nct_ids = [
    "NCT03093116",
    "NCT04687176",
    "NCT05048797",
    "NCT05094336",
    "NCT05211895",
    "NCT05215340",
    "NCT05261399",
    "NCT05410145",
    "NCT05827016",
    "NCT05894239",
    "NCT05920356",
    "NCT06018337",
    "NCT06055465",
    "NCT06065748",
    "NCT06074588",
    "NCT06151574",
    "NCT06211036",
    "NCT06252649",
    "NCT06333951",
    "NCT06346392",
    "NCT06360354",
    "NCT06393374",
    "NCT06497556",
    "NCT06593522",
]


def test_process_nct_ids():
    print(f"Starting processing of {len(nct_ids)} NCT IDs...")
    # Process each ID sequentially
    for i, nct_id in enumerate(nct_ids, start=1):
        print(f"Processing {i}/{len(nct_ids)}: {nct_id}")

        # Run the command
        result = subprocess.run(
            ["python", "main.py", "map", "--nct_id", nct_id],
            # capture_output=True,
            text=True,
        )

        # Check if successful
        if result.returncode == 0:
            print(f"{nct_id} : Success")
        else:
            print(f"{nct_id} : Failed (error code: {result.returncode})")
    print(f"\nFinished! Processed {len(nct_ids)} NCT IDs.")
