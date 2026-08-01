#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מסנכרן את תוכן שלושת דפי הנחיתה מקובץ ה-Google Docs.
הרצה: python scripts/sync_content.py
פלט: data/content.json (נטען דינמית ב-3 דפי ה-HTML דרך js/content-loader.js)

שלבים:
1. מוריד את טקסט המסמך (export?format=txt) דרך curl.
2. מפרק לשלושה נושאים (economy / polls / media) ובתוכם: פסקת פתיחה, מדיה, כתבות.
3. לכל כתבה/קישור מדיה - מנסה לשלוף כותרת ותמונה מייצגת (og:title / og:image)
   מהעמוד המקורי, ומוריד+גוזר את התמונה ל-16:9 לתוך assets/images/<topic>/.
4. ממזג עם data/overrides.json (עדכונים ידניים שלא קיימים במסמך, כמו קישור שהוחלף).
5. כותב את data/content.json הסופי.
"""

import json
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
IMAGES_DIR = ROOT / "assets" / "images"
DOC_ID = "1_W-j2bjlCNfmcpmKQMpm8PcLuhKibC1NWrHE1M7LONg"
DOC_TXT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

HEADERS = {
    "economy": r"^כלכלת בחירות-\s*$",
    "polls": r"^סקרי\s*ם?\s*בחירות-\s*$",
    "media": r"^תקשורת ומסגור\s*-\s*$",
}

DOMAIN_LABELS = {
    "globes.co.il": "גלובס",
    "calcalist.co.il": "כלכליסט",
    "mako.co.il": "מאקו · N12",
    "mekomit.co.il": "שיחה מקומית",
    "idi.org.il": "המכון הישראלי לדמוקרטיה",
    "mida.org.il": "מידה",
    "shakuf.co.il": "שקוף",
    "ice.co.il": "Ice",
    "kan.org.il": "כאן",
    "facebook.com": "פייסבוק",
    "open.spotify.com": "ספוטיפיי",
    "youtube.com": "יוטיוב",
    "youtu.be": "יוטיוב",
}

URL_RE = re.compile(r"https?://\S+")


def curl_bytes(url, timeout=15):
    try:
        res = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", UA, url],
            capture_output=True, check=False,
        )
        return res.stdout
    except FileNotFoundError:
        print("שגיאה: curl לא נמצא בנתיב (PATH). נדרש כדי להריץ את הסקריפט.", file=sys.stderr)
        sys.exit(1)


def fetch_doc_text():
    data = curl_bytes(DOC_TXT_URL, timeout=20)
    text = data.decode("utf-8", errors="ignore")
    text = text.lstrip("﻿")
    if not text.strip():
        print("שגיאה: לא הצלחתי להוריד את תוכן המסמך. יש לוודא שהמסמך משותף לצפייה ('כל מי שיש לו את הקישור').", file=sys.stderr)
        sys.exit(1)
    return text


def split_topics(text):
    positions = []
    for topic, pattern in HEADERS.items():
        m = re.search(pattern, text, re.MULTILINE)
        if m:
            positions.append((m.start(), m.end(), topic))
    positions.sort()
    blocks = {}
    for i, (start, end, topic) in enumerate(positions):
        block_end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        blocks[topic] = text[end:block_end]
    return blocks


def split_sections(block):
    intro_m = re.search(r"^פסקת פתיחה-\s*$", block, re.MULTILINE)
    media_m = re.search(r"^קטע[^\n]*?-", block, re.MULTILINE)
    articles_m = re.search(r"^קרוסלת כתבות-\s*$", block, re.MULTILINE)

    intro_text, media_text, articles_text = "", "", ""

    if intro_m:
        end = media_m.start() if media_m else (articles_m.start() if articles_m else len(block))
        intro_text = block[intro_m.end():end].strip()

    if media_m:
        end = articles_m.start() if articles_m else len(block)
        media_text = block[media_m.end():end].strip()

    if articles_m:
        articles_text = block[articles_m.end():].strip()

    return intro_text, media_text, articles_text


def domain_of(url):
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def label_for_domain(url):
    d = domain_of(url)
    for key, label in DOMAIN_LABELS.items():
        if key in d:
            return label
    return d or "קישור"


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip(" \t\n-–—")


def extract_items(raw_text):
    """מפצל בלוק טקסט (מדיה/כתבות) לפריטים, לפי מיקום כתובות URL.
    בדרך כלל הטקסט שלפני ה-URL הוא המטא-דאטה; אם הוא ריק (כמו קישור
    בודד ואחריו הערה על אותה שורה), נופלים חזרה לטקסט שבא מיד אחריו."""
    urls = list(URL_RE.finditer(raw_text))
    items = []
    prev_end = 0
    for i, m in enumerate(urls):
        url = m.group(0).rstrip(").,‏‎\"'")
        before = raw_text[prev_end:m.start()]
        prev_end = m.end()
        meta = before
        if not clean(before):
            after_end = urls[i + 1].start() if i + 1 < len(urls) else len(raw_text)
            after = raw_text[m.end():after_end]
            stripped = after.strip()
            meta = stripped.splitlines()[0] if stripped else ""
        items.append({"url": url, "meta_raw": meta})
    return items


def parse_meta(meta_raw):
    meta = clean(meta_raw)
    meta = re.sub(r"^\d+\.\s*", "", meta)  # "1. " numbering
    quote_m = re.search(r'"([^"]{2,140})"', meta)
    title, tag, desc = None, None, None
    if quote_m:
        title = quote_m.group(1).strip()
        tag = clean(meta[:quote_m.start()]).strip(" –-")
        desc = clean(meta[quote_m.end():])
        desc = re.sub(r"^\(.*?\)\s*", "", desc)
        if len(desc) > 240:
            desc = desc[:237].rstrip() + "…"
    elif meta:
        tag = meta
    return title, tag or None, desc or None


def media_type_for(url):
    d = domain_of(url)
    if "open.spotify.com" in d:
        return "spotify"
    if "youtube.com" in d or "youtu.be" in d:
        return "youtube"
    return "link"


def spotify_embed(url):
    m = re.search(r"/(episode|track|show)/([A-Za-z0-9]+)", url)
    if not m:
        return None
    return f"https://open.spotify.com/embed/{m.group(1)}/{m.group(2)}?utm_source=generator"


def youtube_embed(url):
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]+)", url) or re.search(r"[?&]v=([A-Za-z0-9_-]+)", url) or re.search(r"youtube\.com/embed/([A-Za-z0-9_-]+)", url)
    if not m:
        return None
    return f"https://www.youtube.com/embed/{m.group(1)}"


def fetch_og(url):
    """מחזיר (title, image_url) מתוך מטא-תגיות og: של העמוד, best-effort."""
    html = curl_bytes(url, timeout=15)
    if not html or len(html) < 200:
        return None, None
    title_m = re.search(rb'<meta property="og:title"[^>]*content="([^"]+)"', html)
    image_m = re.search(rb'<meta property="og:image"[^>]*content="([^"]+)"', html)
    title = title_m.group(1).decode("utf-8", errors="ignore") if title_m else None
    image = image_m.group(1).decode("utf-8", errors="ignore") if image_m else None
    if title:
        title = (title.replace("&quot;", '"').replace("&amp;", "&")
                      .replace("&#39;", "'"))
    if image:
        image = image.replace("&amp;", "&")
    return title, image


def save_cropped_image(image_url, dest_path):
    raw = curl_bytes(image_url, timeout=15)
    if not raw or len(raw) < 500:
        return False
    try:
        img = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        return False
    target_ratio = 16 / 9
    w, h = img.size
    cur_ratio = w / h
    if cur_ratio > target_ratio:
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, h))
    else:
        new_h = int(w / target_ratio)
        y0 = (h - new_h) // 2
        img = img.crop((0, y0, w, y0 + new_h))
    img = img.resize((800, 450))
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest_path, quality=85)
    return True


def placeholder_image(dest_path, text):
    if dest_path.exists():
        return
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (800, 450), "#0f2942")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 410, 800, 450], fill="#b8925a")
    try:
        font = ImageFont.truetype("arial.ttf", 30)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((800 - w) / 2, (410 - h) / 2), text, fill="white", font=font)
    img.save(dest_path, quality=85)


def build_media_items(topic, media_text, fallback_meta):
    items = extract_items(media_text)
    result = []
    for idx, it in enumerate(items, start=1):
        url = it["url"]
        title, tag, desc = parse_meta(it["meta_raw"])
        mtype = media_type_for(url)
        entry = {"type": mtype, "url": url}

        if mtype == "spotify":
            entry["embed"] = spotify_embed(url)
            entry["label"] = title or tag or "פודקאסט"
        elif mtype == "youtube":
            entry["embed"] = youtube_embed(url)
            entry["label"] = title or tag or "סרטון"
        else:
            fb = fallback_meta.get(url, {})
            og_title, og_image = fetch_og(url)  # תמיד שולפים - נדרש כדי לקבל תמונה מייצגת
            entry["label"] = title or tag or og_title or fb.get("title") or label_for_domain(url)
            entry["tag"] = label_for_domain(url)
            img_path = IMAGES_DIR / topic / f"media{idx}.jpg"
            got = False
            if og_image:
                got = save_cropped_image(og_image, img_path)
            if not got and fb.get("image"):
                got = save_cropped_image(fb["image"], img_path)
            placeholder_image(img_path, entry["label"][:20])
            entry["image"] = f"assets/images/{topic}/media{idx}.jpg"
        if desc:
            entry["desc"] = desc
        result.append(entry)
    return result


def build_articles(topic, articles_text, fallback_meta):
    items = extract_items(articles_text)
    result = []
    for idx, it in enumerate(items, start=1):
        url = it["url"]
        title, tag, desc = parse_meta(it["meta_raw"])
        fb = fallback_meta.get(url, {})
        og_title, og_image = fetch_og(url)  # תמיד שולפים - נדרש כדי לקבל תמונה מייצגת
        final_title = title or fb.get("title") or og_title or "כתבה"
        final_tag = tag or label_for_domain(url)

        img_path = IMAGES_DIR / topic / f"article{idx}.jpg"
        got = False
        if og_image:
            got = save_cropped_image(og_image, img_path)
        if not got and fb.get("image"):
            got = save_cropped_image(fb["image"], img_path)
        placeholder_image(img_path, final_title[:20])

        entry = {
            "url": url,
            "tag": final_tag,
            "title": final_title,
            "image": f"assets/images/{topic}/article{idx}.jpg",
        }
        if desc:
            entry["desc"] = desc
        result.append(entry)
    return result


def deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = deep_merge(base.get(k), v) if k in base else v
        return out
    return override if override is not None else base


def main():
    print("מוריד את תוכן המסמך...")
    text = fetch_doc_text()
    blocks = split_topics(text)

    overrides_path = DATA_DIR / "overrides.json"
    overrides = {}
    fallback_meta_by_topic = {}
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        fallback_meta_by_topic = overrides.get("_article_meta_fallback", {})

    content = {}
    for topic in ["economy", "polls", "media"]:
        raw = blocks.get(topic, "")
        intro, media_text, articles_text = split_sections(raw)
        print(f"מעבד נושא: {topic} ...")
        fallback_meta = {u: m for u, m in fallback_meta_by_topic.get(topic, {}).items()}
        media_items = build_media_items(topic, media_text, fallback_meta)
        articles = build_articles(topic, articles_text, fallback_meta)
        content[topic] = {
            "intro": intro,
            "media": media_items,
            "articles": articles,
        }

    topic_overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
    for topic, ov in topic_overrides.items():
        content[topic] = deep_merge(content.get(topic, {}), ov)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "content.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("בוצע! נכתב לקובץ data/content.json")


if __name__ == "__main__":
    main()
