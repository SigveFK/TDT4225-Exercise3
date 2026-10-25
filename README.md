# TDT4225 Exercise 3

## Download the csv files

Two of the csv files were too big for github so they have to be fetched from:
https://drive.google.com/drive/folders/1JzO_kVfT5CJoN753A9c_xCQazhNTKca6?usp=sharing

## Install the requirements

Install the requirements:

python -m pip install -r requirements.txt

## Create the environment file

```env
DATABASE=assignment_db
HOST=localhost
USER=user
PASSWORD=password
MONGO_ROOT_USER=admin
MONGO_ROOT_PASSWORD=root_password
```

## MongoDB with Docker Compose

Run:

docker compose up -d

Status:

docker compose ps -a

Stop:

docker compose down

Stop and delete:

docker compose down -v

