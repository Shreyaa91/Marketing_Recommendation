# scraper.py

import requests
import json
import re
import time
import random
import math
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "en-US,en;q=0.9"
}

session = requests.Session()
session.headers.update(HEADERS)

# ----------------------------------
# UTILITIES
# ----------------------------------

def get_soup(url, retries=3):
    for attempt in range(retries):
        try:
            # Shorter, randomized delay to speed up crawling
            time.sleep(random.uniform(0.3, 0.8))

            response = session.get(url, timeout=12)

            if response.status_code == 429:
                # Back off a bit if rate-limited
                time.sleep(5)
                continue

            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")

        except requests.RequestException:
            # Slight delay before retrying on network errors
            time.sleep(2)

    return None


def normalize(url):
    parsed = urlparse(url)
    return parsed.scheme + "://" + parsed.netloc + parsed.path


def is_same_domain(base, new):
    return urlparse(base).netloc == urlparse(new).netloc


def safe_float(x):
    try:
        return float(x)
    except:
        return 0


def safe_int(x):
    try:
        return int(x)
    except:
        return 0


# ----------------------------------
# LINK EXTRACTION
# ----------------------------------

def extract_product_links(base_url):
    soup = get_soup(base_url)
    if not soup:
        return set()

    links = set()

    for a in soup.find_all("a", href=True):
        link = normalize(urljoin(base_url, a["href"]))

        if not is_same_domain(base_url, link):
            continue

        if "/products/" in link:
            links.add(link)

    return links


def extract_category_links(base_url):
    soup = get_soup(base_url)
    if not soup:
        return set()

    categories = set()

    for a in soup.find_all("a", href=True):
        link = normalize(urljoin(base_url, a["href"]))

        if not is_same_domain(base_url, link):
            continue

        if "/collections/" in link:
            categories.add(link)

    return categories


# ----------------------------------
# PRODUCT SCRAPER
# ----------------------------------

