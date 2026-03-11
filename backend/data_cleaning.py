import pandas as pd

def load_dataset(file_path):
    print("Loading dataset...")
    df = pd.read_csv(file_path)
    print(f"Initial dataset size: {df.shape}")
    return df

def remove_duplicates(df):
    print("Removing duplicate rows...")
    df = df.drop_duplicates()
    print(f"After duplicate removal: {df.shape}")
    return df

def remove_invalid_rows(df):
    print("Removing scraping error rows...")
    # assuming invalid rows have price or rating as NaN or zero
    df = df[df['price'].notna()]
    df = df[df['price'] != 0]
    df = df[df['rating'].notna()]
    print(f"After removing invalid rows: {df.shape}")
    return df

def convert_numeric(df):
    print("Converting numeric columns...")
    for col in ["price", "rating", "review_count", "discount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

def handle_missing_values(df):
    print("Handling missing values...")

    # Remove rows without price
    if "price" in df.columns:
        df = df.dropna(subset=["price"])

    # Fill missing ratings with median, also replace zeros
    if "rating" in df.columns:
        median_rating = df["rating"].median()
        df.loc[:, "rating"] = df["rating"].fillna(median_rating)
        df.loc[:, "rating"] = df["rating"].replace(0, median_rating)

    # Fill missing review_count
    if "review_count" in df.columns:
        df.loc[:, "review_count"] = df["review_count"].fillna(0)

    return df

def standardize_text(df):
    print("Standardizing text columns...")
    text_cols = ["category", "brand"]
    for col in text_cols:
        if col in df.columns:
            df.loc[:, col] = df[col].str.lower().str.strip()
    return df

def save_clean_dataset(df, file_path):
    print("Saving cleaned dataset...")
    df.to_csv(file_path, index=False)
    print(f"Clean dataset saved: {file_path}")
    print(f"Final dataset size: {df.shape}")

if __name__ == "__main__":
    dataset_path = "marketing_dataset.csv"
    clean_path = "marketing_dataset_clean.csv"

    df = load_dataset(dataset_path)
    df = remove_duplicates(df)
    df = remove_invalid_rows(df)
    df = convert_numeric(df)
    df = handle_missing_values(df)
    df = standardize_text(df)
    save_clean_dataset(df, clean_path)