"""
Daily Reddit fetcher (RSS version).

Runs once a day via GitHub Actions. Pulls each subreddit's public RSS feed
(no API key, no Reddit account needed) and outputs the previous 10am-to-10am
PT window of posts to data/pending_posts.json.

RSS gives us: id, title, body excerpt, link, author, posted time.
RSS does NOT give us: score, comment count, upvote ratio.
Those fields are set to null/0; the dashboard handles missing engagement gracefully.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

SUBREDDITS = ["webtoons", "webtoon", "WebtoonCanvas", "LINEwebtoon"]
PT = timezone(timedelta(hours=-7))  # PDT (use -8 for PST roughly Nov-Mar)
USER_AGENT = os.environ.get("USER_AGENT", "canvas-monitor/1.0 (+https://github.com)")

ATOM_NS = "{http://www.w3.org/2005/Atom}"
OUT_PATH = Path(__file__).parent.parent / "data" / "pending_posts.json"


def fetch_rss(subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit=100"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/xml, text/xml",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse_atom(xml_text, subreddit):
    """Parse an Atom feed into a list of post dicts."""
    root = ET.fromstring(xml_text)
    posts = []
    for entry in root.findall(ATOM_NS + "entry"):
        # id looks like "t3_abc123" — strip prefix
        id_elem = entry.find(ATOM_NS + "id")
        full_id = id_elem.text if id_elem is not None else None
        post_id = full_id.split("_", 1)[-1] if full_id else None

        title_elem = entry.find(ATOM_NS + "title")
        title = (title_elem.text or "").strip() if title_elem is not None else ""

        published_elem = entry.find(ATOM_NS + "published")
        published = published_elem.text if published_elem is not None else None
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
        except Exception:
            dt = None
        if dt is None:
            continue
        created_utc = int(dt.timestamp())

        link_elem = entry.find(ATOM_NS + "link")
        link = link_elem.get("href") if link_elem is not None else ""

        # Author: <author><name>/u/username</name></author>
        author = None
        author_elem = entry.find(ATOM_NS + "author")
        if author_elem is not None:
            name_elem = author_elem.find(ATOM_NS + "name")
            if name_elem is not None and name_elem.text:
                author = name_elem.text.strip()
                if author.startswith("/u/"):
                    author = author[3:]

        # Content: HTML blob. Strip tags for selftext excerpt.
        content_elem = entry.find(ATOM_NS + "content")
        content_html = content_elem.text if (content_elem is not None and content_elem.text) else ""
        text = re.sub(r"<[^>]+>", " ", content_html)
        text = re.sub(r"\s+", " ", text).strip()
        # The RSS content includes "submitted by /u/X to /r/Y [link][comments]" prefix/suffix.
        # Trim common boilerplate.
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
            "created_pt": datetime.fromtimestamp(created_utc, tz=PT).isoformat(),
            # Engagement metrics not available via RSS — left as None / 0
            "score": None,
            "num_comments": None,
            "upvote_ratio": None,
            # Sentiment / keywords / summary_ko filled in by Cowork scheduled task.
            "sentiment": None,
            "keywords": [],
            "summary_ko": None,
        })
    return posts


def main():
    now_pt = datetime.now(PT)
    today_pt = now_pt.date()
    window_start_pt = datetime.combine(today_pt - timedelta(days=1), datetime.min.time()).replace(hour=10, tzinfo=PT)
    window_end_pt = datetime.combine(today_pt, datetime.min.time()).replace(hour=10, tzinfo=PT)
    window_start_utc = int(window_start_pt.timestamp())
    window_end_utc = int(window_end_pt.timestamp())
    bucket_date = today_pt.isoformat()

    print(f"PT now: {now_pt.isoformat()}")
    print(f"Window: {window_start_pt.isoformat()} -> {window_end_pt.isoformat()}")

    collected = []
    for sub in SUBREDDITS:
        time.sleep(1.5)  # Be polite
        try:
            xml_text = fetch_rss(sub)
        except urllib.error.HTTPError as e:
            print(f"WARN: r/{sub} HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"WARN: r/{sub} failed: {e}", file=sys.stderr)
            continue

        try:
            posts = parse_atom(xml_text, sub)
        except ET.ParseError as e:
            print(f"WARN: r/{sub} feed parse error: {e}", file=sys.stderr)
            print(f"  First 500 chars of response: {xml_text[:500]}", file=sys.stderr)
            continue

        in_window = 0
        for p in posts:
            cu = p["created_utc"]
            if cu < window_start_utc or cu >= window_end_utc:
                continue
            p["bucket_date"] = bucket_date
            collected.append(p)
            in_window += 1
        print(f"r/{sub}: {in_window} posts in window (of {len(posts)} in feed)")

    output = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "fetched_at_pt": now_pt.isoformat(),
        "bucket_date": bucket_date,
        "window_start_pt": window_start_pt.isoformat(),
        "window_end_pt": window_end_pt.isoformat(),
        "subreddits": SUBREDDITS,
        "source": "reddit-rss",
        "posts": collected,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(collected)} posts to {OUT_PATH}")


if __name__ == "__main__":
    main()
