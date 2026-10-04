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
import collections
import concurrent.futures
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
    أإآٱ→ا, ى→ي, ئ→ي, ؤ→و, ة→ه. Prefixes (ال/و/ف..) are NOT
    stripped — pass your own variants to search_text."""
    s = _HARAKAT.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    return s.replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و").replace("ة", "ه")


def _fetch(path: str, repo: str):
    key = (repo, path)
    if key in _CACHE:
        return _CACHE[key]
    if LOCAL:
        p = os.path.join(LOCAL, repo, "api", path)
        try:
            if p.endswith(".json.gz"):
                with gzip.open(p, "rt", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
        except FileNotFoundError:
            if path.startswith(("idx/", "idxm/")):
                data = {}
            else:
                raise
    else:
        url = f"{BASE}/{repo}/api/{urllib.parse.quote(path)}"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                raw = r.read()
            data = json.loads(gzip.decompress(raw) if path.endswith(".json.gz") else raw)
        except urllib.error.HTTPError as e:
            if e.code == 404 and path.startswith(("idx/", "idxm/")):
                data = {}  # shard absent -> word absent from corpus
            else:
                raise
    _CACHE[key] = data
    return data


def list_sciences():
    """All sciences and their repos. Returns [{science, repo, index_url}]."""
    return [{"science": s, "repo": r, "index_url": f"{BASE}/{r}/api/index.json"}
            for s, r in SCIENCES.items()]


def describe_service(science: str = None):
    """The service's own machine-readable doc block (_api in index.json):
    endpoints, field meanings, boundary flags, hints. Read this first.
    science=None returns all sciences' blocks."""
    if science is None:
        return {s: _fetch("index.json", r).get("_api") for s, r in SCIENCES.items()}
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


_PREFIXES = ("ال", "و", "ف", "ب", "ل", "ك", "س")


def _variants(w: str):
    """Conservative query-side expansion: strip one/two leading clitics
    (ال/و/ف/ب/ل/ك/س) and re-attach the bare form — does NOT touch the index."""
    out = {w}
    for i in (1, 2):
        if len(w) > i + 3 and w[:i] in _PREFIXES:
            out.add(w[i:])
    if not w.startswith("ال") and len(w) > 3:
        out.add("ال" + w)
    return out


def _books_meta(repo):
    d = _fetch("index.json", repo)
    return {b["id"]: b for b in d.get("books", [])}


CAT_LABELS = {1: "usul", 2: "maalem", 3: "wajiz", 4: "kulliyya"}

SURAH_NAMES = ["", "الفاتحة", "البقرة", "آل عمران", "النساء", "المائدة", "الأنعام",
    "الأعراف", "الأنفال", "التوبة", "يونس", "هود", "يوسف", "الرعد", "إبراهيم",
    "الحجر", "النحل", "الإسراء", "الكهف", "مريم", "طه", "الأنبياء", "الحج",
    "المؤمنون", "النور", "الفرقان", "الشعراء", "النمل", "القصص", "العنكبوت",
    "الروم", "لقمان", "السجدة", "الأحزاب", "سبأ", "فاطر", "يس", "الصافات",
    "ص", "الزمر", "غافر", "فصلت", "الشورى", "الزخرف", "الدخان", "الجاثية",
    "الأحقاف", "محمد", "الفتح", "الحجرات", "ق", "الذاريات", "الطور", "النجم",
    "القمر", "الرحمن", "الواقعة", "الحديد", "المجادلة", "الحشر", "الممتحنة",
    "الصف", "الجمعة", "المنافقون", "التغابن", "الطلاق", "التحريم", "الملك",
    "القلم", "الحاقة", "المعارج", "نوح", "الجن", "المزمل", "المدثر",
    "القيامة", "الإنسان", "المرسلات", "النبأ", "النازعات", "عبس", "التكوير",
    "الانفطار", "المطففين", "الانشقاق", "البروج", "الطارق", "الأعلى", "الغاشية",
    "الفجر", "البلد", "الشمس", "الليل", "الضحى", "الشرح", "التين", "العلق",
    "القدر", "البينة", "الزلزلة", "العاديات", "القارعة", "التكاثر", "العصر",
    "الهمزة", "الفيل", "قريش", "الماعون", "الكوثر", "الكافرون", "النصر",
    "المسد", "الإخلاص", "الفلق", "الناس"]


