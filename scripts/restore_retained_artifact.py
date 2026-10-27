"""Explicit restore of registered evidence to a new path outside the checkout."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'job-scout'))
from retained_artifacts import entries,key,restore,ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('original',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        raise ValueError('Restore outside the checkout; never replace an active database')
    item=entries()[key(args.original)]
    print(restore(item,args.output))


if __name__=='__main__':main()
