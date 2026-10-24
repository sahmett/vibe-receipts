// /r/<data>: the site's own page, with the shared receipt's title, description and preview image in its head,
// so a chat app or a social post shows this receipt instead of the site's card. The page itself reads the
// receipt from its address and prints it. A link that does not decode goes to the home page.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { decode, fmt, esc, count, WORDS } from './_receipt.js';

const page = readFileSync(join(process.cwd(), 'index.html'), 'utf8');

export function GET(request) {
  const url = new URL(request.url), d = url.searchParams.get('d') || '', r = decode(d);
  if (!r) return Response.redirect(new URL('/', url), 302);
  const W = WORDS[r.lang], origin = `${url.protocol}//${url.host}`;
  const title = `${r.name} · ${fmt(r.min, r.L)}`;
  const desc = `${fmt(r.min, r.L)} · ${count(r, W)}${r.value_text ? ` · ${r.value_text} ${W.tokens}` : ''}. ${W.measured}`;
  const img = `${origin}/r/${d}/og.png`;
  const tags = `<meta name="description" content="${esc(desc)}">`
    + `<meta property="og:type" content="website"><meta property="og:site_name" content="Slipt"><meta property="og:title" content="${esc(title)}">`
    + `<meta property="og:description" content="${esc(desc)}"><meta property="og:url" content="${esc(`${origin}/r/${d}`)}">`
    + `<meta property="og:image" content="${esc(img)}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">`
    + `<meta property="og:image:alt" content="${esc(`${title}, ${count(r, W)}`)}"><meta name="twitter:card" content="summary_large_image">`
    + `<meta name="twitter:title" content="${esc(title)}"><meta name="twitter:image" content="${esc(img)}">`;
  const html = page.replace(/<!--og-->[\s\S]*?<!--\/og-->/, tags).replace('<title>Slipt</title>', `<title>${esc(title)} · Slipt</title>`);
  // the address is the receipt, so the answer never changes for it
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'public, max-age=300, s-maxage=31536000' } });
}
