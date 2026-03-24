from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from scraper import crawl_stream
from predict_platform import predict_platform
from content_generation import generate_marketing_content

import json
import asyncio
import re
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

nltk.download("vader_lexicon", quiet=True)
sia = SentimentIntensityAnalyzer()

app = FastAPI()

# -----------------------------
# SENTIMENT (same as before)
# -----------------------------
def apply_sentiment(product: dict) -> dict:

    reviews = product.get("reviews") or []
    description = (product.get("description") or "").strip()
    name = (product.get("product_name") or "").strip()

    if reviews:
        scores = [sia.polarity_scores(r)["compound"] for r in reviews]
        avg = round(sum(scores) / len(scores), 3)
        product["avg_sentiment"] = avg
        product["sentiment_source"] = "reviews"
        return product

    if description:
        avg = round(sia.polarity_scores(description)["compound"], 3)
        product["avg_sentiment"] = avg
        product["sentiment_source"] = "description"
        return product

    if name:
        avg = round(sia.polarity_scores(name)["compound"], 3)
        product["avg_sentiment"] = avg
        product["sentiment_source"] = "name"
        return product

    product["avg_sentiment"] = 0.0
    product["sentiment_source"] = "none"
    return product


# -----------------------------
# STREAM ENDPOINT
# -----------------------------
@app.get("/stream-crawl")
async def stream_crawl(url: str):

    async def event_generator():

        aio_queue: asyncio.Queue = asyncio.Queue()

        async def producer():
            async for product in crawl_stream(url):
                await aio_queue.put(product)

            await aio_queue.put(None)

        producer_task = asyncio.create_task(producer())

        KEEPALIVE_INTERVAL = 15

        while True:
            try:
                product = await asyncio.wait_for(
                    aio_queue.get(),
                    timeout=KEEPALIVE_INTERVAL
                )
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            if product is None:
                break

            if not product:
                continue

            # --- In your FastAPI app (main.py) ---
            if "error" not in product:
                product = apply_sentiment(product)
                
                try:
                    # platform_name, confidence = predict_platform(product)
                    primary, secondary, primary_conf, secondary_conf = predict_platform(product)
                    generated_content = generate_marketing_content(product, primary, secondary)
                    
                    # Wrap this in the key Streamlit expects
                    # product["marketing_recommendation"] = {
                    #     "primary_platform": platform_name,
                    #     "platform_confidence": confidence,
                    #     "category": product.get("category", "General"),
                    #     "rules_triggered": [] # Add any rules if you have them
                    # }
                    product["marketing_recommendation"] = {
                    "primary_platform": primary,
                    "secondary_platform": secondary,
                    "platform_confidence": primary_conf,
                    "secondary_confidence": secondary_conf,
                    "category": product.get("category", "General"),
                    "rules_triggered": [],
                    "generated_content": generated_content,
}

                except Exception as e:
                    print(f"Prediction failed: {e}")
                    product["marketing_recommendation"] = {"primary_platform": None}

            yield f"data: {json.dumps(product)}\n\n"

        await producer_task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )