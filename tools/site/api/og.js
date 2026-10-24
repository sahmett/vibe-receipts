// /r/<data>/og.png: the preview card of a shared receipt, 1200 x 630, in the site card's style: the Slipt mark,
// the project and its total time on the left, the receipt itself on the right, running off the card's foot as
// if it were still printing. Drawn from the link alone; nothing is stored.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { ImageResponse } from '@vercel/og';
import { decode, fmt, count, WORDS } from './_receipt.js';

const font = f => readFileSync(join(process.cwd(), 'fonts', f));
const FONTS = [
  { name: 'Geist', data: font('Geist-SemiBold.ttf'), weight: 600, style: 'normal' },
  { name: 'Geist Mono', data: font('GeistMono-Medium.ttf'), weight: 500, style: 'normal' },
  { name: 'Geist Mono', data: font('GeistMono-Bold.ttf'), weight: 700, style: 'normal' },
];
const C = { bg: '#0a0a0c', fg: '#f4f4f5', fg2: '#a1a1a7', fg3: '#5f5f66', paper: '#f4f0e8', ink: '#0b0b0c', ink2: '#6d6d70', red: '#ff4a3d' };
const svg = s => `data:image/svg+xml;base64,${Buffer.from(s).toString('base64')}`;
const MARK = svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><linearGradient id="r" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FF6A4D"/><stop offset="1" stop-color="#E0262C"/></linearGradient><clipPath id="c"><rect width="32" height="32" rx="9"/></clipPath></defs><g clip-path="url(#c)"><rect width="32" height="32" fill="url(#r)"/><path d="M0 19.6 3.2 16.6 6.4 19.6 9.6 16.6 12.8 19.6 16 16.6 19.2 19.6 22.4 16.6 25.6 19.6 28.8 16.6 32 19.6V32H0Z" fill="#F4F0E8"/></g></svg>');
const PW = 372;   // the paper's width
const TEAR = svg(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${PW} 12">${`<path d="M0 12${Array.from({ length: 31 }, (_, i) => ` L${(i + .5) * PW / 31} 0 L${(i + 1) * PW / 31} 12`).join('')}Z" fill="${C.paper}"/>`}</svg>`);
const BARS = (() => {   // a barcode that is the same for every receipt
  let x = 0, d = '', k = 7;
  while (x < 250) { k = (k * 37 + 11) % 97; const w = 1 + k % 4; d += `<rect x="${x}" width="${w}" height="44"/>`; x += w + 1 + (k >> 3) % 3; }
  return svg(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 250 44" fill="${C.ink}">${d}</svg>`);
})();

// a tiny element builder: satori takes React-shaped objects, so no JSX and no build step
const h = (type, style, ...children) => ({ type, props: { style: { display: 'flex', ...style }, children: children.flat().filter(c => c !== null && c !== false && c !== undefined) } });
const img = (src, w, ht, style = {}) => ({ type: 'img', props: { src, width: w, height: ht, style } });
const hr = () => h('div', { height: 0, borderTop: `2px dashed ${C.ink}40`, margin: '14px 0' });
const row = (a, b, style = {}) => h('div', { justifyContent: 'space-between', gap: 16, fontSize: 15, ...style }, h('span', { color: C.ink2 }, a), h('span', { textAlign: 'right' }, b));

function receipt(r) {
  const L = r.L, f = m => fmt(m, L), shown = r.items.slice(0, 7);
  return h('div', { position: 'absolute', right: 92, top: 58, width: PW, flexDirection: 'column', transform: 'rotate(2.2deg)', boxShadow: '0 30px 70px rgba(0,0,0,.6)' },
    img(TEAR, PW, 12),
    h('div', { flexDirection: 'column', background: C.paper, color: C.ink, fontFamily: 'Geist Mono', fontWeight: 500, padding: '20px 26px 160px' },
      h('div', { justifyContent: 'center', fontWeight: 700, fontSize: 25, letterSpacing: 3 }, 'VIBE RECEIPTS'),
      h('div', { justifyContent: 'center', fontSize: 12.5, color: C.ink2, letterSpacing: 3, marginTop: 6 }, L.kind),
      hr(),
      row(L.project, r.name.length > 22 ? r.name.slice(0, 21) + '…' : r.name),
      row(L.period, r.period, { marginTop: 6 }),
      hr(),
      ...shown.map((it, i) => h('div', { fontSize: 14, marginTop: i ? 6 : 0 },
        h('span', { width: 48, color: C.ink2 }, it[0].toLocaleString('en-US')),
        h('span', { flex: 1, overflow: 'hidden', whiteSpace: 'nowrap' }, it[1]),
        h('span', { width: 86, justifyContent: 'flex-end' }, f(it[2])))),
      r.items.length > shown.length ? h('div', { fontSize: 14, marginTop: 6, color: C.ink2 }, `+ ${r.items.length - shown.length}`) : null,
      hr(),
      r.value_text ? row(L.value, r.value_text, { marginBottom: 8 }) : null,
      h('div', { justifyContent: 'space-between', alignItems: 'baseline', fontWeight: 700, fontSize: 30, letterSpacing: -1 }, h('span', {}, L.total), h('span', {}, f(r.min))),
      h('div', { justifyContent: 'center', marginTop: 26 }, img(BARS, 250, 44))));
}

export function GET(request) {
  const r = decode(new URL(request.url).searchParams.get('d') || '');
  if (!r) return new Response('Not a receipt', { status: 404 });
  const W = WORDS[r.lang], L = r.L;
  const card = h('div', { width: 1200, height: 630, position: 'relative', overflow: 'hidden', fontFamily: 'Geist', color: C.fg,
    backgroundColor: C.bg, backgroundImage: 'radial-gradient(70% 90% at 82% 0%, rgba(255,255,255,.05), rgba(255,255,255,0) 60%)' },
    h('div', { position: 'absolute', left: 84, top: 72, bottom: 70, width: 600, flexDirection: 'column' },
      h('div', { alignItems: 'center', gap: 18 }, img(MARK, 60, 60), h('span', { fontSize: 40, fontWeight: 600, letterSpacing: -1.2 }, 'Slipt')),
      h('div', { flex: 1 }),
      h('div', { fontFamily: 'Geist Mono', fontSize: 28, color: C.fg2 }, r.built ? `${r.name} · ${r.built}` : r.name),
      h('div', { fontSize: 136, fontWeight: 600, letterSpacing: -6, lineHeight: 1, marginTop: 14 }, fmt(r.min, L)),
      h('div', { fontFamily: 'Geist Mono', fontSize: 24, color: C.fg3, marginTop: 22 }, count(r, W) + (r.value_text ? ` · ${r.value_text} ${W.tokens}` : '')),
      h('div', { flex: 1 }),
      h('div', { alignItems: 'center', fontFamily: 'Geist Mono', fontSize: 20, color: C.fg2 },
        h('div', { width: 9, height: 9, borderRadius: 9, background: C.red, marginRight: 14, boxShadow: '0 0 0 4px rgba(255,74,61,.18)' }),
        h('span', {}, new URL(request.url).host), h('span', { color: C.fg3, marginLeft: 18 }, `${W.cta} →`))),
    receipt(r));
  return new ImageResponse(card, { width: 1200, height: 630, fonts: FONTS,
    headers: { 'cache-control': 'public, max-age=86400, s-maxage=31536000, immutable' } });
}
