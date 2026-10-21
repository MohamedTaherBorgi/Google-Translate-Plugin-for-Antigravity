import collections
import json
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BIND_HOST = "127.0.0.1"
PORT = int(os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT", "18766"))
APP_DATA_DIR = Path(
    os.environ.get(
        "ANTIGRAVITY_APP_DATA_DIR",
        str(Path.home() / ".gemini" / "antigravity"),
    )
)
PRELOAD_PATH = APP_DATA_DIR / "lib" / "node_modules" / "sidecar_sdk" / "preload.js"

CACHE = collections.OrderedDict()
CACHE_MAX_SIZE = 500


def get_cached(key: str):
    if key in CACHE:
        CACHE.move_to_end(key)
        return CACHE[key]
    return None


def set_cached(key: str, val: dict):
    CACHE[key] = val
    CACHE.move_to_end(key)
    if len(CACHE) > CACHE_MAX_SIZE:
        CACHE.popitem(last=False)


def translate_text(text: str, sl: str = "auto", tl: str = "en"):
    text = (text or "").strip()
    if not text:
        return {"translated": "", "detected": sl}

    cache_key = f"{sl}::{tl}::{text}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    encoded = urllib.parse.quote(text)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }

    # Primary and fallback endpoints (avoiding deprecated/rate-limited client=gtx)
    endpoints = [
        # Strategy 1: Google Translate API (dict-chrome-ex client)
        (
            f"https://translate.googleapis.com/translate_a/single?client=dict-chrome-ex&sl={sl}&tl={tl}&dt=t&dt=bd&dt=rm&q={encoded}",
            "single",
        ),
        # Strategy 2: Google clients5 mirror
        (
            f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl={sl}&tl={tl}&q={encoded}",
            "t",
        ),
        # Strategy 3: Google Translate (at client)
        (
            f"https://translate.google.com/translate_a/single?client=at&sl={sl}&tl={tl}&dt=t&q={encoded}",
            "single",
        ),
    ]

    last_error = None
    for url, parser_type in endpoints:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            if parser_type == "single":
                translated_parts = []
                if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    for part in data[0]:
                        if part and isinstance(part, list) and len(part) > 0 and part[0]:
                            translated_parts.append(str(part[0]))
                translated = "".join(translated_parts)
                detected = sl
                if len(data) > 2 and isinstance(data[2], str):
                    detected = data[2]
            else:
                translated_parts = []
                detected = sl
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, list) and len(item) > 0:
                            if item[0]:
                                translated_parts.append(str(item[0]))
                            if len(item) > 1 and isinstance(item[1], str) and detected == sl:
                                detected = item[1]
                        elif isinstance(item, str):
                            translated_parts.append(item)
                translated = "".join(translated_parts)

            if translated:
                result = {"translated": translated, "detected": detected}
                set_cached(cache_key, result)
                return result
        except Exception as e:
            last_error = e
            continue

    # Strategy 4: If sl is not auto, try MyMemory as secondary external fallback
    if sl != "auto":
        try:
            mm_url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair={sl}|{tl}"
            req = urllib.request.Request(mm_url, headers=headers)
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated and not translated.startswith("MYMEMORY WARNING"):
                result = {"translated": translated, "detected": sl}
                set_cached(cache_key, result)
                return result
        except Exception as e:
            last_error = e

    return {"error": str(last_error or "Translation failed"), "translated": "", "detected": sl}


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Translate</title>
<script src="/preload.js"></script>
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0 !important;
    padding: 0 !important;
    background: #0b1120 !important;
    color: #f8fafc !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif !important;
    font-size: 13px;
    line-height: 1.5;
  }
  .wrap {
    padding: 12px;
    max-width: 520px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    container-type: inline-size;
  }

  /* Topbar */
  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding-bottom: 8px;
    margin-bottom: 10px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
    font-size: 13.5px;
    color: #f8fafc;
    white-space: nowrap;
  }
  .brand-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 7px;
    background: rgba(14, 165, 233, 0.12);
    border: 1px solid rgba(14, 165, 233, 0.25);
    color: #38bdf8;
    flex-shrink: 0;
  }
  .brand-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: #94a3b8;
  }
  .dot-live {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 6px #10b981;
    flex-shrink: 0;
  }

  /* Header & Language Bar */
  .lang-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }
  .lang-select {
    flex: 1;
    background: #131c31;
    color: #f8fafc;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 13px;
    cursor: pointer;
    outline: none;
    font-weight: 500;
  }
  .lang-select:focus {
    border-color: #38bdf8;
  }
  .swap-btn {
    background: #131c31;
    border: 1px solid #1e293b;
    color: #94a3b8;
    border-radius: 8px;
    width: 34px;
    height: 34px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 15px;
    transition: all 0.15s ease;
    flex-shrink: 0;
  }
  .swap-btn:hover:not(:disabled) {
    background: #1e293b;
    color: #38bdf8;
    border-color: #38bdf8;
  }
  .swap-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }

  /* Text Area Cards */
  .card {
    background: #131c31;
    border: 1px solid #1e293b;
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 12px;
    display: flex;
    flex-direction: column;
  }
  .card.target {
    background: #0e172a;
    border-color: #1e293b;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
    font-size: 11px;
    color: #64748b;
  }
  .detected-badge {
    color: #38bdf8;
    font-size: 11px;
    font-weight: 500;
  }

  textarea {
    width: 100%;
    min-height: 100px;
    background: transparent;
    border: none;
    color: #f8fafc;
    font-family: inherit;
    font-size: 14px;
    line-height: 1.5;
    resize: none;
    overflow-y: hidden;
    outline: none;
    padding: 0;
  }
  textarea::placeholder {
    color: #475569;
  }

  .output-text {
    width: 100%;
    min-height: 120px;
    color: #38bdf8;
    font-size: 14px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    user-select: text;
  }
  .output-placeholder {
    color: #475569;
    font-style: italic;
  }

  .card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #1e293b;
    font-size: 11px;
    color: #64748b;
  }
  .btn-group {
    display: flex;
    gap: 6px;
  }
  .btn {
    background: #1e293b;
    border: 1px solid #334155;
    color: #cbd5e1;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 11.5px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    transition: all 0.15s ease;
  }
  .btn:hover {
    background: #334155;
    color: #f8fafc;
  }
  .btn-copy {
    background: #2563eb;
    border-color: #3b82f6;
    color: #ffffff;
    font-weight: 600;
  }
  .btn-copy:hover {
    background: #1d4ed8;
  }

  .toast {
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: #10b981;
    color: #0b1120;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease;
    z-index: 100;
  }
  .toast.show { opacity: 1; }

  /* Responsive & Container Queries */
  @container (max-width: 340px) {
    .wrap { padding: 8px; }
    .lang-select { font-size: 11.5px; padding: 6px 8px; }
    .swap-btn { width: 30px; height: 30px; }
    .card { padding: 10px; }
    .btn { padding: 3px 8px; font-size: 10.5px; }
  }
  @media (max-width: 360px) {
    .wrap { padding: 8px; }
    .lang-select { font-size: 11.5px; padding: 6px 8px; }
    .swap-btn { width: 30px; height: 30px; }
  }
