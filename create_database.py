import argparse
import ast
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from pymongo import InsertOne
from DbConnector import DbConnector

BATCH_SIZE = 1_000
RATINGS_BATCH_SIZE = 10_000
DROPPED_MOVIE_FIELDS = ["homepage", "poster_path", "video"]

csv.field_size_limit(10**9)
parse_failures = 0

def parse_nested(value):
    global parse_failures

    if value is None or not str(value).strip():
        return None

    try:
        parsed = ast.literal_eval(str(value))
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        try:
            parsed = json.loads(str(value))
        except (json.JSONDecodeError, TypeError):
            parse_failures += 1
            return None

    if not isinstance(parsed, (dict, list)):
        parse_failures += 1
        return None
    return parsed

def parse_list(value):
    parsed = parse_nested(value)
    return parsed if isinstance(parsed, list) else []

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
    movie = {
        key: (None if value == "" else value)
        for key, value in row.items()
        if key is not None
    }
    movie_id = as_int(movie.pop("id", None))
    if movie_id is None:
        return None
    for field in DROPPED_MOVIE_FIELDS:
        movie.pop(field, None)

    movie["_id"] = movie_id
    movie["budget"] = as_int(movie.get("budget")) or None
    movie["revenue"] = as_int(movie.get("revenue")) or None
    movie["runtime"] = as_float(movie.get("runtime")) or None
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
    movie["adult"] = str(movie.get("adult") or "").strip().lower() == "true"
    return movie

def person_order(person):
    order = as_int(person.get("order"))
    return order if order is not None else 10**9

def dedupe_people(people, by_job=False):
    unique = {}
    for person in people if isinstance(people, list) else []:
        if not isinstance(person, dict):
            continue
        person_id = as_int(person.get("id"))
        if person_id is None:
            continue
        key = (person_id, person.get("job")) if by_job else person_id
        current = unique.get(key)
        if current is None or person_order(person) < person_order(current):
            unique[key] = {**person, "id": person_id}
    return list(unique.values())


def clean_credit(row):
    movie_id = as_int(row.get("id"))
    if movie_id is None:
        return None
    return {
        "_id": movie_id,
        "cast": dedupe_people(parse_list(row.get("cast"))),
        "crew": dedupe_people(parse_list(row.get("crew")), by_job=True),
    }

def clean_keywords(row):
    movie_id = as_int(row.get("id"))
    if movie_id is None:
        return None
    return {"_id": movie_id, "keywords": parse_list(row.get("keywords"))}

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
    imdb = (row.get("imdbId") or "").strip()
    return {
        "_id": movie_id,
        "movie_id": movie_id,
        "imdb_id": f"tt{imdb}" if imdb else None,
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
        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue

        unique_documents = []
        for candidate in candidates:
            if candidate not in unique_documents:
                unique_documents.append(candidate)
        exact_duplicates += len(candidates) - len(unique_documents)

        titles = {c.get("title") for c in unique_documents if c.get("title")}
        release_dates = {
            c.get("release_date") for c in unique_documents if c.get("release_date")
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

def insert_in_batches(collection, documents, batch_size=BATCH_SIZE):
    inserted = 0
    operations = []
    for document in documents:
        operations.append(InsertOne(document))
        if len(operations) == batch_size:
            collection.bulk_write(operations, ordered=False)
            inserted += len(operations)
            operations = []
    if operations:
        collection.bulk_write(operations, ordered=False)
        inserted += len(operations)
    return inserted

def load_collection(database, name, path, cleaner):
    collection = database[name]
    collection.drop()
    documents = resolve_duplicates(list(read_documents(path, cleaner)), name)
    print(f"{name}: inserted {insert_in_batches(collection, documents):,}")

def load_ratings(database, path, tmdb_ids):
    collection = database.ratings
    collection.drop()
    counts = {"skipped": 0, "no_tmdb_id": 0}

    def documents():
        with path.open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                document = clean_rating(row, tmdb_ids)
                if document is None:
                    counts["skipped"] += 1
                    continue
                if document["tmdb_id"] is None:
                    counts["no_tmdb_id"] += 1
                yield document

    inserted = insert_in_batches(collection, documents(), RATINGS_BATCH_SIZE)
    print(
        f"ratings: inserted {inserted:,}; skipped rows {counts['skipped']:,}; "
        f"ratings without a TMDB id {counts['no_tmdb_id']:,}"
    )

def report_orphans(database):
    movie_ids = {doc["_id"] for doc in database.movies.find({}, {"_id": 1})}
    for name in ("credits", "keywords"):
        orphans = sum(
            1 for doc in database[name].find({}, {"_id": 1}) if doc["_id"] not in movie_ids
        )
        print(f"{name}: documents without a matching movie: {orphans:,}")
    print(
        "links: rows without a TMDB id: "
        f"{database.links.count_documents({'tmdb_id': None}):,}"
    )

def create_indexes(database):
    database.movies.create_index([("overview", "text"), ("tagline", "text")])
    database.movies.create_index("release_year")
    database.movies.create_index("original_language")
    database.movies.create_index("vote_count")
    database.links.create_index("tmdb_id")
    database.ratings.create_index("user_id")

def main():
    parser = argparse.ArgumentParser(description="Load the Movies dataset into MongoDB.")
    parser.add_argument("--data-dir", type=Path, default=Path("csv"))
    parser.add_argument("--ratings", default="ratings_small.csv")
    parser.add_argument("--links", default="links_small.csv")
    args = parser.parse_args()

    if ("small" in args.ratings) != ("small" in args.links):
        print(
            "WARNING: ratings and links files do not match (small vs full); "
            "many ratings will end up without a TMDB id."
        )

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
        report_orphans(connector.db)
        print(f"Nested-field parse failures: {parse_failures:,}")
    finally:
        connector.close_connection()

if __name__ == "__main__":
    main()
