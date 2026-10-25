import argparse
import statistics
import sys
from pprint import pprint
from DbConnector import DbConnector

def median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None

def query_directors(movies, credits):
    pipeline = [
        {"$unwind": "$crew"},
        {"$match": {"crew.job": "Director", "crew.id": {"$ne": None}}},
        {
            "$lookup": {
                "from": "movies",
                "localField": "_id",
                "foreignField": "_id",
                "as": "movie",
            }
        },
        {"$unwind": "$movie"},
        {
            "$group": {
                "_id": "$crew.id",
                "director": {"$first": "$crew.name"},
                "revenues": {"$push": "$movie.revenue"},
                "movie_count": {"$addToSet": "$_id"},
                "vote_averages": {"$push": "$movie.vote_average"},
            }
        },
    ]

    results = []
    for row in credits.aggregate(pipeline):
        vote_averages = [value for value in row["vote_averages"] if value is not None]
        revenues = [value for value in row["revenues"] if value is not None]
        movie_count = len(row["movie_count"])
        if movie_count < 5 or not revenues or not vote_averages:
            continue
        results.append(
            {
                "director": row["director"],
                "movie_count": movie_count,
                "median_revenue": median(revenues),
                "mean_vote_average": sum(vote_averages) / len(vote_averages),
            }
        )
    return sorted(
        results,
        key=lambda row: (row["median_revenue"], row["movie_count"], row["director"]),
        reverse=True,
    )[:10]


def movie_vote_averages(movies, movie_ids):
    return {
        movie["_id"]: movie.get("vote_average")
        for movie in movies.find(
            {"_id": {"$in": movie_ids}}, {"_id": 1, "vote_average": 1}
        )
    }


def query_actor_pairs(movies, credits):
    pipeline = [
        {"$unwind": "$cast"},
        {"$match": {"cast.id": {"$ne": None}}},
        {
            "$project": {
                "movie_id": "$_id",
                "actor_id": "$cast.id",
                "actor": "$cast.name",
            }
        },
        {
            "$lookup": {
                "from": "credits",
                "let": {"movie_id": "$movie_id", "actor_id": "$actor_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$movie_id"]},
                        }
                    },
                    {"$unwind": "$cast"},
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$ne": ["$cast.id", "$$actor_id"]},
                                    {"$gt": ["$cast.id", "$$actor_id"]},
                                ]
                            }
                        }
                    },
                    {
                        "$project": {
                            "_id": 0,
                            "actor_id": "$cast.id",
                            "actor": "$cast.name",
                        }
                    },
                ],
                "as": "co_actor",
            }
        },
        {"$unwind": "$co_actor"},
        {
            "$group": {
                "_id": {
                    "actor_id": "$actor_id",
                    "co_actor_id": "$co_actor.actor_id",
                },
                "actor": {"$first": "$actor"},
                "co_actor": {"$first": "$co_actor.actor"},
                "movie_ids": {"$addToSet": "$movie_id"},
            }
        },
        {"$match": {"$expr": {"$gte": [{"$size": "$movie_ids"}, 3]}}},
        {"$sort": {"_id.actor_id": 1, "_id.co_actor_id": 1}},
    ]

    results = []
    for row in credits.aggregate(pipeline):
        averages = movie_vote_averages(movies, row["movie_ids"])
        values = [averages[movie_id] for movie_id in row["movie_ids"] if averages.get(movie_id) is not None]
        if not values:
            continue
        results.append(
            {
                "actor": row["actor"],
                "co_actor": row["co_actor"],
                "co_appearances": len(row["movie_ids"]),
                "mean_vote_average": sum(values) / len(values),
            }
        )
    return sorted(
        results,
        key=lambda row: (row["co_appearances"], row["mean_vote_average"]),
        reverse=True,
    )

