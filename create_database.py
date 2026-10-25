import argparse
import ast
import csv
import json
from pathlib import Path
from pymongo import InsertOne
from DbConnector import DbConnector

BATCH_SIZE = 1_000

def parse_nested(value):
    if value is None or not value.strip():
        return None

    try:
        return json.loads(value.replace("'", '"'))
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return None

def as_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None

def as_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def clean_movie(row):
    movie = dict(row)
    movie_id = movie.pop("id", "").strip()
    if not movie_id:
        return None

    movie["_id"] = movie_id
    for field in ["budget", "revenue", "vote_count"]:
        movie[field] = as_int(movie.get(field))
    for field in ["runtime", "popularity", "vote_average"]:
        movie[field] = as_float(movie.get(field))
    for field in [
        "belongs_to_collection",
        "genres",
        "production_companies",
        "production_countries",
        "spoken_languages",
    ]:
        movie[field] = parse_nested(movie.get(field))

    movie["release_date"] = movie.get("release_date") or None
    movie["original_language"] = movie.get("original_language") or None
    return movie

def clean_credit(row):
    movie_id = row.get("id", "").strip()
    if not movie_id:
        return None
    return {
        "_id": movie_id,
        "movie_id": movie_id,
        "cast": parse_nested(row.get("cast", "")) or [],
        "crew": parse_nested(row.get("crew", "")) or [],
    }

def clean_keywords(row):
    movie_id = row.get("id", "").strip()
    if not movie_id:
        return None
    return {
        "_id": movie_id,
        "movie_id": movie_id,
        "keywords": parse_nested(row.get("keywords", "")) or [],
    }

def clean_rating(row):
    user_id = as_int(row.get("userId"))
    movie_id = as_int(row.get("movieId"))
    timestamp = as_int(row.get("timestamp"))
    rating = as_float(row.get("rating"))
    if None in (user_id, movie_id, timestamp, rating):
        return None
    return {
        "_id": f"{user_id}_{movie_id}_{timestamp}",
        "user_id": user_id,
        "movie_id": movie_id,
        "rating": rating,
        "timestamp": timestamp,
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

def load_collection(database, name, path, cleaner):
    collection = database[name]
    collection.drop()

    inserted = 0
    skipped = 0
    seen_ids = set()
    operations = []

    for document in read_documents(path, cleaner):
        if document["_id"] in seen_ids:
            skipped += 1
            continue
        seen_ids.add(document["_id"])
        operations.append(InsertOne(document))
        if len(operations) == BATCH_SIZE:
            collection.bulk_write(operations, ordered=False)
            inserted += len(operations)
            operations = []

    if operations:
        collection.bulk_write(operations, ordered=False)
        inserted += len(operations)

    print(f"{name}: inserted {inserted:,}; skipped duplicates {skipped:,}")

def create_indexes(database):
    database.movies.create_index([("overview", "text"), ("tagline", "text")])
    database.movies.create_index("release_date")
    database.movies.create_index("original_language")
    database.movies.create_index("vote_count")

    database.credits.create_index("movie_id", unique=True)
    database.credits.create_index("crew.job")

    database.keywords.create_index("movie_id", unique=True)

    database.ratings.create_index("movie_id")
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
        load_collection(
            connector.db, "keywords", paths["keywords"], clean_keywords
        )
        load_collection(connector.db, "ratings", paths["ratings"], clean_rating)
        load_collection(connector.db, "links", paths["links"], clean_link)
        create_indexes(connector.db)
        print("Indexes created.")
    finally:
        connector.close_connection()

if __name__ == "__main__":
    main()
