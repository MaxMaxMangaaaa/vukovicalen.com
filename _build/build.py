#!/usr/bin/env python3
"""
Build system for vukovicalen.com
Centralizes nav/footer, generates Research dropdown, publishes vault articles.

Usage:
    python _build/build.py              # Rebuild all pages
    python _build/build.py --publish    # Also publish vault articles
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime

# ─── CONFIG ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "_build"
ARTICLES_JSON = ROOT / "research" / "articles.json"
RESEARCH_DIR = ROOT / "research"

# Pages to rebuild (nav/footer injection)
MAIN_PAGES = ["index.html", "about.html", "framegate.html"]

# Active-page mapping: page_name → nav link text
ACTIVE_MAP = {
    "about.html": "about.html",
    "framegate.html": "framegate.html",
}


# ─── HELPERS ─────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_template(name: str) -> str:
    return (BUILD_DIR / name).read_text(encoding="utf-8")


def compute_root(page_path: Path) -> str:
    """Compute relative root prefix for a page.
    index.html → ''  |  research/foo.html → '../'
    """
    rel = page_path.relative_to(ROOT)
    depth = len(rel.parts) - 1  # folders above the file
    if depth == 0:
        return ""
    return "../" * depth


# ─── NAV BUILDER ─────────────────────────────────────────────────────

def build_dropdown_links(articles: dict, categories: dict, root_prefix: str) -> str:
    """Generate the dropdown menu <a> tags from articles.json."""
    lines = []

    # Group by category
    by_cat = {}
    for aid, a in articles.items():
        cat = a.get("category", "other")
        by_cat.setdefault(cat, []).append(a)

    # Sort categories by order
    sorted_cats = sorted(by_cat.items(),
                         key=lambda x: categories.get(x[0], {}).get("order", 999))

    first_cat = True
    for cat_id, cat_articles in sorted_cats:
        cat_meta = categories.get(cat_id, {})

        # Divider between categories (not before first)
        if not first_cat:
            lines.append('                    <div class="dropdown-divider"></div>')

        # Section header (if enabled)
        if cat_meta.get("show_section_header"):
            label = cat_meta.get("label", cat_id)
            lines.append(f'                    <div class="dropdown-section">{label}</div>')

        # Article links
        for a in sorted(cat_articles, key=lambda x: x.get("published", ""), reverse=True):
            href = root_prefix + a["path"]
            title = a["title"]
            lines.append(f'                    <a href="{href}">{title}</a>')

        first_cat = False

    return "\n".join(lines)


def build_nav(articles: dict, categories: dict, root_prefix: str) -> str:
    """Build full <nav> HTML with dropdown links."""
    template = load_template("nav_template.html")
    dropdown = build_dropdown_links(articles, categories, root_prefix)
    nav = template.replace("{DROPDOWN_LINKS}", dropdown)
    nav = nav.replace("{ROOT}", root_prefix)
    return nav


# ─── PAGE REBUILDER ──────────────────────────────────────────────────

def replace_block(html: str, tag: str, replacement: str) -> str:
    """Replace <tag>...</tag> block in HTML."""
    pattern = rf"<{tag}[\s>].*?</{tag}>"
    match = re.search(pattern, html, re.DOTALL)
    if match:
        return html[:match.start()] + replacement + html[match.end():]
    return html


def set_active(html: str, page_name: str) -> str:
    """Set class='active' on the correct nav link."""
    # Remove existing active classes in nav
    html = re.sub(r'(<a\s+[^>]*?)class="active"([^>]*>)', r'\1\2', html)

    if page_name in ACTIVE_MAP:
        target = ACTIVE_MAP[page_name]
        # Add active to the matching href
        html = html.replace(
            f'href="{target}"',
            f'href="{target}" class="active"',
            1
        )
    return html


def rebuild_main_page(page_path: Path, nav_html: str, footer_html: str):
    """Rebuild a main page (index, about, framegate) with new nav/footer."""
    html = page_path.read_text(encoding="utf-8")
    html = replace_block(html, "nav", nav_html)
    html = replace_block(html, "footer", footer_html)
    html = set_active(html, page_path.name)
    page_path.write_text(html, encoding="utf-8")
    print(f"  ✓ {page_path.name}")


# ─── ARTICLE REBUILDER ──────────────────────────────────────────────

def strip_inline_styles(html: str) -> str:
    """Remove all <style>...</style> blocks."""
    return re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)


def extract_body_content(html: str) -> str:
    """Extract content between <body> tags, excluding nav and footer."""
    # Get body content
    body_match = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL)
    if not body_match:
        return html
    body = body_match.group(1)

    # Remove nav
    body = re.sub(r"<nav[\s>].*?</nav>", "", body, flags=re.DOTALL)
    # Remove footer
    body = re.sub(r"<footer[\s>].*?</footer>", "", body, flags=re.DOTALL)

    return body.strip()


def extract_article_content(html: str) -> str:
    """Extract the <article> or <main> content from HTML."""
    # Try to find <article>...</article>
    match = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
    if match:
        content = match.group(1).strip()
    else:
        # Try <main>
        match = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL)
        if match:
            content = match.group(1).strip()
        else:
            # Fallback: body without nav/footer
            content = extract_body_content(html)

    # Remove any stray footer tags from content
    content = re.sub(r"<footer[\s>].*?</footer>", "", content, flags=re.DOTALL)
    return content.strip()


def strip_first_h1(content: str) -> str:
    """Remove the first <h1>...</h1> from content (it's now in the hero)."""
    return re.sub(r"<h1[^>]*>.*?</h1>", "", content, count=1, flags=re.DOTALL).strip()


def strip_document_header(content: str) -> str:
    """Remove .document-header div (replaced by article-hero)."""
    content = re.sub(r'<div\s+class="document-header">.*?</div>', "", content, count=1, flags=re.DOTALL)
    # Also remove standalone meta lines like "Framegate Intelligence | Working Paper..."
    content = re.sub(r'<p[^>]*>\s*<strong>Framegate Intelligence</strong>\s*\|.*?</p>', "", content, count=1, flags=re.DOTALL)
    return content.strip()


def format_date_display(iso_date: str) -> str:
    """Convert 2026-02-13 to February 2026."""
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return dt.strftime("%B %Y")
    except (ValueError, TypeError):
        return iso_date or ""


def fill_template(template: str, meta: dict, nav_html: str, footer_html: str,
                  content: str, root_prefix: str) -> str:
    """Fill article template with all placeholders."""
    # Extract a display title from meta (shorter, reader-friendly)
    display_title = meta.get("og_title", meta.get("title", ""))

    new_html = template
    new_html = new_html.replace("{NAV}", nav_html)
    new_html = new_html.replace("{FOOTER}", footer_html)
    new_html = new_html.replace("{CONTENT}", content)
    new_html = new_html.replace("{ROOT}", root_prefix)
    new_html = new_html.replace("{TITLE}", meta.get("title", ""))
    new_html = new_html.replace("{DISPLAY_TITLE}", display_title)
    new_html = new_html.replace("{SUBTITLE}", meta.get("subtitle", ""))
    new_html = new_html.replace("{DESCRIPTION}", meta.get("description", ""))
    new_html = new_html.replace("{AUTHOR}", meta.get("author", "Alen Vukovic"))
    new_html = new_html.replace("{OG_TITLE}", meta.get("og_title", meta.get("title", "")))
    new_html = new_html.replace("{OG_DESCRIPTION}", meta.get("og_description", meta.get("description", "")))
    new_html = new_html.replace("{PATH}", meta.get("path", ""))
    new_html = new_html.replace("{PUBLISHED}", meta.get("published", ""))
    new_html = new_html.replace("{PUBLISHED_DISPLAY}", format_date_display(meta.get("published", "")))

    # Set active state on Research nav link
    new_html = re.sub(
        r'href="([^"]*atlantic-pulse\.html)"',
        r'href="\1" class="active"',
        new_html,
        count=1
    )
    return new_html


def rebuild_article(article_path: Path, meta: dict, nav_html: str, footer_html: str):
    """Rebuild an existing research article: strip inline CSS, inject nav/footer."""
    html = article_path.read_text(encoding="utf-8")

    # Strip inline styles
    html_clean = strip_inline_styles(html)

    # Extract just the article content
    content = extract_article_content(html_clean)

    # Remove the H1 and document-header (now in the hero section)
    content = strip_first_h1(content)
    content = strip_document_header(content)

    # Build from template
    root_prefix = compute_root(article_path)
    template = load_template("article_template.html")
    new_html = fill_template(template, meta, nav_html, footer_html, content, root_prefix)

    article_path.write_text(new_html, encoding="utf-8")
    print(f"  ✓ {article_path.relative_to(ROOT)} (rebuilt, hero + inline CSS stripped)")


def publish_from_vault(vault_id: str, meta: dict, nav_html: str, footer_html: str):
    """Publish a new article from a Thesis Vault."""
    # Find vault path
    vault_base = ROOT.parent
    vault_dirs = list(vault_base.glob(f"04_THESIS_VAULT/*{vault_id}*"))
    if not vault_dirs:
        # Try the full framegate_assets path
        vault_dirs = list((vault_base / "04_THESIS_VAULT").glob(f"*{vault_id}*"))
    if not vault_dirs:
        print(f"  ✗ Vault not found: {vault_id}")
        return False

    vault_dir = vault_dirs[0]
    sci_dir = vault_dir / "05_outputs" / "scientific"

    # Find HTML file
    html_files = list(sci_dir.glob("FRAMEGATE_WorkingPaper_*.html"))
    if not html_files:
        html_files = list(sci_dir.glob("*.html"))
    if not html_files:
        print(f"  ✗ No HTML found in {sci_dir}")
        return False

    source_html = html_files[0].read_text(encoding="utf-8")
    print(f"  → Source: {html_files[0].name} ({len(source_html)} chars)")

    # Strip inline styles and extract content
    clean = strip_inline_styles(source_html)
    content = extract_article_content(clean)

    # Remove the H1 and document-header (now in the hero section)
    content = strip_first_h1(content)
    content = strip_document_header(content)

    # Build from template
    output_path = ROOT / meta["path"]
    root_prefix = compute_root(output_path)

    # Rebuild nav for this depth
    config = load_json(ARTICLES_JSON)
    nav = build_nav(config["articles"], config["categories"], root_prefix)

    template = load_template("article_template.html")
    footer = load_template("footer_template.html")
    new_html = fill_template(template, meta, nav, footer, content, root_prefix)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(new_html, encoding="utf-8")
    print(f"  ✓ Published: {output_path.relative_to(ROOT)} (from vault {vault_id})")
    return True


# ─── MAIN ────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  vukovicalen.com — Build System v1.0")
    print("=" * 60)

    # 1. Load config
    print("\n[1/4] Loading article registry...")
    config = load_json(ARTICLES_JSON)
    articles = config["articles"]
    categories = config["categories"]
    print(f"  ✓ {len(articles)} articles, {len(categories)} categories")

    # 2. Load templates
    print("\n[2/4] Loading templates...")
    footer_html = load_template("footer_template.html")
    print("  ✓ Templates ready")

    # 3. Rebuild main pages
    print("\n[3/4] Rebuilding main pages...")
    for page_name in MAIN_PAGES:
        page_path = ROOT / page_name
        if not page_path.exists():
            print(f"  ⚠ {page_name} not found, skipping")
            continue
        root_prefix = compute_root(page_path)
        nav_html = build_nav(articles, categories, root_prefix)
        rebuild_main_page(page_path, nav_html, footer_html)

    # 4. Process research articles
    print("\n[4/4] Processing research articles...")
    for aid, meta in articles.items():
        article_path = ROOT / meta["path"]

        # Skip special pages (atlantic-pulse has custom layout)
        if meta.get("skip_rebuild"):
            # Still update nav/footer in special pages
            if article_path.exists():
                html = article_path.read_text(encoding="utf-8")
                root_prefix = compute_root(article_path)
                nav_html = build_nav(articles, categories, root_prefix)
                html = replace_block(html, "nav", nav_html)
                html = replace_block(html, "footer", footer_html)
                # Set Research as active — find the Research nav link
                html = re.sub(r'class="active"', '', html)
                # Match the Research link regardless of prefix
                html = re.sub(
                    r'href="([^"]*atlantic-pulse\.html)"',
                    r'href="\1" class="active"',
                    html,
                    count=1
                )
                article_path.write_text(html, encoding="utf-8")
                print(f"  ✓ {meta['path']} (nav/footer updated, content preserved)")
            continue

        # Check if vault publish
        vault_id = meta.get("vault_id")
        if vault_id:
            publish_from_vault(vault_id, meta, "", footer_html)
            continue

        # Rebuild existing article
        if article_path.exists():
            root_prefix = compute_root(article_path)
            nav_html = build_nav(articles, categories, root_prefix)
            rebuild_article(article_path, meta, nav_html, footer_html)
        else:
            print(f"  ⚠ {meta['path']} not found (no vault_id set)")

    # Done
    print("\n" + "=" * 60)
    print("  ✅ Build complete!")
    print(f"  → git add -A && git commit -m 'Build' && git push")
    print("=" * 60)


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def cmd_publish(vault_id: str, title: str, subtitle: str = "",
                category: str = "us-media-watch", description: str = ""):
    """Register a new vault article and publish it.

    Usage:
        python _build/build.py publish TV:0010 "Article Title" --subtitle "Sub" --category "us-media-watch"
    """
    # Normalize vault_id (accept TV:0010, 0010, etc.)
    vid = vault_id.replace("TV:", "").replace("tv:", "").strip()

    slug = slugify(title)
    path = f"research/{slug}.html"

    print(f"\n  Publishing vault {vid} as '{title}'")
    print(f"  → {path}")

    # Load articles.json
    config = load_json(ARTICLES_JSON)

    # Check if already exists
    if slug in config["articles"]:
        print(f"  ⚠ Article '{slug}' already exists — updating vault_id to {vid}")
        config["articles"][slug]["vault_id"] = vid
    else:
        # Add new entry
        config["articles"][slug] = {
            "title": title,
            "subtitle": subtitle or title,
            "path": path,
            "category": category,
            "published": datetime.now().strftime("%Y-%m-%d"),
            "author": "Alen Vukovic",
            "description": description or title,
            "og_title": title,
            "og_description": description or subtitle or title,
            "vault_id": vid,
            "type": "research_article",
            "skip_rebuild": False,
        }
        print(f"  ✓ Added to articles.json")

    # Ensure category exists
    if category not in config["categories"]:
        config["categories"][category] = {
            "label": category.replace("-", " ").title(),
            "order": len(config["categories"]) + 1,
            "show_section_header": True,
        }
        print(f"  ✓ Added category: {category}")

    # Save
    ARTICLES_JSON.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Now run full build
    main()


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "publish":
        # python _build/build.py publish 0010 "Title" "Subtitle" "category" "description"
        if len(args) < 3:
            print("Usage: python _build/build.py publish <vault_id> <title> [subtitle] [category] [description]")
            print('Example: python _build/build.py publish 0010 "The 4× Gap" "Trump vs. Journalism" "us-media-watch" "93,500 articles analyzed."')
            sys.exit(1)
        vault_id = args[1]
        title = args[2]
        subtitle = args[3] if len(args) > 3 else ""
        category = args[4] if len(args) > 4 else "us-media-watch"
        description = args[5] if len(args) > 5 else ""
        cmd_publish(vault_id, title, subtitle, category, description)
    else:
        main()
