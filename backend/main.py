"""
main.py  —  FastAPI backend
============================
- No asyncio policy changes needed (scraper.py handles isolation)
- SSE keepalive pings every 15s to prevent Streamlit read timeout
- Sentiment + hybrid recommendation applied per product
"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from scraper import crawl_stream
import json
import asyncio
import re
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer
from datetime import datetime

nltk.download("vader_lexicon", quiet=True)
sia = SentimentIntensityAnalyzer()

app = FastAPI()


# ──────────────────────────────────────────────
# SENTIMENT
# ──────────────────────────────────────────────

def apply_sentiment(product: dict) -> dict:
    """
    Sentiment fallback chain
    ─────────────────────────────────────────────────────────
    Level 1 — Customer reviews (most reliable)
        Use all review texts → average VADER compound score.
        sentiment_source = "reviews"

    Level 2 — Product description (if no reviews)
        Run VADER on the description text.
        Useful for well-written product pages (books, skincare etc.)
        sentiment_source = "description"

    Level 3 — Product name only (if no description either)
        Run VADER on the product name.
        Very rough signal — words like "Premium", "Damaged",
        "Luxury", "Anti-dandruff" carry weak but real polarity.
        sentiment_source = "name"

    Level 4 — No text at all
        Set avg_sentiment = 0.0 (neutral).
        sentiment_source = "none"
    ─────────────────────────────────────────────────────────
    The field `sentiment_source` is stored so the frontend
    can show the user where the score came from.
    """
    reviews     = product.get("reviews") or []
    description = (product.get("description") or "").strip()
    name        = (product.get("product_name") or "").strip()

    # ── Level 1: reviews ──────────────────────────────────
    if reviews:
        scores = [sia.polarity_scores(r)["compound"] for r in reviews]
        n      = len(scores)
        avg    = round(sum(scores) / n, 3) if n else 0.0
        product["avg_sentiment"]    = avg
        product["sentiment_scores"] = scores
        product["sentiment_source"] = "reviews"
        print(f"  Sentiment [{name[:40]}] = {avg} (from {n} reviews)")
        return product

    # ── Level 2: description ──────────────────────────────
    if description and len(description) > 20:
        # Split into sentences for a more stable average
        sentences = [s.strip() for s in re.split(r"[.!?]", description) if len(s.strip()) > 8]
        if sentences:
            scores = [sia.polarity_scores(s)["compound"] for s in sentences]
            avg    = round(sum(scores) / len(scores), 3)
        else:
            avg = round(sia.polarity_scores(description)["compound"], 3)

        product["avg_sentiment"]    = avg
        product["sentiment_scores"] = []
        product["sentiment_source"] = "description"
        print(f"  Sentiment [{name[:40]}] = {avg} (estimated from description)")
        return product

    # ── Level 3: product name ─────────────────────────────
    if name:
        avg = round(sia.polarity_scores(name)["compound"], 3)
        product["avg_sentiment"]    = avg
        product["sentiment_scores"] = []
        product["sentiment_source"] = "name"
        print(f"  Sentiment [{name[:40]}] = {avg} (estimated from product name)")
        return product

    # ── Level 4: no text at all ───────────────────────────
    product["avg_sentiment"]    = 0.0
    product["sentiment_scores"] = []
    product["sentiment_source"] = "none"
    print(f"  Sentiment [{name[:40]}] = 0.0 (no text available)")
    return product


# ──────────────────────────────────────────────
# HYBRID RECOMMENDATION ENGINE
# ──────────────────────────────────────────────

def infer_category(product: dict) -> str:
    text = " ".join([
        str(product.get("product_name") or ""),
        str(product.get("description")  or ""),
    ]).lower()
    if any(k in text for k in ["laptop", "phone", "mobile", "tablet", "camera", "electronics", "headphone", "speaker"]):
        return "electronics"
    if any(k in text for k in ["shirt", "tshirt", "t-shirt", "jeans", "dress", "jacket", "fashion", "clothing", "shoes", "kurta", "saree"]):
        return "fashion"
    if any(k in text for k in ["sofa", "chair", "table", "furniture", "home", "decor", "curtain", "pillow"]):
        return "home"
    if any(k in text for k in ["book", "novel", "fiction", "author", "publisher"]):
        return "books"
    if any(k in text for k in ["serum", "moisturizer", "cleanser", "sunscreen", "skincare", "cream", "lotion", "face wash", "toner"]):
        return "skincare"
    return "generic"


def hybrid_marketing_recommendation(product: dict) -> dict:
    rating       = float(product.get("rating")        or 0.0)
    review_count = float(product.get("review_count")  or 0.0)
    sentiment    = float(product.get("avg_sentiment") or 0.0)
    category     = infer_category(product)
    discount     = float(product.get("discount", 0.0) or 0.0)

    norm_rating    = min(rating / 5.0, 1.0)
    norm_reviews   = min(review_count / 1000.0, 1.0)
    norm_sentiment = (sentiment + 1.0) / 2.0

    base = 0.4 * norm_rating + 0.2 * norm_reviews + 0.4 * norm_sentiment

    scores = {
        "Instagram":            base,
        "Facebook Ads":         base * 0.95,
        "YouTube Ads":          base * 0.90,
        "Influencer Marketing": base,
        "Google Ads":           base,
        "Email":                base * 0.90,
        "WhatsApp":             base * 0.90,
        "SMS":                  base * 0.85,
        "Marketplace Ads":      base * 0.90,
    }

    rules = []

    if sentiment > 0.7 and discount < 10:
        scores["Influencer Marketing"] += 0.15
        scores["Instagram"]            += 0.15
        rules.append("High sentiment + low discount → boost Influencer & Instagram")

    if category == "electronics" and datetime.now().month in [9, 10, 11, 12]:
        scores["Google Ads"] += 0.20
        rules.append("Electronics in festival season → boost Google Ads")

    if sentiment > 0.6 and review_count < 20:
        scores["WhatsApp"] += 0.10
        scores["Email"]    += 0.10
        rules.append("High sentiment + low review count → boost WhatsApp & Email")

    if sentiment < 0.2:
        scores["Google Ads"] += 0.10
        rules.append("Low sentiment → boost Google Ads performance campaigns")

    if category == "books":
        scores["Email"]     += 0.10
        scores["Instagram"] += 0.05
        rules.append("Books category → boost Email & Instagram")

    if category == "skincare":
        scores["Instagram"]            += 0.12
        scores["Influencer Marketing"] += 0.12
        rules.append("Skincare category → boost Instagram & Influencer Marketing")

    ranked    = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary   = ranked[0][0] if ranked else None
    secondary = ranked[1][0] if len(ranked) > 1 else None

    return {
        "primary_platform":   primary,
        "secondary_platform": secondary,
        "platform_scores":    scores,
        "rules_triggered":    rules,
        "category":           category,
        "discount":           discount,
    }


# ──────────────────────────────────────────────
# STREAM ENDPOINT
# ──────────────────────────────────────────────

@app.get("/stream-crawl")
async def stream_crawl(url: str):

    async def event_generator():
        # Background task: crawl and push products into an asyncio queue
        aio_queue: asyncio.Queue = asyncio.Queue()

        async def producer():
            try:
                async for product in crawl_stream(url):
                    await aio_queue.put(product)
            except Exception as e:
                await aio_queue.put({"error": str(e)})
            finally:
                await aio_queue.put(None)  # end signal

        producer_task = asyncio.create_task(producer())

        KEEPALIVE_INTERVAL = 15   # seconds — prevents Streamlit read timeout

        while True:
            try:
                # Wait for next product, but send keepalive if nothing arrives
                product = await asyncio.wait_for(aio_queue.get(), timeout=KEEPALIVE_INTERVAL)
            except asyncio.TimeoutError:
                # Send SSE comment as keepalive (Streamlit ignores it, connection stays alive)
                yield ": keepalive\n\n"
                continue

            if product is None:
                break   # crawl finished

            if not product:
                continue

            if "error" not in product:
                product = apply_sentiment(product)
                product["marketing_recommendation"] = hybrid_marketing_recommendation(product)

            yield f"data: {json.dumps(product)}\n\n"

        await producer_task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disables nginx buffering if behind a proxy
        }
    )