import joblib
import pandas as pd
import numpy as np

# Load the separate files saved by main_model.py
model = joblib.load("random_forest_model.pkl")
onehot_encoder = joblib.load("onehot_encoder.pkl")
label_encoder = joblib.load("label_encoder.pkl")

def predict_platform(product):
    # 1. Prepare Numeric Data
    numeric_data = [
        product.get("price", 0),
        product.get("rating", 0),
        product.get("review_count", 0),
        product.get("avg_sentiment", 0),
        product.get("discount", 0)
    ]
    
    # 2. Prepare Categorical Data (Must match the training columns)
    cat_features = pd.DataFrame([{
        "category": product.get("category", "Unknown"),
        "brand": product.get("brand", "Unknown")
    }])
    
    # 3. Transform Categorical Data
    cat_encoded = onehot_encoder.transform(cat_features)
    
    # 4. Combine (Numeric + Encoded)
    final_features = np.hstack([[numeric_data], cat_encoded])

    # # 5. Predict
    # prediction_idx = model.predict(final_features)[0]
    # platform = label_encoder.inverse_transform([prediction_idx])[0]

    # # 6. Confidence
    # proba = model.predict_proba(final_features)[0]
    # confidence_score = proba[prediction_idx]

    # return platform, float(confidence_score)
    proba = model.predict_proba(final_features)[0]

    # sort probabilities (highest first)
    sorted_idx = np.argsort(proba)[::-1]

    primary_idx = sorted_idx[0]
    secondary_idx = sorted_idx[1]

    primary_platform = label_encoder.inverse_transform([primary_idx])[0]
    secondary_platform = label_encoder.inverse_transform([secondary_idx])[0]

    primary_conf = float(proba[primary_idx])
    secondary_conf = float(proba[secondary_idx])

    return primary_platform, secondary_platform, primary_conf, secondary_conf