def query_actor_genres(movies, credits):
    pipeline = [
        {"$unwind": "$cast"},
        {"$match": {"cast.id": {"$ne": None}}},
        {
            "$lookup": {
                "from": "movies",
                "localField": "_id",
                "foreignField": "_id",
                "as": "movie",
            }
        },
        {"$unwind": "$movie"},
        {
            "$group": {
                "_id": "$cast.id",
                "actor": {"$first": "$cast.name"},
                "movies": {"$addToSet": "$_id"},
                "genre_lists": {"$push": {"$ifNull": ["$movie.genres", []]}},
            }
        },
    ]

    results = []
    for row in credits.aggregate(pipeline):
        if len(row["movies"]) < 10:
            continue
        genres = {
            genre.get("name")
            for genre_list in row["genre_lists"]
            for genre in genre_list
            if genre.get("name")
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
        key=lambda row: (row["genre_count"], row["movie_count"], row["actor"]),
        reverse=True,
    )[:10]

def query_collections(movies):
    pipeline = [
        {"$match": {"belongs_to_collection.name": {"$ne": None}}},
        {
            "$group": {
                "_id": "$belongs_to_collection.name",
                "movie_count": {"$sum": 1},
                "revenues": {"$push": "$revenue"},
                "vote_averages": {"$push": "$vote_average"},
                "release_dates": {"$push": "$release_date"},
            }
        },
        {"$match": {"movie_count": {"$gte": 3}}},
    ]

    results = []
    for row in movies.aggregate(pipeline):
        dates = [date for date in row["release_dates"] if date]
        results.append(
            {
                "collection": row["_id"],
                "movie_count": row["movie_count"],
                "total_revenue": sum(value or 0 for value in row["revenues"]),
                "median_vote_average": median(row["vote_averages"]),
                "earliest_release": min(dates) if dates else None,
                "latest_release": max(dates) if dates else None,
            }
        )
    return sorted(results, key=lambda row: row["total_revenue"], reverse=True)[:10]

def query_decade_genres(movies):
    pipeline = [
        {"$match": {"release_year": {"$ne": None}}},
        {
            "$set": {
                "primary_genre": {
                    "$arrayElemAt": [{"$ifNull": ["$genres", []]}, 0]
                }
            }
        },
        {"$match": {"primary_genre.name": {"$ne": None}, "runtime": {"$ne": None}}},
        {
            "$group": {
                "_id": {
                    "decade": {
                        "$multiply": [
                            {
                                "$floor": {
                                    "$divide": [
                                        "$release_year",
                                        10,
                                    ]
                                }
                            },
                            10,
                        ]
                    },
                    "genre": "$primary_genre.name",
                },
                "runtimes": {"$push": "$runtime"},
                "movie_count": {"$sum": 1},
            }
        },
    ]

    results = []
    for row in movies.aggregate(pipeline):
        results.append(
            {
                "decade": f"{int(row['_id']['decade'])}s",
                "primary_genre": row["_id"]["genre"],
                "median_runtime": median(row["runtimes"]),
                "movie_count": row["movie_count"],
            }
        )
    return sorted(
        results,
        key=lambda row: (row["decade"], -(row["median_runtime"] or 0)),
    )

def query_female_cast(movies, credits):
    pipeline = [
        {"$unwind": "$cast"},
        {"$sort": {"_id": 1, "cast.order": 1}},
        {"$group": {"_id": "$_id", "cast": {"$push": "$cast"}}},
        {
            "$lookup": {
                "from": "movies",
                "localField": "_id",
                "foreignField": "_id",
                "as": "movie",
            }
        },
        {"$unwind": "$movie"},
    ]

    by_decade = {}
    for row in credits.aggregate(pipeline):
        known = [
            person for person in row["cast"][:5] if person.get("gender") in (1, 2)
        ]
        year = row["movie"].get("release_year")
        if not known or year is None:
            continue
        decade = year // 10 * 10
        by_decade.setdefault(decade, []).append(
            sum(person.get("gender") == 1 for person in known) / len(known)
        )

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
        {
            "$match": {
                "$text": {"$search": "noir"},
                "vote_count": {"$gte": 50},
            }
        },
        {
            "$project": {
                "_id": 0,
                "title": 1,
                "year": {"$substrBytes": ["$release_date", 0, 4]},
                "vote_average": 1,
                "vote_count": 1,
                "score": {"$meta": "textScore"},
            }
        },
        {"$sort": {"vote_average": -1, "score": -1}},
        {"$limit": 20},
    ]
    return list(movies.aggregate(pipeline))

