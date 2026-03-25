from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "marketing_dataset_balanced_800.csv"
MODEL_PATH = BASE_DIR / "random_forest_pipeline.pkl"

NUMERIC_COLS = ["price", "rating", "review_count", "avg_sentiment", "discount"]
CAT_COLS = ["category"]
TARGET_COL = "primary_platform"
FEATURE_COLS = NUMERIC_COLS + CAT_COLS
TEST_SIZE = 0.25


def load_dataset() -> pd.DataFrame:
    print("Loading cleaned dataset...")
    df = pd.read_csv(DATASET_PATH)
    print(f"Dataset loaded: {df.shape}")

    required = {"secondary_platform", TARGET_COL, *FEATURE_COLS}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = df.copy()
    for col in NUMERIC_COLS:
        df.loc[:, col] = pd.to_numeric(df[col], errors="coerce")
    for col in CAT_COLS:
        df.loc[:, col] = df[col].fillna("unknown").astype(str).str.lower().str.strip()
    df.loc[:, TARGET_COL] = df[TARGET_COL].fillna("").astype(str).str.strip()
    df = df[df[TARGET_COL].ne("")].reset_index(drop=True)
    return df


def build_pipeline() -> Pipeline:
    numeric_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
        ]
    )

    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, NUMERIC_COLS),
            ("cat", categorical_transformer, CAT_COLS),
        ]
    )

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_split=6,
        min_samples_leaf=2,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=1,
    )

    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", model),
        ]
    )


def top_2_accuracy(model, X_test, y_test):
    probs = model.predict_proba(X_test)
    correct = 0

    for i in range(len(y_test)):
        top2 = np.argsort(probs[i])[-2:]
        if y_test.iloc[i] in model.named_steps["model"].classes_[top2]:
            correct += 1

    return correct / len(y_test)


def evaluate_model(model, X_train, X_test, y_train, y_test):
    print("\nMODEL EVALUATION")

    y_pred = model.predict(X_test)

    accuracy = accuracy_score(y_test, y_pred)
    balanced_acc = balanced_accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, average="weighted", zero_division=0)
    recall = recall_score(y_test, y_pred, average="weighted", zero_division=0)
    f1 = f1_score(y_test, y_pred, average="weighted", zero_division=0)

    print(f"\nAccuracy: {accuracy:.4f}")
    print(f"Balanced Accuracy: {balanced_acc:.4f}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall: {recall:.4f}")
    print(f"F1 Score: {f1:.4f}")

    train_acc = model.score(X_train, y_train)
    test_acc = model.score(X_test, y_test)

    print("\nOverfitting Check:")
    print(f"Training Accuracy: {train_acc:.4f}")
    print(f"Testing Accuracy:  {test_acc:.4f}")

    # top2_acc = top_2_accuracy(model, X_test, y_test)
    # print(f"\nTop-2 Accuracy: {top2_acc:.4f}")

    print("\nClassification Report:\n")
    print(classification_report(y_test, y_pred, zero_division=0))

    print("\nConfusion Matrix:\n")
    cm = confusion_matrix(y_test, y_pred, labels=model.named_steps["model"].classes_)
    cm_df = pd.DataFrame(cm, index=model.named_steps["model"].classes_, columns=model.named_steps["model"].classes_)
    print(cm_df)

    print("\nCross Validation (5-Fold, balanced accuracy):")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="balanced_accuracy")
    print("Scores:", cv_scores)
    print("Average CV Balanced Accuracy:", round(cv_scores.mean(), 4))


def train_random_forest(df: pd.DataFrame):
    X = df[FEATURE_COLS].copy()
    y = df[TARGET_COL].copy()

    X_train_raw, X_test, y_train_raw, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=42,
        stratify=y,
    )

    print("\nTraining Random Forest...")
    start_time = time.time()

    model = build_pipeline()
    model.fit(X_train_raw, y_train_raw)

    training_time = time.time() - start_time
    print(f"Training Time: {training_time:.4f} seconds")

    evaluate_model(model, X_train_raw, X_test, y_train_raw, y_test)
    return model


def main():
    df = load_dataset()
    model = train_random_forest(df)

    joblib.dump(model, MODEL_PATH)
    print(f"\nModel saved successfully: {MODEL_PATH}")


if __name__ == "__main__":
    main()
