"""Bounded backoff for idempotent Sheets reads when the per-minute quota fills."""
import sys
import time
from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest


class SheetsRequest(HttpRequest):
    def execute(self, http=None, num_retries=0):
        for attempt in range(3):
            try:
                return super().execute(http=http, num_retries=num_retries)
            except HttpError as error:
                if self.method != "GET" or error.resp.status != 429 or attempt == 2:
                    raise
                print("Google Sheets read quota reached; waiting 60 seconds before retry.",
                      file=sys.stderr, flush=True)
                time.sleep(60)
