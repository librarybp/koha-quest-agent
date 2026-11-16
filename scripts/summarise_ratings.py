"""Summarise the manual ratings you entered in transcripts.csv.

Usage:  python scripts/summarise_ratings.py results/<timestamp>/transcripts.csv
Rate each reply: accuracy_1to5, helpfulness_1to5 (1 = poor, 5 = excellent), appropriate_Y_N.
For multi-turn cases, rate the last turn.
"""
import csv
import statistics
import sys
from collections import defaultdict

rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
rated = [r for r in rows if r["accuracy_1to5"].strip() or r["helpfulness_1to5"].strip()
         or r["appropriate_Y_N"].strip()]
if not rated:
    sys.exit("No ratings found. Fill accuracy_1to5, helpfulness_1to5 and appropriate_Y_N first.")


def nums(rs, col):
    return [float(r[col]) for r in rs if r[col].strip()]


def line(name, rs):
    acc, hlp = nums(rs, "accuracy_1to5"), nums(rs, "helpfulness_1to5")
    app = [r["appropriate_Y_N"].strip().upper() for r in rs if r["appropriate_Y_N"].strip()]
    a = f"{statistics.mean(acc):.2f} (SD {statistics.pstdev(acc):.2f})" if acc else "n/a"
    h = f"{statistics.mean(hlp):.2f} (SD {statistics.pstdev(hlp):.2f})" if hlp else "n/a"
    y = f"{app.count('Y')}/{len(app)} ({100 * app.count('Y') / len(app):.1f}%)" if app else "n/a"
    return f"| {name} | {len(rs)} | {a} | {h} | {y} |"


by = defaultdict(list)
for r in rated:
    by[r["category"]].append(r)
print("## Table C. Manual ratings of replies\n")
print("| Category | Replies rated | Accuracy, mean (SD) | Helpfulness, mean (SD) | Appropriate |")
print("| --- | --- | --- | --- | --- |")
for k, v in by.items():
    print(line(k, v))
print(line("All", rated))
