import argparse
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pprint import pprint
from DbConnector import DbConnector

# For Q8: actor-directors would otherwise be paired with themselves.
EXCLUDE_SELF_PAIRS = True

def median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None

def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None

def aggregate(collection, pipeline):
    return collection.aggregate(pipeline, allowDiskUse=True)

def date_text(value):
    return value.strftime("%Y-%m-%d") if value else None

def movie_lookup(fields, extra_match=None):
    pipeline = []
    if extra_match:
        pipeline.append({"$match": extra_match})
    pipeline.append({"$project": {field: 1 for field in fields}})
    return {
        "$lookup": {
            "from": "movies",
            "localField": "_id",
            "foreignField": "_id",
            "pipeline": pipeline,
            "as": "movie",
        }
    }

def query_directors(credits):
    pipeline = [
        {"$unwind": "$crew"},
        {"$match": {"crew.job": "Director", "crew.id": {"$ne": None}}},
        movie_lookup(["revenue", "vote_average", "vote_count"]),
        {"$unwind": "$movie"},
        {
            "$group": {
                "_id": "$crew.id",
                "director": {"$first": "$crew.name"},
                "movie_ids": {"$addToSet": "$_id"},
                "revenues": {"$push": "$movie.revenue"},
                "vote_averages": {
                    "$push": {
                        "$cond": [
                            {"$gt": ["$movie.vote_count", 0]},
                            "$movie.vote_average",
                            None,
                        ]
                    }
                },
            }
        },
    ]

    results = []
    for row in aggregate(credits, pipeline):
        revenues = [value for value in row["revenues"] if value is not None]
        if len(revenues) < 5:
            continue
        results.append(
            {
                "director": row["director"],
                "movie_count": len(row["movie_ids"]),
                "movies_with_revenue": len(revenues),
                "median_revenue": median(revenues),
                "mean_vote_average": mean(row["vote_averages"]),
            }
        )
    return sorted(
        results,
        key=lambda row: (row["median_revenue"], row["movie_count"], row["director"]),
        reverse=True,
    )[:10]

def query_actor_pairs(movies, credits):
    vote = {
        movie["_id"]: (
            movie.get("vote_average") if (movie.get("vote_count") or 0) > 0 else None
        )
        for movie in movies.find({}, {"vote_average": 1, "vote_count": 1})
    }

    credit_counts = Counter()
    for document in credits.find({}, {"cast.id": 1}):
        credit_counts.update(person["id"] for person in document["cast"])
    eligible = {actor for actor, count in credit_counts.items() if count >= 3}

    stats = defaultdict(lambda: [0, 0.0, 0])  # appearances, vote sum, vote count
    names = {}
    for document in credits.find({}, {"cast.id": 1, "cast.name": 1}):
        if document["_id"] not in vote:
            continue
        cast = sorted(
            (person["id"], person.get("name"))
            for person in document["cast"]
            if person["id"] in eligible
        )
        movie_vote = vote[document["_id"]]
        for (actor_a, name_a), (actor_b, name_b) in combinations(cast, 2):
            names[actor_a], names[actor_b] = name_a, name_b
            entry = stats[(actor_a, actor_b)]
            entry[0] += 1
            if movie_vote is not None:
                entry[1] += movie_vote
                entry[2] += 1

    results = [
        {
            "actor": names[actor_a],
            "co_actor": names[actor_b],
            "co_appearances": appearances,
            "mean_vote_average": vote_sum / vote_count if vote_count else None,
        }
        for (actor_a, actor_b), (appearances, vote_sum, vote_count) in stats.items()
        if appearances >= 3
    ]
    return sorted(
        results,
        key=lambda row: (
            row["co_appearances"],
            row["mean_vote_average"] or 0,
            row["actor"] or "",
            row["co_actor"] or "",
        ),
        reverse=True,
    )

def query_actor_genres(credits):
    pipeline = [
        movie_lookup(["genres.name"]),
        {"$unwind": "$movie"},
        {"$unwind": "$cast"},
        {"$match": {"cast.id": {"$ne": None}}},
        {
            "$group": {
                "_id": "$cast.id",
                "actor": {"$first": "$cast.name"},
                "movies": {"$addToSet": "$_id"},
                "genre_names": {"$push": {"$ifNull": ["$movie.genres.name", []]}},
            }
        },
        {"$match": {"$expr": {"$gte": [{"$size": "$movies"}, 10]}}},
    ]

    results = []
    for row in aggregate(credits, pipeline):
        genres = {
            name for names in row["genre_names"] for name in names if name
        }
        results.append(
            {
                "actor": row["actor"],
                "movie_count": len(row["movies"]),
                "genre_count": len(genres),
                "example_genres": sorted(genres)[:5],
            }
        )
    return sorted(
        results,
        key=lambda row: (row["genre_count"], row["movie_count"], row["actor"] or ""),
        reverse=True,
    )[:10]

