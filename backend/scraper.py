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
            time.sleep(random.uniform(1.5, 3))

            response = session.get(url, timeout=20)

            if response.status_code == 429:
                time.sleep(8)
                continue

            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")

        except requests.RequestException:
            time.sleep(4)

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

                if isinstance(data, dict) and data.get("@type") == "Product":
                    product_data = data
                    break

                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            product_data = item
                            break
            except:
                continue

        if not product_data:
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

        # Fallback HTML extraction
        if rating == 0:
            rating_tag = soup.find("p", class_="rating-text")
            if rating_tag:
                match = re.search(r"([\d\.]+)", rating_tag.text)
                if match:
                    rating = float(match.group(1))

        if review_count == 0:
            review_count_tag = soup.find("p", class_="rating-count")
            if review_count_tag:
                match = re.search(r"\((\d+)\)", review_count_tag.text)
                if match:
                    review_count = int(match.group(1))

        # ---------------- REVIEWS ----------------
        reviews = []
        review_blocks = soup.find_all("div", class_="jdgm-rev")

        for block in review_blocks[:3]:
            body = block.find("div", class_="jdgm-rev__body")

            if body:
                reviews.append(body.text.strip())

        return {
            "product_name": name,
            "price": price,
            "currency": currency,
            "availability": availability,
            "rating": rating,
            "review_count": review_count,
            "reviews": reviews,   # 🔥 List instead of DataFrame
            "brand": product_data.get("brand", {}).get("name")
                     if isinstance(product_data.get("brand"), dict) else None,
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

    with ThreadPoolExecutor(max_workers=2) as executor:

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
