import streamlit as st
import requests
import pandas as pd
import json
import matplotlib.pyplot as plt
import seaborn as sns
from wordcloud import WordCloud
import altair as alt

# Use wide layout so tables and content can expand horizontally
st.set_page_config(page_title="Intelligent Website Crawler", layout="wide")
st.markdown("""
    <style>
        .main .block-container {
            max-width: 1200px;
            margin: auto;
        }
    </style>
""", unsafe_allow_html=True)
# Initialize session state
if "show_results" not in st.session_state:
    st.session_state.show_results = False
if "df_sorted" not in st.session_state:
    st.session_state.df_sorted = None

# global matplotlib / seaborn style
sns.set_style("whitegrid")
sns.set_palette("pastel")
plt.rcParams.update({"figure.facecolor": "white"})

st.title(" Website Product Intelligence Dashboard")



url = st.text_input("Website URL", placeholder="https://example.com")

if st.button("Crawl Website"):

    if not url:
        st.warning("Please enter a valid URL.")
        st.stop()

    try:
        st.info("Streaming crawl started...")

        response = requests.get(
            "http://127.0.0.1:8000/stream-crawl",
            params={"url": url},
            stream=True,
            timeout=300
        )

        all_products = []

        # Placeholders for streaming UI updates
        status_placeholder = st.empty()
        table_placeholder = st.empty()

        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                json_data = line.replace("data: ", "").strip()
                if not json_data:
                    continue

                product = json.loads(json_data)
                if product:
                    all_products.append(product)

                    # 🔄 Update UI incrementally as products stream in
                    df_stream = pd.DataFrame(all_products)
                    status_placeholder.info(f"Scraped products: {len(df_stream)}")

                    # Show a compact live table of key fields
                    if not df_stream.empty:
                        cols = [
                            c
                            for c in [
                                "product_name",
                                "price",
                                "rating",
                                "review_count",
                                "avg_sentiment",
                            ]
                            if c in df_stream.columns
                        ]
                        if cols:
                            table_placeholder.dataframe(df_stream[cols])

        st.success("✅ Crawling completed!")

        df = pd.DataFrame(all_products)

        if df.empty:
            st.warning("No products found.")
            st.stop()

        # -----------------------------
        # Data Cleaning
        # -----------------------------
        df["rating"] = pd.to_numeric(df.get("rating"), errors="coerce").fillna(0)
        df["review_count"] = pd.to_numeric(df.get("review_count"), errors="coerce").fillna(0)
        df["avg_sentiment"] = pd.to_numeric(df.get("avg_sentiment"), errors="coerce").fillna(0)

        # Clean availability
        df["availability"] = df["availability"].apply(
            lambda x: "In Stock" if "InStock" in str(x) or "In Stock" in str(x) else "Out of Stock"
        )

        # Flatten reviews to text for wordcloud/sentiment context
        if "reviews" in df.columns:
            df["reviews_text"] = df["reviews"].apply(
                lambda x: " ".join(x) if isinstance(x, list) else ""
            )

        # Ranking formula (content-based ranking for top products)
        # Uses: rating, review_count, avg_sentiment
        df["ranking_score"] = (
            df["rating"] * 0.4
            + (df["review_count"] / (df["review_count"].max() + 1)) * 0.3
            + df["avg_sentiment"] * 0.3
        )

        df_sorted = df.sort_values(by="ranking_score", ascending=False).reset_index(drop=True)
        df_sorted["Rank"] = df_sorted.index + 1

        # Marketing status classification (needed for All Products explanations)
        def classify_status(row):
            r = row["rating"]
            s = row["avg_sentiment"]
            n = row["review_count"]
            if r >= 4 and s > 0.3 and n >= 20:
                return "Promote"
            if n >= 30 and s < 0:
                return "Improve"
            if n < 10 and s > 0.2:
                return "Advertise More"
            return "Rework"

        df_sorted["marketing_status"] = df_sorted.apply(classify_status, axis=1)

        # Unpack hybrid marketing recommendation from backend, if present
        if "marketing_recommendation" in df_sorted.columns:

            def _extract_primary(rec):
                if isinstance(rec, dict):
                    return rec.get("primary_platform")
                return None

            def _extract_secondary(rec):
                if isinstance(rec, dict):
                    return rec.get("secondary_platform")
                return None

            def _extract_scores(rec):
                if isinstance(rec, dict):
                    return rec.get("platform_scores")
                return {}

            def _extract_rules(rec):
                if isinstance(rec, dict):
                    return rec.get("rules_triggered")
                return []

            df_sorted["primary_platform"] = df_sorted["marketing_recommendation"].apply(
                _extract_primary
            )
            df_sorted["secondary_platform"] = df_sorted["marketing_recommendation"].apply(
                _extract_secondary
            )
            df_sorted["platform_scores"] = df_sorted["marketing_recommendation"].apply(
                _extract_scores
            )
            df_sorted["rules_triggered"] = df_sorted["marketing_recommendation"].apply(
                _extract_rules
            )

        # Store processed data in session state
        st.session_state.df_sorted = df_sorted
        st.session_state.show_results = False

        st.markdown("---")
        st.success("Data scraping completed successfully!")
        #st.info(f"📊 **{len(df_sorted)} products** scraped and analyzed.")

    except requests.exceptions.Timeout:
        st.error("⏳ Request timed out.")

    except Exception as e:
        st.error(f"❌ Error occurred: {e}")