def query_collections(movies):
    pipeline = [
        {"$match": {"belongs_to_collection.name": {"$ne": None}}},
        {
            "$group": {
                "_id": "$belongs_to_collection.id",
                "collection": {"$first": "$belongs_to_collection.name"},
                "movie_count": {"$sum": 1},
                "revenues": {"$push": "$revenue"},
                "vote_averages": {
                    "$push": {
                        "$cond": [{"$gt": ["$vote_count", 0]}, "$vote_average", None]
                    }
                },
                "release_dates": {"$push": "$release_date"},
            }
        },
        {"$match": {"movie_count": {"$gte": 3}}},
    ]

    results = []
    for row in aggregate(movies, pipeline):
        dates = [date for date in row["release_dates"] if date]
        results.append(
            {
                "collection": row["collection"],
                "movie_count": row["movie_count"],
                "total_revenue": sum(value or 0 for value in row["revenues"]),
                "median_vote_average": median(row["vote_averages"]),
                "earliest_release": date_text(min(dates)) if dates else None,
                "latest_release": date_text(max(dates)) if dates else None,
            }
        )
    return sorted(results, key=lambda row: row["total_revenue"], reverse=True)[:10]

def query_decade_genres(movies):
    pipeline = [
        {"$match": {"release_year": {"$ne": None}}},
        {
            "$set": {
                "primary_genre": {"$arrayElemAt": [{"$ifNull": ["$genres", []]}, 0]}
            }
        },
        {"$match": {"primary_genre.name": {"$ne": None}, "runtime": {"$ne": None}}},
        {
            "$group": {
                "_id": {
                    "decade": {
                        "$subtract": [
                            "$release_year",
                            {"$mod": ["$release_year", 10]},
                        ]
                    },
                    "genre": "$primary_genre.name",
                },
                "runtimes": {"$push": "$runtime"},
                "movie_count": {"$sum": 1},
            }
        },
    ]

    results = [
        {
            "decade_start": int(row["_id"]["decade"]),
            "primary_genre": row["_id"]["genre"],
            "median_runtime": median(row["runtimes"]),
            "movie_count": row["movie_count"],
        }
        for row in aggregate(movies, pipeline)
    ]
    results.sort(key=lambda row: (row["decade_start"], -row["median_runtime"]))
    return [
        {
            "decade": f"{row['decade_start']}s",
            "primary_genre": row["primary_genre"],
            "median_runtime": row["median_runtime"],
            "movie_count": row["movie_count"],
        }
        for row in results
    ]

def query_female_cast(credits):
    pipeline = [
        {
            "$project": {
                "cast": {
                    "$slice": [
                        {"$sortArray": {"input": "$cast", "sortBy": {"order": 1}}},
                        5,
                    ]
                }
            }
        },
        movie_lookup(["release_year"]),
        {"$unwind": "$movie"},
        {"$match": {"movie.release_year": {"$ne": None}}},
        {"$project": {"year": "$movie.release_year", "genders": "$cast.gender"}},
    ]

    by_decade = {}
    for row in aggregate(credits, pipeline):
        known = [gender for gender in row["genders"] if gender in (1, 2)]
        if not known:
            continue
        decade = row["year"] // 10 * 10
        by_decade.setdefault(decade, []).append(known.count(1) / len(known))

    return sorted(
        [
            {
                "decade": f"{decade}s",
                "average_female_proportion": sum(values) / len(values),
                "movie_count": len(values),
            }
            for decade, values in by_decade.items()
        ],
        key=lambda row: row["average_female_proportion"],
        reverse=True,
    )

def query_noir(movies):
    pipeline = [
        {"$match": {"$text": {"$search": "noir"}, "vote_count": {"$gte": 50}}},
        {
            "$project": {
                "_id": 0,
                "title": 1,
                "year": "$release_year",
                "vote_average": 1,
                "vote_count": 1,
                "score": {"$meta": "textScore"},
            }
        },
        {"$sort": {"vote_average": -1, "vote_count": -1, "score": -1}},
        {"$limit": 20},
    ]
    return list(movies.aggregate(pipeline))

