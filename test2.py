# csv to  json

import csv
import json
import argparse


def csv_to_json(input_file, output_file):
    result = []

    with open(input_file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)

        for row_number, row in enumerate(reader, start=1):

            values = []

            for cell in row:
                cell = str(cell).strip()

                if cell:
                    values.append(cell)

            if not values:
                continue

            synonyms = list(dict.fromkeys(values))

            result.append(
                {
                    "canonical": synonyms[0],
                    "synonyms": synonyms
                }
            )

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n save kr diye h, {len(result)} entries mile h or ab, iss file me: {output_file} save kr di h.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="csv se json me convert karo (ye sirf iss particualr csv ke iye bna h).")

    parser.add_argument("-i", "--input", required=True, help="csv ka file path de yha pa")

    parser.add_argument("-o", "--output", default="output.json", help="json output file ka path de yha pe")

    args = parser.parse_args()

    csv_to_json(args.input, args.output)


# python test2.py -i "D:\Test\keywords-28.01.2026.csv"
# python test2.py -i "D:\Test\keywords-28.01.2026.csv" -o "output.json"
# python -m py_compile test2.py