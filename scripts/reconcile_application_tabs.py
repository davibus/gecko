"""Archive/verify and consolidate Gecko-owned tabs. Never fill or submit jobs."""
import argparse
from pathlib import Path
import json
from playwright.sync_api import sync_playwright
from application_browser import SingleApplicationTab, recovery_archiver
from application_runtime import ROOT, TrackerClient, batch_lock, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--cdp', default='http://127.0.0.1:9333')
    parser.add_argument('--consolidate', action='store_true')
    args = parser.parse_args()
    base = args.evidence_dir.resolve()
    if base.parent != (ROOT/'reports/playwright-pilot').resolve():
        parser.error('Use an existing application evidence directory')
    if not base.is_dir() or not (base/'selected.json').is_file():
        parser.error('Existing selected-job checkpoints required')
    if args.cdp != 'http://127.0.0.1:9333':
        parser.error('Use the dedicated Gecko Chrome endpoint')
    with batch_lock(ROOT/'reports/playwright-pilot/sequential.lock'), batch_lock(base/'batch.lock'):
        tracker = TrackerClient() if args.consolidate else None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(args.cdp)
                if len(browser.contexts) != 1:
                    raise RuntimeError('Ambiguous dedicated browser context')
                ref = []
                manager = SingleApplicationTab(browser.contexts[0], base,
                    recovery_archiver(base, tracker, ref))
                ref.append(manager)
                def inventory():
                    return [{k: v for k, v in p.items() if k != 'page'} for p in manager.inventory()]
                before = inventory()
                save(base/'tab-consolidation-before.json', before)
                print(json.dumps({'before': before}), flush=True)
                if args.consolidate:
                    try:
                        manager.reconcile(archive_all=True)
                        verified = manager.verify('live consolidation complete')
                        after = inventory()
                        original_unowned = {p['target'] for p in before if not p['owned']}
                        if not original_unowned <= {p['target'] for p in after}:
                            raise RuntimeError('An unrelated target is missing from readback')
                        result = dict(before=before, after=after, verified=verified,
                                      unrelated_targets_preserved=True, applications_restarted=False,
                                      submissions_performed=0)
                        save(base/'tab-consolidation-verified.json', result)
                        print(json.dumps(result), flush=True)
                    finally:
                        manager.detach()
        finally:
            if tracker:
                tracker.close()


if __name__ == '__main__':
    main()
