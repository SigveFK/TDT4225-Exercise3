# TDT4225 Exercise 3

## Install the requirements

Install the requirements:

python -m pip install -r requirements.txt

## Create the environment file

```env
DATABASE=assignment_db
HOST=localhost
USER=assignment_user
PASSWORD=change_this_assignment_password
MONGO_ROOT_USER=admin
MONGO_ROOT_PASSWORD=change_this_root_password
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

