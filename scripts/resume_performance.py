"""Batch-scoped, exclusive phase timings and source memoization.

No persistent factual cache: each access fingerprints the actual authority bytes.
Review waiting is reported separately from active processing.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import json
import hashlib
import os
from pathlib import Path
from time import perf_counter

CURRENT = ContextVar('resume_performance', default=None)
PHASES = ('source_loading', 'tailoring', 'document_creation', 'word_pdf_validation',
          'fitting_retries', 'factual_review', 'review_wait', 'tracker_sync')


class Measurements:
    def __init__(self):
        self.started = perf_counter()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.seconds = dict.fromkeys(PHASES, 0.0)
        self.counts = dict.fromkeys(PHASES, 0)
        self.stack = []
        self.sources = {}
        self.memo = {}
        self.resumes = []

    def snapshot(self):
        return dict(self.seconds), dict(self.counts), perf_counter()

    def delta(self, before):
        seconds, counts, started = before
        elapsed = perf_counter() - started
        phases = {key: round(self.seconds[key] - seconds.get(key, 0), 4) for key in self.seconds}
        return {'wall_seconds': round(elapsed, 4),
                'active_seconds': round(elapsed - phases.get('review_wait', 0), 4),
                'review_wait_seconds': phases.get('review_wait', 0), 'phases_seconds': phases,
                'counts': {key: self.counts[key] - counts.get(key, 0) for key in self.counts}}


@contextmanager
def batch():
    if CURRENT.get() is not None:
        yield CURRENT.get()
        return
    token = CURRENT.set(Measurements())
    try:
        yield CURRENT.get()
    finally:
        CURRENT.reset(token)


@contextmanager
def phase(name):
    metrics = CURRENT.get()
    if metrics is None:
        yield
        return
    frame = [perf_counter(), 0.0]
    metrics.stack.append(frame)
    try:
        yield
    finally:
        elapsed = perf_counter() - frame[0]
        metrics.stack.pop()
        metrics.seconds[name] = metrics.seconds.get(name, 0) + elapsed - frame[1]
        metrics.counts[name] = metrics.counts.get(name, 0) + 1
        if metrics.stack:
            metrics.stack[-1][1] += elapsed


def timed(name):
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            with phase(name):
                return function(*args, **kwargs)
        return invoke
    return decorate


def memoized(function):
    """Memoize parsed source data only in a batch and by exact source content."""
    @wraps(function)
    def invoke(*args, **kwargs):
        metrics = CURRENT.get()
        if metrics is None:
            return function(*args, **kwargs)
        import gecko_v2
        arguments = hashlib.sha256(repr((args, sorted(kwargs.items()))).encode()).hexdigest()
        key = (function.__name__, str(gecko_v2.MASTER.resolve()),
               gecko_v2.source_fingerprint(), arguments)
        if key not in metrics.memo:
            metrics.memo[key] = deepcopy(function(*args, **kwargs))
        return deepcopy(metrics.memo[key])
    return invoke


def queue_batch(function):
    @wraps(function)
    def invoke(*args, **kwargs):
        if kwargs.get('dry_run'):
            return function(*args, **kwargs)
        from word_validation_client import word_session
        with batch() as metrics:
            before = metrics.snapshot()
            try:
                with word_session():
                    return function(*args, **kwargs)
            finally:
                payload = {'started_at': metrics.started_at,
                           'totals': metrics.delta(before), 'resumes': metrics.resumes}
                root = Path(__file__).resolve().parents[1]
                target = Path(os.environ.get('GECKO_RESUME_TIMINGS', str(root / 'reports/resume-performance' /
                    (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + f'-{os.getpid()}.json'))))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload, indent=2), encoding='utf-8')
                print('Resume batch timings: ' + json.dumps(payload['totals']), flush=True)
                print('Timing report: ' + str(target), flush=True)
    return invoke
