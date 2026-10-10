import json
from collections import Counter

with open('d:\\Download\\final_places_combined.json', encoding='utf-8') as f:
    data = json.load(f)

titles = [place.get('title') for place in data if 'title' in place]
counter = Counter(titles)

duplicates = {title: count for title, count in counter.items() if count > 1}

if duplicates:
    print("Duplicated titles found:")
    for title, count in duplicates.items():
        print(f'"{title}": {count} times')
else:
    print("No duplicated titles found.")