</style>
</head>
<body>
<div class="wrap">

  <!-- Clean Top Bar -->
  <div class="topbar">
    <div class="brand">
      <div class="brand-badge" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
      </div>
      <span>Google Translate</span>
    </div>
    <div class="brand-status">
      <span class="dot-live" title="Translator ready"></span>
      <span>Live</span>
    </div>
  </div>

  <!-- Language Bar -->
  <div class="lang-bar">
    <select id="sl-select" class="lang-select" aria-label="Source Language"></select>
    <button id="swap-btn" class="swap-btn" onclick="swapLangs()" title="Swap languages" aria-label="Swap languages">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/></svg>
    </button>
    <select id="tl-select" class="lang-select" aria-label="Target Language"></select>
  </div>

  <!-- Input Card -->
  <div class="card">
    <div class="card-header">
      <span class="detected-badge" id="detected-badge"></span>
      <span id="char-count">0 chars</span>
    </div>
    <textarea id="src-input" placeholder="Type or paste text..." autofocus></textarea>
    <div class="card-footer">
      <span id="status-label" style="font-size: 11px;">Ready</span>
      <div class="btn-group">
        <button class="btn" id="paste-btn" onclick="pasteClipboard()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>
          Paste
        </button>
        <button class="btn" onclick="clearInput()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          Clear
        </button>
      </div>
    </div>
  </div>

  <!-- Output Card -->
  <div class="card target">
    <div class="card-header">
      <span>Translation</span>
      <span id="out-word-count"></span>
    </div>
    <div class="output-text" id="output-text">
      <span class="output-placeholder">Translation...</span>
    </div>
    <div class="card-footer">
      <span></span>
      <div class="btn-group">
        <button class="btn btn-copy" id="copy-btn" onclick="copyTranslation()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          Copy
        </button>
      </div>
    </div>
  </div>

