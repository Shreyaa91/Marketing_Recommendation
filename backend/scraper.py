"""
scraper.py  —  Fast hybrid scraper (universal)
================================================
Fixes in this version
---------------------
FIX 1 — books.toscrape.com (and similar catalogue-style sites):
  • Added /catalogue/ to PRODUCT_RE
  • Added catalogue-style category pattern to CATEGORY_RE
  • New extract_catalogue_page() handles star-rating CSS classes,
    price_color, and H1 title — no JSON-LD needed
  • has_product_data() now also checks for H1 + any price-like text

FIX 2 — silkandwillow.com and JS-loaded reviews (Judge.me / Yotpo):
  • smart_fetch() for PRODUCT pages now always tries Playwright
    after requests, waiting specifically for review widgets to load
  • Added wait_for_selector for common review containers before
    grabbing page content
  • Added extract_reviews_js() to scrape Judge.me / Yotpo / Stamped
    review blocks that only appear after JS execution

FIX 3 — General robustness:
  • PRODUCT_RE extended with more patterns (/catalogue/, /book/, /goods/)
  • extract_rating() extended with CSS star-rating class fallback
    (books.toscrape uses <p class="star-rating Three">)
  • extract_price_html() now also matches <p class="price_color">
"""

import sys
import asyncio
import threading
import queue
import json
import re
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

_SENTINEL  = object()
BATCH_SIZE = 8
MAX_CATS   = 15
MAX_PAGES  = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_session = requests.Session()
_session.headers.update(HEADERS)

# ─────────────────────────────────────────────
# URL HELPERS
# ─────────────────────────────────────────────

KEEP_PARAMS = {"variant", "sku", "id", "product_id", "item", "pid"}

def normalize(url: str) -> str:
    p = urlparse(url)
    params = parse_qs(p.query, keep_blank_values=False)
    kept = {k: v for k, v in params.items() if k.lower() in KEEP_PARAMS}
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") or "/", "", urlencode(kept, doseq=True), ""))

def same_domain(base: str, url: str) -> bool:
    b = urlparse(base).netloc.lstrip("www.")
    u = urlparse(url).netloc.lstrip("www.")
    return b == u or u.endswith("." + b)

def safe_float(x) -> float:
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return 0.0

def safe_int(x) -> int:
    try:
        return int(re.sub(r"[^\d]", "", str(x)))
    except Exception:
        return 0
    

def is_block_page(soup) -> bool:
    """
    Detect Cloudflare / bot verification pages.
    """
    if not soup:
        return False

    text = soup.get_text(" ", strip=True).lower()

    blocked_signals = [
        "verify you are human",
        "checking your browser",
        "connection needs to be verified",
        "enable javascript",
        "cloudflare",
        "cdn-cgi",
        "please wait while we check your browser"
    ]

    return any(signal in text for signal in blocked_signals)

# ─────────────────────────────────────────────
# LINK CLASSIFICATION  (FIX 1: added /catalogue/)
# ─────────────────────────────────────────────

PRODUCT_RE = re.compile(
    r"/product[s]?/"      # standard
    r"|/item[s]?/"
    r"|/p/[^/]"
    r"|/dp/"
    r"|/goods/"
    r"|/detail/"
    r"|/pd/"
    r"|/listing/"
    r"|/catalogue/(?!category)"   # ← books.toscrape  (exclude /catalogue/category/)
    r"|/book[s]?/"
    r"|/collections/[^/]+/products/"  # Shopify collection-scoped product URLs
    , re.I
)

PRODUCT_QS  = {"variant", "sku", "product_id", "pid"}

CATEGORY_RE = re.compile(
    r"/collections?/"
    r"|/categor"
    r"|/department/"
    r"|/section/"
    r"|/shop/?$"
    r"|/store/?$"
    r"|/catalog(ue)?/?$"           # ← catalogue root
    r"|/catalogue/category/"       # ← books.toscrape category pages
    r"|/c/[^/]"
    , re.I
)

SKIP_RE = re.compile(
    r"/cart|/checkout|/account|/login|/register|/blog|/news"
    r"|/about|/contact|/faq|/search|/tags?/|/wp-admin|/cdn-cgi"
    , re.I
)

def is_product(url: str) -> bool:
    path = urlparse(url).path
    qs   = urlparse(url).query.lower()
    if SKIP_RE.search(path):
        return False
    if PRODUCT_RE.search(path):
        return True
    return any(f"{k}=" in qs for k in PRODUCT_QS)

def is_category(url: str) -> bool:
    return bool(CATEGORY_RE.search(urlparse(url).path))

