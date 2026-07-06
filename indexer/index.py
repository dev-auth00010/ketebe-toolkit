#!/usr/bin/env python3
"""
Ketebe Artwork Indexer
Scans ketebe.org and builds a local JSON index of all artwork metadata.

Usage:
    python3 index.py          # build / resume the index
    python3 index.py --serve  # serve the search page after indexing
"""

import html as _html
import json, re, ssl, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import urlopen, Request

# ── Config ────────────────────────────────────────────────────────────────────

ID_START   = 2400
ID_END     = 9200     # upper bound (adjust up if new artworks are added)
WORKERS    = 5        # parallel requests — be polite
SAVE_EVERY = 30       # flush to disk after this many new artworks
OUTPUT     = Path(__file__).parent / "artworks.json"

# ── HTTP ──────────────────────────────────────────────────────────────────────

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode    = ssl.CERT_NONE

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept":     "text/html",
}

def fetch(url, timeout=12):
    try:
        req = Request(url, headers=_HEADERS)
        with urlopen(req, timeout=timeout, context=_SSL) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None

# ── Parse ─────────────────────────────────────────────────────────────────────

def _clean(s):
    return _html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip())

def _dedup(lst):
    return list(dict.fromkeys(lst))

def _parse_styles(contrib_html):
    """Extract calligraphic styles from artworkContributions HTML.

    Each <li> contains: <strong><a>Artist</a></strong><br>
    H. YYYY / M. YYYY-YYYY  ArtForm (Style1, Style2, ...)

    Returns a flat deduped list of all art forms and sub-styles found.
    """
    styles = []
    for li in re.findall(r'<li[^>]*>([\s\S]*?)</li>', contrib_html):
        parts = re.split(r'<br\s*/?>', li, maxsplit=1)
        if len(parts) < 2:
            continue
        text = _clean(parts[1]).strip()
        if not text:
            continue
        # Strip date prefix: "H. 1439 / M. 2017-2018" or "H. 1439-1440 / M. 2018"
        text = re.sub(r'^H\.\s*[\d]+(?:[-–][\d]+)?\s*(?:/\s*M\.\s*[\d]+(?:[-–][\d]+)?)?\s*', '', text, flags=re.I).strip()
        if not text:
            continue
        paren = re.search(r'\(([^)]+)\)', text)
        if paren:
            art_form = text[:paren.start()].strip()
            if art_form:
                styles.append(art_form)
            for s in paren.group(1).split(','):
                s = s.strip()
                if s:
                    styles.append(s)
        else:
            styles.append(text)
    return _dedup(styles)

def parse_artwork(html, artwork_id):
    if not html or 'artworkContentPanel' not in html:
        return None

    # Artists + calligraphic styles (both come from contributions block)
    artists = []
    styles  = []
    cb = re.search(r'artworkContributions([\s\S]{0,6000}?)</ul>', html)
    if cb:
        artists = [m.group(1) for m in
                   re.finditer(r'<strong><a[^>]*>([^<]+)</a></strong>', cb.group(1))]
        styles  = _parse_styles(cb.group(1))

    # Arabic (RTL) and romanized titles
    arabic, titles = [], []
    for m in re.finditer(r'<p([^>]*class="[^"]*artworkName[^"]*"[^>]*)>([\s\S]*?)</p>', html):
        text = _clean(m.group(2))
        if not text:
            continue
        if 'rtl' in m.group(1) or 'dir=' in m.group(1):
            arabic.append(text)
        else:
            titles.append(text)

    # Artwork composition format (Levha, Kıt'a, etc.)
    fm = re.search(r'<p[^>]*artworkCalligraphyForm[^>]*>([\s\S]*?)</p>', html)
    form = _clean(fm.group(1)) if fm else ''

    # Ink / material
    im = re.search(r'<p[^>]*artworkInk[^>]*>([\s\S]*?)</p>', html)
    ink = _clean(im.group(1)) if im else ''

    # Thumbnail (OG image)
    om = (re.search(r'property="og:image"\s+content="([^"]+)"', html) or
          re.search(r'content="([^"]+)"\s+property="og:image"', html))
    thumbnail = om.group(1) if om else ''

    if not artists and not arabic and not titles:
        return None

    return {
        'id':               artwork_id,
        'url':              f'https://ketebe.org/eser/{artwork_id}?ref=artworks',
        'artists':          _dedup(artists),
        'arabicTexts':      _dedup(arabic),
        'titles':           _dedup(titles),
        'calligraphyTypes': styles,   # e.g. ["Hüsn-i Hat", "Nesih", "Sülüs"]
        'form':             form,     # artwork composition format (Levha, Kıt'a…)
        'ink':              ink,
        'thumbnail':        thumbnail,
    }

