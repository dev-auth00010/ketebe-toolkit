# Ketebe Toolkit

Two tools for working with [ketebe.org](https://ketebe.org), a calligraphy archive of ~3,200 artworks whose built-in search is broken:

| Tool | What it does |
|------|-------------|
| **Indexer + Search** | Crawls the site, builds a local JSON index, serves a fast search UI |
| **Chrome Extension** | Downloads any artwork at full resolution (stitches DZI tiles) |

---

## Part 1 — Indexer & Search Page

### Requirements

- Python 3.8 or newer (no third-party packages needed)
- A terminal

### Setup

```bash
git clone https://github.com/dev-auth00010/ketebe-toolkit.git
cd ketebe-toolkit/indexer
```

### Step 1 — Build the index

```bash
python3 index.py
```

This crawls artwork IDs 2400–9200 in parallel (5 workers). It takes roughly **15–30 minutes** for a full run. Progress is printed live and saved to `artworks.json` every 30 artworks, so you can **stop and resume** at any time with Ctrl+C.

When it finishes it will ask:
```
Open search page? [y/n]
```
Type `y` to open the search UI in your browser immediately.

### Step 2 — Open the search page

Any time after building the index:

```bash
python3 index.py --serve
```

This starts a local server at `http://localhost:8765/search.html` and opens it in your browser. Press Ctrl+C in the terminal to stop it.

### What you can search

- **Text box** — searches Arabic text, artist names, titles, calligraphy style, ink, and composition form
- **Style dropdown** — full ketebe.org taxonomy (Hüsn-i Hat, Nesih, Sülüs, Tezhip, Ebru, etc.)
- **Artist dropdown** — all artists sorted by artwork count

Clicking any result opens the artwork page on ketebe.org.

### Keeping the index up to date

Re-run `python3 index.py` at any time. It skips already-indexed IDs automatically.

If you have an old index that's missing the calligraphy style fields, run the one-time patch script:

```bash
python3 patch_styles.py
```

---

## Part 2 — Chrome Extension (Full-Resolution Downloader)

Downloads any artwork at its maximum DZI tile resolution — typically 4000–8000 px wide — and saves it as a single JPEG. No Python required.

### Install

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode** (toggle in the top-right corner)
3. Click **Load unpacked**
4. Select the `chrome-extension/` folder inside this repo

The extension icon (a puzzle piece) will appear in your toolbar. Pin it for easy access.

### Use

1. Navigate to any artwork page on ketebe.org, e.g. `https://ketebe.org/eser/3500?ref=artworks`
2. Click the extension icon
3. The popup shows the image dimensions and tile count
4. Click **Download Full Image**

The download stitches all tiles in parallel (~14 concurrent fetches) and saves as `ketebe_<id>.jpg` in your Downloads folder.

### Notes

- Works on any `ketebe.org/…/<number>` URL — detail pages, search results, etc.
- The extension only contacts `ketebe.org` and `image.yenisafak.com` (the tile CDN)
- No data is collected or sent anywhere else

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `artworks.json` not found when opening search.html directly | Serve through Python: `python3 index.py --serve` (file:// can't load local JSON) |
| SSL errors on macOS with Python 3.14 | Already handled — the indexer disables cert verification for ketebe.org |
| Extension shows "Could not find image data" | The artwork may not have a high-res DZI image; try another artwork |
| Index crawl is slow | Increase `WORKERS` at the top of `index.py` (be considerate of the server) |
| New artworks added to ketebe.org | Update `ID_END` in `index.py` and re-run — it will only fetch new IDs |

---

## File reference

```
ketebe-toolkit/
├── indexer/
│   ├── index.py          # crawls ketebe.org → artworks.json
│   ├── patch_styles.py   # one-time migration for older indexes
│   └── search.html       # search UI (served by index.py --serve)
└── chrome-extension/
    ├── manifest.json
    ├── popup.html
    └── popup.js          # DZI tile stitcher
```

`artworks.json` is generated locally by running `index.py` and is not included in this repo (it's ~5 MB and personal to your crawl run).
