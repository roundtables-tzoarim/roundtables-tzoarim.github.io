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


def spotify_uri(url):
    """spotify:episode:ID וכו' - נדרש עבור ה-iFrame API (כדי לתמוך בהתחלה מדקה מסוימת)."""
    m = re.search(r"/(episode|track|show)/([A-Za-z0-9]+)", url)
    if not m:
        return None
    return f"spotify:{m.group(1)}:{m.group(2)}"


def youtube_embed(url, start=None, end=None):
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]+)", url) or re.search(r"[?&]v=([A-Za-z0-9_-]+)", url) or re.search(r"youtube\.com/embed/([A-Za-z0-9_-]+)", url)
    if not m:
        return None
    params = []
    if start:
        params.append(f"start={start}")
    if end:
        params.append(f"end={end}")
    qs = ("?" + "&".join(params)) if params else ""
    return f"https://www.youtube.com/embed/{m.group(1)}{qs}"


def parse_time_range(text):
    """מזהה טווח דקות שהוגדר בטקסט החופשי במסמך (למשל 'בין דקה 12:00-14:00' או
    'מההתחלה עד דקה 07:00') ומחזיר (start_seconds, end_seconds) - כל אחד יכול להיות None."""
    if not text:
        return None, None
    m = re.search(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})", text)
    if m:
        start = int(m.group(1)) * 60 + int(m.group(2))
        end = int(m.group(3)) * 60 + int(m.group(4))
        return start, end
    m = re.search(r"עד\s+דקה\s+(\d{1,2}):(\d{2})", text)
    if m:
        return 0, int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"דקה\s+(\d{1,3})\s*[-–]\s*(\d{1,3})", text)
    if m:
        return int(m.group(1)) * 60, int(m.group(2)) * 60
    m = re.search(r"מדקה\s+(\d{1,2})(?::(\d{2}))?", text)
    if m:
        sec = int(m.group(2)) if m.group(2) else 0
        return int(m.group(1)) * 60 + sec, None
    return None, None


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
    """תמונה חלופית נאה (לא סתם תיבה עם טקסט) לכתבות שאין להן תמונה אמיתית
    שניתן היה לשלוף אוטומטית. לא דורסת קובץ קיים - כדי לרענן, מוחקים אותו קודם."""
    if dest_path.exists():
        return
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    navy = (15, 41, 66)
    navy_dark = (10, 29, 47)
    gold = (184, 146, 90)
    gold_light = (212, 175, 122)

    img = Image.new("RGB", (800, 450), navy)
    draw = ImageDraw.Draw(img)

    # גרדיאנט אלכסוני עדין
    for y in range(450):
        t = y / 450
        r = int(navy[0] + (navy_dark[0] - navy[0]) * t)
        g = int(navy[1] + (navy_dark[1] - navy[1]) * t)
        b = int(navy[2] + (navy_dark[2] - navy[2]) * t)
        draw.line([(0, y), (800, y)], fill=(r, g, b))

    # עיגול זהב דקורטיבי בפינה
    draw.ellipse([560, -120, 900, 220], outline=gold, width=3)
    draw.ellipse([600, -60, 820, 160], outline=(*gold, ), width=1)

    # אייקון "כתבה": ריבוע עם קפל פינה + שורות טקסט
    ix, iy, isz = 90, 130, 190
    draw.rounded_rectangle([ix, iy, ix + isz, iy + isz * 1.15], radius=10, outline=gold_light, width=4)
    fold = 34
    draw.polygon([(ix + isz - fold, iy), (ix + isz, iy + fold), (ix + isz - fold, iy + fold)], fill=navy, outline=gold_light)
    line_y = iy + 46
    for i in range(4):
        w_line = isz - 40 if i < 3 else isz - 90
        draw.line([(ix + 20, line_y), (ix + 20 + w_line, line_y)], fill=gold_light, width=4)
        line_y += 28

    draw.rectangle([0, 410, 800, 450], fill=gold)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except Exception:
        font = ImageFont.load_default()
    display_text = text[::-1]  # PIL לא יודע bidi - היפוך ידני כדי שעברית תוצג נכון
    bbox = draw.textbbox((0, 0), display_text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((800 - w) / 2, 410 + (40 - h) / 2), display_text, fill=navy_dark, font=font)
    img.save(dest_path, quality=85)


def build_media_items(topic, media_text, fallback_meta):
    items = extract_items(media_text)
    result = []
    for idx, it in enumerate(items, start=1):
        url = it["url"]
        title, tag, desc = parse_meta(it["meta_raw"])
        mtype = media_type_for(url)
        entry = {"type": mtype, "url": url}

        time_start, time_end = parse_time_range(it["meta_raw"] + " " + (desc or ""))

        if mtype == "spotify":
            entry["uri"] = spotify_uri(url)
            if time_start:
                entry["startAt"] = time_start
            entry["label"] = title or tag or "פודקאסט"
        elif mtype == "youtube":
            entry["embed"] = youtube_embed(url, time_start, time_end)
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
