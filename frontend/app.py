import streamlit as st
import requests
import pandas as pd
import json
import matplotlib.pyplot as plt
import seaborn as sns
from wordcloud import WordCloud
import altair as alt

st.set_page_config(page_title="Product Intelligence Dashboard", layout="wide")
st.markdown("""
<style>
    .main .block-container { max-width: 1200px; margin: auto; }
    .why-box {
               border-left: 4px solid #FFA000;
        border-radius: 6px;
        padding: 10px 16px;
        margin-top: 6px;
        font-size: 0.91em;
        line-height: 1.6;
    }
    .action-card {
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 6px;
        font-size: 0.93em;
        line-height: 1.5;
    }
</style>
""", unsafe_allow_html=True)

# basic page routing
if "page" not in st.session_state:
    st.session_state.page = "home"

if "show_results" not in st.session_state:
    st.session_state.show_results = False
if "df_sorted" not in st.session_state:
    st.session_state.df_sorted = None

sns.set_style("whitegrid")
plt.rcParams.update({"figure.facecolor": "white"})

page = st.session_state.page

st.title("🌐 Product Intelligence Dashboard")

# ─────────────────────────────────────────────────────────────────
# HOME PAGE — CRAWLING & INPUT
# ─────────────────────────────────────────────────────────────────
if page == "home":
    url = st.text_input("Website URL", placeholder="https://example.com")

    if st.button("Crawl Website", type="primary"):
        if not url:
            st.warning("Please enter a valid URL.")
            st.stop()

        try:
            st.info("⏳ Crawling started — products stream in as they are scraped...")
            response = requests.get(
                "http://127.0.0.1:8000/stream-crawl",
                params={"url": url},
                stream=True,
                timeout=600,
            )

            all_products = []
            status_ph = st.empty()
            table_ph  = st.empty()

            for line in response.iter_lines(decode_unicode=True):
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    raw = line[6:].strip()
                    if not raw:
                        continue
                    try:
                        product = json.loads(raw)
                    except Exception:
                        continue
                    if "error" in product:
                        st.warning(f"⚠️ {product['error']}")
                        continue
                    if product:
                        all_products.append(product)
                        df_live = pd.DataFrame(all_products)
                        status_ph.info(f"✅ {len(df_live)} products scraped so far…")
                        live_cols = [c for c in ["product_name","price","rating","review_count","avg_sentiment"]
                                     if c in df_live.columns]
                        table_ph.dataframe(df_live[live_cols], use_container_width=True)

            st.success(f"✅ Done! {len(all_products)} products scraped.")

            df = pd.DataFrame(all_products)
            if df.empty:
                st.warning("No products found.")
                st.stop()

            # ── numeric coercion ──────────────────────────────────────
            for col in ["rating", "review_count", "avg_sentiment"]:
                if col not in df.columns:
                    df[col] = 0.0
            if "availability" not in df.columns:
                df["availability"] = "Unknown"

            df["rating"]        = pd.to_numeric(df["rating"],        errors="coerce").fillna(0)
            df["review_count"]  = pd.to_numeric(df["review_count"],  errors="coerce").fillna(0)
            df["avg_sentiment"] = pd.to_numeric(df["avg_sentiment"],  errors="coerce").fillna(0)

            if "reviews" in df.columns:
                df["reviews_text"] = df["reviews"].apply(
                    lambda x: " ".join(x) if isinstance(x, list) else "")

            # ── dedup by product_url then product_name ────────────────
            dedup_col = "product_url" if "product_url" in df.columns else "product_name"
            df = df.drop_duplicates(subset=[dedup_col]).reset_index(drop=True)

            # ── ranking score ─────────────────────────────────────────
            max_rev = df["review_count"].max() or 1
            df["ranking_score"] = (
                df["rating"] * 0.4
                + (df["review_count"] / (max_rev + 1)) * 0.3
                + df["avg_sentiment"] * 0.3
            )
            df_sorted = df.sort_values("ranking_score", ascending=False).reset_index(drop=True)
            df_sorted["Rank"] = df_sorted.index + 1

            # ── marketing status ──────────────────────────────────────
            def classify_status(row):
                r, s, n = row["rating"], row["avg_sentiment"], row["review_count"]
                if r >= 4 and s > 0.3 and n >= 20:  return "Promote"
                if n >= 30 and s < 0:                return "Improve"
                if n < 10 and s > 0.2:               return "Advertise More"
                return "Rework"

            df_sorted["marketing_status"] = df_sorted.apply(classify_status, axis=1)

            # ── unpack recommendation dict ─────────────────────────────
            if "marketing_recommendation" in df_sorted.columns:
                def _get(rec, key):
                    return rec.get(key) if isinstance(rec, dict) else None
                # Add platform_confidence to this list!
                keys_to_unpack = ["primary_platform", "platform_confidence", "secondary_platform", "category", "rules_triggered"]
                for key in keys_to_unpack:
                    df_sorted[key] = df_sorted["marketing_recommendation"].apply(lambda r: _get(r, key))

            # ── also pull sentiment_source from top-level if present ──
            if "sentiment_source" not in df_sorted.columns:
                df_sorted["sentiment_source"] = "none"

            st.session_state.df_sorted    = df_sorted
            st.session_state.show_results = False

        except requests.exceptions.Timeout:
            st.error("⏳ Request timed out. Try again.")
        except Exception as e:
            st.error(f"❌ Error: {e}")


