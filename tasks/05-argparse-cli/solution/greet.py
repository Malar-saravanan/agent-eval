import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--name", default="World")
parser.add_argument("--times", type=int, default=1)
args = parser.parse_args()
for _ in range(args.times):
    print(f"Hello, {args.name}!")
