from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
RAW_DATASET = BASE_DIR / "marketing_dataset.csv"
CLEAN_DATASET = BASE_DIR / "marketing_dataset_clean.csv"


def load_dataset(file_path: Path) -> pd.DataFrame:
    print("Loading dataset...")
    df = pd.read_csv(file_path)
    print(f"Initial dataset size: {df.shape}")
    return df


def remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    print("Removing duplicate rows...")
    df = df.drop_duplicates().copy()
    print(f"After duplicate removal: {df.shape}")
    return df


def convert_numeric(df: pd.DataFrame) -> pd.DataFrame:
    print("Converting numeric columns...")
    numeric_cols = ["price", "rating", "review_count", "avg_sentiment", "discount"]
    for col in numeric_cols:
        if col in df.columns:
            df.loc[:, col] = pd.to_numeric(df[col], errors="coerce")
    return df


def handle_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    print("Handling missing values...")

    df = df.copy()

    if "price" in df.columns:
        df = df.dropna(subset=["price"])
        df = df[df["price"] > 0]

    if "rating" in df.columns:
        rating_clean = df["rating"].replace(0, pd.NA)
        rating_median = rating_clean.median()
        df.loc[:, "rating"] = rating_clean.fillna(rating_median)

    if "review_count" in df.columns:
        df.loc[:, "review_count"] = df["review_count"].fillna(0)

    if "avg_sentiment" in df.columns:
        df.loc[:, "avg_sentiment"] = df["avg_sentiment"].fillna(0)

    if "discount" in df.columns:
        df.loc[:, "discount"] = df["discount"].fillna(0)

    for col in ["product_name", "category", "brand", "primary_platform", "secondary_platform"]:
        if col in df.columns:
            df.loc[:, col] = df[col].fillna("Unknown").astype(str).str.strip()

    return df


def standardize_text(df: pd.DataFrame) -> pd.DataFrame:
    print("Standardizing text columns...")
    for col in ["category", "brand"]:
        if col in df.columns:
            df.loc[:, col] = df[col].str.lower().str.strip()
    return df


def save_clean_dataset(df: pd.DataFrame, file_path: Path) -> None:
    print("Saving cleaned dataset...")
    df.to_csv(file_path, index=False)
    print(f"Clean dataset saved: {file_path}")
    print(f"Final dataset size: {df.shape}")


def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:
    df = remove_duplicates(df)
    df = convert_numeric(df)
    df = handle_missing_values(df)
    df = standardize_text(df)

    if "primary_platform" in df.columns:
        df = df[df["primary_platform"].ne("Unknown") & df["primary_platform"].ne("")]

    return df.reset_index(drop=True)


if __name__ == "__main__":
    df = load_dataset(RAW_DATASET)
    df = clean_dataset(df)
    save_clean_dataset(df, CLEAN_DATASET)
