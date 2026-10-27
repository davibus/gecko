"""Keep observed discovery queries separate from inferred job-title matches."""
import sqlite3
from pathlib import Path
from contextlib import closing

DATABASE = Path(__file__).resolve().parent / 'data' / 'query_provenance.sqlite'


def remember(listings, path=DATABASE):
    records = [(row.url, str(row.metadata.get('_query_used_to_find') or '').strip())
               for row in listings]
    records = [(url, query) for url, query in records if url and query]
    if not records:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.execute('CREATE TABLE IF NOT EXISTS queries (url TEXT PRIMARY KEY, query TEXT NOT NULL)')
        con.executemany('INSERT OR IGNORE INTO queries VALUES (?,?)', records)


def query_for_job(job, path=DATABASE):
    if not Path(path).exists():
        return ''
    from normalize import posting_identity
    urls = [job.url, job.canonical_url, job.original_url,
            *(link.get('url', '') for link in job.source_links)]
    aliases = {posting_identity(url) for url in urls if url}
    with closing(sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True)) as con:
        for url in urls:
            row = con.execute('SELECT query FROM queries WHERE url=?', (url,)).fetchone()
            if row:
                return row[0]
        for url, query in con.execute('SELECT url, query FROM queries'):
            if posting_identity(url) in aliases:
                return query
    return ''


def recover_cached_firecrawl_queries(history_path, path=DATABASE):
    """Recover exact queries from saved result pages; never repeat paid requests."""
    import json
    from urllib.parse import urlsplit, parse_qs
    from models import RawListing
    from sources.indeed_search import ResultPage
    records = []
    with closing(sqlite3.connect(f'file:{Path(history_path).as_posix()}?mode=ro', uri=True)) as con:
        for (raw,) in con.execute("SELECT response_json FROM requests WHERE endpoint='scrape' AND status='succeeded' ORDER BY started_at"):
            data = json.loads(raw or '{}').get('data', {})
            metadata = data.get('metadata') or {}
            url = metadata.get('sourceURL') or metadata.get('url') or ''
            parts = urlsplit(url)
            query = parse_qs(parts.query).get('q', [''])[0]
            if parts.hostname not in ('www.indeed.com', 'indeed.com') or parts.path != '/jobs' or not query:
                continue
            page = ResultPage(url)
            page.feed(data.get('rawHtml') or data.get('html') or '')
            records.extend(RawListing('indeed', key, 'https://www.indeed.com/viewjob?jk=' + key,
                                      title, '', metadata={'_query_used_to_find': query})
                           for key, title in page.jobs.items())
        for url, query in con.execute('SELECT c.original_url, q.query FROM candidates c JOIN queries q ON c.query_key=q.query_key ORDER BY c.first_at, q.day'):
            records.append(RawListing('firecrawl', '', url, '', '', metadata={'_query_used_to_find': query}))
    remember(records, path)
    return len(records)