def query_director_actor(movies, credits):
    pipeline = [
        {
            "$lookup": {
                "from": "movies",
                "localField": "_id",
                "foreignField": "_id",
                "as": "movie",
            }
        },
        {"$unwind": "$movie"},
        {"$match": {"movie.vote_count": {"$gte": 100}}},
        {"$unwind": "$crew"},
        {"$match": {"crew.job": "Director", "crew.id": {"$ne": None}}},
        {"$unwind": "$cast"},
        {"$match": {"cast.id": {"$ne": None}}},
        {
            "$match": {
                "movie.vote_average": {"$ne": None},
            }
        },
        {
            "$group": {
                "_id": {
                    "director_id": "$crew.id",
                    "actor_id": "$cast.id",
                },
                "director": {"$first": "$crew.name"},
                "actor": {"$first": "$cast.name"},
                "films": {"$sum": 1},
                "vote_averages": {"$push": "$movie.vote_average"},
                "revenues": {"$push": "$movie.revenue"},
            }
        },
        {"$match": {"films": {"$gte": 3}}},
    ]

    results = []
    for row in credits.aggregate(pipeline):
        results.append(
            {
                "director": row["director"],
                "actor": row["actor"],
                "films_count": row["films"],
                "mean_vote_average": sum(row["vote_averages"])
                / len(row["vote_averages"]),
                "mean_revenue": (
                    sum(value for value in row["revenues"] if value is not None)
                    / len([value for value in row["revenues"] if value is not None])
                    if any(value is not None for value in row["revenues"])
                    else None
                ),
            }
        )
    return sorted(
        results,
        key=lambda row: (row["mean_vote_average"], row["films_count"], row["director"]),
        reverse=True,
    )[:20]

def query_non_english(movies):
    pipeline = [
        {
            "$match": {
                "original_language": {"$nin": [None, "", "en"]},
                "$or": [
                    {"production_countries.iso_3166_1": "US"},
                    {"production_companies.origin_country": "US"},
                ],
            }
        },
        {"$sort": {"title": 1}},
        {
            "$group": {
                "_id": "$original_language",
                "count": {"$sum": 1},
                "example_title": {"$first": "$title"},
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    return [
        {
            "original_language": row["_id"],
            "count": row["count"],
            "example_title": row["example_title"],
        }
        for row in movies.aggregate(pipeline)
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
    for row in ratings.aggregate(pipeline):
        ratings_count = row["ratings_count"]
        mean = row["rating_sum"] / ratings_count
        variance = row["rating_squared_sum"] / ratings_count - mean**2
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
        key=lambda row: (
            row["distinct_genres"],
            row["ratings_count"],
            row["user_id"],
        ),
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
        database = connector.db
        queries = {
            1: ("1. Directors", lambda: query_directors(database.movies, database.credits)),
            2: ("2. Actor pairs", lambda: query_actor_pairs(database.movies, database.credits)),
            3: ("3. Actor genre breadth", lambda: query_actor_genres(database.movies, database.credits)),
            4: ("4. Film collections", lambda: query_collections(database.movies)),
            5: ("5. Decade and primary genre", lambda: query_decade_genres(database.movies)),
            6: ("6. Female top-five cast", lambda: query_female_cast(database.movies, database.credits)),
            7: ("7. Noir text search", lambda: query_noir(database.movies)),
            8: ("8. Director-actor pairs", lambda: query_director_actor(database.movies, database.credits)),
            9: ("9. Non-English US production", lambda: query_non_english(database.movies)),
            10: ("10. User rating statistics", lambda: query_users(database.movies, database.ratings)),
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
