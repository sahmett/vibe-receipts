// A shared receipt, read from its link: /r/<data>, where <data> is the receipt as receipts.py --share packs it
// (JSON, raw deflate, base64url). Nothing is stored anywhere: the link is the receipt. Files starting with _
// are not routes.
import { inflateRawSync } from 'node:zlib';

const txt = (v, n) => String(v ?? '').slice(0, n);
const num = v => { const x = Number(v); return Number.isFinite(x) ? x : 0; };
const day = v => /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : '';

// the archive's shape, every field the type the page expects (the same rules as clean() in the board page)
export function clean(r) {
  if (!r || typeof r !== 'object' || !Array.isArray(r.items) || !r.items.length || !r.L || typeof r.L !== 'object') return null;
  const end = day(r.end) || day(r.start); if (!end) return null;
  const start = day(r.start) || end, name = txt(r.name, 80) || 'receipt', L = {};
  ['kind', 'project', 'built', 'period', 'active', 'qty', 'item', 'time', 'value', 'total', 'h', 'm'].forEach(k => L[k] = txt(r.L[k], 40));
  const items = r.items.slice(0, 400).filter(Array.isArray).map(i => [Math.max(0, Math.round(num(i[0]))), txt(i[1], 60), Math.max(0, Math.round(num(i[2])))]);
  return {
    name, built: r.built ? txt(r.built, 60) : null, period: txt(r.period, 80), start, end, items,
    min: Math.round(num(r.min)) || items.reduce((s, i) => s + i[2], 0), prompts: Math.round(num(r.prompts)), commits: Math.round(num(r.commits)),
    estimate: !!r.estimate, value_text: r.value_text ? txt(r.value_text, 30) : null, lang: r.lang === 'tr' ? 'tr' : 'en', L,
  };
}

export function decode(d) {
  if (typeof d !== 'string' || !/^[A-Za-z0-9_-]{8,20000}$/.test(d)) return null;
  try { return clean(JSON.parse(inflateRawSync(Buffer.from(d, 'base64url'), { maxOutputLength: 2e5 }).toString('utf8'))); }
  catch { return null; }
}

export const fmt = (m, L) => `${Math.floor(m / 60)}${L.h || 'h'} ${String(m % 60).padStart(2, '0')}${L.m || 'm'}`;
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// the words around a shared receipt, in the receipt's own language
export const WORDS = {
  tr: { prompts: 'prompt', commits: 'commit', cta: 'Kendi fişini çıkar', measured: "Claude Code prompt'larından ölçüldü.", tokens: 'token değeri' },
  en: { prompts: 'prompts', commits: 'commits', cta: 'Get your own receipt', measured: 'Measured from Claude Code prompts.', tokens: 'in tokens' },
};
export const count = (r, W) => r.estimate ? `${r.commits} ${W.commits}` : `${r.prompts.toLocaleString('en-US')} ${W.prompts}`;
