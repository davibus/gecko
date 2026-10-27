"""Register verified private Google Drive upload receipts; never upload or share."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'job-scout'))
import resume_delivery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True,
                        help='JSON with path, metadata from connector readback, and download.sha256')
    args = parser.parse_args()
    receipts = json.loads(args.receipt.read_text(encoding='utf-8'))
    if isinstance(receipts, dict):
        receipts = [receipts]
    from run_gecko import run_lock
    with run_lock():
        for receipt in receipts:
            print(resume_delivery.register(receipt['path'], receipt['metadata'], receipt['download']['sha256']))


if __name__ == '__main__':
    main()
