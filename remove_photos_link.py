import argparse
import json
import os
from pathlib import Path


def remove_key(obj, key):
    """Recursively remove key from dicts inside obj."""
    if isinstance(obj, dict):
        if key in obj:
            del obj[key]
        for v in obj.values():
            remove_key(v, key)
    elif isinstance(obj, list):
        for item in obj:
            remove_key(item, key)


def process_file(path: Path, key: str):
    try:
        text = path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"Skip (read error): {path} -> {e}")
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"Skip (json error): {path} -> {e}")
        return False

    # check if key exists anywhere
    def contains_key(o):
        if isinstance(o, dict):
            if key in o:
                return True
            return any(contains_key(v) for v in o.values())
        if isinstance(o, list):
            return any(contains_key(i) for i in o)
        return False

    if not contains_key(data):
        return False

    # backup
    bak = path.with_suffix(path.suffix + '.bak')
    try:
        if not bak.exists():
            bak.write_text(text, encoding='utf-8')
    except Exception as e:
        print(f"Warning: could not create backup for {path}: {e}")

    remove_key(data, key)
    try:
        path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        print(f"Failed to write {path}: {e}")
        return False

    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Remove a JSON key from all .json files under a root folder')
    parser.add_argument('-root', required=False, default='.', help='Root directory to scan')
    parser.add_argument('-key', required=False, default='photos_link', help='JSON key name to remove')
    args = parser.parse_args()

    root = Path(args.root).resolve()
    key = args.key

    print(f"Scanning {root} for .json files containing key '{key}'...")

    modified = []
    for path in root.rglob('*.json'):
        # skip node_modules or hidden directories quickly
        if any(part.startswith('.') or part in ('node_modules', '__pycache__') for part in path.parts):
            continue
        ok = process_file(path, key)
        if ok:
            modified.append(str(path))

    print('\nSummary:')
    if modified:
        print(f"Modified {len(modified)} files:")
        for p in modified:
            print(' -', p)
    else:
        print('No files modified.')
