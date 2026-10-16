"""Optional Google-auth clock correction using the authenticated token endpoint.

Only service-account JWT timestamps change. The OS clock and job dates do not.
Enabled by the local dashboard to tolerate Windows time drift.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import threading
import time

from google.auth import jwt
from google.oauth2.service_account import Credentials
import requests

_lock = threading.Lock()
_sample = None


def google_timestamp():
    global _sample
    with _lock:
        if _sample is None or time.monotonic() - _sample[1] > 300:
            response = requests.head('https://oauth2.googleapis.com/token', timeout=15,
                                     allow_redirects=False, headers={'Cache-Control': 'no-cache'})
            # HEAD on the token endpoint normally returns 404; its HTTPS Date is usable.
            stamp = parsedate_to_datetime(response.headers['Date']).timestamp()
            if abs(stamp - datetime.now(timezone.utc).timestamp()) > 86400:
                raise RuntimeError('Computer and Google clocks differ by more than a day. Correct Windows time before connecting.')
            _sample = (stamp, time.monotonic())
        return int(_sample[0] + time.monotonic() - _sample[1])


class GoogleClockCredentials(Credentials):
    def _make_authorization_grant_assertion(self):
        stamp = google_timestamp()
        payload = dict(self._additional_claims)
        payload.update(iat=stamp, exp=stamp + 3600, iss=self.service_account_email,
                       aud='https://oauth2.googleapis.com/token', scope=' '.join(self.scopes or ()))
        if self._subject:
            payload['sub'] = self._subject
        return jwt.encode(self.signer, payload)
