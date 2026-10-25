import argparse
import ast
import json
from collections import Counter
from pathlib import Path
import pandas as pd

def read_csv(path):
    return pd.read_csv(path, low_memory=False)

def numeric_ids(series):
    return pd.to_numeric(series, errors="coerce").dropna().astype("int64")

def parse_nested_value(value):
    if pd.isna(value) or not str(value).strip():
        return "empty", None
    text = str(value)
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return "invalid", None
    if not isinstance(parsed, (list, dict)):
        return "invalid", None
    return "ok", parsed

def print_dataset_report(name, data, key_columns):
    print(f"\n{name}:\n")
    print(f"Rows: {len(data):,}")
    print(f"Columns: {len(data.columns)}")
    print(f"Duplicate rows: {data.duplicated().sum():,}")
    duplicate_keys = data.duplicated(subset=key_columns, keep=False)
    duplicate_key_values = data.loc[duplicate_keys, key_columns].drop_duplicates()
    key_name = ", ".join(key_columns)
    print(f"Duplicate key values ({key_name}): {len(duplicate_key_values):,}")
    print(f"Rows with duplicate keys ({key_name}): {duplicate_keys.sum():,}")

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
        print(f"  median: {values.median()}")
        print(f"  maximum: {values.max()}")
        print(f"  mean: {values.mean()}")

def print_nested_field_counts(name, data, columns):
    print(f"\n{name} nested-field counts:")
    for column in columns:
        if column not in data:
            continue
        status_counts = Counter()
        type_counts = Counter()
        for value in data[column]:
            status, parsed = parse_nested_value(value)
            if status != "ok":
                status_counts[status] += 1
                continue
            type_counts[type(parsed).__name__] += 1
            status_counts["ok (empty)" if not parsed else "ok (non-empty)"] += 1
        print(f"\n{column}")
        print(f"  missing/empty values: {status_counts['empty']:,}")
        print(f"  unparseable values: {status_counts['invalid']:,}")
        print(f"  parsed, empty list/dict: {status_counts['ok (empty)']:,}")
        print(f"  parsed, non-empty: {status_counts['ok (non-empty)']:,}")
        print(f"  parsed types: {dict(type_counts)}")

def print_malformed_movie_ids(movies):
    ids = pd.to_numeric(movies["id"], errors="coerce")
    bad = movies.loc[ids.isna(), "id"]
    print("\nMalformed movie ids that is not an integer:")
    print(f"- rows: {len(bad):,}")
    print(f"- values: {bad.head(10).tolist()}")

def print_duplicate_movie_report(movies):
    ids = pd.to_numeric(movies["id"], errors="coerce")
    valid = movies[ids.notna()].copy()
    valid["_id"] = ids[ids.notna()].astype("int64")
    duplicated = valid[valid.duplicated("_id", keep=False)]

    exact_only = same_movie_differing = conflicting = 0
    for _, group in duplicated.groupby("_id"):
        unique = group.drop(columns="_id").drop_duplicates()
        if len(unique) == 1:
            exact_only += 1
        elif unique["title"].nunique() > 1 or unique["release_date"].nunique() > 1:
            conflicting += 1
        else:
            same_movie_differing += 1

    print("\nDuplicate movie ids, by kind:")
    print(f"- ids with only exact duplicate rows: {exact_only:,}")
    print(f"- ids, same movie but differing values: {same_movie_differing:,}")
    print(f"- ids with conflicting title/release date: {conflicting:,}")

def print_movie_value_report(movies):
    print("\nZero values:")
    for column in ["budget", "revenue", "runtime"]:
        values = pd.to_numeric(movies[column], errors="coerce")
        valid = values.notna().sum()
        zeros = (values == 0).sum()
        print(f"- {column}: {zeros:,} of {valid:,} valid values are 0 ({zeros / valid:.1%})")

    vote_count = pd.to_numeric(movies["vote_count"], errors="coerce")
    vote_average = pd.to_numeric(movies["vote_average"], errors="coerce")
    no_votes = vote_count == 0
    print("\nMovies without votes:")
    print(f"- vote_count == 0: {no_votes.sum():,}")
    print(f"- of those, vote_average == 0: {(vote_average[no_votes] == 0).sum():,}")

def print_date_values(data):
    if "release_date" not in data:
        return
    text = data["release_date"].dropna().astype(str)
    well_formed = text.str.fullmatch(r"\d{4}-\d{2}-\d{2}")
    dates = pd.to_datetime(data["release_date"], errors="coerce")
    print("\nRelease dates:")
    print(f"- missing: {data['release_date'].isna().sum():,}")
    print(f"- YYYY-MM-DD format: {well_formed.sum():,}")
    print(f"- present but not YYYY-MM-DD: {(~well_formed).sum():,}")
    print(f"- valid dates: {dates.notna().sum():,}")
    print(f"- earliest: {dates.min()}  latest: {dates.max()}")

