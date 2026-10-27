from pathlib import Path
root=Path(__file__).resolve().parents[1]
for source,target in [(root/'work/prepared_location_evidence.py',root/'job-scout/location_evidence.py'),
                      (root/'reports/discovery/recovery-20261025/country-regions.json',root/'job-scout/country-regions.json')]:
    if target.exists():raise RuntimeError('Refusing to overwrite existing '+str(target))
    target.write_bytes(source.read_bytes())
print('Installed audited eligibility helpers')