# ─────────────────────────────────────────────────────────────────
# RECOMMENDATION EXPLANATION
# ─────────────────────────────────────────────────────────────────

def build_explanation(row) -> str:
    name     = row.get("product_name", "This product")
    platform = row.get("primary_platform", "—")
    sent     = float(row.get("avg_sentiment", 0))
    rating   = float(row.get("rating", 0))
    reviews  = int(row.get("review_count", 0))
    rules    = row.get("rules_triggered") or []
    source   = row.get("sentiment_source", "none")

    src_note = {
        "reviews":     "from customer reviews",
        "description": "estimated from product description ⚠️",
        "name":        "estimated from product name only ⚠️",
        "none":        "unavailable",
    }.get(source, "")

    sent_label = (
        f"very positive ({sent:.2f})" if sent > 0.5 else
        f"positive ({sent:.2f})"      if sent > 0.2 else
        f"neutral ({sent:.2f})"       if sent > -0.1 else
        f"negative ({sent:.2f})"
    )
    rating_label = (
        f"excellent rating {rating}" if rating >= 4.5 else
        f"good rating {rating}"      if rating >= 4.0 else
        f"average rating {rating}"   if rating >= 3.0 else
        f"low rating {rating}"       if rating > 0 else
        "no rating yet"
    )
    rev_label = (
        f"{reviews} reviews (strong social proof)" if reviews >= 100 else
        f"{reviews} reviews"                        if reviews >= 20 else
        f"only {reviews} reviews"                   if reviews > 0 else
        "no reviews yet"
    )

    lines = [f"**{name}** — sentiment {sent_label} ({src_note}), {rating_label}, {rev_label}."]

    if source in ("description", "name"):
        lines.append("⚠️ *No customer reviews found. Collect reviews to get a reliable sentiment score.*")
    if source == "none":
        lines.append("⚠️ *Recommendation based on rating and review count only — no text available for sentiment.*")

    for rule in rules:
        if "High sentiment" in rule and "low discount" in rule:
            lines.append(f"📣 Strong customer approval → **{platform}** and Influencer Marketing amplify existing buzz.")
        elif "festival season" in rule:
            lines.append("🎉 Festival season + electronics → **Google Ads** captures peak purchase intent.")
        elif "low review count" in rule:
            lines.append("💬 Few reviews → **WhatsApp & Email** to nurture buyers into leaving feedback.")
        elif "Low sentiment" in rule:
            lines.append("📉 Low sentiment → **Google Ads** to find new audiences instead of relying on word-of-mouth.")
        elif "Books" in rule:
            lines.append("📚 Books → **Email** (loyal readers) + **Instagram** (reading communities).")
        elif "Skincare" in rule or "skincare" in rule:
            lines.append("💆 Skincare → **Instagram** + **Influencer Marketing** drive highest conversion.")

    if not rules:
        if source == "reviews" and sent > 0.3 and reviews > 20:
            lines.append(f"✅ Strong sentiment + good social proof → **{platform}** is the best channel to scale.")
        elif reviews == 0:
            lines.append(f"🚀 No reviews yet → focus on **{platform}** to build initial awareness.")
        else:
            lines.append(f"📊 Combined score (rating + sentiment + reviews) points to **{platform}** as best ROI.")

    return "\n\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# DASHBOARD PAGE HELPERS (PERFORMANCE / TOP 10 / ALL / RECOMMENDATIONS)