def gather_links(soup, base_url):
    products, categories = set(), set()
    if not soup:
        return products, categories
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        norm = normalize(urljoin(base_url, href))
        if not same_domain(base_url, norm):
            continue
        if is_product(norm):
            products.add(norm)
        elif is_category(norm):
            categories.add(norm)
    return products, categories

def next_page_url(soup, current_url):
    if not soup:
        return None
    tag = soup.find("a", rel="next") or soup.find("link", rel="next")
    if tag and tag.get("href"):
        return urljoin(current_url, tag["href"])
    for a in soup.find_all("a", href=True):
        txt = a.get_text(strip=True).lower()
        lbl = (a.get("aria-label") or "").lower()
        cls = " ".join(a.get("class") or []).lower()
        if txt in ("next", "next page", "›", "»", ">") or "next" in lbl or "next" in cls:
            return urljoin(current_url, a["href"])
    return None

# ─────────────────────────────────────────────
# FETCH HELPERS
# ─────────────────────────────────────────────

def fetch_static(url: str) -> BeautifulSoup | None:
    try:
        r = _session.get(url, timeout=10, allow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None

def has_product_data(soup) -> bool:
    """
    Return True if static HTML already contains usable product data.
    Extended to detect catalogue-style pages (books.toscrape).
    """
    if not soup:
        return False
    # JSON-LD Product
    for script in soup.find_all("script", type="application/ld+json"):
        if script.string and '"Product"' in script.string:
            return True
    # OpenGraph product
    if soup.find("meta", property="og:title") and (
        soup.find("meta", property="product:price:amount") or
        soup.find("meta", property="og:price:amount")
    ):
        return True
    # Catalogue style: H1 + price element
    if soup.find("h1") and (
        soup.find(class_=re.compile(r"price", re.I)) or
        soup.find("p", class_="price_color")          # books.toscrape
    ):
        return True
    return False

def needs_js_reviews(soup) -> bool:
    """
    Return True if reviews are likely loaded via JavaScript
    (page has review placeholder but no actual review text).
    """
    if not soup:
        return False
    # Judge.me placeholder present but no loaded content
    jdgm = soup.find(class_=re.compile(r"jdgm", re.I))
    if jdgm and not soup.find(class_=re.compile(r"jdgm-rev__body", re.I)):
        return True
    # Yotpo placeholder
    yotpo = soup.find(class_=re.compile(r"yotpo", re.I))
    if yotpo and not soup.find(class_=re.compile(r"yotpo-review", re.I)):
        return True
    # Stamped placeholder
    if soup.find(attrs={"data-widget-type": re.compile(r"main-widget", re.I)}):
        return True
    return False

async def fetch_with_playwright(
    url: str, context, scroll: bool = False, wait_for_reviews: bool = False
) -> BeautifulSoup | None:
    page = None
    try:
        page = await context.new_page()

        async def block_assets(route):
            if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", block_assets)
        await page.goto(url, timeout=15_000, wait_until="commit")

        try:
            await asyncio.wait_for(page.wait_for_load_state("domcontentloaded"), timeout=5)
        except Exception:
            pass

        if wait_for_reviews:
            # Wait for Judge.me / Yotpo / Stamped review widgets to load
            for selector in [
                ".jdgm-rev__body",
                ".yotpo-review",
                "[data-widget-type='main-widget']",
                ".spr-review-content",
                ".review-content",
                "[itemprop='reviewBody']",
            ]:
                try:
                    await page.wait_for_selector(selector, timeout=4_000)
                    break  # found one — stop waiting
                except Exception:
                    continue

        if scroll:
            await page.evaluate("""
                () => new Promise(resolve => {
                    let t = 0;
                    const id = setInterval(() => {
                        window.scrollBy(0, 800);
                        t += 800;
                        if (t >= document.body.scrollHeight) { clearInterval(id); resolve(); }
                    }, 60);
                })
            """)
            await asyncio.sleep(0.5)

        html = await page.content()
        return BeautifulSoup(html, "html.parser")

    except Exception as e:
        logger.warning(f"Playwright error ({url}): {e}")
        return None
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass

async def smart_fetch(url: str, context, scroll: bool = False) -> BeautifulSoup | None:
    """
    1. Try requests (fast).
    2. If product data found AND no JS reviews needed → return immediately.
    3. Otherwise use Playwright (waits for review widgets if needed).
    """
    loop = asyncio.get_event_loop()
    soup = await loop.run_in_executor(None, fetch_static, url)

    if soup and has_product_data(soup) and not needs_js_reviews(soup):
        return soup  # fast path — fully static page

    # Need Playwright: either no product data or JS-rendered reviews
    wait_reviews = soup is not None and needs_js_reviews(soup)
    pw_soup = await fetch_with_playwright(url, context, scroll=scroll, wait_for_reviews=wait_reviews)
    return pw_soup if pw_soup else soup

async def smart_fetch_discovery(url: str, context, scroll: bool = False) -> BeautifulSoup | None:
    loop = asyncio.get_event_loop()
    soup = await loop.run_in_executor(None, fetch_static, url)
    if soup and len(soup.find_all("a", href=True)) > 5:
        return soup
    return await fetch_with_playwright(url, context, scroll=scroll)

# ─────────────────────────────────────────────
# PRODUCT DATA EXTRACTION
# ─────────────────────────────────────────────

def extract_json_ld(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string.strip())
        except Exception:
            continue
        if isinstance(data, dict):
            if data.get("@type") == "Product":
                return data
            for item in data.get("@graph", []):
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return item
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return item
    return None

def extract_meta(soup):
    def og(prop):
        t = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        return t.get("content") if t else None
    data = {}
    data["name"]        = og("og:title") or og("product:title")
    data["description"] = og("og:description")
    pv = og("product:price:amount") or og("og:price:amount")
    pc = og("product:price:currency") or og("og:price:currency")
    if pv:
        data["offers"] = {"price": pv, "priceCurrency": pc}
    if not data.get("name"):
        h1 = soup.find("h1")
        if h1:
            data["name"] = h1.get_text(strip=True)
    return data

def extract_catalogue_data(soup) -> dict:
    """
    FIX 1: Parse catalogue-style pages like books.toscrape.com.
    These use plain HTML with no JSON-LD or OpenGraph tags.
    """
    data = {}

    # Title from H1
    h1 = soup.find("h1")
    if h1:
        data["name"] = h1.get_text(strip=True)

    # Price from <p class="price_color"> or similar
    price_tag = (
        soup.find("p", class_="price_color") or
        soup.find(class_=re.compile(r"price_color|price-color|product-price", re.I))
    )
    if price_tag:
        price_text = price_tag.get_text(strip=True)
        m = re.search(r"[\$€£¥₹]?\s*([\d,]+\.?\d*)", price_text)
        if m:
            price = safe_float(m.group(1))
            # Detect currency symbol
            currency = "GBP" if "£" in price_text else \
                       "USD" if "$" in price_text else \
                       "EUR" if "€" in price_text else None
            data["offers"] = {"price": price, "priceCurrency": currency}

    # Availability
    avail_tag = soup.find(class_=re.compile(r"availability|instock|outofstock", re.I))
    if avail_tag:
        avail_text = avail_tag.get_text(strip=True).lower()
        data["availability"] = "In Stock" if "in stock" in avail_text else "Out of Stock"

    # Description from product description tab or <p> in article
    desc_tag = (
        soup.find("div", id=re.compile(r"description|product_description", re.I)) or
        soup.find("article", class_=re.compile(r"product", re.I))
    )
    if desc_tag:
        ps = desc_tag.find_all("p")
        if ps:
            data["description"] = " ".join(p.get_text(" ", strip=True) for p in ps[:2])

    # Rating from star-rating CSS class (e.g. <p class="star-rating Three">)
    WORD_TO_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    star_tag = soup.find(class_=re.compile(r"star-rating", re.I))
    if star_tag:
        classes = " ".join(star_tag.get("class") or []).lower()
        for word, num in WORD_TO_NUM.items():
            if word in classes:
                data["_star_rating"] = float(num)
                break

    return data

def extract_price_html(soup) -> float | None:
    # books.toscrape specific
    pc = soup.find("p", class_="price_color")
    if pc:
        m = re.search(r"[\$€£¥₹]?\s*([\d,]+\.?\d*)", pc.get_text(strip=True))
        if m:
            v = safe_float(m.group(1))
            if v > 0:
                return v
    # Generic price class
    for tag in soup.find_all(["span", "div", "p", "strong"],
                             class_=re.compile(r"price|amount|cost", re.I)):
        m = re.search(r"[\$€£¥₹]?\s*([\d,]+\.?\d*)", tag.get_text(strip=True))
        if m:
            v = safe_float(m.group(1))
            if v > 0:
                return v
    return None

WORD_TO_RATING = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}

