"""Create local-only credentials or pair a deployed HTTPS origin. Never print secrets."""
import argparse
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.parse import urlsplit
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='The final HTTPS website origin, without a path')
    args = parser.parse_args()
    if args.url:
        parsed = urlsplit(args.url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in {'','/'} or parsed.query or parsed.fragment or parsed.username:
            raise SystemExit('Use the final HTTPS website origin, without a path, query, or fragment.')
        public_url = 'https://' + parsed.netloc
    else:
        public_url = ''
    folder = ROOT / '.secrets'
    folder.mkdir(exist_ok=True)
    worker_path = folder/'gecko-web-worker.json'
    env_path = folder/'gecko-web-vercel.env'
    login_path = folder/'gecko-web-signin.txt'
    existing = [path.exists() for path in (worker_path, env_path, login_path)]
    if any(existing) and not all(existing):
        raise SystemExit('Partial online setup exists. Preserve the files and reconcile them before regenerating credentials.')
    if not any(existing):
        password = secrets.token_urlsafe(24)
        bridge = secrets.token_urlsafe(48)
        environment = {
            'GECKO_SESSION_SECRET': secrets.token_urlsafe(48),
            'GECKO_PASSWORD_HASH': generate_password_hash(password, method='scrypt'),
            'GECKO_BRIDGE_SECRET': bridge,
        }
        worker = {'url':public_url, 'secret':bridge}
        login_path.write_text('Gecko Main private website\n\nWorkspace password: '+password+'\n\nKeep this file private. Never paste it into chat, source code, or a Git commit.\n',encoding='utf-8')
    else:
        environment = dict(line.split('=',1) for line in env_path.read_text(encoding='utf-8').splitlines() if line)
        worker = json.loads(worker_path.read_text(encoding='utf-8'))
    if public_url:
        worker['url'] = public_url
        environment['GECKO_PUBLIC_URL'] = public_url
    shortcut = folder/'gecko-web-open.url'
    if worker['url']:
        token = hmac.new(environment['GECKO_SESSION_SECRET'].encode(),
            ('gecko-device-connect-v1:'+worker['url']).encode(),hashlib.sha256).hexdigest()
        shortcut.write_text('[InternetShortcut]\nURL='+worker['url']+'/connect#'+token+'\n',encoding='utf-8')
    worker_path.write_text(json.dumps(worker, indent=2)+'\n',encoding='utf-8')
    env_path.write_text(''.join(key+'='+value+'\n' for key,value in environment.items()),encoding='utf-8')
    if os.name == 'nt':
        for path in (worker_path, env_path, login_path, *([shortcut] if shortcut.exists() else [])):
            subprocess.run(['icacls.exe',str(path),'/inheritance:r','/grant:r',
                            getpass.getuser()+':(F)','SYSTEM:(F)'],check=True,capture_output=True)
    print('Private setup files are ready under .secrets. Existing credentials were preserved.')
    print('Import gecko-web-vercel.env into Vercel. Open gecko-web-open.url once for automatic device access.')
    print('Worker website address is '+('configured.' if worker['url'] else 'pending; run this script with --url after deployment.'))


if __name__ == '__main__':
    main()