def search_text(science: str, words: list, match_all: bool = False, top: int = 50,
                book_ids: list = None, expand: bool = True, snippet: bool = False):
    """Locate text inside a science WITHOUT reading whole books.

    words: surface forms (normalized; pass variants to widen). expand=True
      auto-tries clitic-stripped/ال-attached forms — reported in 'expanded'.
    match_all=False -> union, True -> same-part intersection.
    book_ids=[...] scopes (science books; for hadith it scopes to cat ids 1-4).
    snippet=True fetches top hits and cuts a context window (parallel).

    Science results: {book,part,title,author,score,snippet?} -> get_part().
    Hadith results:  {cat,cat_label,id,score,bab?,snippet?} -> get_hadith()."""
    repo = SCIENCES[science]
    is_hdth = science == "hadith"
    is_quran = science == "tafsir"
    # gather every variant's shard, fetch each shard ONCE in parallel
    word_vars = {w: (_variants(_norm(w)) if expand else {_norm(w)}) for w in words}
    need = {nw[:2] for vs in word_vars.values() for nw in vs if len(nw) >= 2}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        shards = dict(zip(need, ex.map(lambda s: _fetch(f"idx/{s}.json.gz", repo), need)))
    matn_shards = {}
    if is_hdth:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            matn_shards = dict(zip(need, ex.map(
                lambda s: _fetch(f"idxm/{s}.json.gz", repo), need)))
    posts, expanded = {}, {}
    for w, cands in word_vars.items():
        hits = {}
        for nw in cands:
            if len(nw) < 2:
                continue
            v = shards[nw[:2]].get(nw)
            if v:
                hits[nw] = v
        posts[w] = hits
        if len(hits) > 1:
            expanded[w] = sorted(hits)
    missing = [w for w, h in posts.items() if not h]
    if match_all and missing:
        return {"total": 0, "results": [], "missing": missing,
                "note": "word absent from corpus — intersection is empty"}
    if not any(posts.values()):
        return {"total": 0, "results": [], "missing": missing,
                "note": "no postings — try more variants"}
    scope = set(book_ids) if book_ids else None

    capped = {w for w, h in posts.items() if any(isinstance(v, dict) for v in h.values())}

    def all_posts(h):
        for v in h.values():
            if isinstance(v, dict):
                continue
            for bp in v:
                if scope is None or bp[0] in scope:
                    yield tuple(bp)

    if match_all:
        sets = [set(all_posts(h)) for w, h in posts.items() if h]
        hits = set.intersection(*sets) if sets else set()
        if scope and not hits:
            return {"total": 0, "results": [], "missing": missing,
                    "note": "no shared postings in scope"}
        scored = [(h, len(sets)) for h in hits]
    else:
        seen = collections.Counter()
        for h in posts.values():
            for bp in set(all_posts(h)):
                seen[bp] += 1
        scored = list(seen.items())
    scored.sort(key=lambda x: -x[1])
    meta = _books_meta(repo) if not is_hdth and not is_quran else {}
    results = []
    for (b, i), sc in scored[:top]:
        if is_hdth:
            r = {"cat": b, "cat_label": CAT_LABELS.get(b), "id": i, "score": sc}
            r["matn"] = _matn_count((b, i), word_vars, matn_shards)
        elif is_quran:
            r = {"surah": b, "surah_name": SURAH_NAMES[b] if b < len(SURAH_NAMES) else None,
                 "ayah": i, "score": sc}
        else:
            bk = meta.get(b, {})
            r = {"book": b, "part": i, "score": sc,
                 "title": bk.get("title"), "author": bk.get("author")}
        results.append(r)
    out = {"total": len(scored), "results": results, "missing": missing,
           "expanded": expanded, "capped": sorted(capped)}
    if snippet:
        _add_snippets(science, results, posts)
    return out


