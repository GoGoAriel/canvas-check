"""
One-time backfill: pull as many posts as Reddit RSS will give us (up to 100/sub),
write them to data/pending_posts.json with proper PT bucket_date per post.

Run via the manual workflow `.github/workflows/backfill.yml`.

Notes:
- RSS limit is ~100 posts per subreddit. Active subs (~25 posts/day) cover ~4 days.
  Slower subs (~5 posts/day) cover ~20 days.
- Each post is bucketed to the PT day whose 10am→10am window it falls into.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

SUBREDDITS = ["webtoons", "webtoon", "WebtoonCanvas", "LINEwebtoon"]
PT = timezone(timedelta(hours=-7))
USER_AGENT = os.environ.get("USER_AGENT", "canvas-monitor/1.0 (+https://github.com)")

ATOM_NS = "{http://www.w3.org/2005/Atom}"
OUT_PATH = Path(__file__).parent.parent / "data" / "pending_posts.json"


def bucket_date_of(created_pt: datetime) -> date:
    """A post at T (PT) belongs to bucket D iff (D-1) 10:00 PT <= T < D 10:00 PT."""
    if created_pt.hour >= 10:
        return created_pt.date() + timedelta(days=1)
    return created_pt.date()


def fetch_rss(subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit=100"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/xml, text/xml",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse_atom(xml_text, subreddit):
    root = ET.fromstring(xml_text)
    posts = []
    for entry in root.findall(ATOM_NS + "entry"):
        id_elem = entry.find(ATOM_NS + "id")
        full_id = id_elem.text if id_elem is not None else None
        post_id = full_id.split("_", 1)[-1] if full_id else None

        title_elem = entry.find(ATOM_NS + "title")
        title = (title_elem.text or "").strip() if title_elem is not None else ""

        published_elem = entry.find(ATOM_NS + "published")
        published = published_elem.text if published_elem is not None else None
        try:
            dt_utc = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
        except Exception:
            dt_utc = None
        if dt_utc is None:
            continue
        created_pt = dt_utc.astimezone(PT)
        created_utc = int(dt_utc.timestamp())

        link_elem = entry.find(ATOM_NS + "link")
        link = link_elem.get("href") if link_elem is not None else ""

        author = None
        author_elem = entry.find(ATOM_NS + "author")
        if author_elem is not None:
            name_elem = author_elem.find(ATOM_NS + "name")
            if name_elem is not None and name_elem.text:
                author = name_elem.text.strip()
                if author.startswith("/u/"):
                    author = author[3:]

        content_elem = entry.find(ATOM_NS + "content")
        content_html = content_elem.text if (content_elem is not None and content_elem.text) else ""
        text = re.sub(r"<[^>]+>", " ", content_html)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"submitted by\s+/u/\S+(?:\s+to\s+/r/\S+)?", "", text, flags=re.I)
        text = text.replace("[link]", "").replace("[comments]", "").strip()
        selftext = text[:1500]

        posts.append({
            "id": post_id,
            "subreddit": subreddit,
            "title": title,
            "selftext": selftext,
            "url": link,
            "author": author,
            "created_utc": created_utc,
            "created_pt": created_pt.isoformat(),
            "bucket_date": bucket_date_of(created_pt).isoformat(),
            "score": None,
            "num_comments": None,
            "upvote_ratio": None,
            "sentiment": None,
            "keywords": [],
            "summary_ko": None,
        })
    return posts


def main():
    now_pt = datetime.now(PT)
    print(f"Backfill starting. PT now: {now_pt.isoformat()}")

    collected = []
    for sub in SUBREDDITS:
        time.sleep(1.5)
        try:
            xml_text = fetch_rss(sub)
        except urllib.error.HTTPError as e:
            print(f"WARN: r/{sub} HTTP {e.code}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"WARN: r/{sub} failed: {e}", file=sys.stderr)
            continue
        try:
            posts = parse_atom(xml_text, sub)
        except ET.ParseError as e:
            print(f"WARN: r/{sub} parse error: {e}", file=sys.stderr)
            continue
        collected.extend(posts)
        if posts:
            oldest = min(p["created_pt"] for p in posts)
            newest = max(p["created_pt"] for p in posts)
            print(f"r/{sub}: {len(posts)} posts (oldest={oldest}, newest={newest})")

    # Sort newest first
    collected.sort(key=lambda p: p["created_utc"], reverse=True)

    buckets = sorted({p["bucket_date"] for p in collected})
    output = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "fetched_at_pt": now_pt.isoformat(),
        "subreddits": SUBREDDITS,
        "source": "reddit-rss-backfill",
        "buckets_covered": buckets,
        "posts": collected,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(collected)} posts covering {len(buckets)} bucket days "
          f"({buckets[0]} ~ {buckets[-1]}) to {OUT_PATH}")


if __name__ == "__main__":
    main()
