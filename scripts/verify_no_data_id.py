import json
from pathlib import Path

root = Path('..').resolve()  # scripts folder is under maps-scrapper/scripts when run from repo
root = Path(__file__).resolve().parents[1]

matches = []
for p in root.rglob('*.json'):
    if p.suffix == '.bak':
        continue
    # skip backups explicitly and .bak files
    if p.name.endswith('.bak'):
        continue
    try:
        text = p.read_text(encoding='utf-8')
        if '"data_id"' in text:
            matches.append(str(p))
    except Exception:
        pass

if matches:
    print('Found data_id in these JSON files:')
    for m in matches:
        print(' -', m)
else:
    print('No data_id found in .json files (excluding backups).')