# ---------------------------------------------
# RESULTS DASHBOARD (shown after View Results)
# ---------------------------------------------

if st.session_state.df_sorted is not None:

    st.markdown("---")

    # Persistent View Results button
    if st.button("View Results", type="primary", use_container_width=True):
        st.session_state.show_results = True

    if not st.session_state.show_results:
        st.info("👆 Click **'View Results'**  to see the analytics dashboard.")
    else:
        df_sorted = st.session_state.df_sorted

        # -----------------------------
        # MAIN SECTIONS (Horizontal "buttons" via tabs)
        # -----------------------------

        perf_tab, top_tab, all_tab, reco_tab = st.tabs(
            [
                "📈 Performance Metrics",
                "🏆 Top 10 Products",
                "🛒 All Products",
                "📣 Marketing Recommendations",
            ]
        )

        # ==================================================
        # 1. PERFORMANCE METRICS (rich visual analytics)
        # ==================================================

        with perf_tab:

            st.subheader("📊 Overall Performance Metrics")

            col1, col2, col3, col4 = st.columns(4)

            col1.metric("Total Products", len(df_sorted))
            col2.metric("Avg Rating", round(df_sorted["rating"].replace(0, pd.NA).mean(), 2))
            col3.metric("Total Reviews", int(df_sorted["review_count"].sum()))
            col4.metric("Avg Sentiment Score", round(df_sorted["avg_sentiment"].mean(), 3))

            st.markdown("---")

            # 1) Top performing products (horizontal bar by avg sentiment)
            st.subheader("🚀 Top Performing Products (by Avg Sentiment)")
            top_sentiment = df_sorted.sort_values(
                by="avg_sentiment", ascending=False
            ).head(10)
            if not top_sentiment.empty:
                chart1 = (
                    alt.Chart(top_sentiment)
                    .mark_bar()
                    .encode(
                        x=alt.X("avg_sentiment:Q", title="Average Sentiment"),
                        y=alt.Y("product_name:N", sort="-x", title="Product"),
                        tooltip=[
                            "product_name",
                            "avg_sentiment",
                            "rating",
                            "review_count",
                        ],
                    )
                    .properties(width=500, height=300)
                )
                c1, c2, c3 = st.columns([1, 2, 1])
                with c2:
                    st.altair_chart(chart1, use_container_width=False)

            st.markdown(" ")

            # 2) Sentiment distribution (pie chart)
            st.subheader("😊 Sentiment Distribution (Positive / Neutral / Negative)")

            def bucket_sentiment(s):
                if s > 0.05:
                    return "Positive"
                if s < -0.05:
                    return "Negative"
                return "Neutral"

            sentiment_buckets = df_sorted["avg_sentiment"].apply(bucket_sentiment).value_counts()
            if not sentiment_buckets.empty:
                fig2, ax2 = plt.subplots(figsize=(3, 3))

                wedges, texts, autotexts = ax2.pie(
                    sentiment_buckets.values,
                    autopct="%1.1f%%",
                    startangle=90,
                    pctdistance=0.7
                )

                ax2.axis("equal")

                # 🔥 Move labels to legend instead of inside pie
                ax2.legend(
                    wedges,
                    sentiment_buckets.index,
                    title="Sentiment",
                    loc="center left",
                    bbox_to_anchor=(1, 0.5)
                )

                st.pyplot(fig2)


            st.markdown(" ")

            # 3) Most reviewed products (vertical bar)
            st.subheader("🔥 Most Reviewed Products")
            most_reviewed = df_sorted.sort_values(
                by="review_count", ascending=False
            ).head(10)
            if not most_reviewed.empty:
                chart_mr = (
                    alt.Chart(most_reviewed)
                    .mark_bar()
                    .encode(
                        x=alt.X("product_name:N", sort="-y", title="Product"),
                        y=alt.Y("review_count:Q", title="Number of Reviews"),
                        tooltip=[
                            "product_name",
                            "review_count",
                            "rating",
                            "avg_sentiment",
                        ],
                    )
                    .properties(width=500, height=300)
                )
                c1, c2, c3 = st.columns([1, 2, 1])
                with c2:
                    st.altair_chart(chart_mr, use_container_width=False)

            st.markdown(" ")

            # 4) Opportunity Matrix (quadrant chart) - simplified for layman
            st.subheader("🏆 Opportunity Matrix (Reviews vs Sentiment)")
            opp_df = df_sorted.copy()
            if not opp_df.empty:
                median_reviews = opp_df["review_count"].median()
                median_sent = opp_df["avg_sentiment"].median()

                def quadrant(row):
                    if row["review_count"] >= median_reviews and row["avg_sentiment"] >= median_sent:
                        return "⭐ Promote"
                    if row["review_count"] >= median_reviews and row["avg_sentiment"] < median_sent:
                        return "🔧 Improve"
                    if row["review_count"] < median_reviews and row["avg_sentiment"] >= median_sent:
                        return "📢 Advertise More"
                    return "❌ Re-evaluate"

                opp_df["quadrant"] = opp_df.apply(quadrant, axis=1)

                chart_opp = (
                    alt.Chart(opp_df)
                    .mark_circle(size=80)
                    .encode(
                        x=alt.X("review_count:Q", title="Number of Reviews"),
                        y=alt.Y("avg_sentiment:Q", title="Average Sentiment"),
                        color=alt.Color("quadrant:N", legend=alt.Legend(title="Action")),
                        tooltip=[
                            "product_name",
                            "review_count",
                            "avg_sentiment",
                            "quadrant",
                        ],
                    )
                    .properties(width=500, height=300)
                )
                c1, c2, c3 = st.columns([1, 2, 1])
                with c2:
                    st.altair_chart(chart_opp, use_container_width=False)

        # ==================================================
        # 2. TOP 10 PRODUCTS (leaderboard)
        # ==================================================

        with top_tab:

            st.subheader("🏆 Top 10 Ranked Products (Leaderboard)")

            top10 = df_sorted.head(10)

            # Table uses full available width so more columns are visible
            st.dataframe(
                top10[[
                    "Rank",
                    "product_name",
                    "rating",
                    "review_count",
                    "avg_sentiment",
                    "ranking_score",
                    "availability",
                    "primary_platform",
                    "secondary_platform",
                ]],
                use_container_width=True,
            )

        # ==================================================
        # 3. ALL PRODUCTS (Detailed View)
        # ==================================================

        with all_tab:

            sentiment_filter = st.selectbox(
                "Filter by Availability",
                ["All", "In Stock", "Out of Stock"]
            )

            if sentiment_filter != "All":
                df_display = df_sorted[df_sorted["availability"] == sentiment_filter]
            else:
                df_display = df_sorted

            for _, product in df_display.iterrows():

                with st.expander(f"#{product['Rank']} 🛒 {product['product_name']}"):

                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.write("💰 Price:", product.get("price"))
                        st.write("💱 Currency:", product.get("currency"))

                    with col2:
                        st.write("⭐ Rating:", product.get("rating"))
                        st.write("📝 Reviews:", product.get("review_count"))
                        st.write("😊 Avg Sentiment:", round(product.get("avg_sentiment", 0), 3))

                    with col3:
                        st.write("🏷 Brand:", product.get("brand"))
                        st.write("📦 Availability:", product.get("availability"))
                        if product.get("primary_platform"):
                            st.write("📣 Primary Platform:", product.get("primary_platform"))
                        if product.get("secondary_platform"):
                            st.write("📢 Secondary Platform:", product.get("secondary_platform"))

                    st.write("🔗 URL:", product.get("product_url"))

                    # Generate natural language explanation for platform recommendation
                    def explain_platform_choice(row):
                        primary = row.get("primary_platform")
                        secondary = row.get("secondary_platform")
                        rating = row.get("rating", 0)
                        sentiment = row.get("avg_sentiment", 0)
                        reviews = row.get("review_count", 0)
                        status = row.get("marketing_status", "")
                        rules = row.get("rules_triggered", [])

                        explanation = []
                        explanation.append("### 📣 Marketing Platform Recommendation Explanation")

                        if primary:
                            explanation.append(f"**Primary Platform: {primary}**")

                            # Explain based on product characteristics
                            if sentiment > 0.7:
                                explanation.append(
                                    f"• High positive sentiment ({sentiment:.2f}) indicates strong customer satisfaction. "
                                    f"{primary} is ideal for showcasing social proof and customer testimonials."
                                )
                            elif sentiment < 0:
                                explanation.append(
                                    f"• Negative sentiment ({sentiment:.2f}) suggests issues. "
                                    f"{primary} can help address concerns through targeted messaging and customer support."
                                )

                            if reviews >= 50:
                                explanation.append(
                                    f"• High review volume ({reviews}) shows strong engagement. "
                                    f"{primary} leverages this social proof effectively."
                                )
                            elif reviews < 10:
                                explanation.append(
                                    f"• Low review count ({reviews}) indicates limited visibility. "
                                    f"{primary} can help build awareness and generate initial reviews."
                                )

                            if rating >= 4.5:
                                explanation.append(
                                    f"• Excellent rating ({rating:.1f}/5) makes this product ideal for "
                                    f"{primary} campaigns that highlight quality and customer satisfaction."
                                )

                        if secondary:
                            explanation.append(f"\n**Secondary Platform: {secondary}**")
                            explanation.append(
                                f"• {secondary} complements {primary} by reaching different audience segments "
                                f"or providing alternative engagement channels."
                            )

                        if isinstance(rules, list) and rules:
                            explanation.append("\n**Rules Applied:**")
                            for r in rules:
                                explanation.append(f"• {r}")

                        if status:
                            explanation.append(f"\n**Overall Status: {status}**")
                            if status == "Promote":
                                explanation.append(
                                    "This product shows strong performance metrics. Focus marketing efforts on "
                                    "amplifying visibility and leveraging positive customer feedback."
                                )
                            elif status == "Improve":
                                explanation.append(
                                    "High review volume but negative sentiment indicates product issues. "
                                    "Prioritize addressing customer concerns before aggressive marketing."
                                )
                            elif status == "Advertise More":
                                explanation.append(
                                    "Positive sentiment but low reviews suggest untapped potential. "
                                    "Increase marketing spend to build awareness and drive more reviews."
                                )
                            elif status == "Rework":
                                explanation.append(
                                    "Low ratings, sentiment, and reviews suggest fundamental issues. "
                                    "Consider product improvements before investing in marketing."
                                )

                        return "\n".join(explanation)

                    explanation_text = explain_platform_choice(product)
                    st.markdown(explanation_text)

        # ==================================================
        # 4. MARKETING RECOMMENDATIONS (Global View)
        # ==================================================

        with reco_tab:
            st.subheader("📣 Recommended Platforms Overview")

            if "primary_platform" in df_sorted.columns:
                # Fix platform count DataFrame to have explicit columns
                vc = df_sorted["primary_platform"].value_counts().reset_index(name="count")
                vc.columns = ["platform", "count"]
                platform_counts = vc

                # Platform distribution (interactive bar)
                chart_plat = (
                    alt.Chart(platform_counts)
                    .mark_bar()
                    .encode(
                        x=alt.X("platform:N", sort="-y", title="Platform"),
                        y=alt.Y("count:Q", title="Number of Products"),
                        tooltip=["platform", "count"],
                    )
                    .properties(width=500, height=300)
                )
                c1, c2, c3 = st.columns([1, 2, 1])
                with c2:
                    st.altair_chart(chart_plat, use_container_width=False)

                st.markdown(" ")

                # Marketing status classification chart (Promote / Improve / Advertise More / Rework)
                st.subheader("🧠 Marketing Recommendation Status (AI Decision Support)")

                # marketing_status already computed earlier, no need to recompute
                chart_status = (
                    alt.Chart(df_sorted)
                    .mark_circle(size=80)
                    .encode(
                        x=alt.X("review_count:Q", title="Number of Reviews"),
                        y=alt.Y("avg_sentiment:Q", title="Average Sentiment"),
                        color=alt.Color(
                            "marketing_status:N",
                            legend=alt.Legend(title="Status"),
                        ),
                        tooltip=[
                            "product_name",
                            "rating",
                            "review_count",
                            "avg_sentiment",
                            "marketing_status",
                        ],
                    )
                    .properties(width=500, height=300)
                )
                c1, c2, c3 = st.columns([1, 2, 1])
                with c2:
                    st.altair_chart(chart_status, use_container_width=False)

                st.markdown("### Product-Level Marketing Recommendations (Rank Order)")

                # Table uses full available width so more columns are visible
                st.dataframe(
                    df_sorted[
                        [
                            "Rank",
                            "product_name",
                            "rating",
                            "review_count",
                            "avg_sentiment",
                            "primary_platform",
                            "secondary_platform",
                            "marketing_status",
                        ]
                    ],
                    use_container_width=True,
                )
            else:
                st.info("Hybrid marketing recommendations are not available for this crawl.")
