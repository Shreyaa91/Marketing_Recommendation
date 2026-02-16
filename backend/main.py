from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from scraper import crawl_stream
import json
from nltk.sentiment import SentimentIntensityAnalyzer
import nltk

app = FastAPI()

# ✅ Download once at startup
nltk.download("vader_lexicon")
sia = SentimentIntensityAnalyzer()


# ----------------------------------
# SENTIMENT FUNCTION
# ----------------------------------

def apply_sentiment(product):

    reviews = product.get("reviews", [])

    if reviews:

        sentiment_scores = []

        for review in reviews:
            score = sia.polarity_scores(review)["compound"]
            sentiment_scores.append(score)

        # ✅ Average sentiment
        product["avg_sentiment"] = round(
            sum(sentiment_scores) / len(sentiment_scores),
            3
        )

        # Optional: store individual sentiment scores
        product["sentiment_scores"] = sentiment_scores

    else:
        product["avg_sentiment"] = 0

    return product


# ----------------------------------
# STREAM ENDPOINT (FIXED)
# ----------------------------------

@app.get("/stream-crawl")
def stream_crawl(url: str):

    def event_generator():
        try:
            for product in crawl_stream(url):

                if not product:
                    continue

                # ✅ Apply sentiment
                product = apply_sentiment(product)

                # ✅ Convert dict to JSON string
                json_data = json.dumps(product)

                # ✅ Proper SSE format
                yield f"data: {json_data}\n\n"

        except Exception as e:
            error_json = json.dumps({"error": str(e)})
            yield f"data: {error_json}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