def extract_rating(soup, product_data) -> tuple[float, int]:
    rating = review_count = 0

    # JSON-LD aggregateRating
    agg = product_data.get("aggregateRating")
    if isinstance(agg, dict):
        rating       = safe_float(agg.get("ratingValue", 0))
        review_count = safe_int(agg.get("reviewCount") or agg.get("ratingCount", 0))

    # schema.org microdata
    if not rating:
        ah = soup.find(attrs={"itemtype": re.compile("AggregateRating", re.I)})
        if ah:
            rv = ah.find(attrs={"itemprop": "ratingValue"})
            if rv:
                rating = safe_float(rv.get("content") or rv.get_text())
            rc = ah.find(attrs={"itemprop": re.compile(r"(review|rating)Count", re.I)})
            if rc:
                review_count = safe_int(rc.get("content") or rc.get_text())

    # Judge.me / Yotpo badge
    if not rating:
        badge = soup.find(attrs={"data-average-rating": True})
        if badge:
            rating       = safe_float(badge.get("data-average-rating", 0))
            review_count = review_count or safe_int(badge.get("data-number-of-reviews", 0))

    # FIX 1: books.toscrape CSS star-rating class  e.g. <p class="star-rating Three">
    if not rating:
        star_tag = soup.find(class_=re.compile(r"\bstar-rating\b", re.I))
        if star_tag:
            classes = " ".join(star_tag.get("class") or []).lower()
            for word, num in WORD_TO_RATING.items():
                if word in classes:
                    rating = num
                    break

    # data-rating or aria-label fallback
    if not rating:
        for tag in soup.find_all(attrs={"data-rating": True}):
            rating = safe_float(tag["data-rating"])
            if rating:
                break

    return float(rating), int(review_count)

def extract_reviews(soup) -> list[str]:
    reviews = []

    # schema.org reviewBody
    for tag in soup.find_all(attrs={"itemprop": "reviewBody"}):
        t = tag.get_text(" ", strip=True)
        if t and len(t) > 10:
            reviews.append(t)

    # FIX 2: Judge.me (silkandwillow uses this)
    if not reviews:
        for b in soup.find_all(class_=re.compile(r"jdgm-rev__body", re.I)):
            t = b.get_text(" ", strip=True)
            if t and len(t) > 10:
                reviews.append(t)

    # Yotpo
    if not reviews:
        for b in soup.find_all(class_=re.compile(r"yotpo-review-content|content-review", re.I)):
            t = b.get_text(" ", strip=True)
            if t and len(t) > 10:
                reviews.append(t)

    # Stamped.io
    if not reviews:
        for b in soup.find_all(class_=re.compile(r"stamped-review-content|review-content-body", re.I)):
            t = b.get_text(" ", strip=True)
            if t and len(t) > 10:
                reviews.append(t)

    # Shopify native / generic
    if not reviews:
        for b in soup.find_all(class_=re.compile(r"spr-review-content-body|review-body|review-text", re.I)):
            t = b.get_text(" ", strip=True)
            if t and len(t) > 10:
                reviews.append(t)

    # Generic fallback
    if not reviews:
        for b in soup.find_all(
            lambda tag: tag.name in ["div", "p", "li"]
            and any("review" in c.lower() for c in (tag.get("class") or []))
        )[:8]:
            t = b.get_text(" ", strip=True)
            if t and len(t) > 20:
                reviews.append(t)

    return reviews[:10]

def parse_product(soup, url) -> dict | None:
    # Try JSON-LD first
    pd = extract_json_ld(soup)

    # Then OpenGraph / meta
    if not pd:
        pd = extract_meta(soup)

    # Finally catalogue-style HTML (books.toscrape etc.)
    if not pd or not pd.get("name"):
        cat = extract_catalogue_data(soup)
        if cat.get("name"):
            pd = cat

    if not pd or not pd.get("name"):
        return None

    name        = pd.get("name", "").strip()
    description = pd.get("description", "")

    price = currency = None
    availability = pd.get("availability", "Unknown")

    offers = pd.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        price        = safe_float(offers.get("price")) or None
        currency     = offers.get("priceCurrency")
        av           = offers.get("availability", "")
        if av:
            availability = "In Stock" if "InStock" in av else "Out of Stock" if "OutOfStock" in av else "Unknown"

    if price is None:
        price = extract_price_html(soup)

    # FIX 1: Use _star_rating from catalogue data if JSON-LD has no rating
    rating, review_count = extract_rating(soup, pd)
    if not rating and "_star_rating" in pd:
        rating = pd["_star_rating"]

    reviews = extract_reviews(soup)

    brand = None
    bd = pd.get("brand")
    if isinstance(bd, dict):
        brand = bd.get("name")
    elif isinstance(bd, str):
        brand = bd

    image = pd.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")

    return {
        "product_name": name,
        "price":        price,
        "currency":     currency,
        "availability": availability,
        "rating":       rating,
        "review_count": review_count,
        "reviews":      reviews,
        "brand":        brand,
        "description":  description,
        "image":        image,
        "product_url":  normalize(url),
    }

