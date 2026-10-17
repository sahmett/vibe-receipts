#!/usr/bin/env python3
"""Builds the public Slipt site: the same page as --board, with example receipts in Turkish and English, the
install steps under the printer, a language switch and Open Graph tags.

  python3 tools/site/build.py OUT_DIR [--url https://slipt-phi.vercel.app]

Writes OUT_DIR/index.html and OUT_DIR/og.png (copied from og.png here; og.html is its source)."""
import argparse, importlib.util, os, shutil, sys, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import example  # noqa: E402

spec = importlib.util.spec_from_file_location('receipts', os.path.join(ROOT, 'skills', 'vibe-receipts', 'scripts', 'receipts.py'))
receipts = importlib.util.module_from_spec(spec); spec.loader.exec_module(receipts)

ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><linearGradient id="r" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#FF6A4D"/><stop offset="1" stop-color="#E0262C"/></linearGradient><clipPath id="c"><rect width="32" height="32" rx="9"/></clipPath></defs>'
        '<g clip-path="url(#c)"><rect width="32" height="32" fill="url(#r)"/><path d="M0 19.6 3.2 16.6 6.4 19.6 9.6 16.6 12.8 19.6 16 16.6 19.2 19.6 22.4 16.6 25.6 19.6 28.8 16.6 32 19.6V32H0Z" fill="#F4F0E8"/></g></svg>')


def head(url):
    e = lambda s: s.replace('&', '&amp;').replace('"', '&quot;')
    title, desc = 'Slipt · Çalıştığın saatin fişi', "Claude Code'daki kendi prompt aralıklarından ölçülür. Yerelde kalır."
    return (f'<meta name="description" content="{e(desc)}">'
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="Slipt"><meta property="og:title" content="{e(title)}">'
            f'<meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{url}/">'
            f'<meta property="og:image" content="{url}/og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
            f'<meta property="og:image:alt" content="Slipt: Çalıştığın saatin fişi."><meta name="twitter:card" content="summary_large_image">'
            f'<meta name="twitter:title" content="{e(title)}"><meta name="twitter:image" content="{url}/og.png">'
            f'<link rel="icon" href="data:image/svg+xml,{urllib.parse.quote(ICON)}">')


def main():
    ap = argparse.ArgumentParser(description='Build the public Slipt site')
    ap.add_argument('out'); ap.add_argument('--url', default='https://slipt-phi.vercel.app')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    site = dict(github='https://github.com/sahmett/vibe-receipts', today=example.TODAY,
                receipts={'tr': example.receipts('tr'), 'en': example.receipts('en')})
    page = receipts.board_page(site['receipts']['tr'], 'tr', site=site, head=head(a.url.rstrip('/')))
    with open(os.path.join(a.out, 'index.html'), 'w', encoding='utf-8') as f: f.write(page)
    shutil.copyfile(os.path.join(HERE, 'og.png'), os.path.join(a.out, 'og.png'))
    print('wrote', os.path.join(a.out, 'index.html'), 'and og.png')


if __name__ == '__main__':
    main()