# ─────────────────────────────────────────────────────────────────

def render_performance_metrics(df):
    if st.button("⬅ Back to Dashboard", key="back_from_perf"):
        st.session_state.page = "dashboard"
        st.rerun()

    st.subheader("📈 Performance Metrics")

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Products",  len(df))
    k2.metric("Avg Rating",      round(df["rating"].replace(0, pd.NA).mean(), 2))
    k3.metric("Total Reviews",   int(df["review_count"].sum()))
    k4.metric("Avg Sentiment",   round(df["avg_sentiment"].mean(), 3))
    st.markdown("---")

    # ── Top products by sentiment ─────────────────────────
    st.subheader("🚀 Top Products by Customer Sentiment")
    top_s = df.sort_values("avg_sentiment", ascending=False).head(10)
    sent_bar = (
        alt.Chart(top_s).mark_bar().encode(
            x=alt.X("avg_sentiment:Q", title="Sentiment Score"),
            y=alt.Y("product_name:N", sort="-x", title=""),
            color=alt.condition(
                alt.datum.avg_sentiment > 0.3,
                alt.value("#4CAF50"), alt.value("#FF9800")
            ),
            tooltip=["product_name","avg_sentiment","rating","review_count"],
        ).properties(width=600, height=min(320, len(top_s) * 34 + 40))
    )
    c1, c2, c3 = st.columns([1, 3, 1])
    with c2:
        st.altair_chart(sent_bar, use_container_width=False)

    st.markdown(" ")

    # ── Sentiment donut + data quality side by side ───────
    col_donut, col_quality = st.columns(2)

    with col_donut:
        st.subheader("😊 Sentiment Split")
        def bucket(s):
            return "Positive" if s > 0.05 else "Negative" if s < -0.05 else "Neutral"
        bk = df["avg_sentiment"].apply(bucket).value_counts().reset_index()
        bk.columns = ["Sentiment", "Count"]
        donut = (
            alt.Chart(bk)
            .mark_arc(innerRadius=55, outerRadius=90)
            .encode(
                theta=alt.Theta("Count:Q"),
                color=alt.Color(
                    "Sentiment:N",
                    scale=alt.Scale(
                        domain=["Positive","Neutral","Negative"],
                        range=["#4CAF50","#FFC107","#F44336"],
                    ),
                    legend=alt.Legend(orient="right"),
                ),
                tooltip=["Sentiment","Count"],
            )
            .properties(width=220, height=220)
        )
        st.altair_chart(donut, use_container_width=False)

    with col_quality:
        if "sentiment_source" in df.columns:
            st.subheader("🔍 Sentiment Data Quality")
            src_map = {
                "reviews":     "💬 Customer Reviews",
                "description": "📝 From Description",
                "name":        "🏷️ From Name Only",
                "none":        "❌ No Data",
            }
            src_colors = {
                "💬 Customer Reviews": "#4CAF50",
                "📝 From Description": "#FFC107",
                "🏷️ From Name Only":   "#FF9800",
                "❌ No Data":           "#F44336",
            }
            src = df["sentiment_source"].map(src_map).fillna("❌ No Data") \
                   .value_counts().reset_index()
            src.columns = ["Source","Count"]
            src_chart = (
                alt.Chart(src).mark_bar().encode(
                    x=alt.X("Count:Q", title="Products"),
                    y=alt.Y("Source:N", sort="-x", title=""),
                    color=alt.Color(
                        "Source:N",
                        scale=alt.Scale(
                            domain=list(src_colors.keys()),
                            range=list(src_colors.values()),
                        ),
                        legend=None,
                    ),
                    tooltip=["Source","Count"],
                ).properties(width=260, height=180)
            )
            st.altair_chart(src_chart, use_container_width=False)
            no_rev = int(df["sentiment_source"].isin(["description","name","none"]).sum())
            if no_rev:
                st.caption(f"ℹ️ {no_rev} product(s) have no customer reviews — run campaigns to collect feedback.")

    st.markdown(" ")

    # ── Most reviewed products ────────────────────────────
    st.subheader("🔥 Most Reviewed Products")
    mr = df.sort_values("review_count", ascending=False).head(10)
    rev_bar = (
        alt.Chart(mr).mark_bar(color="#5C6BC0").encode(
            x=alt.X("product_name:N", sort="-y", title=""),
            y=alt.Y("review_count:Q", title="Reviews"),
            tooltip=["product_name","review_count","rating","avg_sentiment"],
        ).properties(width=600, height=280)
    )
    c1, c2, c3 = st.columns([1, 3, 1])
    with c2:
        st.altair_chart(rev_bar, use_container_width=False)

    st.markdown(" ")

    # ── Opportunity Matrix with clear quadrant lines ───────
    st.subheader("🎯 Opportunity Matrix")
    st.caption("Dashed lines = median. Top-right = promote. Bottom-left = re-evaluate.")
    opp = df.copy()
    med_rev  = float(opp["review_count"].median())
    med_sent = float(opp["avg_sentiment"].median())

    QUAD_COLORS = {
        " Promote":        "#4CAF50",
        " Advertise More": "#2196F3",
        " Improve":        "#FF9800",
        " Re-evaluate":    "#F44336",
    }

    def quadrant(row):
        hi_rev  = row["review_count"] >= med_rev
        hi_sent = row["avg_sentiment"] >= med_sent
        if hi_rev  and hi_sent:  return " Promote"
        if hi_rev  and not hi_sent: return " Improve"
        if not hi_rev and hi_sent:  return " Advertise More"
        return " Re-evaluate"

    opp["quadrant"] = opp.apply(quadrant, axis=1)

    # reference lines
    vline = alt.Chart(pd.DataFrame({"x": [med_rev]})).mark_rule(
        color="#666", strokeDash=[6, 4], strokeWidth=1.8
    ).encode(x="x:Q")

    hline = alt.Chart(pd.DataFrame({"y": [med_sent]})).mark_rule(
        color="#666", strokeDash=[6, 4], strokeWidth=1.8
    ).encode(y="y:Q")

    # quadrant corner labels (low opacity watermarks)
    x_min  = float(opp["review_count"].min())
    x_max  = float(opp["review_count"].max())
    y_min  = float(opp["avg_sentiment"].min())
    y_max  = float(opp["avg_sentiment"].max())
    x_pad  = (x_max - x_min) * 0.04 + 0.5
    y_pad  = (y_max - y_min) * 0.04 + 0.01

    quad_labels_df = pd.DataFrame([
        {"lx": med_rev + x_pad, "ly": med_sent + y_pad, "label": " Promote"},
        {"lx": med_rev + x_pad, "ly": y_min + y_pad,    "label": " Improve"},
        {"lx": x_min,           "ly": med_sent + y_pad, "label": " Advertise More"},
        {"lx": x_min,           "ly": y_min + y_pad,    "label": " Re-evaluate"},
    ])
    quad_text = (
        alt.Chart(quad_labels_df)
        .mark_text(align="left", fontSize=11, fontWeight="bold", opacity=0.28)
        .encode(x="lx:Q", y="ly:Q", text="label:N")
    )

    dots = (
        alt.Chart(opp)
        .mark_circle(size=90, opacity=0.85)
        .encode(
            x=alt.X("review_count:Q", title="Number of Reviews"),
            y=alt.Y("avg_sentiment:Q", title="Customer Sentiment",
                    scale=alt.Scale(zero=False)),
            color=alt.Color(
                "quadrant:N",
                scale=alt.Scale(
                    domain=list(QUAD_COLORS.keys()),
                    range=list(QUAD_COLORS.values()),
                ),
                title="Action",
            ),
            tooltip=["product_name","review_count","avg_sentiment","quadrant"],
        )
    )

    opp_chart = (dots + vline + hline + quad_text).properties(width=640, height=380)
    c1, c2, c3 = st.columns([0.3, 5, 0.3])
    with c2:
        st.altair_chart(opp_chart, use_container_width=False)