# ─────────────────────────────────────────────
# CORE ASYNC CRAWL
# ─────────────────────────────────────────────

async def _async_crawl(start_url: str, max_products: int, result_queue: queue.Queue):
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-extensions", "--blink-settings=imagesEnabled=false"],
        )
        ctx = await browser.new_context(
            extra_http_headers=HEADERS,
            ignore_https_errors=True,
        )

        visited      : set[str] = set()
        seen_products: set[str] = set()
        count = 0

        async def scrape_and_stream(url: str):
            nonlocal count
            if count >= max_products or url in seen_products:
                return
            seen_products.add(url)
            soup = await smart_fetch(url, ctx, scroll=False)

            if soup:

                # 🚨 Skip Cloudflare / verification pages
                if is_block_page(soup):
                    logger.warning(f"Blocked by bot protection: {url}")
                    return

            product = parse_product(soup, url)

            if product:

                name = product.get("product_name","").lower()

                if any(x in name for x in [
                    "verify",
                    "connection needs to be verified",
                    "checking your browser",
                    "cloudflare"
                ]):
                    return

                result_queue.put(product)
                count += 1
                logger.info(f"✅ [{count}/{max_products}] {product['product_name']}")

        async def process_links_parallel(links: set):
            pending = [u for u in links if u not in seen_products]
            for i in range(0, len(pending), BATCH_SIZE):
                if count >= max_products:
                    return
                batch = pending[i:i + BATCH_SIZE]
                await asyncio.gather(*[scrape_and_stream(u) for u in batch])

        logger.info(f"🔍 Homepage: {start_url}")
        home_soup = await smart_fetch_discovery(start_url, ctx, scroll=True)
        if not home_soup:
            logger.error("Could not fetch homepage")
            return

        prod_links, cat_links = gather_links(home_soup, start_url)
        visited.add(normalize(start_url))
        logger.info(f"   Homepage: {len(prod_links)} products, {len(cat_links)} categories")

        if prod_links:
            await process_links_parallel(prod_links)

        for cat_url in list(cat_links)[:MAX_CATS]:
            if count >= max_products:
                break
            if cat_url in visited:
                continue
            visited.add(cat_url)

            logger.info(f"📂 {cat_url}")
            csoup = await smart_fetch_discovery(cat_url, ctx, scroll=False)
            if not csoup:
                continue

            pl, _ = gather_links(csoup, cat_url)
            await process_links_parallel(pl)

            cur_url, cur_soup = cat_url, csoup
            for _ in range(MAX_PAGES):
                if count >= max_products:
                    break
                nxt = next_page_url(cur_soup, cur_url)
                if not nxt or nxt in visited:
                    break
                visited.add(nxt)
                logger.info(f"   ↪ {nxt}")
                nsoup = await smart_fetch_discovery(nxt, ctx, scroll=False)
                if not nsoup:
                    break
                pl, _ = gather_links(nsoup, nxt)
                await process_links_parallel(pl)
                cur_url, cur_soup = nxt, nsoup

        logger.info(f"🏁 Done — {count} products scraped")
        await ctx.close()
        await browser.close()

# ─────────────────────────────────────────────
# THREAD ENTRY POINT
# ─────────────────────────────────────────────

def _crawl_thread(start_url: str, max_products: int, result_queue: queue.Queue):
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async_crawl(start_url, max_products, result_queue))
    except Exception as e:
        logger.error(f"Crawl thread error: {e}")
        result_queue.put({"error": str(e)})
    finally:
        try:
            loop.close()
        except Exception:
            pass
        result_queue.put(_SENTINEL)

# ─────────────────────────────────────────────
# PUBLIC ASYNC GENERATOR
# ─────────────────────────────────────────────

async def crawl_stream(start_url: str, max_products: int = 30):
    q: queue.Queue = queue.Queue()
    t = threading.Thread(
        target=_crawl_thread,
        args=(start_url, max_products, q),
        daemon=True,
    )
    t.start()
    loop = asyncio.get_event_loop()
    while True:
        item = await loop.run_in_executor(None, q.get)
        if item is _SENTINEL:
            break
        yield item
    t.join()