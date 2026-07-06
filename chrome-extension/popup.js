'use strict';

const BASE_CDN = 'https://image.yenisafak.com/ketebe';
const CONCURRENCY = 14;

let artworkId = null;
let uuid = null;
let dzi = null;

// ── UI ────────────────────────────────────────────────────────────────────────

function show(id) {
  ['idle', 'ready', 'progress', 'done', 'error'].forEach(v =>
    document.getElementById('view-' + v).hidden = (v !== id)
  );
}

function setStatus(text) { document.getElementById('statusText').textContent = text; }

function setProgress(done, total) {
  document.getElementById('progressFill').style.width =
    total ? `${(done / total * 100).toFixed(1)}%` : '0%';
  document.getElementById('progressLabel').textContent =
    total ? `${done} / ${total} tiles` : '';
}

function showError(msg) {
  show('error');
  document.getElementById('errorText').textContent = msg;
}

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  // Extract numeric artwork ID from any ketebe.org URL path segment
  const m = (tab.url || '').match(/ketebe\.org\/(?:[^/?#]+\/)*(\d+)/);
  if (!m) { show('idle'); return; }

  artworkId = m[1];
  show('ready');
  document.getElementById('artworkLabel').textContent = `Artwork #${artworkId}`;

  uuid = await findUUID(artworkId);
  if (!uuid) { showError('Could not find image data for this artwork.'); return; }

  dzi = await fetchDZI(uuid);
  if (!dzi) { showError('Could not load the DZI image descriptor. Try refreshing the ketebe.org page.'); return; }

  const { width, height, cols, rows } = dzi;
  document.getElementById('dimsLabel').textContent =
    `${width.toLocaleString()} × ${height.toLocaleString()} px  ·  ${cols * rows} tiles`;

  const btn = document.getElementById('downloadBtn');
  btn.disabled = false;
  btn.addEventListener('click', startDownload);
});

// ── UUID lookup ───────────────────────────────────────────────────────────────

async function findUUID(id) {
  try {
    const r = await fetch(
      `https://ketebe.org/Ajax/ArtworkSwipper/${id}?ArtistId=&PID=&ircica=`,
      { headers: { 'X-Requested-With': 'XMLHttpRequest' } }
    );
    if (!r.ok) return null;
    const html = await r.text();

    // Prefer explicit .xml reference
    const m1 = html.match(/image\.yenisafak\.com\/ketebe\/file\/([0-9a-f-]{36})\.xml/i);
    if (m1) return m1[1];

    // Fallback: any UUID in the HTML
    const m2 = html.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
    return m2 ? m2[1] : null;
  } catch {
    return null;
  }
}

// ── DZI metadata ──────────────────────────────────────────────────────────────

async function fetchDZI(uuid) {
  for (const ext of ['.xml', '.dzi']) {
    try {
      const r = await fetch(`${BASE_CDN}/file/${uuid}${ext}`);
      if (!r.ok) continue;
      const text = await r.text();

      const doc = new DOMParser().parseFromString(text, 'text/xml');
      const imgEl  = doc.querySelector('Image');
      const sizeEl = doc.querySelector('Size');
      if (!imgEl || !sizeEl) continue;

      const tileSize = parseInt(imgEl.getAttribute('TileSize') ?? '256');
      const overlap  = parseInt(imgEl.getAttribute('Overlap')  ?? '1');
      const width    = parseInt(sizeEl.getAttribute('Width'));
      const height   = parseInt(sizeEl.getAttribute('Height'));
      if (!width || !height) continue;

      // Full-resolution level = ceil(log2(max dimension))
      const maxLevel = Math.ceil(Math.log2(Math.max(width, height)));
      const cols     = Math.ceil(width  / tileSize);
      const rows     = Math.ceil(height / tileSize);

      return { tileSize, overlap, width, height, maxLevel, cols, rows };
    } catch { continue; }
  }
  return null;
}

// ── Download + stitch ─────────────────────────────────────────────────────────

async function startDownload() {
  if (!dzi || !uuid) return;
  document.getElementById('downloadBtn').disabled = true;

  show('progress');
  setStatus('Downloading tiles…');
  setProgress(0, dzi.cols * dzi.rows);

  const { tileSize, overlap, width, height, maxLevel, cols, rows } = dzi;
  const total = cols * rows;

  // Build flat tile list
  const tasks = [];
  for (let row = 0; row < rows; row++)
    for (let col = 0; col < cols; col++)
      tasks.push({ col, row, url: `${BASE_CDN}/file/${uuid}_files/${maxLevel}/${col}_${row}.jpg` });

  // Parallel fetch with concurrency cap
  const bitmaps = [];
  let done = 0;

  async function worker(slice) {
    for (const { col, row, url } of slice) {
      try {
        const r = await fetch(url);
        if (r.ok) {
          const bm = await createImageBitmap(await r.blob());
          bitmaps.push({ col, row, bm });
        }
      } catch { /* skip missing tile */ }
      setProgress(++done, total);
    }
  }

  await Promise.all(
    Array.from({ length: CONCURRENCY }, (_, i) =>
      worker(tasks.filter((_, j) => j % CONCURRENCY === i))
    )
  );

  // Stitch with OffscreenCanvas (no canvas-taint issues)
  setStatus('Stitching image…');
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);

  for (const { col, row, bm } of bitmaps) {
    // Crop shared overlap pixels from non-edge tiles (matches DZI spec)
    const srcX = col > 0 ? overlap : 0;
    const srcY = row > 0 ? overlap : 0;
    const srcW = bm.width  - srcX;
    const srcH = bm.height - srcY;
    ctx.drawImage(bm, srcX, srcY, srcW, srcH,
                  col * tileSize, row * tileSize, srcW, srcH);
    bm.close();
  }

  setStatus('Encoding JPEG…');
  const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.95 });

  // Trigger download
  setStatus('Starting download…');
  const blobUrl = URL.createObjectURL(blob);

  try {
    await chrome.downloads.download({
      url: blobUrl,
      filename: `ketebe_${artworkId}.jpg`,
      saveAs: false,
    });
  } catch {
    // Fallback: anchor click
    const a = Object.assign(document.createElement('a'), {
      href: blobUrl,
      download: `ketebe_${artworkId}.jpg`,
    });
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  // Revoke after browser has had time to copy the blob
  setTimeout(() => URL.revokeObjectURL(blobUrl), 120_000);

  show('done');
  document.getElementById('savedLabel').textContent =
    `${width.toLocaleString()} × ${height.toLocaleString()} px  ·  ${(blob.size / 1048576).toFixed(1)} MB`;
}
