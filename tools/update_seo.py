#!/usr/bin/env python3
"""Regenerate Prankster News sitemaps, the RSS feed, and page SEO tags.

Usage (from the site root):

    python3 tools/update_seo.py

Reads stories/*.html for headlines, descriptions, images, and the visible
byline timestamp. Rewrites canonical, social, and NewsArticle JSON-LD tags
in each page <head>, adds any published story missing from the archive
listing, and writes:

    sitemap.xml        every public page, clean URLs, lastmod from the story date
    sitemap-news.xml   Google News sitemap of stories published in the last 48 hours
    feed.xml           RSS 2.0 of the 30 newest stories

image-choices.html and the science.html redirect stub are not sitemap entries.
Rerun this after adding a story under stories/.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://pranksternews.com"
OG_IMAGE = f"{SITE}/og.jpg"
OG_ALT = "Prankster News"
PUBLISHER_LOGO = f"{SITE}/apple-touch-icon.png"
FEED_PATH = f"{SITE}/feed.xml"
TWITTER_SITE = "@PranksterNewsHQ"
SITE_NAME = "Prankster News"
AUTHOR_DEFAULT = "Prankster News Staff"
EST = timezone(timedelta(hours=-5))
NEWS_WINDOW = timedelta(days=2)
RSS_LIMIT = 30

MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
MONTH_RE = "|".join(MONTHS)
STAMP_RE = re.compile(
    rf"(?:(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})\s*(?P<ampm>AM|PM)\s+"
    rf"(?:EST|EDT|ET)\s+)?"
    rf"(?P<month>{MONTH_RE})\s+(?P<day>\d{{1,2}}),\s*(?P<year>\d{{4}})",
    re.I,
)

# Public pages that are not stories. kind "section" takes lastmod from the
# newest story linked in <main> (or anywhere on the page if <main> has none).
# kind "static" keeps a fixed lastmod because the page has no story date.
PUBLIC_PAGES = [
    ("index.html", "daily", "1.0", "section"),
    ("world.html", "daily", "0.8", "section"),
    ("us.html", "daily", "0.9", "section"),
    ("politics.html", "weekly", "0.8", "section"),
    ("business.html", "weekly", "0.8", "section"),
    ("tech.html", "weekly", "0.8", "section"),
    ("sports.html", "weekly", "0.8", "section"),
    ("leisure.html", "weekly", "0.8", "section"),
    ("archive.html", "daily", "0.8", "section"),
    ("dog-of-the-month.html", "monthly", "0.6", "section"),
    ("weather.html", "hourly", "0.6", "static"),
    ("games.html", "weekly", "0.8", "static"),
    ("crossword.html", "monthly", "0.5", "static"),
    ("about.html", "yearly", "0.4", "static"),
    ("contact.html", "yearly", "0.4", "static"),
    ("privacy.html", "yearly", "0.4", "static"),
    ("author.html", "yearly", "0.4", "static"),
]
STATIC_LASTMOD = {
    "weather.html": "2026-11-09",
    "games.html": "2026-10-23",
    "crossword.html": "2026-10-23",
    "about.html": "2026-10-23",
    "contact.html": "2026-10-23",
    "privacy.html": "2026-10-23",
    "author.html": "2026-10-23",
}
# Served, but not a public URL of its own: science.html refreshes to weather.
SITEMAP_SKIP = {"science.html", "image-choices.html"}
MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def attr_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
    )


def xml_text(value: str) -> str:
    return xml_escape(value)


def xml_attr(value: str) -> str:
    return xml_escape(value, {'"': "&quot;"})


def split_head(document: str) -> tuple[str, str]:
    match = re.search(r"</head>", document, re.I)
    if not match:
        raise SystemExit("page is missing </head>")
    return document[: match.start()], document[match.start() :]


def clean_url(relpath: str) -> str:
    """Public clean URL for a site-relative HTML path."""
    if relpath == "science.html":
        return f"{SITE}/weather"
    if relpath == "index.html":
        return f"{SITE}/"
    if relpath.endswith(".html"):
        relpath = relpath[: -len(".html")]
    return f"{SITE}/{relpath}"


def absolutize(url: str) -> str:
    url = html.unescape(url).strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    while url.startswith("../"):
        url = url[3:]
    if url.startswith("./"):
        url = url[2:]
    return f"{SITE}/{url.lstrip('/')}"


def meta_pattern(attr: str, key: str) -> re.Pattern[str]:
    return re.compile(
        rf"<meta\s+{attr}\s*=\s*[\"']{re.escape(key)}[\"']\s+"
        rf"content\s*=\s*([\"'])(.*?)\1\s*/?>",
        re.I | re.S,
    )


def get_meta(head: str, attr: str, key: str) -> str | None:
    match = meta_pattern(attr, key).search(head)
    if not match:
        return None
    return html.unescape(match.group(2)).strip()


def set_meta(head: str, attr: str, key: str, value: str) -> str:
    """Update a meta tag's content, or insert the tag if it is missing."""
    pattern = meta_pattern(attr, key)
    match = pattern.search(head)
    escaped = attr_escape(value)
    tag = f'<meta {attr}="{key}" content="{escaped}">'
    if match:
        if html.unescape(match.group(2)).strip() == value:
            return head
        return head[: match.start()] + tag + head[match.end() :]
    return insert_line_before_anchor(head, tag)


