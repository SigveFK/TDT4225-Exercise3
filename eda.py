import argparse
import ast
import json
from pathlib import Path
import pandas as pd

def read_csv(path):
    return pd.read_csv(path, low_memory=False)

def parse_nested_value(value):
    if pd.isna(value) or not str(value).strip():
        return []
    try:
        parsed = json.loads(value.replace("'", '"'))
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, SyntaxError):
            return []

def print_dataset_report(name, data):
    print(f"\n{name}:\n")
    print(f"Rows: {len(data):,}")
    print(f"Columns: {len(data.columns)}")
    print(f"Duplicate rows: {data.duplicated().sum():,}")

    print("\nColumns and data types:")
    for column in data.columns:
        print(f"- {column}: {data[column].dtype}")

    print("\nMissing values:")
    for column in data.columns:
        missing = data[column].isna().sum()
        empty = data[column].eq("").sum() if data[column].dtype == "object" else 0
        print(f"- {column}: missing={missing:,}, empty={empty:,}")

def print_numeric_values(name, data, columns):
    print(f"\n{name} column numbers:")
    for column in columns:
        if column not in data:
            continue
        values = pd.to_numeric(data[column], errors="coerce")
        print(f"\n{column}")
        print(f"  valid values: {values.notna().sum():,}")
        print(f"  invalid values: {values.isna().sum():,}")
        print(f"  zero values: {(values == 0).sum():,}")
        print(f"  minimum: {values.min()}")
        print(f"  maximum: {values.max()}")
        print(f"  mean: {values.mean()}")
        print(f"  median: {values.median()}")

def print_nested_field_counts(name, data, columns):
    print(f"\n{name} nested-field counts:")
    for column in columns:
        if column not in data:
            continue
        print(f"\n{column}")
        invalid = 0
        empty = 0
        for value in data[column]:
            if pd.isna(value) or not str(value).strip():
                empty += 1
                continue
            parsed = parse_nested_value(value)
            if not parsed:
                invalid += 1
                continue
        print(f"  empty values: {empty:,}")
        print(f"  invalid or non-list values: {invalid:,}")

def print_date_values(data):
    if "release_date" not in data:
        return
    dates = pd.to_datetime(data["release_date"], errors="coerce")
    print("\nRelease dates:")
    print(f"- valid dates: {dates.notna().sum():,}")
    print(f"- invalid or missing dates: {dates.isna().sum():,}")
    print(f"- first source date: {data['release_date'].dropna().head(1).tolist()}")
    print(f"- last source date: {data['release_date'].dropna().tail(1).tolist()}")

def print_rating_report(ratings):
    print("\nRatings:")
    for column in ["userId", "movieId", "rating", "timestamp"]:
        if column not in ratings:
            continue
        print(f"- {column} unique values: {ratings[column].nunique():,}")
    if "rating" in ratings:
        print_numeric_values("Ratings", ratings, ["rating"])
    if "timestamp" in ratings:
        timestamps = pd.to_datetime(ratings["timestamp"], unit="s", errors="coerce")
        print(f"- valid timestamps: {timestamps.notna().sum():,}")
        print(f"- invalid timestamps: {timestamps.isna().sum():,}")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("csv"))
    parser.add_argument("--ratings", default="ratings_small.csv")
    parser.add_argument("--links", default="links_small.csv")
    args = parser.parse_args()

    data_dir = args.data_dir
    paths = {
        "movies_metadata.csv": data_dir / "movies_metadata.csv",
        args.ratings: data_dir / args.ratings,
        args.links: data_dir / args.links,
        "credits.csv": data_dir / "credits.csv",
        "keywords.csv": data_dir / "keywords.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing dataset files: " + ", ".join(missing))

    movies = read_csv(paths["movies_metadata.csv"])
    ratings = read_csv(paths[args.ratings])
    links = read_csv(paths[args.links])
    credits = read_csv(paths["credits.csv"])
    keywords = read_csv(paths["keywords.csv"])

    print_dataset_report("movies_metadata.csv", movies)
    print_numeric_values(
        "Movies",
        movies,
        ["budget", "revenue", "runtime", "vote_average", "vote_count"],
    )
    print_date_values(movies)
    print_nested_field_counts(
        "Movies",
        movies,
        [
            "genres",
            "belongs_to_collection",
            "production_companies",
            "production_countries",
            "spoken_languages",
        ],
    )

    print_dataset_report(args.ratings, ratings)
    print_rating_report(ratings)

    print_dataset_report(args.links, links)
    print_dataset_report("credits.csv", credits)
    print_nested_field_counts("Credits", credits, ["cast", "crew"])

    print_dataset_report("keywords.csv", keywords)
    print_nested_field_counts("Keywords", keywords, ["keywords"])

if __name__ == "__main__":
    main()
