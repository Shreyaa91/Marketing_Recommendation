import json

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(page_title="AI Marketing Dashboard", layout="wide")

BACKEND_STREAM_URL = "http://127.0.0.1:8000/stream-crawl"
DASH_HEIGHT = 760


def init_state():
    if "app1_products" not in st.session_state:
        st.session_state.app1_products = []
    if "app1_error" not in st.session_state:
        st.session_state.app1_error = None


def normalize_products(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["rating", "review_count", "avg_sentiment"]:
        if col not in df.columns:
            df[col] = 0.0
    if "availability" not in df.columns:
        df["availability"] = "Unknown"

    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(0)
    df["review_count"] = pd.to_numeric(df["review_count"], errors="coerce").fillna(0)
    df["avg_sentiment"] = pd.to_numeric(df["avg_sentiment"], errors="coerce").fillna(0)

    dedup_col = "product_url" if "product_url" in df.columns else "product_name"
    df = df.drop_duplicates(subset=[dedup_col]).reset_index(drop=True)

    max_reviews = df["review_count"].max() or 1
    df["ranking_score"] = (
        df["rating"] * 0.4
        + (df["review_count"] / (max_reviews + 1)) * 0.3
        + df["avg_sentiment"] * 0.3
    )
    df = df.sort_values("ranking_score", ascending=False).reset_index(drop=True)
    df["Rank"] = df.index + 1

    # ── Compute the SAME scale functions the matrix uses ──
    reviews   = df["review_count"].astype(float)
    sentiment = df["avg_sentiment"].astype(float)

    rmin, rmax = reviews.min(), reviews.max()
    smin, smax = sentiment.min(), sentiment.max()

    def sx(v):
        return 50.0 if rmax == rmin else 8 + ((v - rmin) / (rmax - rmin)) * 84

    def sy(v):
        return 50.0 if smax == smin else 8 + ((smax - v) / (smax - smin)) * 84

    cx = 50.0  # visual crosshair is always at 50% (matches make_matrix_points sentinel)
    cy = 50.0

    def classify_status(row):
        xp = sx(float(row["review_count"]))
        yp = sy(float(row["avg_sentiment"]))
        right = xp >= cx   # high reviews
        top   = yp <= cy   # high sentiment (Y is inverted)
        if top and right:       return "Promote"
        if top and not right:   return "Advertise More"
        if not top and right:   return "Improve"
        return "Rework"

    df["marketing_status"] = df.apply(classify_status, axis=1)

    if "marketing_recommendation" in df.columns:
        def pick(rec, key):
            return rec.get(key) if isinstance(rec, dict) else None
        for key in ["primary_platform", "secondary_platform", "platform_confidence",
                    "secondary_confidence", "category", "rules_triggered"]:
            df[key] = df["marketing_recommendation"].apply(lambda r: pick(r, key))

    if "sentiment_source" not in df.columns:
        df["sentiment_source"] = "none"

    return df


def fetch_products(url: str) -> list[dict]:
    response = requests.get(BACKEND_STREAM_URL, params={"url": url}, stream=True, timeout=600)
    response.raise_for_status()

    all_products = []
    status_ph = st.empty()
    table_ph = st.empty()

    status_ph.markdown(
        """<div style="background:rgba(10,17,37,.72);border:1px solid rgba(255,255,255,.10);
        border-radius:24px;padding:18px 20px;color:#e5eefb;">
        <div style="font-size:.78rem;letter-spacing:.22em;text-transform:uppercase;color:#9fb3d9;">Live Analysis</div>
        <div style="margin-top:8px;font-size:1.05rem;font-weight:600;">Scraping in progress…</div></div>""",
        unsafe_allow_html=True,
    )

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
        status_ph.markdown(
            f"""<div style="background:rgba(10,17,37,.72);border:1px solid rgba(255,255,255,.10);
            border-radius:24px;padding:18px 20px;color:#e5eefb;">
            <div style="font-size:.78rem;letter-spacing:.22em;text-transform:uppercase;color:#9fb3d9;">Live Analysis</div>
            <div style="margin-top:8px;font-size:1.05rem;font-weight:600;">{len(df_live)} products analyzed so far.</div></div>""",
            unsafe_allow_html=True,
        )
        live_cols = [c for c in ["product_name", "price", "rating", "review_count", "avg_sentiment"]
                     if c in df_live.columns]
        if live_cols:
            table_ph.dataframe(df_live[live_cols], use_container_width=True, hide_index=True)

    return all_products


def make_matrix_points(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    reviews   = df["review_count"].astype(float)
    sentiment = df["avg_sentiment"].astype(float)

    rmin, rmax = reviews.min(), reviews.max()
    smin, smax = sentiment.min(), sentiment.max()

    # Use same median split as classify_status so colors always match
    r_median = reviews.median()
    s_median = sentiment.median()

    # Scale to 8%-92% of matrix width/height
    def sx(v):
        return 50.0 if rmax == rmin else 8 + ((v - rmin) / (rmax - rmin)) * 84

    # Y inverted: high sentiment = low Y% = near top
    def sy(v):
        return 50.0 if smax == smin else 8 + ((smax - v) / (smax - smin)) * 84

    # Crosshair always at visual 50/50 centre — matches median split
    cx, cy = 50.0, 50.0

    # Color by visual position vs crosshair — identical logic to classify_status
    def quad_color(x_pct, y_pct):
        right = x_pct >= cx   # right = high reviews (above median)
        top   = y_pct <= cy   # top   = high sentiment (above median, Y inverted)
        if top and right:      return "#22c55e"  # Promote        top-right  green
        if top and not right:  return "#f97316"  # Advertise More top-left   orange
        if not top and right:  return "#fbbf24"  # Improve        bot-right  amber
        return "#ef4444"                          # Rework         bot-left   red

    points = []
    for _, r in df.iterrows():
        rev  = float(r.get("review_count",  0))
        sent = float(r.get("avg_sentiment", 0))
        xp = round(sx(rev),  1)
        yp = round(sy(sent), 1)
        points.append({
            "name":  r.get("product_name", "?"),
            "x":     xp,
            "y":     yp,
            "color": quad_color(xp, yp),
        })

    # Sentinel: crosshair at visual centre
    points.append({"__cx__": cx, "__cy__": cy})
    return points


def build_payload(products: list[dict]) -> dict:
    empty = {"hasData": False, "metrics": [], "topProducts": [], "products": [],
             "recommendationBuckets": [], "aiContent": [], "performanceBars": [],
             "sentimentMix": [], "matrixDots": [], "budgetAllocation": [],
             "dashHeight": DASH_HEIGHT}
    if not products:
        return empty

    df = normalize_products(pd.DataFrame(products))
    avg_rating = round(df["rating"].replace(0, pd.NA).mean(), 2) if not df.empty else 0
    avg_sentiment = round(df["avg_sentiment"].mean(), 3) if not df.empty else 0
    total_reviews = int(df["review_count"].sum()) if not df.empty else 0
    top_channel = (df["primary_platform"].fillna("N/A").value_counts().idxmax()
                   if "primary_platform" in df.columns and not df["primary_platform"].dropna().empty else "N/A")
    top_product = df.iloc[0]["product_name"] if not df.empty else "N/A"

    metrics = [
        {"label": "Products Analyzed", "value": str(len(df)),       "sub": "Live crawl results",        "icon": "cube",      "color": "#6366f1"},
        {"label": "Avg Rating",         "value": str(avg_rating),    "sub": f"{total_reviews} reviews",  "icon": "star",      "color": "#f59e0b"},
        {"label": "Avg Sentiment",      "value": str(avg_sentiment), "sub": "From reviews / text",       "icon": "heart",     "color": "#22c55e"},
        {"label": "Top Channel",        "value": str(top_channel),   "sub": top_product,                 "icon": "megaphone", "color": "#38bdf8"},
    ]

    top_products = [
        {"Rank": f"#{int(r['Rank'])}", "Product": r.get("product_name", "-"),
         "Channel": r.get("primary_platform", "-"),
         "Score": round(float(r.get("ranking_score", 0)) * 20, 1),
         "Rating": round(float(r.get("rating", 0)), 2),
         "Reviews": int(r.get("review_count", 0))}
        for _, r in df.head(10).iterrows()
    ]

    products_table = [
        {"Product": r.get("product_name", "-"), "Category": r.get("category", r.get("brand", "-")),
         "Rating": round(float(r.get("rating", 0)), 2), "Reviews": int(r.get("review_count", 0)),
         "Sentiment": round(float(r.get("avg_sentiment", 0)), 3),
         "Status": r.get("marketing_status", "-"), "Channel": r.get("primary_platform", "-")}
        for _, r in df.iterrows()
    ]

    rec_buckets = []
    for status, color in [("Promote", "emerald"), ("Advertise More", "sky"),
                           ("Improve", "amber"), ("Rework", "rose")]:
        g = df[df["marketing_status"] == status]
        rec_buckets.append({"title": status, "color": color,
                             "copy": f"{len(g)} product(s) in this bucket.",
                             "items": g["product_name"].tolist()})

    ai_content = []
    for _, row in df.iterrows():
        rec = row.get("marketing_recommendation")
        gen = rec.get("generated_content") if isinstance(rec, dict) else None
        if not isinstance(gen, dict):
            continue
        ai_content.append({
            "product": row.get("product_name", "-"), "channel": row.get("primary_platform", "-"),
            "caption": gen.get("caption", "N/A"), "promo_copy": gen.get("promo_copy", "N/A"),
            "ad_description": gen.get("ad_description", "N/A"), "cta": gen.get("call_to_action", "N/A"),
            "hashtags": gen.get("hashtags", [])
        })

    perf_bars = []
    if "primary_platform" in df.columns:
        cc = df["primary_platform"].fillna("Unknown").value_counts()
        mx = cc.max() or 1
        perf_bars = [{"label": str(ch), "value": round((cnt / mx) * 100)} for ch, cnt in cc.head(6).items()]

    sentiment_mix = [
        {"label": "Positive", "value": int((df["avg_sentiment"] > 0.05).sum()),  "color": "#22c55e"},
        {"label": "Neutral",  "value": int(((df["avg_sentiment"] >= -0.05) & (df["avg_sentiment"] <= 0.05)).sum()), "color": "#38bdf8"},
        {"label": "Negative", "value": int((df["avg_sentiment"] < -0.05).sum()), "color": "#fb7185"},
    ]

    budget = []
    if "primary_platform" in df.columns and not df["primary_platform"].dropna().empty:
        cc = df["primary_platform"].fillna("Unknown").value_counts()
        tot = int(cc.sum()) or 1
        budget = [{"label": str(ch), "value": f"{round((cnt/tot)*100,1)}%"} for ch, cnt in cc.head(6).items()]

    return {
        "hasData": True, "metrics": metrics, "topProducts": top_products,
        "products": products_table, "recommendationBuckets": rec_buckets,
        "aiContent": ai_content, "performanceBars": perf_bars,
        "sentimentMix": sentiment_mix, "matrixDots": make_matrix_points(df),
        "budgetAllocation": budget, "dashHeight": DASH_HEIGHT,
    }


def build_html(payload: dict) -> str:
    payload_json = json.dumps(payload)
    h = payload["dashHeight"]
    ih = h - 32

    return (r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, #root {
  width: 100%; height: IH_PX;
  overflow: hidden;
  font-family: 'Inter', ui-sans-serif, system-ui, sans-serif;
  color: #e2e8f0;
  background:
    radial-gradient(ellipse 80% 50% at 10% -10%, rgba(99,102,241,.22) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 90% 110%, rgba(168,85,247,.18) 0%, transparent 55%),
    linear-gradient(160deg, #060b18 0%, #0a1128 50%, #0e1740 100%);
}

.shell { display:flex; width:100%; height:IH_PX; overflow:hidden; }

/* ══ Sidebar ══ */
.sidebar {
  width: 220px; flex-shrink: 0;
  height: IH_PX; overflow-y: auto; overflow-x: hidden;
  padding: 16px 10px;
  background: rgba(6,11,24,.95);
  border-right: 1px solid rgba(255,255,255,.06);
  display: flex; flex-direction: column; gap: 2px;
}
.sidebar::-webkit-scrollbar { width: 2px; }
.sidebar::-webkit-scrollbar-thumb { background: rgba(99,102,241,.4); border-radius: 99px; }

.brand {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 10px; margin-bottom: 10px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(99,102,241,.2), rgba(168,85,247,.15));
  border: 1px solid rgba(99,102,241,.25);
}
.brand-icon {
  width: 34px; height: 34px; border-radius: 10px; flex-shrink: 0;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 12px rgba(99,102,241,.4);
}
.brand-title { font-size: 15px; font-weight: 700; color: #fff; line-height: 1.2; }
.brand-sub   { font-size: 10px; color: rgba(165,180,252,.7); margin-top: 1px; }

.nav-section-label {
  font-size: 9px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .14em; color: rgba(148,163,184,.45);
  padding: 10px 10px 4px;
}
.nav-btn {
  display: flex; align-items: center; gap: 9px;
  width: 100%; padding: 9px 10px; border-radius: 10px;
  border: none; cursor: pointer; font-family: inherit;
  font-size: 14px; font-weight: 500; color: rgba(148,163,184,.85);
  background: transparent; transition: all .15s ease; position: relative;
}
.nav-btn:hover { background: rgba(255,255,255,.05); color: #e2e8f0; }
.nav-btn.active {
  background: linear-gradient(135deg, rgba(99,102,241,.25), rgba(139,92,246,.2));
  color: #a5b4fc; font-weight: 600; border: 1px solid rgba(99,102,241,.3);
}
.nav-btn.active::before {
  content: ''; position: absolute; left: 0; top: 20%; bottom: 20%;
  width: 3px; border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, #6366f1, #8b5cf6);
}
.nav-icon {
  width: 28px; height: 28px; border-radius: 8px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.07);
  transition: all .15s;
}
.nav-btn.active .nav-icon {
  background: rgba(99,102,241,.25); border-color: rgba(99,102,241,.35); color: #a5b4fc;
}

/* ══ Main ══ */
.main {
  flex: 1; height: IH_PX;
  overflow-y: auto; overflow-x: hidden;
  padding: 16px 20px;
}
.main::-webkit-scrollbar { width: 4px; }
.main::-webkit-scrollbar-thumb { background: rgba(99,102,241,.35); border-radius: 99px; }

/* ══ Cards ══ */
.card {
  background: rgba(13,20,40,.75);
  border: 1px solid rgba(255,255,255,.07);
  border-radius: 16px;
  backdrop-filter: blur(20px);
}

/* ══ Metrics ══ */
.metric-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; margin-bottom: 14px; }
.metric-card { padding: 16px 18px; border-radius: 16px; position: relative; overflow: hidden; }
.metric-card::after {
  content: ''; position: absolute; top: 0; right: 0;
  width: 80px; height: 80px; border-radius: 50%;
  background: var(--accent-glow); filter: blur(30px); opacity: .35;
}
.metric-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .16em; color: rgba(148,163,184,.6); margin-bottom: 8px; }
.metric-value { font-size: 30px; font-weight: 800; color: #fff; line-height: 1; margin-bottom: 6px; }
.metric-sub   { font-size: 13px; color: rgba(148,163,184,.7); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.metric-icon  {
  position: absolute; top: 14px; right: 14px;
  width: 32px; height: 32px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  background: var(--accent-bg); border: 1px solid var(--accent-border);
  color: var(--accent-color); z-index: 1;
}

/* ══ Panel ══ */
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.panel-title { font-size: 16px; font-weight: 700; color: #f1f5f9; }
.panel-sub   { font-size: 13px; color: rgba(148,163,184,.65); margin-top: 3px; }

.section-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: .18em;
  color: #a5b4fc; background: rgba(99,102,241,.12);
  border: 1px solid rgba(99,102,241,.22); border-radius: 99px;
  padding: 4px 10px; margin-bottom: 8px;
}

/* ══ Table ══ */
.tbl-wrap {
  overflow-y: auto; border-radius: 12px;
  border: 1px solid rgba(255,255,255,.06);
  max-height: CALC_TBL;
}
.tbl-wrap.full { max-height: CALC_FULL; }
.tbl-wrap::-webkit-scrollbar { width: 3px; }
.tbl-wrap::-webkit-scrollbar-thumb { background: rgba(99,102,241,.3); border-radius: 99px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead tr { background: rgba(99,102,241,.08); border-bottom: 1px solid rgba(255,255,255,.06); }
th { padding: 10px 13px; text-align: left; font-weight: 600; font-size: 12px;
     color: rgba(165,180,252,.8); white-space: nowrap; letter-spacing: .02em; }
tbody tr { border-bottom: 1px solid rgba(255,255,255,.03); transition: background .1s; }
tbody tr:hover { background: rgba(99,102,241,.07); }
td { padding: 10px 13px; color: #cbd5e1; white-space: nowrap; }

/* ══ Badges ══ */
.badge { display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }
.badge-promote   { background: rgba(34,197,94,.15);   color: #22c55e; border: 1px solid rgba(34,197,94,.35); }   /* green */
.badge-improve   { background: rgba(251,191,36,.15);  color: #fbbf24; border: 1px solid rgba(251,191,36,.35); }  /* amber */
.badge-advertise { background: rgba(249,115,22,.15);  color: #f97316; border: 1px solid rgba(249,115,22,.35); }  /* orange */
.badge-rework    { background: rgba(239,68,68,.15);   color: #ef4444; border: 1px solid rgba(239,68,68,.35); }   /* red */

/* ══ Progress bars ══ */
.pbar-track { height: 10px; border-radius: 99px; background: rgba(255,255,255,.07); overflow: hidden; }
.pbar-fill  {
  height: 100%; border-radius: 99px;
  background: linear-gradient(90deg, #6366f1, #8b5cf6, #38bdf8);
  box-shadow: 0 0 10px rgba(99,102,241,.55);
}

/* ══ Sentiment donut ══ */
.donut-wrap { display: flex; gap: 20px; align-items: center; padding: 8px 0; }
.donut-hole {
  width: 82px; height: 82px; border-radius: 50%;
  background: #060d1e;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  box-shadow: inset 0 0 0 2px rgba(99,102,241,.15);
}

/* ══ Opportunity Matrix — improved ══ */
.matrix-wrap {
  position: relative; border-radius: 14px; overflow: hidden;
  background: rgba(4,8,20,.85);
  border: 1px solid rgba(99,102,241,.2);
  box-shadow: inset 0 0 40px rgba(99,102,241,.04);
}
/* main grid lines — clearly visible */
.matrix-grid {
  background-image:
    linear-gradient(rgba(99,102,241,.2) 1px, transparent 1px),
    linear-gradient(90deg, rgba(99,102,241,.2) 1px, transparent 1px);
  background-size: 50px 50px;
  position: absolute; inset: 0;
}
/* faint sub-grid */
.matrix-subgrid {
  background-image:
    linear-gradient(rgba(99,102,241,.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(99,102,241,.06) 1px, transparent 1px);
  background-size: 25px 25px;
  position: absolute; inset: 0;
}
/* centre crosshair */
.matrix-hline {
  position: absolute; top: 50%; left: 0; right: 0; height: 1px;
  background: rgba(165,180,252,.35);
  box-shadow: 0 0 6px rgba(99,102,241,.5);
}
.matrix-vline {
  position: absolute; left: 50%; top: 0; bottom: 0; width: 1px;
  background: rgba(165,180,252,.35);
  box-shadow: 0 0 6px rgba(99,102,241,.5);
}
/* axis labels */
.matrix-axis {
  position: absolute; font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .14em;
  color: rgba(165,180,252,.65);
  background: rgba(6,11,24,.7); padding: 2px 7px; border-radius: 4px;
}
/* quadrant labels */
.matrix-quad {
  position: absolute; font-size: 11px; font-weight: 700;
  letter-spacing: .04em; padding: 3px 10px; border-radius: 6px;
}
/* dots */
.matrix-dot { position: absolute; transform: translate(-50%,-50%); cursor: pointer; }
.matrix-dot-inner {
  width: 14px; height: 14px; border-radius: 50%;
  border: 2px solid rgba(255,255,255,.3);
  transition: transform .15s, box-shadow .15s;
}
.matrix-dot:hover .matrix-dot-inner {
  transform: scale(1.8);
  border-color: rgba(255,255,255,.8);
}
/* tooltip on hover */
.matrix-dot-tip {
  display: none; position: absolute; bottom: 120%; left: 50%; transform: translateX(-50%);
  background: rgba(13,20,40,.97); border: 1px solid rgba(99,102,241,.3);
  color: #e2e8f0; font-size: 11px; font-weight: 500;
  padding: 4px 10px; border-radius: 7px; white-space: nowrap; z-index: 10;
  pointer-events: none;
}
.matrix-dot:hover .matrix-dot-tip { display: block; }

/* ══ Rec cards ══ */
.rec-card { border-radius: 14px; padding: 14px 15px; }
.rec-dot  { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.rec-items-list {
  max-height: 120px; overflow-y: auto;
  display: flex; flex-direction: column; gap: 4px; margin-top: 8px;
}
.rec-items-list::-webkit-scrollbar { width: 2px; }
.rec-items-list::-webkit-scrollbar-thumb { background: rgba(148,163,184,.2); border-radius: 99px; }
.rec-item {
  font-size: 13px; color: #cbd5e1; background: rgba(255,255,255,.05);
  border-radius: 7px; padding: 5px 11px; border: 1px solid rgba(255,255,255,.05);
}

/* ══ Budget ══ */
.budget-card {
  border-radius: 13px; padding: 14px 16px; text-align: center;
  background: rgba(13,20,40,.8); border: 1px solid rgba(255,255,255,.07); transition: all .15s;
}
.budget-card:hover { border-color: rgba(99,102,241,.3); transform: translateY(-2px); }

/* ══ Content accordion ══ */
.content-card {
  border-radius: 14px; border: 1px solid rgba(255,255,255,.07);
  background: rgba(13,20,40,.7); overflow: hidden; transition: border-color .15s;
}
.content-card:hover { border-color: rgba(99,102,241,.25); }
.content-summary {
  display: flex; align-items: center; gap: 10px;
  padding: 13px 14px; cursor: pointer; list-style: none;
}
.content-icon {
  width: 34px; height: 34px; border-radius: 9px; flex-shrink: 0;
  background: linear-gradient(135deg, rgba(99,102,241,.3), rgba(139,92,246,.25));
  border: 1px solid rgba(99,102,241,.25);
  display: flex; align-items: center; justify-content: center;
}
.content-field {
  border-radius: 9px; background: rgba(4,8,20,.6);
  border: 1px solid rgba(255,255,255,.05); padding: 8px 10px; margin-bottom: 6px;
}
.content-field-label {
  font-size: 9px; text-transform: uppercase; letter-spacing: .14em;
  color: rgba(148,163,184,.5); margin-bottom: 3px; font-weight: 600;
}
.content-field-val { font-size: 11px; color: #cbd5e1; line-height: 1.5; }
.hashtag {
  font-size: 10px; color: #a5b4fc; background: rgba(99,102,241,.12);
  border: 1px solid rgba(99,102,241,.2); border-radius: 99px; padding: 2px 9px;
}

/* ══ Grids ══ */
.g2    { display: grid; grid-template-columns: 1.35fr .65fr; gap: 14px; }
.g2e   { display: grid; grid-template-columns: 1fr 1fr;     gap: 14px; margin-bottom: 14px; }
.g2r   { display: grid; grid-template-columns: 1fr 1fr;     gap: 12px; }
.g4    { display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; }
.g3    { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; }
.g-right { display: flex; flex-direction: column; gap: 14px; }
.gap12   { display: flex; flex-direction: column; gap: 12px; }

/* ══ Hero ══ */
.hero {
  border-radius: 18px; padding: 20px 24px; margin-bottom: 14px;
  position: relative; overflow: hidden;
  background: linear-gradient(135deg, rgba(13,20,40,.9), rgba(20,28,56,.85));
  border: 1px solid rgba(99,102,241,.2);
}
.hero::before {
  content: ''; position: absolute; right: -60px; top: -60px;
  width: 200px; height: 200px; border-radius: 50%;
  background: radial-gradient(circle, rgba(139,92,246,.25), transparent 70%);
}
.hero::after {
  content: ''; position: absolute; left: -40px; bottom: -40px;
  width: 160px; height: 160px; border-radius: 50%;
  background: radial-gradient(circle, rgba(99,102,241,.2), transparent 70%);
}
.hero-content { position: relative; z-index: 1; }
.hero h1 { font-size: 22px; font-weight: 800; color: #fff; line-height: 1.2; margin: 8px 0 5px; letter-spacing: -.3px; }
.hero p  { font-size: 12px; color: rgba(148,163,184,.75); }

/* ══ Util ══ */
.mb12 { margin-bottom: 12px; }
.mb14 { margin-bottom: 14px; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.btn-primary {
  border-radius: 9px; padding: 8px 18px; font-size: 12px; font-weight: 600;
  color: #fff; border: none; cursor: pointer; font-family: inherit;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  box-shadow: 0 4px 14px rgba(99,102,241,.35);
  transition: opacity .15s, transform .15s;
}
.btn-primary:hover { opacity: .9; transform: translateY(-1px); }

/* ══ Empty ══ */
.empty {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; text-align: center; gap: 12px; padding: 40px;
}
.empty-icon {
  width: 64px; height: 64px; border-radius: 20px;
  background: linear-gradient(135deg, rgba(99,102,241,.2), rgba(139,92,246,.15));
  border: 1px solid rgba(99,102,241,.25);
  display: flex; align-items: center; justify-content: center; color: #a5b4fc;
}
.empty h2 { font-size: 20px; font-weight: 800; color: #fff; }
.empty p  { font-size: 12px; color: rgba(148,163,184,.7); max-width: 340px; line-height: 1.7; }
</style>
</head>
<body>
<div id="root"></div>
<script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script>window.__D__ = PAYLOAD_JSON;</script>
<script type="text/babel">
const { useMemo, useState } = React;
const D = window.__D__;

const NAV = [
  { id:"dashboard",       label:"Dashboard",        icon:"home"      },
  { id:"performance",     label:"Performance",      icon:"chart"     },
  { id:"top10",           label:"Top 10 Products",  icon:"trophy"    },
  { id:"products",        label:"All Products",     icon:"cube"      },
  { id:"recommendations", label:"Recommendations",  icon:"megaphone" },
  { id:"content",         label:"AI Content",       icon:"sparkles"  },
];

function Ico({ n, s=14 }) {
  const p = { width:s, height:s, viewBox:"0 0 24 24", fill:"none", stroke:"currentColor",
               strokeWidth:"2", strokeLinecap:"round", strokeLinejoin:"round" };
  const map = {
    home:      <svg {...p}><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>,
    chart:     <svg {...p}><path d="M4 20h16"/><path d="M7 16v-5"/><path d="M12 16V6"/><path d="M17 16v-8"/></svg>,
    trophy:    <svg {...p}><path d="M8 21h8"/><path d="M12 17v4"/><path d="M7 4h10v4a5 5 0 0 1-10 0V4Z"/><path d="M7 6H4a3 3 0 0 0 3 3"/><path d="M17 6h3a3 3 0 0 1-3 3"/></svg>,
    cube:      <svg {...p}><path d="m12 3 8 4.5v9L12 21 4 16.5v-9L12 3Z"/><path d="m12 12 8-4.5"/><path d="m12 12-8-4.5"/><path d="M12 12v9"/></svg>,
    megaphone: <svg {...p}><path d="m3 11 13-5v12L3 13v-2Z"/><path d="M16 8c2.2 0 4 1.8 4 4s-1.8 4-4 4"/><path d="M6 13v4a2 2 0 0 0 2 2h1"/></svg>,
    sparkles:  <svg {...p}><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8L12 3Z"/><path d="M19 4v4"/><path d="M21 6h-4"/><path d="M5 16v5"/><path d="M7.5 18.5h-5"/></svg>,
    star:      <svg {...p}><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>,
    heart:     <svg {...p}><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>,
  };
  return map[n] || map.cube;
}

function NavItem({ item, active, onClick }) {
  return (
    <button className={`nav-btn ${active ? "active" : ""}`} onClick={() => onClick(item.id)}>
      <span className="nav-icon"><Ico n={item.icon} s={13}/></span>
      {item.label}
    </button>
  );
}

const ACCENT = {
  cube:      { color:"#818cf8", bg:"rgba(99,102,241,.15)",  border:"rgba(99,102,241,.25)",  glow:"rgba(99,102,241,1)"  },
  star:      { color:"#fcd34d", bg:"rgba(245,158,11,.15)",  border:"rgba(245,158,11,.25)",  glow:"rgba(245,158,11,1)"  },
  heart:     { color:"#4ade80", bg:"rgba(34,197,94,.15)",   border:"rgba(34,197,94,.25)",   glow:"rgba(34,197,94,1)"   },
  megaphone: { color:"#7dd3fc", bg:"rgba(56,189,248,.15)",  border:"rgba(56,189,248,.25)",  glow:"rgba(56,189,248,1)"  },
};
function MC({ label, value, sub, icon }) {
  const a = ACCENT[icon] || ACCENT.cube;
  return (
    <div className="card metric-card" style={{"--accent-color":a.color,"--accent-bg":a.bg,"--accent-border":a.border,"--accent-glow":a.glow}}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-sub">{sub}</div>
      <div className="metric-icon"><Ico n={icon} s={14}/></div>
    </div>
  );
}

function Panel({ title, subtitle, action, children, style, className }) {
  return (
    <div className={`card ${className||""}`} style={{padding:"16px 18px", borderRadius:16, ...style}}>
      <div className="panel-head">
        <div>
          <div className="panel-title">{title}</div>
          {subtitle && <div className="panel-sub">{subtitle}</div>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function StatusBadge({ val }) {
  const cls = val === "Promote" ? "badge-promote"
            : val === "Improve" ? "badge-improve"
            : val === "Advertise More" ? "badge-advertise"
            : "badge-rework";
  return <span className={`badge ${cls}`}>{val}</span>;
}

function DT({ rows, full }) {
  if (!rows?.length) return <p style={{color:"rgba(148,163,184,.5)",fontSize:12,padding:8}}>No data available.</p>;
  const keys = Object.keys(rows[0]);
  return (
    <div className={`tbl-wrap${full?" full":""}`}>
      <table>
        <thead><tr>{keys.map(k => <th key={k}>{k}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {keys.map(k => (
                <td key={k}>{k === "Status" ? <StatusBadge val={row[k]}/> : row[k]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PBars() {
  const items = D.performanceBars || [];
  if (!items.length) return <p style={{color:"rgba(148,163,184,.5)",fontSize:13}}>No data.</p>;
  return (
    <div style={{display:"flex",flexDirection:"column",gap:13}}>
      {items.map((it, i) => (
        <div key={it.label}>
          <div className="flex-between" style={{fontSize:13,marginBottom:6}}>
            <span style={{color:"#94a3b8",fontWeight:500}}>{it.label}</span>
            <span style={{color:"#a5b4fc",fontWeight:700}}>{it.value}%</span>
          </div>
          <div className="pbar-track">
            <div className="pbar-fill" style={{width:`${it.value}%`, opacity: 0.7 + i * 0.05}}/>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Improved Sentiment Donut ── */
function Sent() {
  const items = D.sentimentMix || [];
  const total = items.reduce((s,i) => s + i.value, 0);
  if (!total) return <p style={{color:"rgba(148,163,184,.5)",fontSize:13}}>No data.</p>;

  const d0 = (items[0]?.value / total) * 360;
  const d1 = d0 + ((items[1]?.value / total) * 360);

  return (
    <div className="donut-wrap">
      {/* Donut ring — bigger, proper gap between ring and hole */}
      <div style={{
        flexShrink:0, width:110, height:110, borderRadius:"50%",
        background:`conic-gradient(
          #22c55e 0deg ${d0}deg,
          #38bdf8 ${d0}deg ${d1}deg,
          #fb7185 ${d1}deg 360deg
        )`,
        display:"flex", alignItems:"center", justifyContent:"center",
        boxShadow:"0 0 28px rgba(99,102,241,.25), 0 0 0 1px rgba(99,102,241,.15)",
        padding: 6,
      }}>
        <div className="donut-hole">
          <span style={{fontSize:22,fontWeight:800,color:"#fff",lineHeight:1}}>{total}</span>
          <span style={{fontSize:9,color:"rgba(148,163,184,.6)",textTransform:"uppercase",letterSpacing:".1em",marginTop:3}}>total</span>
        </div>
      </div>

      {/* Legend */}
      <div style={{flex:1,display:"flex",flexDirection:"column",gap:10}}>
        {items.map((it, i) => {
          const pct = Math.round((it.value / total) * 100);
          return (
            <div key={it.label}>
              <div className="flex-between" style={{marginBottom:5}}>
                <div style={{display:"flex",alignItems:"center",gap:7}}>
                  <div style={{width:10,height:10,borderRadius:"50%",background:it.color,boxShadow:`0 0 6px ${it.color}99`,flexShrink:0}}/>
                  <span style={{fontSize:13,color:"#cbd5e1",fontWeight:500}}>{it.label}</span>
                </div>
                <div style={{display:"flex",alignItems:"center",gap:8}}>
                  <span style={{fontSize:13,color:it.color,fontWeight:700}}>{it.value}</span>
                  <span style={{fontSize:11,color:"rgba(148,163,184,.5)",minWidth:32,textAlign:"right"}}>{pct}%</span>
                </div>
              </div>
              <div className="pbar-track" style={{height:5}}>
                <div style={{height:5,borderRadius:99,width:`${Math.max(pct,3)}%`,background:it.color,boxShadow:`0 0 6px ${it.color}66`}}/>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Opportunity Matrix ── */
function Matrix() {
  const raw  = D.matrixDots || [];

  // Separate the crosshair sentinel from real dots
  const sentinel = raw.find(d => d.__cx__ !== undefined) || { __cx__: 50, __cy__: 50 };
  const dots     = raw.filter(d => d.__cx__ === undefined);
  const cx       = sentinel.__cx__;   // % position of median-reviews crosshair
  const cy       = sentinel.__cy__;   // % position of median-sentiment crosshair

  /*
    Axes (crosshair sits at data medians, not 50%):
      X → review_count:  left=low,  right=high
      Y → avg_sentiment: top=high,  bottom=low  (screen Y inverted)

    Quadrants:
      Top-right  (high sent + high rev) → Promote       green
      Top-left   (high sent + low  rev) → Advertise More blue
      Bot-right  (low  sent + high rev) → Improve       amber
      Bot-left   (low  sent + low  rev) → Rework        rose
  */
  const quads = [
    { label:"● Promote",        s:{ right:10, top:8,    color:"rgba(34,197,94,.95)",   background:"rgba(34,197,94,.15)",   border:"1px solid rgba(34,197,94,.35)"   } },
    { label:"● Advertise More", s:{ left:10,  top:8,    color:"rgba(249,115,22,.95)",  background:"rgba(249,115,22,.15)",  border:"1px solid rgba(249,115,22,.35)"  } },
    { label:"● Improve",        s:{ right:10, bottom:8, color:"rgba(251,191,36,.95)",  background:"rgba(251,191,36,.15)",  border:"1px solid rgba(251,191,36,.35)"  } },
    { label:"● Rework",         s:{ left:10,  bottom:8, color:"rgba(239,68,68,.95)",   background:"rgba(239,68,68,.15)",   border:"1px solid rgba(239,68,68,.35)"   } },
  ];

  return (
    <div className="matrix-wrap" style={{height:280, position:"relative"}}>
      <div className="matrix-subgrid"/>
      <div className="matrix-grid"/>

      {/* Crosshair at actual data medians */}
      <div style={{
        position:"absolute", top:`${cy}%`, left:0, right:0, height:2,
        background:"linear-gradient(90deg,transparent,rgba(165,180,252,.55),transparent)",
        boxShadow:"0 0 8px rgba(99,102,241,.5)",
      }}/>
      <div style={{
        position:"absolute", left:`${cx}%`, top:0, bottom:0, width:2,
        background:"linear-gradient(180deg,transparent,rgba(165,180,252,.55),transparent)",
        boxShadow:"0 0 8px rgba(99,102,241,.5)",
      }}/>

      {/* Axis labels */}
      <div style={{
        position:"absolute", left:"50%", top:5,
        transform:"translateX(-50%)",
        fontSize:9, fontWeight:700, textTransform:"uppercase",
        letterSpacing:".13em", color:"rgba(165,180,252,.7)",
        background:"rgba(6,11,24,.75)", padding:"2px 8px", borderRadius:4,
      }}>↑ Sentiment high</div>
      <div style={{
        position:"absolute", right:6, top:"50%",
        transform:"translateY(-50%)",
        fontSize:9, fontWeight:700, textTransform:"uppercase",
        letterSpacing:".13em", color:"rgba(165,180,252,.7)",
        background:"rgba(6,11,24,.75)", padding:"2px 8px", borderRadius:4,
      }}>Reviews high →</div>

      {/* Quadrant labels */}
      {quads.map(q => (
        <div key={q.label} style={{
          position:"absolute", fontSize:11, fontWeight:700,
          padding:"3px 10px", borderRadius:7, ...q.s
        }}>{q.label}</div>
      ))}

      {/* Dots */}
      {dots.map((d, i) => (
        <div key={i} className="matrix-dot" style={{left:`${d.x}%`, top:`${d.y}%`}}>
          <div className="matrix-dot-inner" style={{
            background: d.color,
            boxShadow: `0 0 10px ${d.color}cc, 0 0 22px ${d.color}44`,
          }}/>
          <div className="matrix-dot-tip">{d.name}</div>
        </div>
      ))}
    </div>
  );
}

function RecCard({ b }) {
  const pal = {
    emerald:{ bg:"rgba(34,197,94,.08)",   bd:"rgba(34,197,94,.25)",   dot:"#22c55e", glow:"rgba(34,197,94,.3)"   },  // Promote — green
    sky:    { bg:"rgba(249,115,22,.08)",  bd:"rgba(249,115,22,.25)",  dot:"#f97316", glow:"rgba(249,115,22,.3)"  },  // Advertise More — orange
    amber:  { bg:"rgba(251,191,36,.08)",  bd:"rgba(251,191,36,.25)",  dot:"#fbbf24", glow:"rgba(251,191,36,.3)"  },  // Improve — amber
    rose:   { bg:"rgba(239,68,68,.08)",   bd:"rgba(239,68,68,.25)",   dot:"#ef4444", glow:"rgba(239,68,68,.3)"   },  // Rework — red
  };
  const c = pal[b.color] || pal.rose;
  return (
    <div className="rec-card" style={{background:c.bg, border:`1px solid ${c.bd}`}}>
      <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:6}}>
        <div className="rec-dot" style={{background:c.dot,boxShadow:`0 0 6px ${c.glow}`}}/>
        <span style={{fontWeight:700,color:"#f1f5f9",fontSize:14}}>{b.title}</span>
        <span style={{marginLeft:"auto",fontSize:11,color:"rgba(148,163,184,.6)",
          background:"rgba(255,255,255,.06)",border:"1px solid rgba(255,255,255,.07)",
          borderRadius:99,padding:"2px 10px"}}>{b.items?.length||0}</span>
      </div>
      <p style={{fontSize:12,color:"rgba(148,163,184,.7)",marginBottom:8,lineHeight:1.55}}>{b.copy}</p>
      <div className="rec-items-list">
        {(b.items||[]).map((item,i) => <div key={i} className="rec-item">{item}</div>)}
      </div>
    </div>
  );
}

/* ════ VIEWS ════ */

function VDashboard() {
  return (
    <div>
      <div className="hero">
        <div className="hero-content">
          <div className="section-badge"><Ico n="sparkles" s={9}/> AI Marketing Command Center</div>
          <h1>Marketing Analytics Dashboard</h1>
          <p>Real-time insights powered by the live FastAPI crawl stream.</p>
        </div>
      </div>
      <div className="metric-grid mb14">
        {D.metrics.map(m => <MC key={m.label} {...m}/>)}
      </div>
      <div className="g2">
        <Panel title="Top 10 Products" subtitle="Ranked by rating, reviews & platform fit.">
          <DT rows={D.topProducts}/>
        </Panel>
        <div className="g-right">
          <Panel title="Channel Momentum" subtitle="Distribution by recommended channel."><PBars/></Panel>
          <Panel title="Sentiment Mix" subtitle="Product sentiment breakdown."><Sent/></Panel>
        </div>
      </div>
    </div>
  );
}

function VPerformance() {
  const [show, setShow] = useState(false);
  return (
    <div>
      <div className="metric-grid mb12">{D.metrics.map(m => <MC key={m.label} {...m}/>)}</div>
      <div className="flex-between mb12">
        <div>
          <div style={{fontSize:15,fontWeight:700,color:"#f1f5f9"}}>Charts & Analysis</div>
          <div style={{fontSize:12,color:"rgba(148,163,184,.6)",marginTop:2}}>Toggle to reveal performance visualizations</div>
        </div>
        <button className="btn-primary" onClick={() => setShow(v => !v)}>
          {show ? "Hide Charts" : "Show Charts & Matrix"}
        </button>
      </div>
      {show ? (
        <div>
          <div className="g2e">
            <Panel title="Performance by Channel" subtitle="Relative channel strength."><PBars/></Panel>
            <Panel title="Sentiment Distribution" subtitle="Across the full product set."><Sent/></Panel>
          </div>
          <Panel title="Opportunity Matrix" subtitle="Products plotted by review volume vs sentiment score.">
            <Matrix/>
          </Panel>
        </div>
      ) : (
        <div style={{borderRadius:14,border:"1px dashed rgba(99,102,241,.25)",
          background:"rgba(99,102,241,.04)",padding:"32px",textAlign:"center"}}>
          <div style={{color:"rgba(165,180,252,.7)",fontSize:14,fontWeight:600,marginBottom:5}}>Charts are hidden</div>
          <div style={{color:"rgba(148,163,184,.5)",fontSize:12}}>Click the button above to reveal all charts and the opportunity matrix.</div>
        </div>
      )}
    </div>
  );
}

function VTop10() {
  return (
    <Panel title="Top 10 Products" subtitle="Highest-scoring products from the live crawl dataset.">
      <DT rows={D.topProducts} full/>
    </Panel>
  );
}

function VProducts() {
  return (
    <Panel title="All Products" subtitle="Every product received from the backend, normalized and scored.">
      <DT rows={D.products} full/>
    </Panel>
  );
}

function VRecommendations() {
  return (
    <div className="gap12">
      <Panel title="Marketing Recommendations" subtitle="Bucketed by rating, review volume and sentiment score.">
        <div className="g2r">{D.recommendationBuckets.map(b => <RecCard key={b.title} b={b}/>)}</div>
      </Panel>
      <Panel title="Budget Guidance" subtitle="Suggested allocation share by recommended channel.">
        <div className="g4">
          {(D.budgetAllocation||[]).map(it => (
            <div key={it.label} className="budget-card">
              <div style={{fontSize:12,color:"rgba(148,163,184,.6)",marginBottom:5}}>{it.label}</div>
              <div style={{fontSize:24,fontWeight:800,color:"#a5b4fc"}}>{it.value}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function VContent() {
  return (
    <Panel title="AI Content Generation" subtitle="Generated content from the backend recommendation payload.">
      <div className="g3">
        {(D.aiContent||[]).length ? D.aiContent.map(item => (
          <details key={item.product} className="content-card">
            <summary className="content-summary">
              <div className="content-icon"><Ico n="sparkles" s={13}/></div>
              <div style={{flex:1,minWidth:0}}>
                <div style={{fontSize:13,fontWeight:700,color:"#f1f5f9",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{item.product}</div>
                <div style={{fontSize:11,color:"rgba(148,163,184,.55)",marginTop:2}}>{item.channel}</div>
              </div>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(148,163,184,.5)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </summary>
            <div style={{padding:"0 14px 14px"}}>
              {[["Caption",item.caption],["Promo Copy",item.promo_copy],["Ad Description",item.ad_description],["Call to Action",item.cta]].map(([lbl,val]) => (
                <div key={lbl} className="content-field">
                  <div className="content-field-label">{lbl}</div>
                  <div className="content-field-val">{val}</div>
                </div>
              ))}
              {(item.hashtags||[]).length > 0 && (
                <div style={{display:"flex",flexWrap:"wrap",gap:5,marginTop:6}}>
                  {item.hashtags.map(t => <span key={t} className="hashtag">{t}</span>)}
                </div>
              )}
            </div>
          </details>
        )) : <p style={{color:"rgba(148,163,184,.5)",fontSize:12,padding:8}}>No AI content available.</p>}
      </div>
    </Panel>
  );
}

function EmptyState() {
  return (
    <div className="empty">
      <div className="empty-icon"><Ico n="sparkles" s={28}/></div>
      <h2>Ready to Analyze</h2>
      <p>Go to the Analyze Website tab, enter a URL and click Analyze. The dashboard will populate automatically.</p>
    </div>
  );
}

function App() {
  const [active, setActive] = useState("dashboard");
  const view = useMemo(() => {
    if (active === "dashboard")       return <VDashboard/>;
    if (active === "performance")     return <VPerformance/>;
    if (active === "top10")           return <VTop10/>;
    if (active === "products")        return <VProducts/>;
    if (active === "recommendations") return <VRecommendations/>;
    if (active === "content")         return <VContent/>;
    return <VDashboard/>;
  }, [active]);

  if (!D.hasData) return (
    <div className="shell" style={{justifyContent:"center",alignItems:"center"}}><EmptyState/></div>
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon"><Ico n="sparkles" s={16}/></div>
          <div>
            <div className="brand-title">AI Marketing</div>
            <div className="brand-sub">Campaign Dashboard</div>
          </div>
        </div>
        <div className="nav-section-label">Navigation</div>
        {NAV.map(item => <NavItem key={item.id} item={item} active={active===item.id} onClick={setActive}/>)}
      </aside>
      <main className="main">{view}</main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
</script>
</body>
</html>
""".replace("IH_PX",       f"{ih}px")
   .replace("CALC_TBL",    f"calc({ih}px - 230px)")
   .replace("CALC_FULL",   f"calc({ih}px - 120px)")
   .replace("PAYLOAD_JSON", payload_json))


def main():
    init_state()

    st.title("AI Marketing Campaign")

    st.markdown("""
    <style>
        .stApp {
            background:
                radial-gradient(ellipse 80% 50% at 10% -10%, rgba(99,102,241,.18) 0%, transparent 55%),
                radial-gradient(ellipse 60% 40% at 90% 110%, rgba(168,85,247,.15) 0%, transparent 50%),
                linear-gradient(160deg, #060b18 0%, #0a1128 50%, #0e1740 100%);
            color: #e2e8f0;
        }
        [data-testid="stHeader"] { background: transparent; }
        .main .block-container { max-width: 1500px; padding-top: 1.5rem; padding-bottom: 2rem; }
        div[data-testid="stDataFrame"] {
            border: 1px solid rgba(99,102,241,0.2); overflow: hidden;
            background: rgba(13,20,40,0.8); box-shadow: 0 8px 32px rgba(6,11,24,0.4);
            border-radius: 16px;
        }
        .stTextInput > div > div > input {
            background: rgba(13,20,40,0.8); border: 1px solid rgba(99,102,241,0.25);
            color: #e2e8f0; border-radius: 12px;
        }
        .stTextInput > div > div > input:focus {
            border-color: rgba(99,102,241,0.5) !important;
            box-shadow: 0 0 0 2px rgba(99,102,241,0.15) !important;
        }
        .stButton > button {
            border-radius: 12px; min-height: 3rem;
            border: 1px solid rgba(99,102,241,0.3);
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            color: white; font-weight: 600;
            box-shadow: 0 4px 14px rgba(99,102,241,0.3);
        }
        .stCaption, .stMarkdown, label { color: #a5b4fc; }
        div[data-testid="stVerticalBlockBorderWrapper"] > div {
            border: 1px solid rgba(99,102,241,0.2) !important;
            border-radius: 16px !important;
            background: rgba(13,20,40,0.6) !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 6px; background: rgba(13,20,40,0.85);
            border-radius: 14px; padding: 5px;
            border: 1px solid rgba(99,102,241,0.2);
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 10px; padding: 9px 22px; color: #94a3b8;
            font-weight: 600; font-size: 0.92rem;
        }
        .stTabs [aria-selected="true"] {
            background: linear-gradient(135deg,#6366f1,#8b5cf6) !important;
            color: white !important;
            box-shadow: 0 4px 12px rgba(99,102,241,.35) !important;
        }
        .stTabs [data-baseweb="tab-border"]    { display: none; }
        .stTabs [data-baseweb="tab-highlight"] { display: none; }
        div[data-testid="stAlert"] { border-radius: 12px; }
    </style>
    """, unsafe_allow_html=True)

    tab_scrape, tab_dashboard = st.tabs(["🔍  Analyze Website", "📊  Marketing Dashboard"])

    with tab_scrape:
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                url = st.text_input("Website URL", placeholder="https://example.com",
                                    label_visibility="collapsed")
            with col2:
                analyze = st.button("🔍 Analyze Website", type="primary", use_container_width=True)

            if analyze:
                if not url:
                    st.warning("Please enter a valid URL.")
                else:
                    try:
                        st.session_state.app1_error = None
                        products = fetch_products(url)
                        st.session_state.app1_products = products
                        if not products:
                            st.warning("No products were returned from the backend.")
                        else:
                            st.success(
                                f"✅ Analysis complete — **{len(products)} products** loaded. "
                                "Switch to the **📊 Marketing Dashboard** tab to explore results."
                            )
                    except requests.exceptions.RequestException as exc:
                        st.session_state.app1_error = (
                            f"Could not reach the FastAPI backend at `{BACKEND_STREAM_URL}`. Error: {exc}"
                        )
                    except Exception as exc:
                        st.session_state.app1_error = f"Unexpected error: {exc}"

        if st.session_state.app1_error:
            st.error(st.session_state.app1_error)

        if st.session_state.app1_products and not analyze:
            st.info(
                f"📊 **{len(st.session_state.app1_products)} products** already loaded. "
                "Switch to the **Marketing Dashboard** tab to view the full analysis."
            )

    with tab_dashboard:
        payload = build_payload(st.session_state.app1_products)
        components.html(build_html(payload), height=DASH_HEIGHT, scrolling=False)


main()