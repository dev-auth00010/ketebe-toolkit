#!/usr/bin/env python3
"""
Patch existing artworks.json to add calligraphyTypes and fix HTML entities.
Run once after updating index.py:

    python3 patch_styles.py
"""

import json, ssl, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import urlopen, Request
from index import fetch, _parse_styles, _clean

OUTPUT   = Path(__file__).parent / "artworks.json"
WORKERS  = 8
SAVE_EVERY = 100

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode    = ssl.CERT_NONE

def patch_one(artwork):
    aid = artwork['id']
    url = f'https://ketebe.org/Ajax/ArtworkSwipper/{aid}'
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
        with urlopen(req, timeout=12, context=_SSL) as r:
            html = r.read().decode('utf-8', errors='replace')
    except Exception:
        return artwork  # leave unchanged on error

    import re
    cb = re.search(r'artworkContributions([\s\S]{0,6000}?)</ul>', html)
    styles = _parse_styles(cb.group(1)) if cb else []

    fm = re.search(r'<p[^>]*artworkCalligraphyForm[^>]*>([\s\S]*?)</p>', html)
    form = _clean(fm.group(1)) if fm else artwork.get('form', '')

    im = re.search(r'<p[^>]*artworkInk[^>]*>([\s\S]*?)</p>', html)
    ink = _clean(im.group(1)) if im else artwork.get('ink', '')

    artwork['calligraphyTypes'] = styles
    artwork['form'] = form
    artwork['ink']  = ink
    return artwork

def main():
    with open(OUTPUT, encoding='utf-8') as f:
        artworks = json.load(f)

    need_patch = [a for a in artworks if 'calligraphyTypes' not in a]
    print(f"{len(artworks)} artworks loaded — {len(need_patch)} need patching\n")

    if not need_patch:
        print("Nothing to patch.")
        return

    lookup = {a['id']: a for a in artworks}
    done = 0
    t0 = time.time()

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(patch_one, a): a['id'] for a in need_patch}
            for future in as_completed(futures):
                result = future.result()
                lookup[result['id']] = result
                done += 1
                pct = done * 100 // len(need_patch)
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed else 1
                eta = int((len(need_patch) - done) / rate)
                styles_found = len(result.get('calligraphyTypes', []))
                print(f"  [{pct:3d}%] #{result['id']}  styles={styles_found}  ETA ~{eta}s", end='\r')

                if done % SAVE_EVERY == 0:
                    artworks = list(lookup.values())
                    with open(OUTPUT, 'w', encoding='utf-8') as f:
                        json.dump(artworks, f, ensure_ascii=False)
                    print(f"\n  ✓ Saved ({done}/{len(need_patch)} patched)\n")

    except KeyboardInterrupt:
        print("\n\nStopped early.")

    artworks = list(lookup.values())
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(artworks, f, ensure_ascii=False)

    elapsed = time.time() - t0
    print(f"\n\nDone in {int(elapsed)}s — all artworks patched → {OUTPUT.name}")

    # Quick stats
    from collections import Counter
    all_styles = []
    for a in artworks:
        all_styles.extend(a.get('calligraphyTypes', []))
    top = Counter(all_styles).most_common(15)
    print("\nTop calligraphic styles found:")
    for style, n in top:
        print(f"  {n:4d}  {style}")

if __name__ == '__main__':
    main()
