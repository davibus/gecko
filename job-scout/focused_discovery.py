"""Bounded new-job rounds. Workers never publish or share tracker connections.

Existing-job maintenance is deliberately a separate caller operation. A confirmed
publication is the only event that advances the target. Failed verification stops
the round, leaving durable candidate/review evidence with the caller.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED


def reconcile_pending(candidates, *, confirmed, verify, record):
    """Recover successful writes with missing receipts before sizing paid work."""
    for candidate in candidates:
        if candidate['id'] in set(confirmed()):
            continue
        receipt = verify(candidate)
        if receipt and receipt.get('verified'):
            record(candidate, receipt)


def run_round(candidates, *, target, confirmed, identity, known, review,
              publish, checkpoint, status=lambda stage, detail: None,
              max_workers=3, stopped=lambda: False):
    if not 1 <= max_workers <= 3:
        raise ValueError('Independent review concurrency must be 1..3')
    seen = set()
    pending = iter(candidates)
    exhausted = False
    accepted = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        running = {}
        while True:
            remaining = target - len(set(confirmed()))
            while not stopped() and not exhausted and len(running) < min(max_workers, remaining):
                try:
                    candidate = next(pending)
                except StopIteration:
                    exhausted = True
                    break
                key = identity(candidate)
                if not key or key in seen or known(candidate):
                    checkpoint(candidate, 'duplicate', None)
                    continue
                seen.add(key)
                checkpoint(candidate, 'queued', None)
                status('reviews', candidate)
                running[pool.submit(review, candidate)] = candidate
            if not running:
                break
            done, _ = wait(running, timeout=20, return_when=FIRST_COMPLETED)
            if not done:
                status('waiting', len(running))
                continue
            for future in done:
                candidate = running.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    checkpoint(candidate, 'pending', type(exc).__name__ + ': ' + str(exc))
                    continue
                checkpoint(candidate, 'reviewed', result)
                if not result.get('accepted') or stopped():
                    continue
                if len(set(confirmed())) >= target:
                    continue
                # A duplicate may have been published by an earlier completion.
                if known(candidate):
                    checkpoint(candidate, 'duplicate', None)
                    continue
                status('publication', candidate)
                receipt = publish(candidate, result)
                if not receipt or not receipt.get('verified'):
                    checkpoint(candidate, 'publication_pending', receipt)
                    raise RuntimeError('Publication readback unconfirmed; preserving candidate')
                checkpoint(candidate, 'published', receipt)
                accepted.append(receipt)
    status('stopped' if stopped() else 'finished' if len(set(confirmed())) >= target else 'waiting', len(set(confirmed())))
    return accepted
