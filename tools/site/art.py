"""The drawings on the site's "Ask Claude" cards (tools/site/art/<n>-default.svg and -hover.svg), made ready to
sit side by side in one page and to move on hover.

Each card shows its default drawing inline. Its ids get the card's key as a prefix (six drawings share one
page), its <title> goes (a tooltip over the card), and the parts that change in the hover drawing get classes
the page's CSS animates: .lift (the drawing rises to the hover position), .hv (the red ambient light and the
board's glow fade in), and one small motion of each card's own (.spark, .feed, .bar, .title, .pop)."""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
CARDS = [('r', '01-receipt'), ('v', '02-phone'), ('b', '03-grid'), ('i', '04-document'), ('w', '05-hours'), ('s', '06-card')]

def _once(s, a, b):
    assert s.count(a) >= 1, a
    return s.replace(a, b, 1)

def card(k, name):
    s = open(os.path.join(HERE, 'art', f'{name}-default.svg'), encoding='utf-8').read()
    s = re.sub(r'<title[^>]*>.*?</title>|<desc[^>]*>.*?</desc>', '', s, flags=re.S)
    s = re.sub(r' (width|height)="\d+"(?= viewBox)', '', s, count=2)
    s = s.replace(' role="img" aria-labelledby="title desc"', ' aria-hidden="true" focusable="false"')
    s = re.sub(r'id="([\w-]+)"', lambda m: f'id="{k}-{m[1]}"', s)
    s = re.sub(r'url\(#([\w-]+)\)', lambda m: f'url(#{k}-{m[1]})', s)
    # the hover drawing's light: a red ambient glow and a slightly lighter tile, faded in over the default ones
    s = _once(s, '</defs>', f'<radialGradient id="{k}-ambientH"><stop stop-color="#ff6551" stop-opacity=".12"/>'
                            f'<stop offset="1" stop-color="#111216" stop-opacity="0"/></radialGradient></defs>')
    s = _once(s, f'fill="url(#{k}-ambient)" />', f'fill="url(#{k}-ambient)" /><g class="hv"><rect x="1" y="1" width="468" height="416" rx="36" '
                                                 f'fill="#fff" fill-opacity=".022"/><rect x="1" y="1" width="468" height="416" rx="36" fill="url(#{k}-ambientH)"/></g>')
    s = _once(s, '<g transform="translate(0 0)">', '<g class="lift">')   # to translate(-7 -13) scale(1.03) on hover
    if k == 'r': s = _once(s, f'<g fill="none" stroke="url(#r-red)"', f'<g class="spark" fill="none" stroke="url(#r-red)"')
    if k == 'v': s = _once(s, '<g filter="url(#v-smallShadow)">', '<g class="feed" filter="url(#v-smallShadow)">')
    if k == 'b':
        s = _once(s, '<rect x="78" y="116"', f'<rect class="hv" x="76" y="116" width="12" height="84" rx="6" fill="#ff5744" opacity=".48" filter="url(#b-glow)"/><rect class="bar" x="78" y="116"')
    if k == 'i':
        s = _once(s, '<g filter="url(#i-smallShadow)">', '<g class="feed" filter="url(#i-smallShadow)">')
        s = _once(s, '<rect x="165" y="107"', '<rect class="title" x="165" y="107"')
    if k == 'w': s = _once(s, '<g filter="url(#w-smallShadow)">', '<g class="feed down" filter="url(#w-smallShadow)">')
    if k == 's':
        s = _once(s, '<circle ', '<circle class="pop" ')
        s = _once(s, '<rect x="109" y="191"', '<g class="feed"><rect x="109" y="191"')
        s = s[:s.rindex('</g></g></svg>')] + '</g></g></g></svg>'
    return s.strip()

def cards():
    return {k: card(k, n) for k, n in CARDS}
