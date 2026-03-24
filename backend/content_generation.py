import re


def _safe_text(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _title_case_platform(platform: str) -> str:
    return _safe_text(platform, "your best channel")


def _infer_category(product: dict) -> str:
    text = " ".join(
        [
            _safe_text(product.get("category")),
            _safe_text(product.get("product_name")),
            _safe_text(product.get("description")),
        ]
    ).lower()

    category_keywords = {
        "electronics": ["laptop", "phone", "mobile", "camera", "headphone", "speaker", "charger"],
        "fashion": ["shirt", "dress", "jacket", "shoes", "fashion", "clothing", "kurta", "saree"],
        "books": ["book", "novel", "author", "publisher", "fiction"],
        "skincare": ["serum", "moisturizer", "cleanser", "sunscreen", "skincare", "toner", "lotion"],
        "haircare": ["shampoo", "conditioner", "hair", "scalp", "beard oil", "hair serum"],
        "home": ["sofa", "chair", "table", "decor", "curtain", "mattress", "lamp"],
    }

    for category, keywords in category_keywords.items():
        if any(keyword in text for keyword in keywords):
            return category
    return _safe_text(product.get("category"), "general").lower()


def _extract_keywords(product: dict) -> list[str]:
    text = " ".join(
        [
            _safe_text(product.get("product_name")),
            _safe_text(product.get("brand")),
            _safe_text(product.get("description")),
        ]
    )
    words = re.findall(r"[A-Za-z]{4,}", text.lower())
    stop_words = {
        "with", "this", "that", "from", "your", "have", "will", "into", "about",
        "product", "brand", "more", "only", "best", "great", "made", "helps",
        "perfect", "designed", "premium", "quality", "daily", "ideal",
    }
    seen = []
    for word in words:
        if word in stop_words or word in seen:
            continue
        seen.append(word)
        if len(seen) == 4:
            break
    return seen


def _build_benefit_line(product: dict, category: str) -> str:
    rating = float(product.get("rating") or 0)
    sentiment = float(product.get("avg_sentiment") or 0)
    review_count = int(product.get("review_count") or 0)

    social_proof = (
        f"backed by {review_count}+ customer voices"
        if review_count >= 100
        else f"rated {rating:.1f}/5 by early buyers"
        if rating >= 4
        else "crafted to stand out in a crowded market"
    )

    category_lines = {
        "electronics": "Built for buyers who compare performance before they purchase",
        "fashion": "Styled for shoppers who buy with both confidence and emotion",
        "books": "Positioned to attract readers looking for their next meaningful pick",
        "skincare": "Framed around visible value, trust, and repeat-use appeal",
        "haircare": "Built around results-led messaging and routine-based retention",
        "home": "Designed to connect comfort, utility, and style in one message",
    }

    tone_line = (
        "customer feedback is strongly positive"
        if sentiment > 0.35
        else "the positioning should focus on trust and clarity"
        if sentiment < 0
        else "the messaging should emphasize practical value"
    )

    return f"{category_lines.get(category, 'Positioned to highlight clear product value')}; {social_proof}, and {tone_line}."


def _build_cta(platform: str) -> str:
    platform_lower = _safe_text(platform).lower()
    if "instagram" in platform_lower:
        return "Tap to shop and share it with someone who'd love this."
    if "facebook" in platform_lower:
        return "Click through now to explore features, pricing, and customer feedback."
    if "youtube" in platform_lower:
        return "Watch, compare, and shop with confidence."
    if "google" in platform_lower:
        return "Search, discover, and buy while demand is high."
    if "email" in platform_lower:
        return "Open, explore, and claim the offer before it ends."
    if "whatsapp" in platform_lower:
        return "Reply now to get product details and a quick buying nudge."
    if "marketplace" in platform_lower:
        return "View the listing now and compare why buyers are choosing it."
    if "influencer" in platform_lower:
        return "See why creators are spotlighting this pick right now."
    return "Explore the product now and turn interest into action."


def _build_hashtags(product: dict, category: str) -> list[str]:
    brand = re.sub(r"[^A-Za-z0-9]", "", _safe_text(product.get("brand")))
    keywords = _extract_keywords(product)
    raw_tags = [
        category,
        "shopnow",
        "trending",
        brand.lower() if brand else "",
        *keywords[:2],
    ]
    tags = []
    for tag in raw_tags:
        cleaned = re.sub(r"[^a-z0-9]", "", tag.lower())
        if cleaned and cleaned not in tags:
            tags.append(f"#{cleaned}")
    return tags[:5]


def generate_marketing_content(product: dict, primary_platform: str, secondary_platform: str | None = None) -> dict:
    name = _safe_text(product.get("product_name"), "This product")
    brand = _safe_text(product.get("brand"), "your brand")
    price = product.get("price")
    price_text = f" at {price}" if price not in (None, "", 0, 0.0) else ""
    category = _infer_category(product)
    platform = _title_case_platform(primary_platform)
    fallback_platform = _title_case_platform(secondary_platform) if secondary_platform else "supporting campaigns"
    benefit_line = _build_benefit_line(product, category)
    cta = _build_cta(platform)
    hashtags = _build_hashtags(product, category)

    caption = (
        f"{name} from {brand}{price_text} is ready for {platform}. "
        f"{benefit_line} {cta}"
    )

    ad_description = (
        f"Promote {name} on {platform} with a value-first message that highlights why buyers should care now. "
        f"{benefit_line} Use {fallback_platform} to reinforce reach and retarget interested audiences."
    )

    promo_copy = (
        f"Featured offer: {name} by {brand}. Built for {category} shoppers, this product should be positioned with "
        f"trust, relevance, and a strong call to action on {platform}. {cta}"
    )

    return {
        "caption": caption,
        "ad_description": ad_description,
        "promo_copy": promo_copy,
        "call_to_action": cta,
        "hashtags": hashtags,
        "content_mode": "template_nlp",
    }