def _matn_count(loc, word_vars, matn_shards):
    """How many query words appear in this hadith's MATN (via idxm postings)."""
    n = 0
    for w, variants in word_vars.items():
        for nw in variants:
            if len(nw) < 2:
                continue
            v = matn_shards.get(nw[:2], {}).get(nw)
            if v and not isinstance(v, dict) and loc in map(tuple, v):
                n += 1
                break
    return n


def _add_snippets(science, results, posts, width=160):
    variants = [v for h in posts.values() for v in h]

    def snip(r):
        try:
            if science == "hadith":
                d = get_hadith(r["cat"], r["id"])
                r["bab"] = d.get("bab")
                r["n_sharh"] = d.get("n_sharh")
                texts = [d.get("text", "")] + [s.get("text", "") for s in d.get("sharh", [])]
                t = _norm(re.sub(r"<[^>]+>", "", " ".join(texts)))
            elif science == "tafsir":
                q = _fetch(f"quran/{r['surah']:03d}.json.gz", "tfsr")
                t = _norm(q["ayahs"][str(r["ayah"])]["n"])
            else:
                t = _norm(re.sub(r"<[^>]+>", "", get_part(science, r["book"], r["part"])["text"]))
            best = min((t.find(v) for v in variants), key=lambda x: (x < 0, x), default=-1)
            if best >= 0:
                r["snippet"] = t[max(0, best - 40):best + width]
        except Exception:
            pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(snip, results))


def search_phrase(science: str, phrase: str, top: int = 20,
                  book_ids: list = None, width: int = 160):
    """Exact normalized phrase inside a science — candidate parts fetched in
    parallel and verified for containment. Results carry a text snippet around
    the hit plus book title/author. book_ids=[...] scopes candidates."""
    repo = SCIENCES[science]
    ws = [w for w in (_norm(x) for x in phrase.split()) if len(w) >= 2]
    if not ws:
        return {"results": [], "note": "phrase has no searchable words"}
    cand = search_text(science, ws, match_all=True, top=max(top * 4, 40),
                       book_ids=book_ids)
    np_ = " ".join(ws)
    meta = _books_meta(repo) if science not in ("hadith", "tafsir") else {}

    def probe(r):
        try:
            if science == "hadith":
                d = get_hadith(r["cat"], r["id"])
                tm = _norm(re.sub(r"<[^>]+>", "", d.get("text", "")))
                texts = [d.get("text", "")] + [s.get("text", "") for s in d.get("sharh", [])]
                t = _norm(re.sub(r"<[^>]+>", "", " ".join(texts)))
                i = t.find(np_)
                if i < 0:
                    return None
                return {"cat": r["cat"], "cat_label": CAT_LABELS.get(r["cat"]),
                        "id": r["id"], "offset": i, "bab": d.get("bab"),
                        "in_matn": tm.find(np_) >= 0,
                        "snippet": t[max(0, i - 50):i + width]}
            if science == "tafsir":
                q = _fetch(f"quran/{r['surah']:03d}.json.gz", "tfsr")
                t = _norm(q["ayahs"][str(r["ayah"])]["n"])
                i = t.find(np_)
                if i < 0:
                    return None
                return {"surah": r["surah"], "surah_name": SURAH_NAMES[r["surah"]],
                        "ayah": r["ayah"], "offset": i,
                        "snippet": q["ayahs"][str(r["ayah"])]["t"]}
            p = get_part(science, r["book"], r["part"])
        except Exception:
            return None
        t = _norm(re.sub(r"<[^>]+>", "", p["text"]))
        i = t.find(np_)
        if i < 0:
            return None
        bk = meta.get(r["book"], {})
        return {"book": r["book"], "part": r["part"], "offset": i,
                "title": bk.get("title"), "author": bk.get("author"),
                "snippet": t[max(0, i - 50):i + width]}

    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(probe, cand.get("results", [])):
            if res:
                out.append(res)
                if len(out) >= top:
                    break
    return {"total": len(out), "results": out}


