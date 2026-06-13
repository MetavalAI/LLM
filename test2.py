# csv to  json




import csv
import json
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--input", required=True)
parser.add_argument("-o", "--output", required=True)

args = parser.parse_args()

result = []

with open(args.input, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)

    for row in reader:
        synonyms = []

        for value in row.values():
            value = value.strip()
            if value:
                synonyms.append(value)

        if not synonyms:
            continue

        result.append({
            "canonical": synonyms[0],  
            "synonyms": list(dict.fromkeys(synonyms))  
        })

with open(args.output, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"Saved {len(result)} records to {args.output}")


# python test2.py -i "D:\Test\keywords-28.01.2026.csv"
# python test2.py -i "D:\Test\keywords-28.01.2026.csv" -o output.json