import csv
import sys
from collections import defaultdict

path, group_col, sum_col = sys.argv[1:4]
totals = defaultdict(int)
with open(path, newline="") as fh:
    for row in csv.DictReader(fh):
        totals[row[group_col]] += int(row[sum_col])
for group in sorted(totals):
    print(f"{group},{totals[group]}")