# ── Crawl ─────────────────────────────────────────────────────────────────────

def fetch_one(artwork_id):
    html = fetch(f'https://ketebe.org/Ajax/ArtworkSwipper/{artwork_id}')
    return parse_artwork(html, artwork_id)

def run_index():
    # Load existing index (resume support)
    artworks = []
    if OUTPUT.exists():
        with open(OUTPUT, encoding='utf-8') as f:
            artworks = json.load(f)
        print(f"Resuming — {len(artworks)} artworks already indexed.\n")

    indexed_ids = {a['id'] for a in artworks}
    to_scan     = [i for i in range(ID_START, ID_END) if i not in indexed_ids]
    total       = len(to_scan)
    processed   = 0
    new_count   = 0
    buf         = []

    print(f"Scanning IDs {ID_START}–{ID_END - 1}  ({total} IDs, {WORKERS} parallel workers)")
    print("Ctrl+C to stop — progress is saved every", SAVE_EVERY, "artworks.\n")

    def flush():
        artworks.extend(buf)
        buf.clear()
        with open(OUTPUT, 'w', encoding='utf-8') as f:
            json.dump(artworks, f, ensure_ascii=False)

    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(fetch_one, i): i for i in to_scan}
            for future in as_completed(futures):
                processed += 1
                artwork = future.result()

                if artwork:
                    buf.append(artwork)
                    new_count += 1
                    artist = artwork['artists'][0] if artwork['artists'] else '—'
                    text   = (artwork['arabicTexts'][0] if artwork['arabicTexts']
                              else artwork['titles'][0]  if artwork['titles'] else '—')
                    pct    = processed * 100 // total
                    elapsed = time.time() - t0
                    rate   = processed / elapsed if elapsed > 0 else 1
                    eta    = (total - processed) / rate
                    print(f"  [{pct:3d}%] #{futures[future]}  {artist}  |  {text}")
                    print(f"         {len(artworks) + len(buf)} indexed  •  ETA ~{int(eta)}s", end='\r')
                else:
                    pct = processed * 100 // total
                    print(f"  [{pct:3d}%] scanning… {len(artworks) + len(buf)} found", end='\r')

                if len(buf) >= SAVE_EVERY:
                    flush()
                    print(f"\n  ✓ Saved {len(artworks)} artworks\n")

    except KeyboardInterrupt:
        print("\n\nStopped.")

    if buf:
        flush()

    elapsed = time.time() - t0
    print(f"\n\nDone in {int(elapsed)}s — {len(artworks)} artworks → {OUTPUT.name}")
    return len(artworks)

# ── Local server ──────────────────────────────────────────────────────────────

def serve():
    import http.server, socketserver, webbrowser, threading, os

    port = 8765
    os.chdir(Path(__file__).parent)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass  # silence request logs

    with socketserver.TCPServer(('', port), Handler) as httpd:
        url = f'http://localhost:{port}/search.html'
        print(f"Serving at {url}")
        print("Press Ctrl+C to stop.\n")
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    run_index()
    if '--serve' in sys.argv or input("\nOpen search page? [y/n] ").strip().lower() == 'y':
        serve()