def insert_line_after(head: str, pattern: re.Pattern[str], line: str) -> str:
    match = pattern.search(head)
    if not match:
        return insert_line_before_anchor(head, line)
    line_end = head.find("\n", match.end())
    if line_end == -1:
        line_end = len(head)
        prefix = head + "\n"
        line_end = len(prefix) - 1
        head = prefix
    line_start = head.rfind("\n", 0, match.start()) + 1
    indent = re.match(r"[ \t]*", head[line_start:]).group(0)
    return head[:line_end] + "\n" + indent + line + head[line_end:]


def insert_line_before_match(head: str, pattern: re.Pattern[str], line: str) -> str | None:
    match = pattern.search(head)
    if not match:
        return None
    line_start = head.rfind("\n", 0, match.start()) + 1
    indent = re.match(r"[ \t]*", head[line_start:]).group(0)
    return head[:line_start] + indent + line + "\n" + head[line_start:]


def insert_line_before_anchor(head: str, line: str) -> str:
    for pattern in (
        re.compile(r"<link\s+[^>]*rel\s*=\s*[\"'](?:icon|apple-touch-icon)[\"']", re.I),
        re.compile(r"<style\b", re.I),
        re.compile(r"</head>", re.I),
    ):
        inserted = insert_line_before_match(head, pattern, line)
        if inserted is not None:
            return inserted
    if not head.endswith("\n"):
        head += "\n"
    return head + "  " + line + "\n"


def ensure_meta(head: str, attr: str, key: str, value: str, *, after: re.Pattern[str] | None = None, before: re.Pattern[str] | None = None) -> str:
    if get_meta(head, attr, key) is not None:
        return set_meta(head, attr, key, value)
    tag = f'<meta {attr}="{key}" content="{attr_escape(value)}">'
    if before is not None:
        inserted = insert_line_before_match(head, before, tag)
        if inserted is not None:
            return inserted
    if after is not None and after.search(head):
        return insert_line_after(head, after, tag)
    return insert_line_before_anchor(head, tag)


def ensure_canonical(head: str, url: str) -> str:
    pattern = re.compile(
        r"<link\b[^>]*\brel\s*=\s*[\"']canonical[\"'][^>]*>",
        re.I,
    )
    match = pattern.search(head)
    tag = f'<link rel="canonical" href="{attr_escape(url)}">'
    if match:
        return head[: match.start()] + tag + head[match.end() :]
    anchor = re.compile(r"<meta\s+name\s*=\s*[\"']description[\"'][^>]*>", re.I)
    if anchor.search(head):
        return insert_line_after(head, anchor, tag)
    title = re.compile(r"<title\b[^>]*>.*?</title>", re.I | re.S)
    if title.search(head):
        return insert_line_after(head, title, tag)
    return insert_line_before_anchor(head, tag)


def ensure_rss_safe(head: str) -> str:
    pattern = re.compile(
        r"<link\b(?:(?!>).)*application/rss\+xml(?:(?!>).)*>",
        re.I | re.S,
    )
    tag = (
        '<link rel="alternate" type="application/rss+xml" '
        f'title="{SITE_NAME}" href="{FEED_PATH}">'
    )
    match = pattern.search(head)
    if match:
        return head[: match.start()] + tag + head[match.end() :]
    canonical = re.compile(r"<link\b[^>]*\brel\s*=\s*[\"']canonical[\"'][^>]*>", re.I)
    if canonical.search(head):
        return insert_line_after(head, canonical, tag)
    description = re.compile(r"<meta\s+name\s*=\s*[\"']description[\"'][^>]*>", re.I)
    if description.search(head):
        return insert_line_after(head, description, tag)
    title = re.compile(r"<title\b[^>]*>.*?</title>", re.I | re.S)
    if title.search(head):
        return insert_line_after(head, title, tag)
    return insert_line_before_anchor(head, tag)


def get_title(head: str) -> str:
    match = re.search(r"<title\b[^>]*>(.*?)</title>", head, re.I | re.S)
    if not match:
        return SITE_NAME
    return strip_tags(match.group(1))


def to_24_hour(hour: int, ampm: str) -> int:
    ampm = ampm.upper()
    if ampm == "AM":
        return 0 if hour == 12 else hour
    return hour if hour == 12 else hour + 12


def parse_stamp(match: re.Match[str]) -> tuple[datetime, str]:
    year = int(match.group("year"))
    month = MONTHS[match.group("month").title()]
    day = int(match.group("day"))
    if match.group("hour"):
        hour = to_24_hour(int(match.group("hour")), match.group("ampm"))
        minute = int(match.group("minute"))
        published = datetime(year, month, day, hour, minute, tzinfo=EST)
        iso = published.strftime("%Y-%m-%dT%H:%M:%S-05:00")
    else:
        published = datetime(year, month, day, tzinfo=EST)
        iso = published.strftime("%Y-%m-%d")
    return published, iso


class Story:
    def __init__(self, path: Path, document: str) -> None:
        self.path = path
        self.slug = path.stem
        self.relpath = f"stories/{path.name}"
        self.url = clean_url(self.relpath)
        head, _tail = split_head(document)
        self.headline = self._headline(document, head)
        description = get_meta(head, "name", "description")
        if not description:
            raise SystemExit(f"{self.relpath} is missing a meta description")
        self.description = description
        image = get_meta(head, "property", "og:image")
        if not image:
            img = re.search(r'<article\b[^>]*>.*?<img\s+[^>]*src="([^"]+)"', document, re.S)
            if not img:
                raise SystemExit(f"{self.relpath} is missing an image")
            image = img.group(1)
        self.image = absolutize(image)
        byline_html = self._byline_html(document)
        byline_text = strip_tags(byline_html)
        stamp = STAMP_RE.search(byline_text)
        if not stamp:
            raise SystemExit(f"{self.relpath} byline has no publication date: {byline_text!r}")
        self.published, self.iso = parse_stamp(stamp)
        self.display_date = re.sub(
            r"\s*·\s*\d+\s+min read\b.*",
            "",
            byline_text,
            count=1,
            flags=re.I,
        ).strip()
        author = re.search(r'<a\b[^>]*href="[^"]*author\.html"[^>]*>(.*?)</a>', byline_html, re.S)
        self.author = strip_tags(author.group(1)) if author else AUTHOR_DEFAULT
        if not self.author:
            self.author = AUTHOR_DEFAULT

    @staticmethod
    def _headline(document: str, head: str) -> str:
        h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", document, re.S)
        if h1:
            return strip_tags(h1.group(1))
        title = get_title(head)
        suffix = f" – {SITE_NAME}"
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
        return title

    @staticmethod
    def _byline_html(document: str) -> str:
        for match in re.finditer(r'<div class="meta">(.*?)</div>', document, re.S):
            if re.search(r"\d+\s+min read", match.group(1), re.I):
                return match.group(1)
        raise SystemExit("story is missing a byline")


def load_stories() -> list[Story]:
    stories = []
    for path in sorted((ROOT / "stories").glob("*.html")):
        stories.append(Story(path, read_text(path)))
    stories.sort(key=lambda story: (story.published, story.slug), reverse=True)
    return stories


def story_slugs(fragment: str) -> list[str]:
    return re.findall(r"stories/([a-z0-9-]+)\.html", fragment)


def section_lastmod(document: str, by_slug: dict[str, Story]) -> str | None:
    main = re.search(r"<main\b[^>]*>(.*?)</main>", document, re.S | re.I)
    slugs = story_slugs(main.group(1)) if main else []
    if not slugs:
        slugs = story_slugs(document)
    dates = [by_slug[slug].published for slug in slugs if slug in by_slug]
    if not dates:
        return None
    return max(dates).strftime("%Y-%m-%d")


def json_ld(story: Story) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": story.headline,
        "description": story.description,
        "image": story.image,
        "datePublished": story.iso,
        "dateModified": story.iso,
        "author": {"@type": "Organization", "name": story.author},
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "logo": {
                "@type": "ImageObject",
                "url": PUBLISHER_LOGO,
                "width": 180,
                "height": 180,
            },
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": story.url},
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    raw = raw.replace("<", "\\u003c")
    indented = "\n".join("  " + line for line in raw.split("\n"))
    return (
        '  <script type="application/ld+json">\n'
        f"{indented}\n"
        "  </script>\n"
    )