def scrape_product(url):
    try:
        soup = get_soup(url)
        if not soup:
            return None

        scripts = soup.find_all("script", type="application/ld+json")
        product_data = None

        for script in scripts:
            if not script.string:
                continue

            try:
                data = json.loads(script.string.strip())

                if isinstance(data, dict):

                    # Case 1: Direct Product
                    if data.get("@type") == "Product":
                        product_data = data
                        break

                    # Case 2: @graph format (very common in WooCommerce, Magento)
                    if "@graph" in data:
                        for item in data["@graph"]:
                            if isinstance(item, dict) and item.get("@type") == "Product":
                                product_data = item
                                break


                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            product_data = item
                            break
            except:
                continue

        # -------------------------------------------------
        # If JSON-LD not found → try extracting manually
        # -------------------------------------------------
        if not product_data:
            product_data = {}

            # Try OpenGraph title
            og_title = soup.find("meta", property="og:title")
            if og_title:
                product_data["name"] = og_title.get("content")

            # Try meta description
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                product_data["description"] = og_desc.get("content")

            # Try product price meta
            meta_price = soup.find("meta", property="product:price:amount")
            if meta_price:
                product_data["offers"] = {
                    "price": meta_price.get("content"),
                    "priceCurrency": soup.find("meta", property="product:price:currency")
                }

            # Try H1 as fallback name
            if not product_data.get("name"):
                h1 = soup.find("h1")
                if h1:
                    product_data["name"] = h1.get_text(strip=True)

            # If still no name → not a product
            if not product_data.get("name"):
                return None


        name = product_data.get("name")
        description = product_data.get("description")

        # ---------------- PRICE ----------------
        price = None
        currency = None
        availability = "Unknown"

        offers = product_data.get("offers")

        if isinstance(offers, list) and offers:
            offers = offers[0]

        if isinstance(offers, dict):
            price = safe_float(offers.get("price"))
            currency = offers.get("priceCurrency")

            availability_raw = offers.get("availability", "")

            if "InStock" in availability_raw:
                availability = "In Stock"
            elif "OutOfStock" in availability_raw:
                availability = "Out of Stock"

        # ---------------- RATING ----------------
        rating = 0
        review_count = 0

        aggregate = product_data.get("aggregateRating")

        if isinstance(aggregate, dict):
            rating = safe_float(aggregate.get("ratingValue"))
            review_count = safe_int(aggregate.get("reviewCount"))

        # Fallbacks for rating / review count when JSON-LD is missing or incomplete
        if rating == 0:
            # 1) schema.org AggregateRating in HTML
            agg_html = soup.find(attrs={"itemtype": "http://schema.org/AggregateRating"})
            if agg_html:
                rv_tag = agg_html.find(attrs={"itemprop": "ratingValue"})
                if rv_tag and rv_tag.get("content"):
                    rating = safe_float(rv_tag["content"])
                elif rv_tag:
                    rating = safe_float(rv_tag.get_text(strip=True))

                rc_tag = agg_html.find(attrs={"itemprop": "reviewCount"})
                if rc_tag and rc_tag.get("content"):
                    review_count = safe_int(rc_tag["content"])
                elif rc_tag:
                    review_count = safe_int(rc_tag.get_text(strip=True))

        if rating == 0:
            # 2) Generic jdgm/judge.me preview badge (data-average-rating / data-number-of-reviews)
            badge = soup.find(attrs={"data-average-rating": True}) or soup.find(
                attrs={"class": re.compile("jdgm-prev-badge", re.I)}
            )
            if badge:
                rating = safe_float(badge.get("data-average-rating", 0))
                if review_count == 0:
                    review_count = safe_int(badge.get("data-number-of-reviews", 0))

        if rating == 0:
            # 3) Generic "rating" text fallback
            rating_tag = soup.find("p", class_="rating-text") or soup.find(
                attrs={"class": re.compile("rating", re.I)}
            )
            if rating_tag:
                match = re.search(r"([\d\.]+)", rating_tag.get_text(" ", strip=True))
                if match:
                    rating = safe_float(match.group(1))

        if review_count == 0:
            # 4) Specific class-based fallback
            review_count_tag = soup.find("p", class_="rating-count") or soup.find(
                attrs={"class": re.compile("review", re.I)}
            )
            if review_count_tag:
                # Patterns like "(123)", "123 reviews", "123 Ratings"
                text = review_count_tag.get_text(" ", strip=True)
                match = re.search(r"(\d+)\s*(reviews?|ratings?)?", text, re.I)
                if match:
                    review_count = safe_int(match.group(1))

        # ---------------- REVIEWS ----------------
        reviews = []

        # 1) schema.org reviewBody
        for tag in soup.find_all(attrs={"itemprop": "reviewBody"}):
            text = tag.get_text(" ", strip=True)
            if text:
                reviews.append(text)

        # 2) Judge.me style blocks (Shopify apps)
        if not reviews:
            review_blocks = soup.find_all("div", class_="jdgm-rev")
            for block in review_blocks[:5]:
                body = block.find("div", class_="jdgm-rev__body")
                if body:
                    text = body.get_text(" ", strip=True)
                    if text:
                        reviews.append(text)

        # 3) Generic fallback: any div/span with "review" in class name
        if not reviews:
            generic_blocks = soup.find_all(
                lambda tag: tag.name in ["div", "p", "span"]
                and tag.get("class")
                and any("review" in c.lower() for c in tag.get("class"))
            )
            for block in generic_blocks[:5]:
                text = block.get_text(" ", strip=True)
                if text:
                    reviews.append(text)
        # ---------------- BRAND ----------------
        brand = None
        brand_data = product_data.get("brand")

        if isinstance(brand_data, dict):
            brand = brand_data.get("name")
        elif isinstance(brand_data, str):
            brand = brand_data

        return {
            "product_name": name,
            "price": price,
            "currency": currency,
            "availability": availability,
            "rating": rating,
            "review_count": review_count,
            "reviews": reviews,   # 🔥 List instead of DataFrame
            "brand": brand,
            "description": description,
            "product_url": normalize(url)
        }

    except Exception as e:
        logger.error(f"Error scraping {url}: {e}")
        return None


# ----------------------------------
# STREAM CRAWLER (STABLE VERSION)
# ----------------------------------

def crawl_stream(start_url, max_products=50):

    logger.info("🚀 Starting controlled crawl...")

    product_links = set()

    product_links.update(extract_product_links(start_url))

    categories = extract_category_links(start_url)

    for cat in list(categories)[:5]:
        product_links.update(extract_product_links(cat))

    visited_products = set()
    count = 0

    # Higher concurrency for faster crawling
    with ThreadPoolExecutor(max_workers=8) as executor:

        futures = {
            executor.submit(scrape_product, url): url
            for url in product_links
        }

        for future in as_completed(futures):

            try:
                product = future.result(timeout=30)
            except Exception as e:
                logger.warning(f"Thread error: {e}")
                continue

            if not product:
                continue

            name = product.get("product_name")

            if not name or name in visited_products:
                continue

            visited_products.add(name)

            yield product

            count += 1
            if count >= max_products:
                break
