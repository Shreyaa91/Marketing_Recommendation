from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from scraper import crawl_stream
import json
from nltk.sentiment import SentimentIntensityAnalyzer
import nltk
from datetime import datetime

app = FastAPI()

# ✅ Download once at startup
nltk.download("vader_lexicon")
sia = SentimentIntensityAnalyzer()


# ----------------------------------
# SENTIMENT FUNCTION
# ----------------------------------

def apply_sentiment(product):
    """
    Uses NLTK VADER to calculate sentiment for each review and the
    overall average sentiment for the product.

    Formula (printed in the terminal for transparency):
        avg_sentiment = sum(compound_scores) / number_of_reviews
    """

    reviews = product.get("reviews", []) or []

    if reviews:

        sentiment_scores = []

        print("\n" + "=" * 80)
        print(f"[{datetime.now()}] 🔍 Sentiment analysis for product: {product.get('product_name')}")
        print("-" * 80)

        for idx, review in enumerate(reviews, start=1):
            score_dict = sia.polarity_scores(review)
            compound = score_dict["compound"]
            sentiment_scores.append(compound)

            # ✅ Show extracted review + raw VADER output in the terminal
            print(f"Review {idx}: {review}")
            print(f"VADER scores: {score_dict}")
            print("-" * 40)

        total = sum(sentiment_scores)
        n = len(sentiment_scores)
        avg = total / n if n else 0.0

        # ✅ Average sentiment (VADER compound mean)
        product["avg_sentiment"] = round(avg, 3)

        # Optional: store individual sentiment scores
        product["sentiment_scores"] = sentiment_scores

        # ✅ Explicitly print the formula being applied
        print(
            f"avg_sentiment = sum(compound_scores) / number_of_reviews "
            f"= {total:.4f} / {n} = {avg:.4f}"
        )
        print("=" * 80 + "\n")

    else:
        product["avg_sentiment"] = 0.0
        product["sentiment_scores"] = []

    return product


# ----------------------------------
# HYBRID RECOMMENDATION ENGINE
# ----------------------------------

def _infer_category(product: dict) -> str:
    """
    Try to infer a simple category from product data using keywords in
    the name/description. This is a lightweight content feature.
    """
    text = " ".join(
        [
            str(product.get("product_name") or ""),
            str(product.get("description") or ""),
        ]
    ).lower()

    if any(k in text for k in ["laptop", "phone", "mobile", "camera", "electronics"]):
        return "electronics"
    if any(k in text for k in ["shirt", "tshirt", "t-shirt", "jeans", "dress", "fashion"]):
        return "fashion"
    if any(k in text for k in ["sofa", "chair", "table", "furniture", "home"]):
        return "home"

    return "generic"


def _get_discount(product: dict) -> float:
    """
    Placeholder discount feature.
    If you later parse discount in the scraper, wire it here.
    Currently assumes 0 when not present.
    """
    try:
        return float(product.get("discount", 0.0))
    except (TypeError, ValueError):
        return 0.0