def strip_newsarticle_ld(head: str) -> str:
    pattern = re.compile(
        r"[ \t]*<script\s+type=\"application/ld\+json\">.*?</script>[ \t]*\n?",
        re.S | re.I,
    )

    def replace(match: re.Match[str]) -> str:
        if "NewsArticle" in match.group(0):
            return ""
        return match.group(0)

    return pattern.sub(replace, head)


def update_story_head(head: str, story: Story) -> str:
    head = strip_newsarticle_ld(head)
    head = ensure_canonical(head, story.url)
    head = ensure_rss_safe(head)
    head = ensure_meta(
        head,
        "property",
        "og:site_name",
        SITE_NAME,
        before=re.compile(r"<meta\s+property\s*=\s*[\"']og:title[\"']", re.I),
    )
    image = get_meta(head, "property", "og:image")
    if image:
        head = set_meta(head, "property", "og:image", absolutize(image))
    twitter_image = get_meta(head, "name", "twitter:image")
    if twitter_image:
        head = set_meta(head, "name", "twitter:image", absolutize(twitter_image))
    head = ensure_meta(head, "property", "og:url", story.url)
    head = ensure_meta(
        head,
        "property",
        "og:type",
        "article",
        after=re.compile(r"<meta\s+property\s*=\s*[\"']og:url[\"']", re.I),
    )
    head = ensure_meta(
        head,
        "property",
        "article:published_time",
        story.iso,
        after=re.compile(r"<meta\s+property\s*=\s*[\"']og:type[\"']", re.I),
    )
    head = ensure_meta(head, "name", "twitter:card", "summary_large_image")
    head = ensure_meta(
        head,
        "name",
        "twitter:site",
        TWITTER_SITE,
        after=re.compile(r"<meta\s+name\s*=\s*[\"']twitter:card[\"']", re.I),
    )
    if not head.endswith("\n"):
        head += "\n"
    return head + json_ld(story)


def sync_social_copy(head: str) -> str:
    """Point social title and description at the page's own title and description.

    Section templates were copied between pages, so a few social titles still
    name a different section. Visible page text is left as it is.
    """
    title = get_title(head)
    description = get_meta(head, "name", "description")
    if title and get_meta(head, "property", "og:title") not in (None, title):
        head = set_meta(head, "property", "og:title", title)
    if title and get_meta(head, "name", "twitter:title") not in (None, title):
        head = set_meta(head, "name", "twitter:title", title)
    if description and get_meta(head, "property", "og:description") not in (None, description):
        head = set_meta(head, "property", "og:description", description)
    if description and get_meta(head, "name", "twitter:description") not in (None, description):
        head = set_meta(head, "name", "twitter:description", description)
    return head


def update_page_head(head: str, url: str, *, social: bool) -> str:
    head = ensure_canonical(head, url)
    head = ensure_rss_safe(head)
    if not social:
        return head
    head = sync_social_copy(head)
    title = get_title(head)
    description = get_meta(head, "name", "description")
    head = ensure_meta(
        head,
        "property",
        "og:site_name",
        SITE_NAME,
        before=re.compile(r"<meta\s+property\s*=\s*[\"']og:title[\"']", re.I),
    )
    if get_meta(head, "property", "og:title") is None and title:
        head = ensure_meta(head, "property", "og:title", title)
    if description and get_meta(head, "property", "og:description") is None:
        head = ensure_meta(
            head,
            "property",
            "og:description",
            description,
            after=re.compile(r"<meta\s+property\s*=\s*[\"']og:title[\"']", re.I),
        )
    head = ensure_meta(head, "property", "og:image", OG_IMAGE)
    head = ensure_meta(
        head,
        "property",
        "og:image:width",
        "1200",
        after=re.compile(r"<meta\s+property\s*=\s*[\"']og:image[\"']", re.I),
    )
    head = ensure_meta(
        head,
        "property",
        "og:image:height",
        "630",
        after=re.compile(r"<meta\s+property\s*=\s*[\"']og:image:width[\"']", re.I),
    )
    head = ensure_meta(
        head,
        "property",
        "og:image:alt",
        OG_ALT,
        after=re.compile(r"<meta\s+property\s*=\s*[\"']og:image:height[\"']", re.I),
    )
    head = ensure_meta(
        head,
        "property",
        "og:url",
        url,
        after=re.compile(r"<meta\s+property\s*=\s*[\"']og:image:alt[\"']", re.I),
    )
    head = ensure_meta(
        head,
        "property",
        "og:type",
        "website",
        after=re.compile(r"<meta\s+property\s*=\s*[\"']og:url[\"']", re.I),
    )
    head = ensure_meta(head, "name", "twitter:card", "summary_large_image")
    head = ensure_meta(
        head,
        "name",
        "twitter:site",
        TWITTER_SITE,
        after=re.compile(r"<meta\s+name\s*=\s*[\"']twitter:card[\"']", re.I),
    )
    if get_meta(head, "name", "twitter:title") is None and title:
        head = ensure_meta(
            head,
            "name",
            "twitter:title",
            title,
            after=re.compile(r"<meta\s+name\s*=\s*[\"']twitter:site[\"']", re.I),
        )
    if description and get_meta(head, "name", "twitter:description") is None:
        head = ensure_meta(
            head,
            "name",
            "twitter:description",
            description,
            after=re.compile(r"<meta\s+name\s*=\s*[\"']twitter:title[\"']", re.I),
        )
    head = ensure_meta(head, "name", "twitter:image", OG_IMAGE)
    return head


