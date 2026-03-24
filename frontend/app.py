import json

import altair as alt
import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="Product Intelligence Dashboard", layout="wide")
st.markdown(
    """
    <style>
        :root {
            --bg: #f4f7fb;
            --panel: rgba(255, 255, 255, 0.94);
            --panel-strong: #ffffff;
            --border: #d9e3ef;
            --text: #172233;
            --muted: #607086;
            --brand: #0f4c81;
            --accent: #0f766e;
            --success: #2e7d5b;
            --warning: #c7791f;
            --danger: #c44747;
            --shadow: 0 18px 44px rgba(15, 36, 64, 0.08);
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(15, 76, 129, 0.10), transparent 28%),
                radial-gradient(circle at top right, rgba(15, 118, 110, 0.08), transparent 24%),
                linear-gradient(180deg, #f9fbfe 0%, var(--bg) 100%);
            color: var(--text);
        }

        .main .block-container {
            max-width: 1220px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        h1, h2, h3 {
            color: var(--text);
            letter-spacing: -0.02em;
        }

        .hero {
            background: linear-gradient(135deg, rgba(15, 76, 129, 0.98), rgba(17, 94, 89, 0.94));
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 28px;
            padding: 30px 32px;
            box-shadow: var(--shadow);
            margin-bottom: 1.2rem;
            color: #ffffff;
        }

        .hero h1 {
            margin: 0 0 0.45rem 0;
            color: #ffffff;
            font-size: 2.25rem;
        }

        .hero p {
            margin: 0;
            max-width: 860px;
            color: rgba(255, 255, 255, 0.90);
            line-height: 1.65;
            font-size: 1rem;
        }

        .section-intro {
            margin: 0.15rem 0 1rem 0;
        }

        .section-intro h3 {
            margin-bottom: 0.15rem;
            font-size: 1.32rem;
        }

        .section-intro p {
            margin: 0;
            color: var(--muted);
        }

        .card-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 14px;
            margin: 0.35rem 0 1.35rem 0;
        }

        .card {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 16px 18px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(8px);
        }

        .card .label {
            color: var(--brand);
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 0.45rem;
        }

        .card .value {
            color: var(--text);
            font-size: 1rem;
            line-height: 1.6;
        }

        .insight-box {
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid var(--border);
            border-left: 4px solid var(--warning);
            border-radius: 14px;
            padding: 14px 18px;
            line-height: 1.7;
            box-shadow: var(--shadow);
        }

        .content-card {
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px;
            box-shadow: var(--shadow);
        }

        div[data-testid="stMetric"] {
            background: var(--panel-strong);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 12px 14px;
            box-shadow: var(--shadow);
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid var(--border);
            border-radius: 18px;
            overflow: hidden;
            background: var(--panel-strong);
            box-shadow: var(--shadow);
        }

        div[data-testid="stExpander"] {
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.95);
            box-shadow: var(--shadow);
        }

        .stButton > button {
            border-radius: 12px;
            border: 1px solid var(--border);
            min-height: 2.9rem;
            font-weight: 600;
            background: #ffffff;
            color: var(--text);
            box-shadow: 0 8px 22px rgba(15, 36, 64, 0.06);
        }

        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, var(--brand), #1565a7);
            color: #ffffff;
            border-color: transparent;
        }

        .stCaption, .stMarkdown p {
            color: var(--muted);
        }

        .stAlert {
            border-radius: 14px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


if "page" not in st.session_state:
    st.session_state.page = "home"
if "show_results" not in st.session_state:
    st.session_state.show_results = False
if "df_sorted" not in st.session_state:
    st.session_state.df_sorted = None


page = st.session_state.page


def render_hero(title: str, subtitle: str):
    st.markdown(
        f"""
        <section class="hero">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_section_intro(title: str, subtitle: str):
    st.markdown(
        f"""
        <div class="section-intro">
            <h3>{title}</h3>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_cards(items):
    blocks = []
    for label, value in items:
        blocks.append(
            f"""
            <div class="card">
                <div class="label">{label}</div>
                <div class="value">{value}</div>
            </div>
            """
        )
    st.markdown(f'<div class="card-grid">{"".join(blocks)}</div>', unsafe_allow_html=True)


def get_generated_content(row) -> dict:
    recommendation = row.get("marketing_recommendation")
    if isinstance(recommendation, dict):
        generated = recommendation.get("generated_content")
        if isinstance(generated, dict):
            return generated
    return {}


def build_explanation(row) -> str:
    name = row.get("product_name", "This product")
    platform = row.get("primary_platform", "-")
    sent = float(row.get("avg_sentiment", 0))
    rating = float(row.get("rating", 0))
    reviews = int(row.get("review_count", 0))
    rules = row.get("rules_triggered") or []
    source = row.get("sentiment_source", "none")

    src_note = {
        "reviews": "from customer reviews",
        "description": "estimated from product description",
        "name": "estimated from product name",
        "none": "unavailable",
    }.get(source, "")

    sent_label = (
        f"very positive ({sent:.2f})" if sent > 0.5 else
        f"positive ({sent:.2f})" if sent > 0.2 else
        f"neutral ({sent:.2f})" if sent > -0.1 else
        f"negative ({sent:.2f})"
    )
    rating_label = (
        f"excellent rating {rating}" if rating >= 4.5 else
        f"good rating {rating}" if rating >= 4.0 else
        f"average rating {rating}" if rating >= 3.0 else
        f"low rating {rating}" if rating > 0 else
        "no rating yet"
    )
    review_label = (
        f"{reviews} reviews with strong social proof" if reviews >= 100 else
        f"{reviews} reviews" if reviews >= 20 else
        f"only {reviews} reviews" if reviews > 0 else
        "no reviews yet"
    )

    lines = [f"**{name}** has {sent_label} sentiment ({src_note}), {rating_label}, and {review_label}."]

    if source in ("description", "name"):
        lines.append("No customer reviews were found, so the sentiment score is based on lighter text signals.")
    if source == "none":
        lines.append("This recommendation leans on rating and review volume because no text data was available.")

    for rule in rules:
        if "High sentiment" in rule and "low discount" in rule:
            lines.append(f"Strong approval suggests that **{platform}** can amplify existing product momentum.")
        elif "festival season" in rule:
            lines.append("Seasonal demand makes search-oriented acquisition especially valuable right now.")
        elif "low review count" in rule:
            lines.append("Low review volume means feedback-building channels can strengthen trust before scaling.")
        elif "Low sentiment" in rule:
            lines.append("Weak sentiment suggests focusing on broader discovery rather than depending on advocacy.")
        elif "Books" in rule:
            lines.append("This product fits a reader-oriented audience that responds well to retention and community channels.")
        elif "Skincare" in rule or "skincare" in rule:
            lines.append("This category benefits from visual storytelling and trust-led promotion.")

    if not rules:
        if source == "reviews" and sent > 0.3 and reviews > 20:
            lines.append(f"The combined signals point to **{platform}** as the most scalable marketing channel.")
        elif reviews == 0:
            lines.append(f"With limited proof available, **{platform}** is the best option to build initial awareness.")
        else:
            lines.append(f"The overall score suggests **{platform}** is the strongest near-term channel.")

    return "\n\n".join(lines)


def normalize_products(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["rating", "review_count", "avg_sentiment"]:
        if col not in df.columns:
            df[col] = 0.0
    if "availability" not in df.columns:
        df["availability"] = "Unknown"

    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(0)
    df["review_count"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0)
    df["avg_sentiment"] = pd.to_numeric(df["avg_sentiment"], errors="coerce").fillna(0)

    if "reviews" in df.columns:
        df["reviews_text"] = df["reviews"].apply(lambda x: " ".join(x) if isinstance(x, list) else "")

    dedup_col = "product_url" if "product_url" in df.columns else "product_name"
    df = df.drop_duplicates(subset=[dedup_col]).reset_index(drop=True)

    max_rev = df["review_count"].max() or 1
    df["ranking_score"] = (
        df["rating"] * 0.4
        + (df["review_count"] / (max_rev + 1)) * 0.3
        + df["avg_sentiment"] * 0.3
    )
    df = df.sort_values("ranking_score", ascending=False).reset_index(drop=True)
    df["Rank"] = df.index + 1

    def classify_status(row):
        rating, sentiment, reviews = row["rating"], row["avg_sentiment"], row["review_count"]
        if rating >= 4 and sentiment > 0.3 and reviews >= 20:
            return "Promote"
        if reviews >= 30 and sentiment < 0:
            return "Improve"
        if reviews < 10 and sentiment > 0.2:
            return "Advertise More"
        return "Rework"

    df["marketing_status"] = df.apply(classify_status, axis=1)

    if "marketing_recommendation" in df.columns:
        def get_recommendation_value(rec, key):
            return rec.get(key) if isinstance(rec, dict) else None

        for key in ["primary_platform", "platform_confidence", "secondary_platform", "category", "rules_triggered"]:
            df[key] = df["marketing_recommendation"].apply(lambda rec: get_recommendation_value(rec, key))

    if "sentiment_source" not in df.columns:
        df["sentiment_source"] = "none"

    return df


def render_home_page():
    render_section_intro(
        "Website Analysis",
        "Start with a storefront URL and the dashboard will crawl the site, rank products, and prepare channel recommendations.",
    )

    url = st.text_input("Website URL", placeholder="https://example.com")

    if st.button("Analyze Website", type="primary"):
        if not url:
            st.warning("Please enter a valid URL.")
            st.stop()

        try:
            st.info("Crawling has started. Products will appear as they are discovered.")
            response = requests.get(
                "http://127.0.0.1:8000/stream-crawl",
                params={"url": url},
                stream=True,
                timeout=600,
            )

            all_products = []
            status_placeholder = st.empty()
            table_placeholder = st.empty()

            for line in response.iter_lines(decode_unicode=True):
                if not line or line.startswith(":") or not line.startswith("data: "):
                    continue

                raw = line[6:].strip()
                if not raw:
                    continue

                try:
                    product = json.loads(raw)
                except Exception:
                    continue

                if "error" in product:
                    st.warning(product["error"])
                    continue

                all_products.append(product)
                df_live = pd.DataFrame(all_products)
                status_placeholder.info(f"{len(df_live)} products analyzed so far.")
                live_cols = [
                    c for c in ["product_name", "price", "rating", "review_count", "avg_sentiment"]
                    if c in df_live.columns
                ]
                table_placeholder.dataframe(df_live[live_cols], use_container_width=True, hide_index=True)

            st.success(f"Analysis complete. {len(all_products)} products were collected.")

            df = pd.DataFrame(all_products)
            if df.empty:
                st.warning("No products were found for this website.")
                st.stop()

            st.session_state.df_sorted = normalize_products(df)
            st.session_state.show_results = False

        except requests.exceptions.Timeout:
            st.error("The request timed out. Please try again.")
        except Exception as exc:
            st.error(f"Error: {exc}")


def render_performance_metrics(df: pd.DataFrame):
    if st.button("Back to Dashboard", key="back_from_perf"):
        st.session_state.page = "dashboard"
        st.rerun()

    render_section_intro(
        "Performance Metrics",
        "Review customer signals across the catalog and identify where product momentum is strongest.",
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Products", len(df))
    k2.metric("Average Rating", round(df["rating"].replace(0, pd.NA).mean(), 2))
    k3.metric("Total Reviews", int(df["review_count"].sum()))
    k4.metric("Average Sentiment", round(df["avg_sentiment"].mean(), 3))

    st.markdown("---")

    top_sentiment = df.sort_values("avg_sentiment", ascending=False).head(10)
    render_section_intro("Top Products by Sentiment", "Products with the strongest positive customer language.")
    sent_chart = (
        alt.Chart(top_sentiment)
        .mark_bar(cornerRadiusEnd=5)
        .encode(
            x=alt.X("avg_sentiment:Q", title="Sentiment Score"),
            y=alt.Y("product_name:N", sort="-x", title=None),
            color=alt.Color(
                "avg_sentiment:Q",
                scale=alt.Scale(domain=[-1, 1], range=["#c44747", "#2e7d5b"]),
                legend=None,
            ),
            tooltip=["product_name", "avg_sentiment", "rating", "review_count"],
        )
        .properties(height=min(360, len(top_sentiment) * 34 + 40))
    )
    st.altair_chart(sent_chart, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        render_section_intro("Sentiment Mix", "Positive, neutral, and negative product distribution.")

        def bucket(value):
            if value > 0.05:
                return "Positive"
            if value < -0.05:
                return "Negative"
            return "Neutral"

        sentiment_mix = df["avg_sentiment"].apply(bucket).value_counts().reset_index()
        sentiment_mix.columns = ["Sentiment", "Count"]
        donut = (
            alt.Chart(sentiment_mix)
            .mark_arc(innerRadius=60)
            .encode(
                theta="Count:Q",
                color=alt.Color(
                    "Sentiment:N",
                    scale=alt.Scale(
                        domain=["Positive", "Neutral", "Negative"],
                        range=["#2e7d5b", "#d5a021", "#c44747"],
                    ),
                ),
                tooltip=["Sentiment", "Count"],
            )
            .properties(height=300)
        )
        st.altair_chart(donut, use_container_width=True)

    with col2:
        render_section_intro("Sentiment Source Quality", "How much of the sentiment is based on direct review text.")
        src = df["sentiment_source"].fillna("none").value_counts().reset_index()
        src.columns = ["Source", "Count"]
        quality = (
            alt.Chart(src)
            .mark_bar(cornerRadiusEnd=5, color="#0f4c81")
            .encode(
                x=alt.X("Count:Q", title="Products"),
                y=alt.Y("Source:N", sort="-x", title=None),
                tooltip=["Source", "Count"],
            )
            .properties(height=300)
        )
        st.altair_chart(quality, use_container_width=True)

    st.markdown("---")
    render_section_intro(
        "Opportunity Matrix",
        "Use review volume and customer sentiment together to spot products ready to scale versus products that need attention.",
    )

    opp = df.copy()
    med_rev = float(opp["review_count"].median())
    med_sent = float(opp["avg_sentiment"].median())

    def quadrant(row):
        high_reviews = row["review_count"] >= med_rev
        high_sentiment = row["avg_sentiment"] >= med_sent
        if high_reviews and high_sentiment:
            return "Promote"
        if high_reviews and not high_sentiment:
            return "Improve"
        if not high_reviews and high_sentiment:
            return "Advertise More"
        return "Re-evaluate"

    opp["quadrant"] = opp.apply(quadrant, axis=1)

    review_floor = max(float(opp["review_count"].replace(0, pd.NA).min(skipna=True) or 1), 1.0)
    review_ceiling = max(float(opp["review_count"].max() or 1), review_floor + 1)
    sent_min = float(opp["avg_sentiment"].min())
    sent_max = float(opp["avg_sentiment"].max())
    sent_pad = max((sent_max - sent_min) * 0.08, 0.08)

    vline = alt.Chart(pd.DataFrame({"x": [med_rev]})).mark_rule(
        color="#7b8798",
        strokeDash=[6, 4],
        strokeWidth=1.5,
    ).encode(x="x:Q")

    hline = alt.Chart(pd.DataFrame({"y": [med_sent]})).mark_rule(
        color="#7b8798",
        strokeDash=[6, 4],
        strokeWidth=1.5,
    ).encode(y="y:Q")

    labels = pd.DataFrame(
        [
            {"x": review_ceiling, "y": sent_max + sent_pad * 0.45, "label": "Promote"},
            {"x": review_ceiling, "y": sent_min - sent_pad * 0.25, "label": "Improve"},
            {"x": review_floor, "y": sent_max + sent_pad * 0.45, "label": "Advertise More"},
            {"x": review_floor, "y": sent_min - sent_pad * 0.25, "label": "Re-evaluate"},
        ]
    )

    label_layer = (
        alt.Chart(labels)
        .mark_text(fontSize=11, fontWeight="bold", opacity=0.32, align="left")
        .encode(x="x:Q", y="y:Q", text="label:N")
    )

    dots = (
        alt.Chart(opp)
        .mark_circle(size=115, opacity=0.9)
        .encode(
            x=alt.X(
                "review_count:Q",
                title="Review Volume",
                scale=alt.Scale(type="log", domain=[review_floor, review_ceiling]),
            ),
            y=alt.Y(
                "avg_sentiment:Q",
                title="Customer Sentiment",
                scale=alt.Scale(domain=[sent_min - sent_pad, sent_max + sent_pad]),
            ),
            color=alt.Color(
                "quadrant:N",
                scale=alt.Scale(
                    domain=["Promote", "Advertise More", "Improve", "Re-evaluate"],
                    range=["#2e7d5b", "#0f4c81", "#c7791f", "#c44747"],
                ),
                title="Action",
            ),
            tooltip=["product_name", "review_count", "avg_sentiment", "quadrant"],
        )
        .properties(height=420)
    )
    st.altair_chart(dots + vline + hline + label_layer, use_container_width=True)

    st.markdown("---")
    render_section_intro("Most Reviewed Products", "Products with the highest level of customer interaction.")
    most_reviewed = df.sort_values("review_count", ascending=False).head(10)
    reviewed_chart = (
        alt.Chart(most_reviewed)
        .mark_bar(cornerRadiusEnd=5, color="#0f766e")
        .encode(
            x=alt.X("review_count:Q", title="Reviews"),
            y=alt.Y("product_name:N", sort="-x", title=None),
            tooltip=["product_name", "review_count", "rating", "avg_sentiment"],
        )
        .properties(height=320)
    )
    st.altair_chart(reviewed_chart, use_container_width=True)


def render_top10_products(df: pd.DataFrame):
    if st.button("Back to Dashboard", key="back_from_top10"):
        st.session_state.page = "dashboard"
        st.rerun()

    render_section_intro(
        "Top 10 Ranked Products",
        "The highest-ranked products based on rating, review volume, and overall customer sentiment.",
    )
    disp = [
        c for c in ["Rank", "product_name", "price", "currency", "rating", "review_count", "avg_sentiment", "availability", "brand"]
        if c in df.columns
    ]
    st.dataframe(df[disp].head(10), use_container_width=True, hide_index=True)

    st.markdown("---")
    render_section_intro("Ranking Breakdown", "See how rating, social proof, and sentiment contribute to the final score.")

    top10 = df.head(10).copy()
    max_rev = top10["review_count"].max() or 1
    top10["Rating"] = (top10["rating"] / 5.0) * 0.4
    top10["Social Proof"] = (top10["review_count"] / (max_rev + 1)) * 0.3
    top10["Sentiment"] = ((top10["avg_sentiment"] + 1) / 2) * 0.3
    melted = top10[["product_name", "Rating", "Social Proof", "Sentiment"]].melt(
        id_vars="product_name",
        var_name="Factor",
        value_name="Score",
    )

    chart = (
        alt.Chart(melted)
        .mark_bar()
        .encode(
            x=alt.X("Score:Q", stack="zero", title="Contribution"),
            y=alt.Y("product_name:N", sort="-x", title=None),
            color=alt.Color(
                "Factor:N",
                scale=alt.Scale(
                    domain=["Rating", "Social Proof", "Sentiment"],
                    range=["#0f4c81", "#0f766e", "#d9902f"],
                ),
            ),
            tooltip=["product_name", "Factor", alt.Tooltip("Score:Q", format=".3f")],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, use_container_width=True)


def render_all_products(df: pd.DataFrame):
    if st.button("Back to Dashboard", key="back_from_all"):
        st.session_state.page = "dashboard"
        st.rerun()

    render_section_intro(
        "All Products",
        "Browse the full analyzed product list, then expand any product to inspect recommendation details and generated content.",
    )
    disp = [
        c for c in ["Rank", "product_name", "price", "currency", "rating", "review_count", "avg_sentiment", "brand", "marketing_status", "primary_platform", "platform_confidence"]
        if c in df.columns
    ]
    st.dataframe(df[disp], use_container_width=True, hide_index=True)

    st.markdown("---")
    render_section_intro("Recommendation Details", "Each product includes rationale, key metrics, and campaign copy when available.")

    seen = set()
    for _, row in df.iterrows():
        uid = str(row.get("product_url", row.get("product_name", "")))
        if uid in seen:
            continue
        seen.add(uid)

        label = (
            f"{row.get('product_name', '-')} | {row.get('primary_platform', '-')} | "
            f"Rating {row.get('rating', 0)} | Sentiment {float(row.get('avg_sentiment', 0)):.3f}"
        )
        with st.expander(label):
            st.markdown(f'<div class="insight-box">{build_explanation(row)}</div>', unsafe_allow_html=True)
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Rating", row.get("rating", 0))
            m2.metric("Reviews", int(row.get("review_count", 0)))
            m3.metric("Sentiment", round(float(row.get("avg_sentiment", 0)), 3))
            m4.metric("Status", row.get("marketing_status", "-"))
            source_label = {
                "reviews": "Reviews",
                "description": "Description",
                "name": "Name",
                "none": "None",
            }.get(row.get("sentiment_source", "none"), "-")
            m5.metric("Sentiment Source", source_label)


def render_marketing_recommendations(df: pd.DataFrame):
    if st.button("Back to Dashboard", key="back_from_reco"):
        st.session_state.page = "dashboard"
        st.rerun()

    render_section_intro(
        "Marketing Recommendations",
        "Turn product signals into channel priorities, action buckets, and a practical budget view.",
    )

    if "primary_platform" not in df.columns:
        st.info("No recommendation data is available.")
        return

    top_channel = df["primary_platform"].value_counts().idxmax() if not df["primary_platform"].isna().all() else "-"
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Top Channel", top_channel)
    k2.metric("Promote", int((df["marketing_status"] == "Promote").sum()))
    k3.metric("Advertise More", int((df["marketing_status"] == "Advertise More").sum()))
    k4.metric("Improve", int((df["marketing_status"] == "Improve").sum()))
    k5.metric("Rework", int((df["marketing_status"] == "Rework").sum()))

    st.markdown("---")
    render_section_intro("Action List", "Products grouped by the next best marketing action to take.")

    action_cfg = {
        "Promote": {"border": "#2e7d5b", "tip": "These products are ready for broader paid distribution and stronger placement across high-performing channels."},
        "Advertise More": {"border": "#0f4c81", "tip": "These products have promise but need more visibility and more customer feedback to build momentum."},
        "Improve": {"border": "#c7791f", "tip": "These products attract attention but need product, pricing, or experience improvements before scaling spend."},
        "Rework": {"border": "#c44747", "tip": "These products should be reconsidered or repositioned before marketing budget is committed."},
    }

    for status, cfg in action_cfg.items():
        grp = df[df["marketing_status"] == status]
        if grp.empty:
            continue
        with st.expander(f"{status} | {len(grp)} products", expanded=(status == "Promote")):
            st.markdown(
                f'<div class="content-card" style="border-left:4px solid {cfg["border"]};">{cfg["tip"]}</div>',
                unsafe_allow_html=True,
            )
            show = [
                c for c in ["product_name", "price", "rating", "review_count", "avg_sentiment", "primary_platform", "secondary_platform"]
                if c in grp.columns
            ]
            st.dataframe(grp[show].reset_index(drop=True), use_container_width=True, hide_index=True)

    st.markdown("---")
    render_section_intro("Budget Allocation", "Suggested budget distribution based on how often each channel is recommended.")
    plat = df["primary_platform"].value_counts().reset_index()
    plat.columns = ["Channel", "Products"]
    plat["Budget %"] = (plat["Products"] / plat["Products"].sum() * 100).round(1)

    col1, col2 = st.columns([3, 2])
    with col1:
        budget_chart = (
            alt.Chart(plat)
            .mark_bar(cornerRadiusEnd=5)
            .encode(
                x=alt.X("Budget %:Q", title="Suggested Budget %"),
                y=alt.Y("Channel:N", sort="-x", title=None),
                color=alt.Color("Channel:N", legend=None),
                tooltip=["Channel", "Products", alt.Tooltip("Budget %:Q", format=".1f")],
            )
            .properties(height=max(220, len(plat) * 34))
        )
        st.altair_chart(budget_chart, use_container_width=True)
    with col2:
        st.dataframe(plat.rename(columns={"Products": "Products Count"}), use_container_width=True, hide_index=True)


def render_ai_content_page(df: pd.DataFrame):
    if st.button("Back to Dashboard", key="back_from_ai"):
        st.session_state.page = "dashboard"
        st.rerun()

    render_section_intro(
        "AI Content Generation",
        "Use these drafts as starting points for captions, promotional copy, and ad messaging tied to each recommended platform.",
    )

    found = False
    for _, row in df.iterrows():
        generated = get_generated_content(row)
        if not generated:
            continue
        found = True
        with st.expander(f"{row.get('product_name', '-')} | {row.get('primary_platform', '-')}"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Caption**")
                st.code(generated.get("caption", "Not available"), language="text")
                st.markdown("**Promotional Copy**")
                st.code(generated.get("promo_copy", "Not available"), language="text")
            with col2:
                st.markdown("**Ad Description**")
                st.code(generated.get("ad_description", "Not available"), language="text")
                st.markdown("**Call to Action**")
                st.code(generated.get("call_to_action", "Not available"), language="text")
                hashtags = generated.get("hashtags") or []
                if hashtags:
                    st.markdown("**Hashtags**")
                    st.code(" ".join(hashtags), language="text")

    if not found:
        st.info("No AI-generated content is available for the current results.")


def render_dashboard(df: pd.DataFrame):
    if st.button("Back to Home", key="back_to_home"):
        st.session_state.page = "home"
        st.rerun()

    render_section_intro(
        "Results Dashboard",
        "Choose the view that best matches your next decision, from product performance to campaign content.",
    )
    render_cards([("Catalog overview", f"{len(df)} products analyzed and ranked for decision-making.")])

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Performance Metrics", use_container_width=True, key="open_perf"):
            st.session_state.page = "performance"
            st.rerun()
        if st.button("All Products", use_container_width=True, key="open_all"):
            st.session_state.page = "all_products"
            st.rerun()
        if st.button("AI Content Generation", use_container_width=True, key="open_ai"):
            st.session_state.page = "ai_content"
            st.rerun()
    with col2:
        if st.button("Top 10 Products", use_container_width=True, key="open_top10"):
            st.session_state.page = "top10"
            st.rerun()
        if st.button("Marketing Recommendations", use_container_width=True, key="open_reco"):
            st.session_state.page = "reco"
            st.rerun()


render_hero(
    "Product Intelligence Dashboard",
    "Analyze storefronts, rank products, interpret customer signals, and turn model recommendations into campaign-ready decisions.",
)

if page == "home":
    render_home_page()

if st.session_state.df_sorted is not None:
    df = st.session_state.df_sorted

    if page == "home":
        st.markdown("---")
        st.info("The analysis is ready. Open the results dashboard to explore the product views.")
        if st.button("View Results", type="primary", use_container_width=True, key="view_results_btn"):
            st.session_state.page = "dashboard"
            st.rerun()
    elif page == "dashboard":
        render_dashboard(df)
    elif page == "performance":
        render_performance_metrics(df)
    elif page == "top10":
        render_top10_products(df)
    elif page == "all_products":
        render_all_products(df)
    elif page == "reco":
        render_marketing_recommendations(df)
    elif page == "ai_content":
        render_ai_content_page(df)