def get_tafsir(surah: int, ayah: int, editions: list = None, html: bool = False):
    """Tafsir of one ayah. editions=list of slugs to keep (default: all 41);
    html=False returns plain text field 'p' only (x omitted). Ayahs whose
    tafsir is grouped under another (p empty, g='s:a') auto-resolve to the
    group's text and report 'merged_into'."""
    d = _fetch(f"ayah/{surah}/{ayah}.json.gz", "tfsr")
    out = {"s": d["s"], "a": d["a"], "tafsir": {}}
    for slug, e in d["tafsir"].items():
        if editions and slug not in editions:
            continue
        e = dict(e)
        if not e.get("p") and e.get("g") and e["g"] != f"{surah}:{ayah}":
            try:
                gs, ga = (int(x) for x in e["g"].split(":")[:2])
                pe = _fetch(f"ayah/{gs}/{ga}.json.gz", "tfsr")["tafsir"].get(slug)
                if pe and pe.get("p"):
                    e.update({"p": pe["p"], "x": pe.get("x", ""),
                              "f": pe.get("f"), "t": pe.get("t"),
                              "merged_into": e["g"]})
            except Exception:
                pass
        out["tafsir"][slug] = e if html else {k: e.get(k) for k in
                                              ("g", "f", "t", "p", "merged_into") if k in e or k != "merged_into"}
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


def _all_hadith_records():
    """Every shami record across the 4 cats -> [(cat_int, rec)]."""
    out = []
    for cat, name in enumerate(("usul", "maalem", "wajiz", "kulliyya"), 1):
        for rec in _fetch(f"hadiths/{name}.json.gz", "hdth").values():
            out.append((cat, rec))
    return out


def list_source_babs(source: str = None):
    """Chapter (bab) index of the source books via locs.babs across all cats.

    source=None -> {source_book: n_distinct_babs} (the browsing menu, e.g.
      'صحيح البخاري': 99+ chapters aggregated from all four collections).
    source='صحيح البخاري' -> {'source':..., 'babs':{bab_name: n_hadiths}}
      feed each bab into hadiths_in_bab()."""
    index = {}
    for cat, rec in _all_hadith_records():
        for book, l in (rec.get("locs") or {}).items():
            for bab in (l.get("babs") or []):
                index.setdefault(book, {}).setdefault(bab, 0)
                index[book][bab] += 1
    if source is None:
        return {b: len(v) for b, v in
                sorted(index.items(), key=lambda x: -len(x[1]))}
    return {"source": source, "babs": index.get(source, {}),
            "known_sources": sorted(index)}


def hadiths_in_bab(source: str, bab: str, top: int = 200):
    """Hadiths filed under one bab of a source book (inverse of locs).
    -> [{'cat','cat_label','id','no','hukm','nums','excerpt'}].
    source/bab names from list_source_babs()."""
    out = []
    for cat, rec in _all_hadith_records():
        l = (rec.get("locs") or {}).get(source)
        if not l or bab not in (l.get("babs") or []):
            continue
        nums = l.get("nums") or []
        babs = l.get("babs") or []
        out.append({"cat": cat, "cat_label": CAT_LABELS.get(cat),
                    "id": rec["id"], "no": rec.get("no"),
                    "hukm": rec.get("hukm"),
                    "nums": nums,
                    "excerpt": re.sub(r"<[^>]+>", "",
                                      rec.get("text", ""))[:120]})
        if len(out) >= top:
            break
    return {"source": source, "bab": bab, "total": len(out), "results": out}


def main():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("pip install mcp required", file=sys.stderr)
        sys.exit(1)
    app = FastMCP("turath")
    for t in (list_sciences, describe_service, list_books, get_toc, get_part,
              search_text, search_phrase, get_tafsir, get_tafsir_surah,
              list_hadiths, get_hadith, list_source_babs, hadiths_in_bab):
        app.tool()(t)
    app.run()


if __name__ == "__main__":
    main()
