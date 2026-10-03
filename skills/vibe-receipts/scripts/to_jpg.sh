#!/usr/bin/env bash
# HTML raporu tam sayfa JPEG'e çevirir (retina 2x, alttaki boşluğu kırpar).
# Kullanım: bash to_jpg.sh output/<repo>-rapor.html
# Gereksinim: macOS + Google Chrome, python3 + Pillow (pip3 install pillow)
set -euo pipefail
HTML="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT="${HTML%.html}.jpg"
TMP="${HTML%.html}._full.png"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

"$CHROME" --headless --disable-gpu --hide-scrollbars --no-sandbox \
  --force-device-scale-factor=2 --window-size=980,9000 \
  --screenshot="$TMP" "file://$HTML" 2>/dev/null

python3 - "$TMP" "$OUT" << 'PY'
import sys
from PIL import Image
src,dst=sys.argv[1],sys.argv[2]
im=Image.open(src).convert('RGB'); W,H=im.size; px=im.load()
bg=px[W-1,H-1]
def bgrow(y):
    return all(abs(px[x,y][0]-bg[0])+abs(px[x,y][1]-bg[1])+abs(px[x,y][2]-bg[2])<=24 for x in range(0,W,7))
y=H-1
while y>0 and bgrow(y): y-=1
im.crop((0,0,W,min(H,y+80))).save(dst,'JPEG',quality=92)
print("JPEG:",dst,"->",W,"x",min(H,y+80))
PY

rm -f "$TMP"
