"""Short-lived requests, not a second job tracker. No command is requeued."""
import json
import os
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit

PREFIX = 'gecko-main:v1:'


class Redis:
    def __init__(self):
        self.url = os.environ.get('UPSTASH_REDIS_REST_URL', '').rstrip('/')
        self.token = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
        parsed = urlsplit(self.url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.path
                or parsed.query or parsed.fragment or not self.token):
            raise RuntimeError('Connect an Upstash Redis store before using Gecko online.')

    def command(self, *args):
        req = Request(self.url, data=json.dumps(args).encode(), headers={
            'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with build_opener(NoRedirect).open(req, timeout=8) as response:
            result = json.load(response)
        if result.get('error'):
            raise RuntimeError('The temporary request store could not complete this operation.')
        return result.get('result')

    def eval(self, script, keys, *args):
        return self.command('EVAL', script, len(keys), *keys, *args)


ENQUEUE = """
if not redis.call('GET', KEYS[3]) then return 0 end
if redis.call('LLEN', KEYS[1]) >= 100 then return -1 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', 300)
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], 300)
return 1
"""

# A claim is consumed even if the connection drops. Never retry an uncertain edit/run.
CLAIM = """
redis.call('SET', KEYS[2], ARGV[1], 'EX', 45)
for i = 1, 100 do
  local id = redis.call('LPOP', KEYS[1])
  if not id then return nil end
  local key = ARGV[2] .. id
  local raw = redis.call('GET', key)
  if raw then
    local item = cjson.decode(raw)
    if item.state == 'queued' and item.deadline >= tonumber(ARGV[3]) then
      item.state = 'claimed'
      redis.call('SET', key, cjson.encode(item), 'EX', 300)
      return cjson.encode(item)
    end
  end
end
return nil
"""

COMPLETE = """
local raw = redis.call('GET', KEYS[1])
if not raw then return 0 end
local item = cjson.decode(raw)
if item.state == 'done' then return 1 end
if item.state ~= 'claimed' then return 0 end
local result = cjson.decode(ARGV[1])
if result.chunks then
  for i = 0, result.chunks - 1 do
    local chunk = KEYS[1] .. ':chunk:' .. i
    if redis.call('EXISTS', chunk) == 0 then return -1 end
    redis.call('EXPIRE', chunk, 120)
  end
end
item.state = 'done'
item.result = result
redis.call('SET', KEYS[1], cjson.encode(item), 'EX', 120)
return 1
"""

LIMIT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""
