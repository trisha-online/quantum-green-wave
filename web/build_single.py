"""Inline the data and scripts into self-contained pages (for hosting as single files):
  web/index.html + data.js + app.js  ->  web/dist/index.html       (the SUMO replay dashboard)
  web/site/index.html + site-data.js ->  web/site/dist/index.html  (the public website)"""
import os

h = os.path.dirname(os.path.abspath(__file__))


def read(*parts):
    with open(os.path.join(h, *parts), encoding="utf-8") as f:
        return f.read()


def inline(folder, scripts):
    html = read(folder, "index.html")
    for name in scripts:
        tag = f'<script src="{name}"></script>'
        if html.count(tag) != 1:
            raise SystemExit(f"{tag} must appear exactly once in {folder or 'web'}/index.html")
        # "</script" inside the inlined code would end the tag early
        html = html.replace(tag, "<script>" + read(folder, name).replace("</script", "<\\/script") + "</script>")
    out = os.path.join(h, folder, "dist")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(os.path.join(folder, "dist", "index.html"), len(html) // 1024, "KB")


inline("", ["data.js", "app.js"])
inline("site", ["site-data.js"])