def print_credit_people_report(credits):
    genders = Counter()
    cast_total = 0
    cast_with_duplicate_people = 0
    top5_order_problems = 0
    crew_people_with_several_jobs = 0
    crew_exact_duplicates = 0
    without_director = 0
    several_directors = 0

    for cast_value, crew_value in zip(credits["cast"], credits["crew"]):
        cast_status, cast = parse_nested_value(cast_value)
        crew_status, crew = parse_nested_value(crew_value)
        cast = [p for p in cast if isinstance(p, dict)] if cast_status == "ok" and isinstance(cast, list) else []
        crew = [p for p in crew if isinstance(p, dict)] if crew_status == "ok" and isinstance(crew, list) else []

        cast_total += len(cast)
        genders.update(person.get("gender") for person in cast)
        cast_ids = [person.get("id") for person in cast]
        if len(cast_ids) != len(set(cast_ids)):
            cast_with_duplicate_people += 1
        orders = {person.get("order") for person in cast}
        if set(range(min(5, len(cast)))) - orders:
            top5_order_problems += 1

        jobs_by_person = {}
        for person in crew:
            jobs_by_person.setdefault(person.get("id"), []).append(person.get("job"))
        if any(len(set(jobs)) > 1 for jobs in jobs_by_person.values()):
            crew_people_with_several_jobs += 1
        if any(len(jobs) != len(set(jobs)) for jobs in jobs_by_person.values()):
            crew_exact_duplicates += 1
        directors = sum(person.get("job") == "Director" for person in crew)
        without_director += directors == 0
        several_directors += directors > 1

    print("\nCast and crew details:")
    print(f"- cast entries in total: {cast_total:,}")
    for code, label in [(1, "female"), (2, "male"), (0, "unknown")]:
        print(f"  gender {code} ({label}): {genders[code]:,} ({genders[code] / max(cast_total, 1):.1%})")
    print(f"- movies where the same person appears twice in cast: {cast_with_duplicate_people:,}")
    print(f"- movies whose top-5 cast do not have orders 0-4: {top5_order_problems:,}")
    print(f"- movies where a person has several different crew jobs: {crew_people_with_several_jobs:,}")
    print(f"- movies where a person has the same crew job twice: {crew_exact_duplicates:,}")
    print(f"- movies without a Director: {without_director:,}")
    print(f"- movies with more than one Director: {several_directors:,}")

def print_cross_file_report(movies, credits, keywords, links, ratings):
    movie_ids = set(numeric_ids(movies["id"]))
    credit_ids = set(numeric_ids(credits["id"]))
    keyword_ids = set(numeric_ids(keywords["id"]))

    print("\nCross-file consistency:")
    print(f"- movies without credits: {len(movie_ids - credit_ids):,}")
    print(f"- credits without a movie: {len(credit_ids - movie_ids):,}")
    print(f"- movies without keywords: {len(movie_ids - keyword_ids):,}")
    print(f"- keywords without a movie: {len(keyword_ids - movie_ids):,}")

    tmdb = links["tmdbId"].dropna().astype("int64")
    print(f"- links without a tmdbId: {links['tmdbId'].isna().sum():,}")
    print(f"- links whose tmdbId is not in movies: {(~tmdb.isin(movie_ids)).sum():,}")
    print(f"- tmdbIds used by more than one link: {tmdb.duplicated(keep=False).sum():,}")

    mapping = links.drop_duplicates("movieId").set_index("movieId")["tmdbId"]
    mapped = ratings["movieId"].map(mapping)
    print(f"- ratings whose movieId is not in links: {(~ratings['movieId'].isin(mapping.index)).sum():,}")
    print(f"- ratings without a usable tmdbId: {mapped.isna().sum():,}")
    print(f"- ratings whose tmdbId is not in movies: {(~mapped.dropna().astype('int64').isin(movie_ids)).sum():,}")

def print_rating_report(ratings):
    print("\nRatings:")
    for column in ["userId", "movieId", "rating", "timestamp"]:
        if column in ratings:
            print(f"- {column} unique values: {ratings[column].nunique():,}")
    print_numeric_values("Ratings", ratings, ["rating"])
    print(f"- rating values: {sorted(ratings['rating'].unique().tolist())}")
    timestamps = pd.to_datetime(ratings["timestamp"], unit="s", errors="coerce")
    print(f"- valid timestamps: {timestamps.notna().sum():,}")
    print(f"- invalid timestamps: {timestamps.isna().sum():,}")
    print(f"- earliest: {timestamps.min()}  latest: {timestamps.max()}")
    per_user = ratings.groupby("userId").size()
    print(f"- users with >= 20 ratings: {(per_user >= 20).sum():,} of {len(per_user):,}")

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

    print_dataset_report("movies_metadata.csv", movies, ["id"])
    print_malformed_movie_ids(movies)
    print_duplicate_movie_report(movies)
    print_numeric_values(
        "Movies",
        movies,
        ["budget", "revenue", "runtime", "vote_average", "vote_count", "popularity"],
    )
    print_movie_value_report(movies)
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

    print_dataset_report(args.ratings, ratings, ["userId", "movieId"])
    print_rating_report(ratings)

    print_dataset_report(args.links, links, ["movieId"])
    print_dataset_report("credits.csv", credits, ["id"])
    print_nested_field_counts("Credits", credits, ["cast", "crew"])
    print_credit_people_report(credits)

    print_dataset_report("keywords.csv", keywords, ["id"])
    print_nested_field_counts("Keywords", keywords, ["keywords"])

    print_cross_file_report(movies, credits, keywords, links, ratings)

if __name__ == "__main__":
    main()
