#!/usr/bin/env python3
"""OCR 校對工具
左:圖檔  右:可編輯文字  支援清單/上下頁/跳頁/直接覆寫存檔

固定使用本檔案旁邊的 txt/ 與 img/ 資料夾:
    python3 tool.py                 # 啟動並自動開瀏覽器
    python3 tool.py --port 5001 --host 0.0.0.0 --no-browser
一般使用者直接雙擊 start.bat (Windows) / start.command (Mac) / start.sh (Linux)。

預設只綁 127.0.0.1(本機)。要讓同網段的機器連進來才加 --host 0.0.0.0。
"""
import argparse
import os
import pathlib
import re
import socket
import threading
import webbrowser

from flask import Flask, abort, jsonify, render_template_string, request, send_file

IMG_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff', '.bmp', '.gif'}
TXT_EXTS = {'.txt', '.md'}

BASE_DIR = pathlib.Path(__file__).resolve().parent
TXT_DIR = BASE_DIR / 'txt'
IMG_DIR = BASE_DIR / 'img'

app = Flask(__name__)


# ---------------------------------------------------------------- 檔名配對
def natkey(s):
    """自然排序: _2 排在 _10 前面。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def norm_stem(stem):
    """把數字的前導零去掉, 讓 _001 和 _1 對得起來。"""
    return re.sub(r'\d+', lambda m: str(int(m.group())), stem)


def scan_pages(txt_dir, img_dir):
    """掃描資料夾, 把文字檔和圖檔配成一頁一頁。

    配對順序: 檔名完全相同 → 去掉前導零後相同 → (完全配不到且數量一樣時) 依序配。
    只有圖沒有文字檔的, 也會列出來, 存檔時會在文字夾建立同名 .txt。
    """
    txts, imgs = [], []
    if txt_dir and txt_dir.is_dir():
        txts = sorted(
            (p for p in txt_dir.iterdir()
             if p.is_file() and p.suffix.lower() in TXT_EXTS and not p.name.startswith('.')),
            key=lambda p: natkey(p.name))
    if img_dir and img_dir.is_dir():
        imgs = sorted(
            (p for p in img_dir.iterdir()
             if p.is_file() and p.suffix.lower() in IMG_EXTS and not p.name.startswith('.')),
            key=lambda p: natkey(p.name))

    by_stem = {}
    for p in imgs:
        by_stem.setdefault(p.stem, p)
        by_stem.setdefault(norm_stem(p.stem), p)

    pages, used = [], set()
    for t in txts:
        im = by_stem.get(t.stem) or by_stem.get(norm_stem(t.stem))
        if im:
            used.add(im)
        pages.append({'txt': t, 'img': im, 'label': t.stem})

    # 完全配不到, 但兩邊數量一樣 → 依排序依序配
    if txts and imgs and not used and len(txts) == len(imgs):
        for pg, im in zip(pages, imgs):
            pg['img'] = im
        used = set(imgs)

    # 有圖沒文字檔的, 也列出來(存檔時才建立 .txt)
    for im in imgs:
        if im in used:
            continue
        target = (txt_dir or img_dir) / (im.stem + '.txt')
        pages.append({'txt': target, 'img': im, 'label': im.stem})

    pages.sort(key=lambda pg: natkey(pg['label']))
    return pages


def short_labels(pages):
    """側邊欄用: 所有檔名共同的開頭砍掉, 看起來清爽一點。"""
    labels = [pg['label'] for pg in pages]
    if len(labels) < 2:
        return labels
    pre = os.path.commonprefix(labels)
    if len(pre) < 3 or any(len(l) - len(pre) < 1 for l in labels):
        return labels
    return [l[len(pre):] for l in labels]


# ---------------------------------------------------------------- 校對頁
INDEX_HTML = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>OCR 校對</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0;}
  html,body{font:14px/1.5 system-ui,-apple-system,sans-serif;background:#1e1e1e;color:#ddd;height:100vh;overflow:hidden;}
  .topbar{display:flex;align-items:center;gap:12px;padding:8px 12px;background:#2d2d2d;border-bottom:1px solid #444;flex-wrap:wrap;}
  .topbar a{color:#7cb;text-decoration:none;padding:4px 10px;border:1px solid #555;border-radius:4px;}
  .topbar a:hover{background:#3a3a3a;}
  .topbar button{background:#3a3a3a;color:#ddd;border:1px solid #555;padding:4px 12px;border-radius:4px;cursor:pointer;font:inherit;}
  .topbar button:hover{background:#4a4a4a;}
  .topbar input[type=number]{width:70px;padding:3px 6px;background:#1e1e1e;color:#ddd;border:1px solid #555;border-radius:4px;font:inherit;}
  .topbar .label{color:#999;}
  .topbar .filename{color:#fff;font-weight:bold;}
  .topbar .wsname{color:#8ab;font-size:12px;font-family:monospace;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .topbar .status{margin-left:auto;color:#aaa;font-size:12px;}
  .main{display:flex;flex:1;min-height:0;}
  body{display:flex;flex-direction:column;}
  .sidebar{width:240px;background:#252525;border-right:1px solid #444;overflow-y:auto;flex-shrink:0;}
  .sidebar .item{padding:6px 12px;cursor:pointer;border-bottom:1px solid #333;color:#bbb;font-size:13px;
                 overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .sidebar .item:hover{background:#333;}
  .sidebar .item.active{background:#5a8;color:#fff;font-weight:bold;}
  .sidebar .item.noimg::after{content:' (無圖)';color:#777;font-size:11px;}
  .sidebar .item.new::after{content:' (新)';color:#c95;font-size:11px;}
  .content{flex:1;display:flex;min-width:0;min-height:0;}
  .pane{flex:1;min-width:0;min-height:0;display:flex;overflow:hidden;flex-direction:column;}
  .pane.img{background:#000;position:relative;}
  .img-wrap{flex:1;overflow:auto;padding:8px;min-height:0;text-align:center;}
  .img-wrap img{display:inline-block;}
  .img-wrap.fit{display:flex;align-items:center;justify-content:center;text-align:initial;}
  .img-wrap.fit img{max-width:100%;max-height:100%;object-fit:contain;}
  .pane.txt{position:relative;}
  .pane.txt textarea{flex:1;background:#1e1e1e;color:#eee;border:none;padding:16px;font:14px/1.7 'Noto Sans Mono CJK TC','Source Han Mono',monospace;resize:none;outline:none;width:100%;}
  .pane.txt textarea.vert{writing-mode:vertical-rl;text-orientation:upright;}
  .toolbar{display:flex;gap:4px;background:#2d2d2d;padding:6px 8px;border-bottom:1px solid #444;align-items:center;flex-shrink:0;}
  .toolbar button{background:#3a3a3a;color:#ddd;border:1px solid #555;padding:4px 10px;border-radius:4px;cursor:pointer;font:bold 13px monospace;min-width:32px;}
  .toolbar button:hover{background:#4a4a4a;}
  .toolbar .zlabel{color:#aaa;padding:0 6px;font-size:12px;min-width:48px;text-align:center;}
  .topbar button.save{background:#5a8;color:#fff;border-color:#5a8;font-weight:bold;padding:5px 18px;}
  .topbar button.save:hover{background:#7cb;}
</style>
</head>
<body>
<div class="topbar">
  <button onclick="goPrev()">← 上一頁</button>
  <span><span class="label">頁</span> <input type="number" id="jump" min="1" max="{{ total }}" value="{{ idx+1 }}" onchange="jumpTo()"> / {{ total }}</span>
  <button onclick="goNext()">下一頁 →</button>
  <span class="label">|</span>
  <span class="filename">{{ filename }}</span>
  <button class="save" onclick="save()" id="save">儲存 (Ctrl+S)</button>
  <span class="status" id="status"></span>
</div>
<div class="main">
  <div class="sidebar" id="sidebar">
    {% for p in page_list %}
      <div class="item {{ 'active' if loop.index0==idx else '' }}{{ ' noimg' if not p.has_img else '' }}{{ ' new' if not p.has_txt else '' }}"
           onclick="navigate({{ loop.index0 }})" data-idx="{{ loop.index0 }}" title="{{ p.full }}">
        {{ p.label }}
      </div>
    {% endfor %}
  </div>
  <div class="content">
    <div class="pane img">
      {% if img_exists %}
        <div class="toolbar">
          <button onclick="zoom(-1)">−</button>
          <span class="zlabel" id="zlabel">100%</span>
          <button onclick="zoom(1)">+</button>
          <button onclick="zoomReset()" title="重設">⤢</button>
        </div>
        <div class="img-wrap fit" id="imgwrap">
          <img id="pageimg" src="/img?idx={{ idx }}" alt="page image" onload="applyZoom()">
        </div>
      {% else %}
        <div style="color:#888;padding:40px;">(無圖)</div>
      {% endif %}
    </div>
    <div class="pane txt">
      <div class="toolbar">
        <button onclick="tzoom(-1)">A−</button>
        <span class="zlabel" id="tzlabel">14px</span>
        <button onclick="tzoom(1)">A+</button>
        <button onclick="toggleVert()" id="vertbtn" title="直式 / 橫式">直</button>
      </div>
      <textarea id="txt" spellcheck="false">{{ text }}</textarea>
    </div>
  </div>
</div>
<script>
const idx = {{ idx }};
const total = {{ total }};
const initialText = document.getElementById('txt').value;
let dirty = false;

document.addEventListener('DOMContentLoaded', () => {
  const item = document.querySelector('.sidebar .item.active');
  if (item) item.scrollIntoView({block:'center'});
});
document.getElementById('txt').addEventListener('input', () => {
  dirty = (document.getElementById('txt').value !== initialText);
});

async function save(){
  if(!dirty) return true;
  const text=document.getElementById('txt').value;
  const btn=document.getElementById('save');
  const stat=document.getElementById('status');
  btn.disabled=true; stat.textContent='儲存中…'; stat.style.color='#aaa';
  try{
    const r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idx,text})});
    const j=await r.json();
    if(j.ok){
      stat.textContent='✓ 已儲存 '+new Date().toLocaleTimeString();
      stat.style.color='#5a8';
      dirty=false;
      return true;
    } else {
      stat.textContent='✗ '+j.error; stat.style.color='#e66';
      return false;
    }
  }catch(e){
    stat.textContent='✗ '+e.message; stat.style.color='#e66';
    return false;
  }finally{ btn.disabled=false; }
}
async function navigate(targetIdx){
  if(targetIdx<0 || targetIdx>=total || targetIdx===idx) return;
  const ok = await save();
  if(!ok && dirty){
    if(!confirm('儲存失敗。仍要切換頁面?(未儲存的修改會遺失)')) return;
  }
  location.href=`/?idx=${targetIdx}`;
}
async function goPrev(){ await navigate(idx-1); }
async function goNext(){ await navigate(idx+1); }
async function jumpTo(){
  const v=parseInt(document.getElementById('jump').value);
  if(v>=1 && v<=total) await navigate(v-1);
}
window.addEventListener('beforeunload', e => {
  if(dirty){ e.preventDefault(); e.returnValue=''; return ''; }
});
let zoomLevel = 1.0;  // 1.0 = "fit to container", anything else multiplies natural pixel size
function applyZoom(){
  const img = document.getElementById('pageimg');
  const wrap = document.getElementById('imgwrap');
  if(!img || !wrap) return;
  if(zoomLevel === 1.0){
    wrap.classList.add('fit');
    img.style.width = '';
    img.style.height = '';
  } else {
    wrap.classList.remove('fit');
    if(img.naturalWidth){
      img.style.width = (img.naturalWidth * zoomLevel) + 'px';
      img.style.height = 'auto';
    }
  }
  document.getElementById('zlabel').textContent = Math.round(zoomLevel*100)+'%';
}
const ZOOM_STEPS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0];
function zoom(dir){
  let cur = ZOOM_STEPS.indexOf(zoomLevel);
  if(cur < 0){
    cur = ZOOM_STEPS.findIndex(s => s >= zoomLevel);
    if(cur < 0) cur = ZOOM_STEPS.length - 1;
  }
  const nxt = Math.max(0, Math.min(ZOOM_STEPS.length - 1, cur + dir));
  zoomLevel = ZOOM_STEPS[nxt];
  applyZoom();
}
function zoomReset(){ zoomLevel = 1.0; applyZoom(); }

// ---- 文字區字級 ----
const FONT_STEPS = [10,12,14,16,18,20,24,28,32,40,48];
let fontIdx = (function(){
  const saved = parseInt(localStorage.getItem('ocr_fontIdx'));
  return (saved>=0 && saved<FONT_STEPS.length) ? saved : 2;  // 14px
})();
function applyTzoom(){
  const ta = document.getElementById('txt');
  if(!ta) return;
  ta.style.fontSize = FONT_STEPS[fontIdx]+'px';
  document.getElementById('tzlabel').textContent = FONT_STEPS[fontIdx]+'px';
  localStorage.setItem('ocr_fontIdx', fontIdx);
}
function tzoom(d){
  fontIdx = Math.max(0, Math.min(FONT_STEPS.length-1, fontIdx+d));
  applyTzoom();
}
// ---- 直式 / 橫式 ----
function toggleVert(){
  const ta = document.getElementById('txt');
  const btn = document.getElementById('vertbtn');
  const v = ta.classList.toggle('vert');
  btn.textContent = v ? '橫' : '直';
  localStorage.setItem('ocr_vert', v ? '1' : '0');
}
document.addEventListener('DOMContentLoaded', () => {
  applyTzoom();
  if(localStorage.getItem('ocr_vert') === '1'){
    document.getElementById('txt').classList.add('vert');
    document.getElementById('vertbtn').textContent = '橫';
  }
});

document.addEventListener('keydown', e => {
  if((e.ctrlKey||e.metaKey) && e.key==='s'){ e.preventDefault(); save(); }
  if(e.altKey && e.key==='ArrowLeft'){ e.preventDefault(); goPrev(); }
  if(e.altKey && e.key==='ArrowRight'){ e.preventDefault(); goNext(); }
  if(e.altKey && (e.key==='+' || e.key==='=')){ e.preventDefault(); zoom(1); }
  if(e.altKey && (e.key==='-' || e.key==='_')){ e.preventDefault(); zoom(-1); }
  if(e.altKey && e.key==='0'){ e.preventDefault(); zoomReset(); }
  if(e.ctrlKey && e.shiftKey && (e.key==='+' || e.key==='=')){ e.preventDefault(); tzoom(1); }
  if(e.ctrlKey && e.shiftKey && (e.key==='-' || e.key==='_')){ e.preventDefault(); tzoom(-1); }
  if(e.ctrlKey && e.shiftKey && (e.key==='V' || e.key==='v')){ e.preventDefault(); toggleVert(); }
});

// Ctrl+wheel zoom on image
document.addEventListener('wheel', e => {
  const imgwrap = document.getElementById('imgwrap');
  if(imgwrap && imgwrap.contains(e.target) && e.ctrlKey){
    e.preventDefault();
    zoom(e.deltaY < 0 ? 1 : -1);
  }
}, {passive: false});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- routes
def get_pages():
    return scan_pages(TXT_DIR, IMG_DIR)


@app.route('/')
def index():
    pages = get_pages()
    if not pages:
        return f'<p>{TXT_DIR} 與 {IMG_DIR} 裡沒有可校對的檔案。</p>'
    idx = max(0, min(len(pages) - 1, int(request.args.get('idx', 0))))
    p = pages[idx]
    text = p['txt'].read_text(encoding='utf-8', errors='replace') if p['txt'].exists() else ''
    return render_template_string(
        INDEX_HTML,
        idx=idx,
        total=len(pages),
        filename=p['txt'].name,
        text=text,
        img_exists=p['img'] is not None,
        page_list=[{'label': sl, 'full': q['label'], 'has_img': q['img'] is not None,
                    'has_txt': q['txt'].exists()}
                   for q, sl in zip(pages, short_labels(pages))],
    )


@app.route('/img')
def img():
    pages = get_pages()
    idx = int(request.args.get('idx', 0))
    if idx < 0 or idx >= len(pages) or not pages[idx]['img']:
        abort(404)
    return send_file(str(pages[idx]['img']))


@app.route('/save', methods=['POST'])
def save():
    data = request.get_json(force=True)
    pages = get_pages()
    idx = int(data.get('idx', -1))
    if idx < 0 or idx >= len(pages):
        return jsonify(ok=False, error='page out of range'), 400
    target = pages[idx]['txt']
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 一律存成 \n 換行: 避免 Windows 存檔時換行變成 \r\n, 收回來整份都是 diff
        text = data.get('text', '').replace('\r\n', '\n').replace('\r', '\n')
        with open(target, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        return jsonify(ok=True, path=str(target))
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


def pick_port(host, port):
    """指定的 port 被占用時(例如 macOS 的 AirPlay 佔 5000), 改用系統給的空 port。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return port
        except OSError:
            s.bind((host, 0))
            return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser(description='OCR 校對工具')
    ap.add_argument('--port', type=int, default=5000)
    ap.add_argument('--host', default='127.0.0.1', help='預設只開本機; 要給同網段用才改 0.0.0.0')
    ap.add_argument('--no-browser', action='store_true', help='不要自動開瀏覽器')
    args = ap.parse_args()

    port = pick_port(args.host, args.port)
    url = f'http://{"127.0.0.1" if args.host in ("0.0.0.0", "127.0.0.1") else args.host}:{port}/'
    print('OCR 校對工具')
    print(f'文字: {TXT_DIR}')
    print(f'圖片: {IMG_DIR}')
    print(f'{len(get_pages())} 頁, 開啟瀏覽器: {url}')
    print('要結束時, 關掉這個視窗 (或按 Ctrl+C)')
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host=args.host, port=port, debug=False)


if __name__ == '__main__':
    main()
