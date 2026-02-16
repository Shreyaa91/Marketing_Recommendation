import streamlit as st
import requests
import pandas as pd
import json
import matplotlib.pyplot as plt
import seaborn as sns
from wordcloud import WordCloud

st.set_page_config(page_title="Intelligent Website Crawler", layout="wide")

st.title("🚀 Intelligent Website Product Intelligence Dashboard")

url = st.text_input("🌐 Website URL", placeholder="https://example.com")

if st.button("Crawl Website"):

    if not url:
        st.warning("Please enter a valid URL.")
        st.stop()

    try:
        st.info("🚀 Streaming crawl started...")

        response = requests.get(
            "http://127.0.0.1:8000/stream-crawl",
            params={"url": url},
            stream=True,
            timeout=300
        )

        all_products = []

        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                json_data = line.replace("data: ", "").strip()
                if not json_data:
                    continue

                product = json.loads(json_data)
                if product:
                    all_products.append(product)

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
            lambda x: "In Stock" if "InStock" in str(x) else "Out of Stock"
        )

        # Ranking formula
        df["ranking_score"] = (
            df["rating"] * 0.4 +
            (df["review_count"] / (df["review_count"].max() + 1)) * 0.3 +
            df["avg_sentiment"] * 0.3
        )

        df_sorted = df.sort_values(by="ranking_score", ascending=False).reset_index(drop=True)
        df_sorted["Rank"] = df_sorted.index + 1

        # -----------------------------
        # TABS
        # -----------------------------

        tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "🏆 Top 10 Products", "🛒 All Products"])

        # ==================================================
        # TAB 1 - ADVANCED DASHBOARD
        # ==================================================

        with tab1:

            st.subheader("📊 Overall Performance Metrics")

            col1, col2, col3, col4 = st.columns(4)

            col1.metric("Total Products", len(df_sorted))
            col2.metric("Avg Rating", round(df_sorted["rating"].mean(), 2))
            col3.metric("Total Reviews", int(df_sorted["review_count"].sum()))
            col4.metric("Avg Sentiment Score", round(df_sorted["avg_sentiment"].mean(), 3))

            st.markdown("---")

            # -------------------------
            # Ranking Visualization
            # -------------------------
            st.subheader("🏆 Top Ranked Products")

            top_products = df_sorted.head(10)

            fig1, ax1 = plt.subplots()
            sns.barplot(
                data=top_products,
                x="ranking_score",
                y="product_name",
                ax=ax1
            )
            plt.title("Top 10 Products by Ranking Score")
            st.pyplot(fig1)

            # -------------------------
            # Rating Distribution
            # -------------------------
            st.subheader("⭐ Rating Distribution")

            fig2, ax2 = plt.subplots()
            sns.histplot(df_sorted["rating"], bins=10, kde=True, ax=ax2)
            plt.title("Rating Distribution")
            st.pyplot(fig2)

            # -------------------------
            # Review Count Distribution
            # -------------------------
            st.subheader("📝 Review Count Distribution")

            fig3, ax3 = plt.subplots()
            sns.histplot(df_sorted["review_count"], bins=20, kde=True, ax=ax3)
            plt.title("Review Count Distribution")
            st.pyplot(fig3)

            # -------------------------
            # Sentiment Distribution
            # -------------------------
            st.subheader("😊 Sentiment Score Distribution")

            fig4, ax4 = plt.subplots()
            sns.histplot(df_sorted["avg_sentiment"], bins=20, kde=True, ax=ax4)
            plt.title("Average Sentiment Score Distribution")
            st.pyplot(fig4)

            # -------------------------
            # WordCloud (If reviews exist)
            # -------------------------
            if "reviews_text" in df.columns:

                st.subheader("☁ Most Frequent Words in Reviews")

                all_text = " ".join(df["reviews_text"].dropna().astype(str))

                if all_text.strip():
                    wordcloud = WordCloud(
                        width=800,
                        height=400,
                        background_color="white"
                    ).generate(all_text)

                    fig5, ax5 = plt.subplots(figsize=(10, 5))
                    ax5.imshow(wordcloud, interpolation="bilinear")
                    ax5.axis("off")
                    st.pyplot(fig5)

        # ==================================================
        # TAB 2 - TOP 10 PRODUCTS TABLE
        # ==================================================

        with tab2:

            st.subheader("🏆 Top 10 Ranked Products")

            top10 = df_sorted.head(10)

            st.dataframe(
                top10[[
                    "Rank",
                    "product_name",
                    "rating",
                    "review_count",
                    "avg_sentiment",
                    "ranking_score",
                    "availability"
                ]]
            )

        # ==================================================
        # TAB 3 - ALL PRODUCTS (Detailed View)
        # ==================================================

        with tab3:

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

                    st.write("🔗 URL:", product.get("product_url"))

    except requests.exceptions.Timeout:
        st.error("⏳ Request timed out.")

    except Exception as e:
        st.error(f"❌ Error occurred: {e}")