def query_director_actor(credits):
    pipeline = [
        movie_lookup(
            ["vote_average", "revenue"],
            extra_match={"vote_count": {"$gte": 100}, "vote_average": {"$ne": None}},
        ),
        {"$unwind": "$movie"},
        {"$unwind": "$crew"},
        {"$match": {"crew.job": "Director", "crew.id": {"$ne": None}}},
        {"$unwind": "$cast"},
        {"$match": {"cast.id": {"$ne": None}}},
    ]
    if EXCLUDE_SELF_PAIRS:
        pipeline.append({"$match": {"$expr": {"$ne": ["$crew.id", "$cast.id"]}}})
    pipeline.extend(
        [
            {
                "$group": {
                    "_id": {"director_id": "$crew.id", "actor_id": "$cast.id"},
                    "director": {"$first": "$crew.name"},
                    "actor": {"$first": "$cast.name"},
                    "films": {"$sum": 1},
                    "vote_averages": {"$push": "$movie.vote_average"},
                    "revenues": {"$push": "$movie.revenue"},
                }
            },
            {"$match": {"films": {"$gte": 3}}},
        ]
    )

    results = []
    for row in aggregate(credits, pipeline):
        revenues = [value for value in row["revenues"] if value is not None]
        results.append(
            {
                "director": row["director"],
                "actor": row["actor"],
                "films_count": row["films"],
                "mean_vote_average": mean(row["vote_averages"]),
                "mean_revenue": mean(revenues),
                "films_with_revenue": len(revenues),
            }
        )
    return sorted(
        results,
        key=lambda row: (
            row["mean_vote_average"],
            row["films_count"],
            row["director"] or "",
        ),
        reverse=True,
    )[:20]


def query_non_english(movies):
    pipeline = [
        {
            "$match": {
                "original_language": {"$nin": [None, "", "en"]},
                "production_countries.iso_3166_1": "US",
            }
        },
        {
            "$group": {
                "_id": "$original_language",
                "count": {"$sum": 1},
                "example_title": {"$min": "$title"},
            }
        },
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": 10},
    ]
    return [
        {
            "original_language": row["_id"],
            "count": row["count"],
            "example_title": row["example_title"],
        }
        for row in aggregate(movies, pipeline)
    ]

def query_users(movies, ratings):
    genre_by_movie = {
        movie["_id"]: {
            genre.get("name")
            for genre in movie.get("genres") or []
            if genre.get("name")
        }
        for movie in movies.find({}, {"_id": 1, "genres": 1})
    }
    pipeline = [
        {
            "$group": {
                "_id": "$user_id",
                "ratings_count": {"$sum": 1},
                "rating_sum": {"$sum": "$rating"},
                "rating_squared_sum": {"$sum": {"$multiply": ["$rating", "$rating"]}},
                "movie_ids": {"$addToSet": "$tmdb_id"},
            }
        },
        {"$match": {"ratings_count": {"$gte": 20}}},
    ]

    results = []
    for row in aggregate(ratings, pipeline):
        ratings_count = row["ratings_count"]
        rating_mean = row["rating_sum"] / ratings_count
        variance = row["rating_squared_sum"] / ratings_count - rating_mean**2
        genres = {
            genre
            for movie_id in row["movie_ids"]
            for genre in genre_by_movie.get(movie_id, set())
        }
        results.append(
            {
                "user_id": row["_id"],
                "ratings_count": ratings_count,
                "population_variance": max(variance, 0),
                "distinct_genres": len(genres),
            }
        )

    by_genres = sorted(
        results,
        key=lambda row: (row["distinct_genres"], row["ratings_count"], row["user_id"]),
        reverse=True,
    )[:10]
    by_variance = sorted(
        results,
        key=lambda row: (
            row["population_variance"],
            row["ratings_count"],
            row["user_id"],
        ),
        reverse=True,
    )[:10]
    return {"most_genre_diverse": by_genres, "highest_variance": by_variance}

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run the Part 2 MongoDB queries.")
    parser.add_argument(
        "--query",
        type=int,
        choices=range(1, 11),
        help="Run only one query. By default all queries are run.",
    )
    args = parser.parse_args()

    connector = DbConnector()
    try:
        db = connector.db
        queries = {
            1: ("1. Directors", lambda: query_directors(db.credits)),
            2: ("2. Actor pairs", lambda: query_actor_pairs(db.movies, db.credits)),
            3: ("3. Actor genre breadth", lambda: query_actor_genres(db.credits)),
            4: ("4. Film collections", lambda: query_collections(db.movies)),
            5: ("5. Decade and primary genre", lambda: query_decade_genres(db.movies)),
            6: ("6. Female top-five cast", lambda: query_female_cast(db.credits)),
            7: ("7. Noir text search", lambda: query_noir(db.movies)),
            8: ("8. Director-actor pairs", lambda: query_director_actor(db.credits)),
            9: ("9. Non-English US production", lambda: query_non_english(db.movies)),
            10: ("10. User rating statistics", lambda: query_users(db.movies, db.ratings)),
        }

        selected = [args.query] if args.query else queries.keys()
        for number in selected:
            title, query = queries[number]
            print(f"\n{title}")
            print("-" * len(title))
            pprint(query(), sort_dicts=False)
    finally:
        connector.close_connection()

if __name__ == "__main__":
    main()