</div>

<div class="toast" id="toast">Copied!</div>

<script>
  const LANGUAGES = [
    { code: 'auto', name: 'Auto Detect' },
    { code: 'en', name: 'English' },
    { code: 'fr', name: 'French' },
    { code: 'ar', name: 'Arabic' },
    { code: 'es', name: 'Spanish' },
    { code: 'de', name: 'German' },
    { code: 'it', name: 'Italian' },
    { code: 'pt', name: 'Portuguese' },
    { code: 'ru', name: 'Russian' },
    { code: 'tr', name: 'Turkish' },
    { code: 'zh-CN', name: 'Chinese' },
    { code: 'ja', name: 'Japanese' },
    { code: 'ko', name: 'Korean' },
    { code: 'nl', name: 'Dutch' },
    { code: 'pl', name: 'Polish' },
    { code: 'hi', name: 'Hindi' }
  ];

  const slSelect = document.getElementById('sl-select');
  const tlSelect = document.getElementById('tl-select');
  const swapBtn = document.getElementById('swap-btn');
  const srcInput = document.getElementById('src-input');
  const outputText = document.getElementById('output-text');
  const charCount = document.getElementById('char-count');
  const outWordCount = document.getElementById('out-word-count');
  const detectedBadge = document.getElementById('detected-badge');
  const statusLabel = document.getElementById('status-label');
  const toast = document.getElementById('toast');

  let debounceTimer = null;
  let lastTranslatedText = '';

  function initLanguages() {
    slSelect.innerHTML = '';
    tlSelect.innerHTML = '';

    for (const lang of LANGUAGES) {
      const opt1 = document.createElement('option');
      opt1.value = lang.code;
      opt1.textContent = lang.name;
      slSelect.appendChild(opt1);

      if (lang.code !== 'auto') {
        const opt2 = document.createElement('option');
        opt2.value = lang.code;
        opt2.textContent = lang.name;
        tlSelect.appendChild(opt2);
      }
    }

    slSelect.value = localStorage.getItem('gt_sl') || 'auto';
    tlSelect.value = localStorage.getItem('gt_tl') || 'en';
    updateSwapButton();
  }

  function updateSwapButton() {
    swapBtn.disabled = (slSelect.value === 'auto');
  }

  function swapLangs() {
    if (slSelect.value === 'auto') return;
    const oldSl = slSelect.value;
    const oldTl = tlSelect.value;
    slSelect.value = oldTl;
    tlSelect.value = oldSl;
    localStorage.setItem('gt_sl', oldTl);
    localStorage.setItem('gt_tl', oldSl);
    updateSwapButton();

    if (lastTranslatedText && lastTranslatedText !== srcInput.value) {
      srcInput.value = lastTranslatedText;
      autoResize();
    }
    doTranslate();
  }

  slSelect.addEventListener('change', () => {
    localStorage.setItem('gt_sl', slSelect.value);
    updateSwapButton();
    doTranslate();
  });

  tlSelect.addEventListener('change', () => {
    localStorage.setItem('gt_tl', tlSelect.value);
    doTranslate();
  });

  function autoResize() {
    srcInput.style.height = 'auto';
    srcInput.style.height = Math.max(100, srcInput.scrollHeight) + 'px';
  }

  srcInput.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(debounceTimer);
      doTranslate();
    }
  });

  srcInput.addEventListener('input', () => {
    autoResize();
    const len = srcInput.value.length;
    charCount.textContent = `${len} char${len === 1 ? '' : 's'}`;
    clearTimeout(debounceTimer);
    if (!srcInput.value.trim()) {
      clearOutput();
      return;
    }
    statusLabel.textContent = 'Translating...';
    debounceTimer = setTimeout(doTranslate, 450);
  });

  function clearOutput() {
    outputText.innerHTML = '<span class="output-placeholder">Translation...</span>';
    detectedBadge.textContent = '';
    outWordCount.textContent = '';
    statusLabel.textContent = 'Ready';
    lastTranslatedText = '';
  }

  function clearInput() {
    srcInput.value = '';
    srcInput.style.height = '100px';
    charCount.textContent = '0 chars';
    clearOutput();
    srcInput.focus();
  }

  async function pasteClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        srcInput.value = text;
        autoResize();
        const len = srcInput.value.length;
        charCount.textContent = `${len} char${len === 1 ? '' : 's'}`;
        doTranslate();
      }
    } catch (e) {
      srcInput.focus();
    }
  }

  async function doTranslate() {
    const q = srcInput.value.trim();
    if (!q) {
      clearOutput();
      return;
    }

    const sl = slSelect.value;
    const tl = tlSelect.value;
    statusLabel.textContent = 'Translating...';

    try {
      const res = await fetch('/api/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: q, sl, tl })
      });

      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();

      if (data.error) {
        statusLabel.textContent = 'Error';
        outputText.innerHTML = `<span style="color:#fb7185">Error: ${data.error}</span>`;
        return;
      }

      const translated = data.translated || '';
      lastTranslatedText = translated;
      outputText.textContent = translated || '(No translation)';
      statusLabel.textContent = 'Done';

      if (sl === 'auto' && data.detected) {
        const found = LANGUAGES.find(l => l.code === data.detected);
        const name = found ? found.name : data.detected.toUpperCase();
        detectedBadge.textContent = `Detected: ${name}`;
      } else {
        detectedBadge.textContent = '';
      }

      const words = translated ? translated.trim().split(/\s+/).length : 0;
      outWordCount.textContent = `${words} word${words === 1 ? '' : 's'}`;

    } catch (err) {
      statusLabel.textContent = 'Error';
      outputText.innerHTML = `<span style="color:#fb7185">Network error</span>`;
    }
  }

  async function copyTranslation() {
    if (!lastTranslatedText) return;
    try {
      await navigator.clipboard.writeText(lastTranslatedText);
      showToast('Copied!');
    } catch (e) {
      const ta = document.createElement('textarea');
      ta.value = lastTranslatedText;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast('Copied!');
    }
  }

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 1500);
  }

  initLanguages();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/preload.js":
            if PRELOAD_PATH.exists():
                self._send(
                    200,
                    "application/javascript; charset=utf-8",
                    PRELOAD_PATH.read_bytes(),
                )
            else:
                self._send(200, "application/javascript; charset=utf-8", b"")
            return

        if parsed.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML_PAGE.encode("utf-8"))
            return

        self._send(404, "text/plain; charset=utf-8", b"Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/translate":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                data = {}

            text = data.get("text", "")
            sl = data.get("sl", "auto")
            tl = data.get("tl", "en")

            result = translate_text(text, sl=sl, tl=tl)
            self._send(
                200,
                "application/json; charset=utf-8",
                json.dumps(result).encode("utf-8"),
            )
            return

        self._send(404, "text/plain; charset=utf-8", b"Not Found")


if __name__ == "__main__":
    server = ThreadingHTTPServer((BIND_HOST, PORT), Handler)
    print(f"[translator] listening on http://{BIND_HOST}:{PORT}", flush=True)
    server.serve_forever()