def hybrid_marketing_recommendation(product: dict) -> dict:
    """
    Hybrid Recommendation = Content-based scoring + Knowledge-based rules.

    Content-based part:
        Uses features: rating, review_count, avg_sentiment.
        For each platform we compute a score:

        base_score = (
            w_rating   * normalized_rating +
            w_reviews  * normalized_review_count +
            w_sent     * normalized_sentiment
        )

    Knowledge-based part:
        Applies business rules and boosts platform scores. Examples:
        - If sentiment > 0.7 and discount < 10%  -> boost Influencer / Instagram
        - If electronics and festival season      -> boost Google Ads
        - If high sentiment but low review_count  -> boost WhatsApp / Email
    """

    rating = float(product.get("rating") or 0.0)
    review_count = float(product.get("review_count") or 0.0)
    sentiment = float(product.get("avg_sentiment") or 0.0)

    category = _infer_category(product)
    discount = _get_discount(product)

    # ------------- CONTENT-BASED SCORING -------------
    # Normalize features to [0, 1] ranges for scoring
    norm_rating = rating / 5.0  # assuming 5-star system
    # "Soft" normalization – more than 1000 reviews treated as max
    norm_reviews = min(review_count / 1000.0, 1.0)
    # VADER compound already in [-1, 1]; shift to [0, 1]
    norm_sentiment = (sentiment + 1) / 2

    # Feature weights for content-based recommendation
    w_rating = 0.4
    w_reviews = 0.2
    w_sent = 0.4

    base_score = (
        w_rating * norm_rating
        + w_reviews * norm_reviews
        + w_sent * norm_sentiment
    )

    # Core digital channels considered in this hybrid model.
    # These are domain-driven choices, not scraped from the site.
    platform_scores = {
        # Social & visual
        "Instagram": base_score,
        "Facebook Ads": base_score * 0.95,
        "YouTube Ads": base_score * 0.9,
        "Influencer Marketing": base_score,
        # Performance / search
        "Google Ads": base_score,
        # Owned / retention
        "Email": base_score * 0.9,
        "WhatsApp": base_score * 0.9,
        "SMS": base_score * 0.85,
        # Marketplace / other
        "Marketplace Ads": base_score * 0.9,
    }

    rules_triggered = []

    # ------------- KNOWLEDGE-BASED RULES -------------

    # Rule 1: If sentiment > 0.7 and discount < 10%, suggest influencer marketing
    if sentiment > 0.7 and discount < 10:
        boost = 0.15
        platform_scores["Influencer Marketing"] += boost
        platform_scores["Instagram"] += boost
        rules_triggered.append(
            "Rule 1: High sentiment and low discount → boost Influencer & Instagram"
        )

    # Rule 2: If electronics + (roughly) festival season, suggest Google Ads
    # (Simple season check: Oct–Dec treated as festival-heavy by default)
    month = datetime.now().month
    if category == "electronics" and month in [9, 10, 11, 12]:
        boost = 0.2
        platform_scores["Google Ads"] += boost
        rules_triggered.append(
            "Rule 2: Electronics during festival season → boost Google Ads discount campaigns"
        )

    # Rule 3: High sentiment but low review volume → focus on conversational channels
    if sentiment > 0.6 and review_count < 20:
        boost = 0.1
        platform_scores["WhatsApp"] += boost
        platform_scores["Email"] += boost
        rules_triggered.append(
            "Rule 3: High sentiment but low review_count → boost WhatsApp & Email for nurturing"
        )

    # Rule 4: Generic / low sentiment products → rely more on performance channels
    if sentiment < 0.2:
        boost = 0.1
        platform_scores["Google Ads"] += boost
        rules_triggered.append(
            "Rule 4: Low sentiment → rely more on performance channels (Google Ads)"
        )

    # Pick best and second-best platforms after hybrid scoring
    sorted_platforms = sorted(
        platform_scores.items(), key=lambda x: x[1], reverse=True
    )
    primary_platform = sorted_platforms[0][0] if sorted_platforms else None
    secondary_platform = sorted_platforms[1][0] if len(sorted_platforms) > 1 else None

    # Log recommendation in terminal for transparency
    print(f"📈 Hybrid recommendation for: {product.get('product_name')}")
    print(f"  Category inferred : {category}")
    print(f"  Rating            : {rating}")
    print(f"  Reviews           : {review_count}")
    print(f"  Avg sentiment     : {sentiment}")
    print(f"  Discount          : {discount}")
    print(f"  Platform scores   : {platform_scores}")
    print(f"  Primary platform  : {primary_platform}")
    if secondary_platform:
        print(f"  Secondary         : {secondary_platform}")
    if rules_triggered:
        print("  Rules triggered   :")
        for r in rules_triggered:
            print(f"    - {r}")
    print("\n")

    return {
        "primary_platform": primary_platform,
        "secondary_platform": secondary_platform,
        "platform_scores": platform_scores,
        "rules_triggered": rules_triggered,
        "category": category,
        "discount": discount,
    }


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

                # ✅ Apply sentiment (with terminal logging)
                product = apply_sentiment(product)

                # ✅ Hybrid marketing recommendation (content-based + rule-based)
                rec = hybrid_marketing_recommendation(product)
                product["marketing_recommendation"] = rec

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
