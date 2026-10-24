"""Local, one-job Playwright pilot. No OpenClaw, model calls, or tracker writes.

Run with --packet reports/playwright-pilot/<ID>/packet.json. Commands are JSON
files named command-*.json beside the packet; results and screenshots stay there.
The browser stays open until closed by the user or a stop command is received.
"""
import argparse
import hashlib
import json
import pathlib
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temp.replace(path)


def inspect(page):
    return {
        'url': page.url,
        'title': page.title(),
        'links': page.locator('a').evaluate_all('els=>els.map(e=>({text:e.innerText,href:e.href}))'),
        'text': page.locator('body').inner_text()[:24000],
        'fields': page.locator('input,textarea,select,button').evaluate_all('''els => els.map(e => ({
            tag:e.tagName, id:e.id, name:e.name, type:e.type,
            label:[...(e.labels||[])].map(l=>l.innerText).join(' '),
            placeholder:e.getAttribute('placeholder'), text:e.tagName==='BUTTON'?e.innerText:undefined,
            required:e.required, value:e.type==='password'?'<redacted>':e.value,
            checked:e.checked, files:e.files?[...e.files].map(f=>({name:f.name,size:f.size})):undefined,
            options:e.options?[...e.options].map(o=>({value:o.value,text:o.text,selected:o.selected})):undefined
        }))'''),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True, type=pathlib.Path)
    args = parser.parse_args()
    packet_path = args.packet.resolve()
    packet = json.loads(packet_path.read_text(encoding='utf-8-sig'))
    out = packet_path.parent
    resume = pathlib.Path(packet['resume']).resolve()
    assert resume.parent == ROOT / 'output/resumes' and resume.is_file()
    row = packet['row']
    assert str(row.get('Scout ID', row.get('ID', ''))).strip() == str(packet['id'])
    assert row['Company'] == packet['company'] and row['Job Title'] == packet['title']
    assert not str(row.get('Applied', '')).strip(), 'Already applied'
    assert row['Qualifies to Apply?'] == 'Yes', 'Not eligible'
    assert str(row.get('Resume Created', '')).strip().upper() == 'X'
    allowed_host = urlparse(packet['url']).hostname
    allowed_path = urlparse(packet['url']).path.rstrip('/')
    profile = ROOT / '.tools/playwright-profile'
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile), channel='chrome', headless=False)
        page = context.new_page()
        page.set_default_timeout(12000)
        page.goto(packet['url'], wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(2000)
        save(out / 'initial.json', inspect(page))
        with (out / 'audit.jsonl').open('a', encoding='utf-8') as audit:
            while not page.is_closed():
                for command_path in sorted(out.glob('command-*.json')):
                    result_path = command_path.with_name(command_path.stem + '-result.json')
                    if command_path.stem.endswith('-result') or result_path.exists():
                        continue
                    command = json.loads(command_path.read_text(encoding='utf-8-sig'))
                    action = command['action']
                    result = {'action': action, 'job_id': packet['id'],
                              'time': datetime.now(timezone.utc).isoformat()}
                    try:
                        assert urlparse(page.url).hostname == allowed_host, 'Unexpected application host'
                        assert urlparse(page.url).path.rstrip('/') in (
                            allowed_path, allowed_path + '/apply'
                        ), 'Unexpected job identity; refusing to modify another application'
                        if action == 'inspect':
                            pass
                        elif action == 'fill':
                            for field in command['fields']:
                                element = page.locator(field['selector'])
                                assert element.count() == 1, 'Field selector must be unique'
                                kind = field.get('kind', 'text')
                                if kind == 'select':
                                    element.select_option(label=field['value'])
                                elif kind == 'check':
                                    element.set_checked(field['value'])
                                else:
                                    element.fill(field['value'])
                        elif action == 'upload':
                            data = resume.read_bytes()
                            page.locator(command['selector']).set_input_files(str(resume))
                            page.wait_for_timeout(3000)
                            result['resume'] = {'name': resume.name, 'bytes': len(data),
                                                'sha256': hashlib.sha256(data).hexdigest()}
                        elif action == 'click':
                            target = page.locator(command['selector'])
                            assert target.count() == 1
                            info = target.evaluate('(e)=>({type:e.type||null,text:e.innerText,form:!!e.form})')
                            assert info['type'] != 'submit' and not any(
                                x in info['text'].lower() for x in ('submit','finish','send application')
                            ), 'Final submission is excluded from the pilot command interface'
                            target.click()
                            page.wait_for_timeout(1000)
                        elif action == 'stop':
                            save(result_path, dict(result, ok=True))
                            context.close()
                            return
                        else:
                            raise ValueError('Unknown action')
                        result.update(ok=True, page=inspect(page))
                        page.screenshot(path=str(out / (command_path.stem + '.png')), full_page=True)
                    except Exception as exc:
                        result.update(ok=False, error=str(exc))
                    save(result_path, result)
                    audit.write(json.dumps({k:v for k,v in result.items() if k != 'page'})+'\n')
                    audit.flush()
                page.wait_for_timeout(500)


if __name__ == '__main__':
    main()
