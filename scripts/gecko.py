"""Repository command router. Bare Gecko still uses the existing daily task."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='gecko')
    commands = parser.add_subparsers(dest='command', required=True)
    job = commands.add_parser('job').add_subparsers(dest='job_command', required=True)
    search = job.add_parser('search', help='Unified manual discovery; no resumes or applications')
    mode = search.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Local plan only; no API/database/Sheet writes')
    mode.add_argument('--sync-only', action='store_true', help='Retry publication only; no discovery or enrichment')
    search.add_argument('--db')
    search.add_argument('--preferences')
    search.add_argument('--sources-config')
    search.add_argument('--results', type=int, default=20, help='Existing internal source page size; Firecrawl uses its policy')
    search.add_argument('--publish-as-found', action='store_true')
    search.add_argument('--broad-discovery', action='store_true', help='Explicit paid broad market discovery')
    args = parser.parse_args(argv)
    forwarded = []
    for field in ('db', 'preferences', 'sources_config'):
        if getattr(args, field): forwarded += ['--' + field.replace('_', '-'), getattr(args, field)]
    forwarded += ['search', '--source', 'all', '--unified', '--results', str(args.results)]
    if args.dry_run: forwarded.append('--dry-run')
    if args.sync_only: forwarded.append('--sync-only')
    if args.publish_as_found: forwarded.append('--publish-as-found')
    if args.broad_discovery: forwarded.append('--broad-discovery')
    import scout
    return scout.main(forwarded)


if __name__ == '__main__': raise SystemExit(main())
