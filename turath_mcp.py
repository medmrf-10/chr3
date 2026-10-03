#!/usr/bin/env python3
"""
turath_mcp.py — سيرفر MCP واحد لخدمة التراث كلها (medmrf-10 على GitHub Pages).

يعمل بوضعين:
  • عن بُعد (افتراضي): يجلب JSON من https://medmrf-10.github.io/<repo>/api/...
  • محلي بلا إنترنت: عرّف TURATH_LOCAL=<جذر يحوي مجلدات الخدمات> ويقرأ الملفات مباشرة.

التركيب في أي عميل MCP:
  python3 turath_mcp.py            (stdio)
المتطلبات: pip install mcp
"""
import gzip
import io
import json
import os
import sys
import urllib.request

BASE = "https://medmrf-10.github.io"
LOCAL = os.environ.get("TURATH_LOCAL", "").rstrip("/")

# science name -> (repo dir on pages / local folder)
SCIENCES = {
    "tafsir": "tfsr",
    "hadith": "hdth",
    "maliki": "maliki",
    "tarajim": "tarajim",
    "tari5": "tari5",
    "sirah": "sirah",
    "ossoul": "ossoul",
    "3olomQuran": "3olomQuran",
    "9awa3idFi9h": "9awa3idFi9h",
    "akida": "akidaV1",
    "tazkia": "tazkiaV1",
}


def _fetch(path: str, repo: str):
    """Fetch path under api/ for a science repo. Returns parsed JSON."""
    if LOCAL:
        # local mode: <LOCAL>/<repo>/api/<path> (parts live .gz on disk)
        p = os.path.join(LOCAL, repo, "api", path)
        if p.endswith(".json.gz"):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    url = f"{BASE}/{repo}/api/{path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    if path.endswith(".json.gz"):
        data = gzip.decompress(data)
    return json.loads(data)


def list_sciences():
    """كل العلوم المتوفرة وأسماء ريبوهاتها."""
    return [{"science": s, "repo": r, "index_url": f"{BASE}/{r}/api/index.json"} for s, r in SCIENCES.items()]


def list_books(science: str):
    """قائمة كتب علم: id/title/author/death/nparts لكل كتاب."""
    repo = SCIENCES[science]
    return _fetch("index.json", repo)


def get_toc(science: str, book_id: int):
    """فهرس كتاب: [{i,t,d,pg}] — i رقم الجزء المطلوب لـget_part."""
    repo = SCIENCES[science]
    return _fetch(f"books/{book_id}/toc.json", repo)


def get_part(science: str, book_id: int, part: int):
    """نص جزء (عنوان من الفهرس): {i,t,pg,b,text} — b: m دقيق/t مطابقة-نص/a تقريبي."""
    repo = SCIENCES[science]
    return _fetch(f"books/{book_id}/parts/{part:04d}.json.gz", repo)


def get_tafsir(surah: int, ayah: int):
    """تفسير آية من كل الطبعات الـ41 دفعة واحدة."""
    return _fetch(f"ayah/{surah}/{ayah}.json.gz", "tfsr")


def get_hadith(category: int, hadith_id: int):
    """حديث شامي: النص+المرجع+الباب+الحكم+كل مقاطع الشروح."""
    return _fetch(f"hadith/{category}/{hadith_id}.json.gz", "hdth")


def main():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("pip install mcp required", file=sys.stderr)
        sys.exit(1)
    app = FastMCP("turath")
    app.tool()(list_sciences)
    app.tool()(list_books)
    app.tool()(get_toc)
    app.tool()(get_part)
    app.tool()(get_tafsir)
    app.tool()(get_hadith)
    app.run()


if __name__ == "__main__":
    main()
