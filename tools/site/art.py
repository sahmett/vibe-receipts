"""The drawings on the site's "Ask Claude" cards (tools/site/art/<n>-default.svg and -hover.svg), made ready to
sit side by side in one page and to move on hover.

Each card shows its default drawing inline. Its ids get the card's key as a prefix (six drawings share one
page), its <title> goes (a tooltip over the card), and the parts that change in the hover drawing get classes
the page's CSS animates: .lift (the drawing rises to the hover position), .hv (the red ambient light and the
board's glow fade in), and one small motion of each card's own (.spark, .feed, .bar, .title, .pop).

Every colour is tied to the site's own tokens, so the drawings match the page in both themes: greys become a
mix of --fg into --panel (or --bg below it) at the same brightness, papers a mix of --paper and --ink, reds a
tint or shade of --accent, and shadows scale with --art-shade."""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
CARDS = [('r', '01-receipt'), ('v', '02-phone'), ('b', '03-grid'), ('i', '04-document'), ('w', '05-hours'), ('s', '06-card')]

def _rgb(h): return [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]

def _pct(x): return f'{max(0, min(100, round(x * 100)))}%'

def token(h):
    """A drawing's colour as the site's tokens, keeping its brightness (in the dark theme the page starts in)."""
    r, g, b = _rgb(h); v = (r + g + b) / 3
    if r - max(g, b) > .28:                                    # a red: --accent (#FF4A3D, brightness .51), lighter or darker
        return (f'color-mix(in srgb,var(--accent) {_pct((1 - v) / .49)},#fff)' if v > .51
                else f'color-mix(in srgb,var(--accent) {_pct(v / .51)},#000)')
    if v > .6:                                                 # a paper: --paper (#f6f6f4, .962) toward --ink (#0b0b0c, .044)
        return f'color-mix(in srgb,var(--art-paper,var(--paper)) {_pct((v - .044) / .918)},var(--ink))'
    if v < .067:                                               # darker than the panel: toward the page's own background
        return f'color-mix(in srgb,var(--bg) {_pct((.067 - v) / .032)},var(--panel))'
    return f'color-mix(in srgb,var(--fg) {_pct((v - .067) / .89)},var(--panel))'   # a grey between --panel and --fg

def themed(s):
    """Colour attributes to style properties on the tokens (attributes cannot hold var())."""
    def tag(m):
        t = m[0]; props = []
        def take(a):
            nonlocal t
            x = re.search(rf' {a}="(#[0-9a-fA-F]{{6}})"', t)
            if x: props.append(f'{a}:{token(x[1])}'); t = t.replace(x[0], '')
        for a in ('stop-color', 'fill', 'stroke'): take(a)
        if t.startswith('<feDropShadow'):                      # shadows: as dark as the theme wants
            o = re.search(r' flood-opacity="([\d.]+)"', t)
            props.append(f'flood-opacity:calc(var(--art-shade,1) * {o[1] if o else 1})')
            if o: t = t.replace(o[0], '')
        if not props: return t
        end = '/>' if t.endswith('/>') else '>'
        return t[:-len(end)].rstrip() + f' style="{";".join(props)}"' + end
    return re.sub(r'<[^!][^>]*>', tag, s)

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
                                                 f'style="fill:var(--fg)" fill-opacity=".03"/><rect x="1" y="1" width="468" height="416" rx="36" fill="url(#{k}-ambientH)"/></g>')
    s = _once(s, '<g transform="translate(0 0)">', '<g class="lift">')
    s = re.sub(rf'(<linearGradient id="{k}-ink"[^>]*>)<stop stop-color="#[0-9a-f]+"/><stop offset="1" stop-color="#[0-9a-f]+"/>',
               r'\1<stop style="stop-color:color-mix(in srgb,var(--ink) 90%,var(--art-paper,var(--paper)))"/><stop offset="1" style="stop-color:var(--ink)"/>', s)   # to translate(-7 -13) scale(1.03) on hover
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
    return themed(s).strip()

def cards():
    return {k: card(k, n) for k, n in CARDS}