def render_top10_products(df):
    if st.button("⬅ Back to Dashboard", key="back_from_top10"):
        st.session_state.page = "dashboard"
        st.rerun()

    st.subheader("🏆 Top 10 Ranked Products")
    disp = [c for c in ["Rank","product_name","price","currency","rating",
                          "review_count","avg_sentiment","availability","brand"]
            if c in df.columns]
    st.dataframe(df[disp].head(10), use_container_width=True)

    st.markdown("---")
    st.subheader("📊 What's Driving Each Product's Rank?")
    st.caption("Stacked bar shows how much rating, social proof, and sentiment each contribute to the score.")

    top10 = df.head(10).copy()
    max_rev_t = top10["review_count"].max() or 1
    top10["⭐ Rating"]       = (top10["rating"] / 5.0) * 0.4
    top10["💬 Social Proof"] = (top10["review_count"] / (max_rev_t + 1)) * 0.3
    top10["😊 Sentiment"]    = ((top10["avg_sentiment"] + 1) / 2) * 0.3

    melted = top10[["product_name","⭐ Rating","💬 Social Proof","😊 Sentiment"]].melt(
        id_vars="product_name", var_name="Factor", value_name="Score"
    )
    stack = (
        alt.Chart(melted).mark_bar().encode(
            x=alt.X("Score:Q", stack="zero", title="Score Contribution"),
            y=alt.Y("product_name:N", sort="-x", title=""),
            color=alt.Color(
                "Factor:N",
                scale=alt.Scale(
                    domain=["⭐ Rating","💬 Social Proof","😊 Sentiment"],
                    range=["#5C6BC0","#26A69A","#FFA726"],
                ),
            ),
            tooltip=["product_name","Factor", alt.Tooltip("Score:Q", format=".3f")],
        ).properties(width=580, height=min(320, len(top10) * 36 + 40))
    )
    c1, c2, c3 = st.columns([0.5, 4, 0.5])
    with c2:
        st.altair_chart(stack, use_container_width=False)