def ensure_archive_listing(document: str, stories: list[Story]) -> str:
    match = re.search(r'(<ul class="archive-list">)(.*?)(</ul>)', document, re.S)
    if not match:
        raise SystemExit("archive.html is missing ul.archive-list")
    inner = match.group(2)
    listed = set(story_slugs(inner))
    missing = [story for story in stories if story.slug not in listed]
    if not missing:
        return document
    # Newest first, matching the existing list. Insert each missing story
    # before the first entry that is strictly older.
    items = list(re.finditer(r"[ \t]*<li>.*?</li>", inner, re.S))
    by_slug = {story.slug: story for story in stories}
    for story in sorted(missing, key=lambda item: item.published, reverse=True):
        block = (
            "        <li>\n"
            f'          <a href="stories/{story.slug}.html?from=archive">{html.escape(story.headline)}</a>\n'
            f'          <div class="meta">{html.escape(story.display_date)}</div>\n'
            "        </li>"
        )
        insert_at = None
        for item in items:
            slug_match = re.search(r"stories/([a-z0-9-]+)\.html", item.group(0))
            if not slug_match:
                continue
            other = by_slug.get(slug_match.group(1))
            if other and other.published < story.published:
                insert_at = item.start()
                break
        if insert_at is None:
            insert_at = items[-1].end() if items else len(inner)
            inner = inner[:insert_at] + "\n" + block + inner[insert_at:]
        else:
            inner = inner[:insert_at] + block + "\n" + inner[insert_at:]
        items = list(re.finditer(r"[ \t]*<li>.*?</li>", inner, re.S))
    return document[: match.start()] + match.group(1) + inner + match.group(3) + document[match.end() :]


def render_url(loc: str, lastmod: str, changefreq: str, priority: str) -> str:
    return (
        "  <url>\n"
        f"    <loc>{xml_text(loc)}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>{changefreq}</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        "  </url>"
    )


def write_sitemap(stories: list[Story], pages: dict[str, str]) -> None:
    by_slug = {story.slug: story for story in stories}
    chunks = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for relpath, changefreq, priority, kind in PUBLIC_PAGES:
        document = pages[relpath]
        if kind == "section":
            lastmod = section_lastmod(document, by_slug)
            if not lastmod:
                raise SystemExit(f"{relpath} has no story to date the section")
        else:
            lastmod = STATIC_LASTMOD[relpath]
        chunks.append(render_url(clean_url(relpath), lastmod, changefreq, priority))
    for story in stories:
        chunks.append(
            render_url(story.url, story.published.strftime("%Y-%m-%d"), "monthly", "0.6")
        )
    chunks.append("</urlset>\n")
    write_text(ROOT / "sitemap.xml", "\n".join(chunks))


