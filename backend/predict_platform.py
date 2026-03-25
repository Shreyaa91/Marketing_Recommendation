from pathlib import Path

import joblib
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "random_forest_pipeline.pkl"

pipeline = joblib.load(MODEL_PATH)


def _normalize_product(product: dict) -> pd.DataFrame:
    row = {
        "price": product.get("price", 0),
        "rating": product.get("rating", 0),
        "review_count": product.get("review_count", 0),
        "avg_sentiment": product.get("avg_sentiment", 0),
        "discount": product.get("discount", 0),
        "category": str(product.get("category", "unknown")).lower().strip(),
    }
    return pd.DataFrame([row])


def predict_platform(product):
    sample = _normalize_product(product)

    proba = pipeline.predict_proba(sample)[0]
    classes = pipeline.named_steps["model"].classes_

    sorted_idx = np.argsort(proba)[::-1]
    primary_idx = sorted_idx[0]
    secondary_idx = sorted_idx[1] if len(sorted_idx) > 1 else sorted_idx[0]

    primary_platform = classes[primary_idx]
    secondary_platform = classes[secondary_idx]
    primary_conf = float(proba[primary_idx])
    secondary_conf = float(proba[secondary_idx])

    return primary_platform, secondary_platform, primary_conf, secondary_conf
