import argparse
import ast
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from pymongo import InsertOne
from DbConnector import DbConnector

BATCH_SIZE = 1_000
csv.field_size_limit(10**9)
parse_failures = 0

def parse_nested(value):
    global parse_failures

    if value is None or not str(value).strip():
        return None

    try:
        parsed = ast.literal_eval(str(value))
    except (ValueError, SyntaxError):
        try:
            parsed = json.loads(str(value))
        except (json.JSONDecodeError, TypeError):
            parse_failures += 1
            return None

    if not isinstance(parsed, (dict, list)):
        parse_failures += 1
        return None
    return parsed

def as_int(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
        return int(number) if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None

def as_float(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None

def as_date(value):
    if value is None or not str(value).strip():
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None

def clean_movie(row):
    movie = dict(row)
    movie_id = as_int(movie.pop("id", None))
    if movie_id is None:
        return None

    movie["_id"] = movie_id
    for field in ["budget", "revenue", "runtime"]:
        value = as_float(movie.get(field))
        movie[field] = value if value else None
    movie["vote_count"] = as_int(movie.get("vote_count"))
    movie["popularity"] = as_float(movie.get("popularity"))
    movie["vote_average"] = as_float(movie.get("vote_average"))

    for field in [
        "belongs_to_collection",
        "genres",
        "production_companies",
        "production_countries",
        "spoken_languages",
    ]:
        movie[field] = parse_nested(movie.get(field))

    movie["release_date"] = as_date(movie.get("release_date"))
    movie["release_year"] = (
        movie["release_date"].year if movie["release_date"] else None
    )
    movie["adult"] = str(movie.get("adult", "")).strip().lower() == "true"
    return movie

def dedupe_people(people):
    unique = {}
    for person in people or []:
        person_id = as_int(person.get("id"))
        if person_id is None:
            continue
        person = dict(person)
        person["id"] = person_id
        current = unique.get(person_id)
        if current is None or person.get("order", 10**9) < current.get("order", 10**9):
            unique[person_id] = person
    return list(unique.values())

def clean_credit(row):
    movie_id = as_int(row.get("id"))
    if movie_id is None:
        return None
    return {
        "_id": movie_id,
        "cast": dedupe_people(parse_nested(row.get("cast"))),
        "crew": dedupe_people(parse_nested(row.get("crew"))),
    }

def clean_keywords(row):
    movie_id = as_int(row.get("id"))
    if movie_id is None:
        return None
    return {
        "_id": movie_id,
        "keywords": parse_nested(row.get("keywords")) or [],
    }

def clean_rating(row, tmdb_ids):
    user_id = as_int(row.get("userId"))
    movie_id = as_int(row.get("movieId"))
    rating = as_float(row.get("rating"))
    timestamp = as_int(row.get("timestamp"))
    if None in (user_id, movie_id, rating, timestamp):
        return None

    return {
        "user_id": user_id,
        "movie_id": movie_id,
        "tmdb_id": tmdb_ids.get(movie_id),
        "rating": rating,
        "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc),
    }

def clean_link(row):
    movie_id = as_int(row.get("movieId"))
    if movie_id is None:
        return None
    return {
        "_id": movie_id,
        "movie_id": movie_id,
        "imdb_id": row.get("imdbId") or None,
        "tmdb_id": as_int(row.get("tmdbId")),
    }

def read_documents(path, cleaner):
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            document = cleaner(row)
            if document is not None:
                yield document

def value_count(value):
    if value is None or value == "":
        return 0
    if isinstance(value, dict):
        return sum(value_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(value_count(item) for item in value)
    return 1

def resolve_duplicates(documents, name):
    grouped = {}
    for document in documents:
        grouped.setdefault(document["_id"], []).append(document)

    resolved = []
    exact_duplicates = 0
    conflicting_records = 0
    selected_records = 0

    for candidates in grouped.values():
        unique_documents = []
        for candidate in candidates:
            if candidate not in unique_documents:
                unique_documents.append(candidate)
        exact_duplicates += len(candidates) - len(unique_documents)

        titles = {candidate.get("title") for candidate in unique_documents if candidate.get("title")}
        release_dates = {
            candidate.get("release_date")
            for candidate in unique_documents
            if candidate.get("release_date")
        }
        if name == "movies" and (len(titles) > 1 or len(release_dates) > 1):
            conflicting_records += len(unique_documents)
            continue

        selected = max(
            unique_documents,
            key=lambda candidate: (
                value_count(candidate),
                candidate.get("vote_count") or 0,
            ),
        )
        resolved.append(selected)
        selected_records += len(unique_documents) - 1

    print(
        f"{name}: duplicate rows removed {exact_duplicates:,}; "
        f"records dropped {conflicting_records:,}; "
        f"records replaced {selected_records:,}"
    )
    return resolved

def load_collection(database, name, path, cleaner, resolve=True):
    collection = database[name]
    collection.drop()
    documents = read_documents(path, cleaner)
    if resolve:
        documents = resolve_duplicates(list(documents), name)

    inserted = 0
    operations = []
    for document in documents:
        operations.append(InsertOne(document))
        if len(operations) == BATCH_SIZE:
            collection.bulk_write(operations, ordered=False)
            inserted += len(operations)
            operations = []

    if operations:
        collection.bulk_write(operations, ordered=False)
        inserted += len(operations)
    print(f"{name}: inserted {inserted:,}")

def load_ratings(database, path, tmdb_ids):
    collection = database.ratings
    collection.drop()
    inserted = 0
    skipped = 0
    operations = []

    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            document = clean_rating(row, tmdb_ids)
            if document is None:
                skipped += 1
                continue
            operations.append(InsertOne(document))
            if len(operations) == BATCH_SIZE:
                collection.bulk_write(operations, ordered=False)
                inserted += len(operations)
                operations = []

    if operations:
        collection.bulk_write(operations, ordered=False)
        inserted += len(operations)
    print(f"ratings: inserted {inserted:,}; skipped rows {skipped:,}")

def create_indexes(database):
    database.movies.create_index([("overview", "text"), ("tagline", "text")])
    database.movies.create_index("release_year")
    database.movies.create_index("original_language")
    database.movies.create_index("vote_count")
    database.credits.create_index("crew.job")
    database.keywords.create_index("keywords.name")
    database.links.create_index("tmdb_id")
    database.ratings.create_index("movie_id")
    database.ratings.create_index("tmdb_id")
    database.ratings.create_index("user_id")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("csv"))
    parser.add_argument("--ratings", default="ratings_small.csv")
    parser.add_argument("--links", default="links_small.csv")
    args = parser.parse_args()

    data_dir = args.data_dir
    paths = {
        "movies": data_dir / "movies_metadata.csv",
        "credits": data_dir / "credits.csv",
        "keywords": data_dir / "keywords.csv",
        "ratings": data_dir / args.ratings,
        "links": data_dir / args.links,
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing dataset files: " + ", ".join(missing))

    connector = DbConnector()
    try:
        load_collection(connector.db, "movies", paths["movies"], clean_movie)
        load_collection(connector.db, "credits", paths["credits"], clean_credit)
        load_collection(connector.db, "keywords", paths["keywords"], clean_keywords)
        load_collection(connector.db, "links", paths["links"], clean_link)

        tmdb_ids = {
            document["movie_id"]: document["tmdb_id"]
            for document in connector.db.links.find(
                {"tmdb_id": {"$ne": None}}, {"movie_id": 1, "tmdb_id": 1}
            )
        }
        load_ratings(connector.db, paths["ratings"], tmdb_ids)
        create_indexes(connector.db)
        print(f"Nested-field parse failures: {parse_failures:,}")
    finally:
        connector.close_connection()

if __name__ == "__main__":
    main()
