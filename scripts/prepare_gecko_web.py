"""Refresh the deployable UI without changing the local dashboard's files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'dashboard/static'
    destination = ROOT / 'web/assets'
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('index.html', 'app.js', 'manual.js', 'match-scores.js', 'filters.js', 'style.css'):
        text = (source / name).read_text(encoding='utf-8')
        if name == 'index.html':
            text = text.replace('<script src="/filters.js"', '<script src="/cloud.js" defer></script><script src="/filters.js"', 1)
        if name == 'app.js':
            text = text.replace('Open resume in Word', 'Download resume')
            text = text.replace('Resume opened in your default Word document app.', 'Resume downloaded. Open the document on this device to review it.')
            text = text.replace('Your local workspace could not be refreshed.', 'Your Gecko workspace could not be refreshed.')
        (destination / name).write_text(text, encoding='utf-8')
    print('Prepared the Gecko Main website assets. Local dashboard files were preserved.')


if __name__ == '__main__':
    main()
