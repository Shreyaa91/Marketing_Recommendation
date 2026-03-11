import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import OneHotEncoder, LabelEncoder
from sklearn.metrics import accuracy_score, classification_report
import joblib

def preprocess_data(df):
    # Target column
    y = df['primary_platform']

    # Features: drop product_name and platform columns
    X = df.drop(columns=['product_name', 'primary_platform', 'secondary_platform'])

    # Identify categorical columns
    cat_cols = ['category', 'brand']

    # One-hot encode categorical columns (updated for sklearn >=1.2)
    encoder = OneHotEncoder(sparse_output=False, handle_unknown='ignore')
    X_encoded = encoder.fit_transform(X[cat_cols])

    # Drop original categorical columns and combine numeric + encoded features
    X_numeric = X.drop(columns=cat_cols)
    X_final = np.hstack([X_numeric.values, X_encoded])

    # Encode target
    le = LabelEncoder()
    y_encoded = le.fit_transform(y)

    return X_final, y_encoded, encoder, le


def train_random_forest(X, y):
    # Split into train/test
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Train Random Forest
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    print("Accuracy:", accuracy_score(y_test, y_pred))
    print("Classification Report:\n", classification_report(y_test, y_pred))

    return model

def main():
    print("Loading dataset...")
    df = pd.read_csv("marketing_dataset_clean.csv")
    print("Dataset loaded:", df.shape)

    X, y, encoder, le = preprocess_data(df)
    model = train_random_forest(X, y)

    # Save model and encoders
    joblib.dump(model, "random_forest_model.pkl")
    joblib.dump(encoder, "onehot_encoder.pkl")
    joblib.dump(le, "label_encoder.pkl")
    print("Model and encoders saved!")

if __name__ == "__main__":
    main()