def write_news_sitemap(stories: list[Story]) -> list[Story]:
    cutoff = datetime.now(timezone.utc) - NEWS_WINDOW
    recent = [story for story in stories if story.published >= cutoff]
    chunks = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">',
    ]
    for story in recent:
        published = story.iso
        if "T" not in published:
            published = story.published.strftime("%Y-%m-%dT%H:%M:%S-05:00")
        chunks.append(
            "  <url>\n"
            f"    <loc>{xml_text(story.url)}</loc>\n"
            "    <news:news>\n"
            "      <news:publication>\n"
            f"        <news:name>{xml_text(SITE_NAME)}</news:name>\n"
            "        <news:language>en</news:language>\n"
            "      </news:publication>\n"
            f"      <news:publication_date>{xml_text(published)}</news:publication_date>\n"
            f"      <news:title>{xml_text(story.headline)}</news:title>\n"
            "    </news:news>\n"
            "  </url>"
        )
    chunks.append("</urlset>\n")
    write_text(ROOT / "sitemap-news.xml", "\n".join(chunks))
    return recent


def local_image(url: str) -> tuple[int, str] | None:
    prefix = f"{SITE}/"
    if not url.startswith(prefix):
        return None
    rel = url[len(prefix) :].split("?", 1)[0].split("#", 1)[0]
    path = ROOT / rel
    if not path.is_file():
        return None
    return path.stat().st_size, MIME.get(path.suffix.lower(), "application/octet-stream")


def write_feed(stories: list[Story]) -> None:
    newest = stories[:RSS_LIMIT]
    build = format_datetime(newest[0].published) if newest else format_datetime(datetime.now(EST))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">',
        "  <channel>",
        f"    <title>{xml_text(SITE_NAME)}</title>",
        f"    <link>{SITE}/</link>",
        "    <description>Prankster News delivers current breaking news across world, politics, business, technology, sports, and weather.</description>",
        "    <language>en</language>",
        f"    <lastBuildDate>{xml_text(build)}</lastBuildDate>",
        f'    <atom:link href="{FEED_PATH}" rel="self" type="application/rss+xml"/>',
    ]
    for story in newest:
        lines.append("    <item>")
        lines.append(f"      <title>{xml_text(story.headline)}</title>")
        lines.append(f"      <link>{xml_text(story.url)}</link>")
        lines.append(f'      <guid isPermaLink="true">{xml_text(story.url)}</guid>')
        lines.append(f"      <pubDate>{xml_text(format_datetime(story.published))}</pubDate>")
        lines.append(f"      <description>{xml_text(story.description)}</description>")
        image_info = local_image(story.image)
        if image_info:
            length, mime = image_info
            lines.append(
                f'      <enclosure url="{xml_attr(story.image)}" length="{length}" type="{mime}"/>'
            )
            lines.append(
                f'      <media:content url="{xml_attr(story.image)}" medium="image" type="{mime}"/>'
            )
        else:
            ext = Path(story.image.split("?", 1)[0]).suffix.lower()
            mime = MIME.get(ext, "image/jpeg")
            lines.append(
                f'      <media:content url="{xml_attr(story.image)}" medium="image" type="{mime}"/>'
            )
        lines.append("    </item>")
    lines.append("  </channel>")
    lines.append("</rss>\n")
    write_text(ROOT / "feed.xml", "\n".join(lines))


def update_documents(stories: list[Story]) -> dict[str, str]:
    by_path = {story.relpath: story for story in stories}
    pages: dict[str, str] = {}
    html_paths = sorted(ROOT.glob("*.html")) + sorted((ROOT / "stories").glob("*.html"))
    for path in html_paths:
        relpath = path.relative_to(ROOT).as_posix()
        document = read_text(path)
        head, tail = split_head(document)
        if relpath.startswith("stories/"):
            head = update_story_head(head, by_path[relpath])
        elif relpath == "image-choices.html":
            head = ensure_rss_safe(head)
        else:
            head = update_page_head(head, clean_url(relpath), social=True)
        document = head + tail
        if relpath == "archive.html":
            document = ensure_archive_listing(document, stories)
        write_text(path, document)
        pages[relpath] = document
    return pages


def main() -> None:
    stories = load_stories()
    pages = update_documents(stories)
    # Section lastmod must see the archive listing after the missing story is added.
    pages["archive.html"] = read_text(ROOT / "archive.html")
    write_sitemap(stories, pages)
    recent = write_news_sitemap(stories)
    write_feed(stories)
    print(f"stories: {len(stories)}")
    print(f"news sitemap: {len(recent)}")
    for story in recent:
        print(f"  {story.iso} {story.slug}")
    print(f"feed: {min(RSS_LIMIT, len(stories))}")
    missing_archive = [
        story.slug
        for story in stories
        if story.slug not in story_slugs(pages["archive.html"])
    ]
    if missing_archive:
        print("still missing from archive:", ", ".join(missing_archive))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
