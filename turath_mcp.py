#!/usr/bin/env python3
"""
turath_mcp.py — unified MCP server for the Turath static APIs (medmrf-10 GitHub Pages).

Two modes:
  • remote (default): reads JSON over https://medmrf-10.github.io/<repo>/api/...
  • local offline: set TURATH_LOCAL=<root containing the cloned service repos>
    (e.g. /path/to/repos where /path/to/repos/maliki/api/index.json exists)

Install: pip install mcp ; run: python3 turath_mcp.py (stdio)

Service contract (identical across the 9 book sciences):
  index.json -> books/<id>/toc.json -> books/<id>/parts/NNNN.json.gz
Boundary flags: m=source marker (exact) | t=title located in text (exact)
  a=approx (title unfound; text is the claimed page window) | z=zero-length heading.
Part fields: i,t(heading),pg(printed page),j(juz),b(flag),text,fn(footnotes dict).

Arabic URLs must be percent-encoded by the caller (urllib.parse.quote) —
GitHub Pages rejects raw non-ASCII paths with 400.
"""
import gzip
import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = "https://medmrf-10.github.io"
LOCAL = os.environ.get("TURATH_LOCAL", "").rstrip("/")

SCIENCES = {
    "tafsir": "tfsr", "hadith": "hdth", "maliki": "maliki", "tarajim": "tarajim",
    "tari5": "tari5", "sirah": "sirah", "ossoul": "ossoul", "3olomQuran": "3olomQuran",
    "9awa3idFi9h": "9awa3idFi9h", "akida": "akidaV1", "tazkia": "tazkiaV1",
}

_CACHE = {}
_HARAKAT = re.compile(r"[ً-ْٰـ]")
_WORD = re.compile(r"[ء-غف-ي]+")


def _norm(s: str) -> str:
    """Match the index normalization exactly: no diacritics/tatweel,
    أإآٱ→ا, ى→ي, ة→ه. Prefixes (ال/و/ف..) are NOT stripped —
    pass your own variants to search_text."""
    s = _HARAKAT.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    return s.replace("ى", "ي").replace("ة", "ه")


def _fetch(path: str, repo: str):
    key = (repo, path)
    if key in _CACHE:
        return _CACHE[key]
    if LOCAL:
        p = os.path.join(LOCAL, repo, "api", path)
        if p.endswith(".json.gz"):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                data = json.load(f)
        else:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
    else:
        url = f"{BASE}/{repo}/api/{urllib.parse.quote(path)}"
        with urllib.request.urlopen(url, timeout=60) as r:
            raw = r.read()
        data = json.loads(gzip.decompress(raw) if path.endswith(".json.gz") else raw)
    _CACHE[key] = data
    return data


def list_sciences():
    """All sciences and their repos. Returns [{science, repo, index_url}]."""
    return [{"science": s, "repo": r, "index_url": f"{BASE}/{r}/api/index.json"}
            for s, r in SCIENCES.items()]


def describe_service(science: str):
    """The service's own machine-readable doc block (_api in index.json):
    endpoints, field meanings, boundary flags, hints. Read this first."""
    repo = SCIENCES[science]
    return _fetch("index.json", repo).get("_api")


def list_books(science: str):
    """Every book in a science: {id,slug,title,author,death,nparts,betaka,m,t,a,z}."""
    repo = SCIENCES[science]
    return _fetch("index.json", repo)


def get_toc(science: str, book_id: int):
    """A book's own toc: {id,title,author,toc:[{i,t,d,pg,j,sz}]} —
    i is the part index for get_part; sz is approx size in bytes."""
    repo = SCIENCES[science]
    return _fetch(f"books/{book_id}/toc.json", repo)


def get_part(science: str, book_id: int, part: int, offset: int = 0, limit: int = 0):
    """One toc entry's text: {i,t,pg,j,b,text,fn?}. offset/limit (chars) window
    the text for reading around a hit without taking the whole part."""
    repo = SCIENCES[science]
    p = _fetch(f"books/{book_id}/parts/{part:04d}.json.gz", repo)
    if offset or limit:
        full = p["text"]
        p = dict(p)
        p["text"] = full[offset:offset + limit if limit else len(full)]
        p["text_len"] = len(full)
        p["offset"] = offset
    return p


