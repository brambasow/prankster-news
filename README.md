# Prankster News

The public site. Cloudflare Pages should publish this repository with no build step. The site root is this folder.

## SEO feeds

`tools/update_seo.py` rewrites canonical, social, and NewsArticle tags in page heads, and regenerates `sitemap.xml`, `sitemap-news.xml`, and `feed.xml` from `stories/`. After adding a story, run:

```bash
python3 tools/update_seo.py
```

The news sitemap includes stories published in the last 48 hours. The RSS feed lists the 30 newest stories.

## Images

New story images should be about 1280 pixels wide, saved as JPEG, and kept under 250 KB. The hero image on a page can load immediately. Every other image should use `loading="lazy"`.
