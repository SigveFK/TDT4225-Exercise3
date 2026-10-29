# TDT4225 Exercise 3

## Download the CSV files

Some of the CSV files are too large for GitHub and must be downloaded from:

https://drive.google.com/drive/folders/1JzO_kVfT5CJoN753A9c_xCQazhNTKca6?usp=sharing

Place the downloaded files in the `csv` directory.

## Install the requirements

Install the requirements in the global Python environment:

```powershell
python -m pip install -r requirements.txt
```

## Create the environment file

Create a `.env` file in the project root:

```text
DATABASE=assignment_db
HOST=localhost
USER=user
PASSWORD=your_application_password
MONGO_ROOT_USER=admin
MONGO_ROOT_PASSWORD=your_root_password
```

Set `PASSWORD` to the password for the application MongoDB user.
`USER` and `PASSWORD` are the MongoDB credentials.
`MONGO_ROOT_USER` and `MONGO_ROOT_PASSWORD` are used by Docker Compose to
initialize the MongoDB root account.

## MongoDB with Docker Compose

Start MongoDB:

```powershell
docker compose up -d
```

Check the service status:

```powershell
docker compose ps -a
```

Run the Python programs after the `mongodb-user-init` service has completed
successfully.

Stop MongoDB without deleting the database volume:

```powershell
docker compose down
```

Stop MongoDB and delete the database volume:

```powershell
docker compose down -v
```

Deleting the volume removes the stored MongoDB data.

## Run the programs

Part 1 consists of:

- `eda.py`: exploratory data analysis
- `create_database.py`: data cleaning and database loading

Part 2 consists of:

- `part2.py`: the ten MongoDB analysis queries

Run EDA with the default small ratings and links files:

```powershell
python .\eda.py
```

Create or rebuild the MongoDB database with the default small files:

```powershell
python .\create_database.py
```

Run all ten Part 2 queries:

```powershell
python .\part2.py
```

Run one Part 2 query:

```powershell
python .\part2.py --query 10
```

The database loader drops and recreates the `movies`, `credits`, `keywords`,
`links`, and `ratings` collections each time it runs. Running it again replaces
the existing contents of those collections.

## Small and full datasets

By default, `eda.py` and `create_database.py` use:

- `ratings_small.csv`
- `links_small.csv`

Run EDA on the full ratings and links files:

```powershell
python .\eda.py --ratings ratings.csv --links links.csv
```

Load the full ratings and links files:

```powershell
python .\create_database.py --ratings ratings.csv --links links.csv
```

See [database_model.md](database_model.md) for the database model diagram.