def search_text(science: str, words: list, match_all: bool = False, top: int = 50):
    """Locate text inside a science's books WITHOUT reading whole books.

    words: list of surface forms (they are normalized; pass morphological
      variants to widen: ["صبر","صابر","يصبر"]). match_all=False -> union
      (any word hits), True -> intersection (all words in the same part).
    Returns {total, results:[{book,part}...top], per_word:{w:n}} then use
    get_part(science,book,part) — the part carries b-flag precision."""
    repo = SCIENCES[science]
    posts = {}
    for w in words:
        nw = _norm(w)
        if len(nw) < 2:
            continue
        sh = _fetch(f"idx/{nw[:2]}.json.gz", repo)
        posts[nw] = sh.get(nw)
    found = {w: v for w, v in posts.items() if v}
    missing = [w for w, v in posts.items() if not v]
    if match_all and missing:
        return {"total": 0, "results": [], "missing": missing,
                "note": "word absent from corpus — intersection is empty"}
    if not found:
        return {"total": 0, "results": [], "missing": missing,
                "note": "no postings — try more variants (ال/و/ة/ى spellings)"}
    counts = {w: (v["~"] if isinstance(v, dict) else len(v)) for w, v in found.items()}
    if match_all:
        sets = [set(map(tuple, v)) for w, v in found.items() if not isinstance(v, dict)]
        if len(sets) < len(found):
            return {"total": 0, "results": [], "missing": missing,
                    "per_word": counts,
                    "note": "one word is capped/common — drop it or add rarer words"}
        hits = set.intersection(*sets) if sets else set()
    else:
        hits = set()
        for v in found.values():
            if not isinstance(v, dict):
                hits.update(map(tuple, v))
    results = [{"book": b, "part": i} for b, i in sorted(hits)][:top]
    return {"total": len(hits), "results": results, "missing": missing,
            "per_word": counts}


def search_phrase(science: str, phrase: str, top: int = 20):
    """Exact normalized phrase inside a science. Fetches candidate parts and
    verifies containment — slower but exact. Returns [{book,part,offset}]."""
    repo = SCIENCES[science]
    ws = [w for w in (_norm(x) for x in phrase.split()) if len(w) >= 2]
    if not ws:
        return {"results": [], "note": "phrase has no searchable words"}
    cand = search_text(science, ws, match_all=True, top=200)
    np_ = " ".join(ws)
    out = []
    for r in cand.get("results", []):
        p = get_part(science, r["book"], r["part"])
        t = _norm(re.sub(r"<[^>]+>", "", p["text"]))
        i = t.find(np_)
        if i >= 0:
            out.append({"book": r["book"], "part": r["part"], "offset": i})
            if len(out) >= top:
                break
    return {"total": len(out), "results": out}


def get_tafsir(surah: int, ayah: int, editions: list = None, html: bool = False):
    """Tafsir of one ayah. editions=list of slugs to keep (default: all 41);
    html=False returns plain text field 'p' only (x omitted)."""
    d = _fetch(f"ayah/{surah}/{ayah}.json.gz", "tfsr")
    out = {"s": d["s"], "a": d["a"], "tafsir": {}}
    for slug, e in d["tafsir"].items():
        if editions and slug not in editions:
            continue
        out["tafsir"][slug] = dict(e) if html else {k: e[k] for k in ("g", "f", "t", "p")}
    return out


def get_tafsir_surah(edition_slug: str, surah: int):
    """One edition's tafsir for a whole surah: {ed,s,ayahs:{a:{g,f,t,p,x}}}.
    edition_slug from the editions list in list_books('tafsir')."""
    return _fetch(f"ed/{edition_slug}/s{surah:03d}.json.gz", "tfsr")


def list_hadiths(category):
    """Hadith catalog of one shami category: hadiths/<cat>.json.gz ->
    {id:{id,no,text,reference,bab,hukm,locs}}. cat: 1=usul 2=maalem
    3=wajiz 4=kulliyya — or the name directly."""
    name = {1: "usul", 2: "maalem", 3: "wajiz", 4: "kulliyya"}.get(
        category if isinstance(category, int) else -1, category)
    return _fetch(f"hadiths/{name}.json.gz", "hdth")


def get_hadith(category: int, hadith_id: int):
    """Full hadith record: {id,cat,no,text,reference,bab,hukm,locs,sharh,n_sharh}.
    cat: 1=usul(ids 6000-28738) 2=maalem(1-4324) 3=wajiz(4325-5726)
    4=kulliyya(28739-28889). sharh segs: ok=true verified / ok=false fuzzy."""
    return _fetch(f"hadith/{category}/{hadith_id}.json.gz", "hdth")


def main():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("pip install mcp required", file=sys.stderr)
        sys.exit(1)
    app = FastMCP("turath")
    for t in (list_sciences, describe_service, list_books, get_toc, get_part,
              search_text, search_phrase, get_tafsir, get_tafsir_surah,
              list_hadiths, get_hadith):
        app.tool()(t)
    app.run()


if __name__ == "__main__":
    main()