def render_all_products(df):
    if st.button("⬅ Back to Dashboard", key="back_from_all"):
        st.session_state.page = "dashboard"
        st.rerun()

    st.subheader("🛒 All Products")
    disp = [c for c in ["Rank","product_name","price","currency","rating",
                          "review_count","avg_sentiment","brand",
                          "marketing_status","primary_platform","platform_confidence"]
            if c in df.columns]
    st.dataframe(df[disp], use_container_width=True)

    st.markdown("---")
    st.subheader("💡 Recommendation Explanations")
    st.caption("Expand a product to understand why that marketing channel was chosen.")

    # deduplicate display (df already deduped at ingestion, but guard anyway)
    seen = set()
    for _, row in df.iterrows():
        uid = str(row.get("product_url", row.get("product_name", "")))
        if uid in seen:
            continue
        seen.add(uid)

        label = (
            f"🛍️ {row.get('product_name','—')}   "
            f"| {row.get('primary_platform','—')}   "
            f"| Rating: {row.get('rating',0)}   "
            f"| Sentiment: {float(row.get('avg_sentiment',0)):.3f}"
        )
        with st.expander(label):
            st.markdown(
                f'<div class="why-box">{build_explanation(row)}</div>',
                unsafe_allow_html=True,
            )
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Rating",    row.get("rating", 0))
            m2.metric("Reviews",   int(row.get("review_count", 0)))
            m3.metric("Sentiment", round(float(row.get("avg_sentiment", 0)), 3))
            m4.metric("Status",    row.get("marketing_status", "—"))
            src_icon = {
                "reviews": "💬 Reviews", "description": "📝 Description",
                "name": "🏷️ Name", "none": "❌ None",
            }.get(row.get("sentiment_source","none"), "—")
            m5.metric("Sentiment From", src_icon)


