# chr3 — سيرفر MCP لخدمة التراث

سيرفر MCP واحد يغطي كل خدمات التراث على GitHub Pages — يعمل عن بُعد بلا تنزيل، أو محلياً بلا إنترنت من نسخة الريبوهات.

## التثبيت لأي عميل MCP

```json
{
  "mcpServers": {
    "turath": {
      "command": "python3",
      "args": ["/path/to/turath_mcp.py"]
    }
  }
}
```
المتطلبات: `pip install mcp`

## الأدوات

| الأداة | الوصف |
|---|---|
| `list_sciences()` | كل العلوم وعناوين فهارسها |
| `list_books(science)` | كتالوج كتب العلم (id/title/author/nparts) |
| `get_toc(science, book_id)` | فهرس كتاب: [{i,t,d,pg}] |
| `get_part(science, book_id, part)` | نص جزء: {i,t,pg,b,text} |
| `get_tafsir(surah, ayah)` | تفسير آية من كل الطبعات الـ41 |
| `get_hadith(category, id)` | حديث + كل مقاطع شروحه |

العلوم (`science`): `maliki tarajim tari5 sirah ossoul 3olomQuran 9awa3idFi9h akida tazkia` — و`tafsir`/`hadith` عبر الأداتين المخصصتين.

## الوضع المحلي (بلا إنترنت)

انسخ ريبوهات الخدمة (مثلاً `maliki` و`sirah`...) في جذر واحد ثم:
```
TURATH_LOCAL=/path/to/root python3 turath_mcp.py
```
يقرأ `<root>/<repo>/api/...` مباشرة بدل HTTP — نفس الأدوات، نفس الأجوبة.

حقل `b` في الأجزاء: `m` علامة مصدرية دقيقة، `t` مطابقة نص العنوان، `a` تقريبي عند بداية الصفحة (لا نقص).