def render_marketing_recommendations(df):
    if st.button("⬅ Back to Dashboard", key="back_from_reco"):
        st.session_state.page = "dashboard"
        st.rerun()

    st.subheader("📣 Marketing Recommendations")

    if "primary_platform" not in df.columns:
        st.info("No recommendation data available.")
        return

    # ── KPI strip ─────────────────────────────────────
    top_plat = df["primary_platform"].value_counts().idxmax() \
               if not df["primary_platform"].isna().all() else "—"
    n_promote   = int((df["marketing_status"] == "Promote").sum())
    n_advertise = int((df["marketing_status"] == "Advertise More").sum())
    n_improve   = int((df["marketing_status"] == "Improve").sum())
    n_rework    = int((df["marketing_status"] == "Rework").sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("🏆 Top Channel",       top_plat)
    k2.metric("✅ Promote",            n_promote)
    k3.metric("📢 Advertise More",     n_advertise)
    k4.metric("🔧 Needs Improvement",  n_improve)
    k5.metric("❌ Needs Rework",        n_rework)

    st.markdown("---")

    # ── SECTION A: Immediate Action List ──────────────
    st.subheader("🚀 Action List — What to Do Right Now")
    st.caption("Products sorted into four clear buckets. Start with ✅ Promote, pause spend on ❌ Rework.")

    ACTION_CFG = {
        "Promote": {
           "border": "#4CAF50", "icon": "✅",
            "tip": "Your best products. Run paid ads, push on Instagram/Influencer channels, feature on your homepage. Maximise reach now.",
        },
        "Advertise More": {
           "border": "#2196F3", "icon": "📢",
            "tip": "Good products that lack visibility. Invest in Google Ads and social campaigns to grow awareness and collect more reviews.",
        },
        "Improve": {
             "border": "#FF9800", "icon": "🔧",
            "tip": "High traffic but low customer satisfaction. Pause ad spend — fix the product, description, or pricing before promoting.",
        },
        "Rework": {
            "border": "#F44336", "icon": "❌",
            "tip": "Poor on all signals. Do not advertise yet. Revisit the product quality, price point, or consider removing from the store.",
        },
    }

    for status, cfg in ACTION_CFG.items():
        grp = df[df["marketing_status"] == status]
        if grp.empty:
            continue
        with st.expander(
            f"{cfg['icon']} **{status}** — {len(grp)} product(s)",
            expanded=(status == "Promote"),
        ):
            st.markdown(
                f'<div class="action-card";'
                f'border-left:4px solid {cfg["border"]};">'
                f'<strong>What to do:</strong> {cfg["tip"]}</div>',
                unsafe_allow_html=True,
            )
            show = [c for c in ["product_name","price","rating","review_count",
                                 "avg_sentiment","primary_platform","secondary_platform"]
                    if c in grp.columns]
            st.dataframe(grp[show].reset_index(drop=True), use_container_width=True)

    st.markdown("---")

    # ── SECTION B: Budget Allocation ──────────────────
    st.subheader("💰 Where to Put Your Ad Budget")
    st.caption("Suggested budget split based on how many products each channel serves.")

    plat = df["primary_platform"].value_counts().reset_index()
    plat.columns = ["Channel", "Products"]
    plat["Budget %"] = (plat["Products"] / plat["Products"].sum() * 100).round(1)

    col_c, col_t = st.columns([3, 2])
    with col_c:
        budget_bar = (
            alt.Chart(plat)
            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
            .encode(
                x=alt.X("Budget %:Q", title="Suggested Budget %"),
                y=alt.Y("Channel:N", sort="-x", title=""),
                color=alt.Color("Channel:N", legend=None),
                tooltip=["Channel","Products",
                         alt.Tooltip("Budget %:Q", format=".1f")],
            )
            .properties(width=340, height=max(180, len(plat) * 36))
        )
        st.altair_chart(budget_bar, use_container_width=False)

    with col_t:
        st.dataframe(
            plat.rename(columns={"Products": "# Products"}),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("---")


# ─────────────────────────────────────────────────────────────────
# PAGE ROUTING AFTER CRAWL
# ─────────────────────────────────────────────────────────────────

if st.session_state.df_sorted is not None:
    df = st.session_state.df_sorted

    if page == "home":
        st.markdown("---")
        st.info("Click **View Results** to explore dashboards for performance, top products, all products, and marketing recommendations.")
        if st.button("View Results", type="primary", use_container_width=True, key="view_results_btn"):
            st.session_state.page = "dashboard"
            st.rerun()

    elif page == "dashboard":
        st.markdown("---")
        if st.button("⬅ Back to Home", key="back_to_home_from_dashboard"):
            st.session_state.page = "home"
            st.rerun()

        st.subheader("📊 Results Dashboard")
        st.caption("Choose which view you want to open in a separate page.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📈 Performance Metrics", use_container_width=True, key="open_perf"):
                st.session_state.page = "performance"
                st.rerun()
            if st.button("🛒 All Products", use_container_width=True, key="open_all"):
                st.session_state.page = "all_products"
                st.rerun()
        with col2:
            if st.button("🏆 Top 10 Products", use_container_width=True, key="open_top10"):
                st.session_state.page = "top10"
                st.rerun()
            if st.button("📣 Marketing Recommendations", use_container_width=True, key="open_reco"):
                st.session_state.page = "reco"
                st.rerun()

    elif page == "performance":
        render_performance_metrics(df)

    elif page == "top10":
        render_top10_products(df)

    elif page == "all_products":
        render_all_products(df)

    elif page == "reco":
        render_marketing_recommendations(df)


                # # ── SECTION C: Product Strategy Map ───────────────
                # st.subheader("🗺️ Product Strategy Map")
                # st.caption(
                #     "X = sentiment, Y = rating, size = review count, colour = recommended channel. "
                #     "**Top-right = safe to promote. Bottom-left = needs work.**"
                # )
                # bub = df[["product_name","rating","avg_sentiment",
                #            "review_count","primary_platform","marketing_status"]].copy()
                # bub["review_count"] = bub["review_count"].fillna(1).clip(lower=1)

                # # horizontal guide at rating=4 and vertical guide at sentiment=0.3
                # hg = alt.Chart(pd.DataFrame({"y":[4.0]})).mark_rule(
                #     color="#aaa", strokeDash=[4,3], strokeWidth=1.2).encode(y="y:Q")
                # vg = alt.Chart(pd.DataFrame({"x":[0.3]})).mark_rule(
                #     color="#aaa", strokeDash=[4,3], strokeWidth=1.2).encode(x="x:Q")

                # bubbles = (
                #     alt.Chart(bub)
                #     .mark_circle(opacity=0.82)
                #     .encode(
                #         x=alt.X("avg_sentiment:Q", title="Customer Sentiment →",
                #                 scale=alt.Scale(zero=False)),
                #         y=alt.Y("rating:Q", title="Product Rating →",
                #                 scale=alt.Scale(domain=[0, 5])),
                #         size=alt.Size("review_count:Q", title="Reviews",
                #                       scale=alt.Scale(range=[60, 700])),
                #         color=alt.Color("primary_platform:N", title="Channel"),
                #         tooltip=["product_name","rating","avg_sentiment",
                #                  "review_count","primary_platform","marketing_status"],
                #     )
                # )
                # # corner annotations
                # ann_df = pd.DataFrame([
                #     {"ax": 0.32, "ay": 4.1,  "alabel": "→ Promote these"},
                #     {"ax": -0.9, "ay": 0.3,  "alabel": "Rework / Improve →"},
                # ])
                # ann = (
                #     alt.Chart(ann_df)
                #     .mark_text(align="left", fontSize=10, color="#888", fontStyle="italic")
                #     .encode(x="ax:Q", y="ay:Q", text="alabel:N")
                # )
                # map_chart = (bubbles + hg + vg + ann).properties(width=660, height=400)
                # c1, c2, c3 = st.columns([0.3, 5, 0.3])
                # with c2:
                #     st.altair_chart(map_chart, use_container_width=False)

                # st.markdown("---")

                # # ── SECTION D: Category Intelligence ──────────────
                # if "category" in df.columns:
                #     st.subheader("🗂️ Category Intelligence")
                #     st.caption("Which categories perform best and where to invest.")

                #     cat = (
                #         df.groupby("category")
                #         .agg(
                #             Products   =("product_name",  "count"),
                #             Avg_Rating =("rating",        "mean"),
                #             Avg_Sent   =("avg_sentiment", "mean"),
                #             Total_Rev  =("review_count",  "sum"),
                #         )
                #         .reset_index()
                #         .rename(columns={
                #             "category":   "Category",
                #             "Avg_Rating": "Avg Rating",
                #             "Avg_Sent":   "Avg Sentiment",
                #             "Total_Rev":  "Total Reviews",
                #         })
                #     )
                #     cat["Avg Rating"]    = cat["Avg Rating"].round(2)
                #     cat["Avg Sentiment"] = cat["Avg Sentiment"].round(3)

                #     ca, cb = st.columns(2)
                #     with ca:
                #         st.altair_chart(
                #             alt.Chart(cat).mark_bar(color="#7986CB").encode(
                #                 x=alt.X("Category:N", sort="-y", title=""),
                #                 y=alt.Y("Avg Sentiment:Q"),
                #                 tooltip=["Category","Avg Sentiment","Products"],
                #             ).properties(width=260, height=200, title="Avg Sentiment"),
                #             use_container_width=False,
                #         )
                #     with cb:
                #         st.altair_chart(
                #             alt.Chart(cat).mark_bar(color="#26A69A").encode(
                #                 x=alt.X("Category:N", sort="-y", title=""),
                #                 y=alt.Y("Avg Rating:Q", scale=alt.Scale(domain=[0,5])),
                #                 tooltip=["Category","Avg Rating","Products"],
                #             ).properties(width=260, height=200, title="Avg Rating"),
                #             use_container_width=False,
                #         )
                #     st.dataframe(cat, use_container_width=True, hide_index=True)

                # st.markdown("---")

                # # ── SECTION E: Full summary table ─────────────────
                # st.subheader("📋 Full Recommendation Summary")
                # sum_cols = [c for c in ["Rank","product_name","category","rating",
                #                          "avg_sentiment","review_count","marketing_status",
                #                          "primary_platform","secondary_platform"]
                #             if c in df.columns]

                # def _color(v):
                #     return {
                #         "Promote":        "background-color:#e8f5e9",
                #         "Advertise More": "background-color:#e3f2fd",
                #         "Improve":        "background-color:#fff3e0",
                #         "Rework":         "background-color:#ffebee",
                #     }.get(v, "")

                # st.dataframe(df[sum_cols], use_container_width=True)