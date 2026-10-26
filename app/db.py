"""Engine and session factory. Connection settings come from the PG* variables the Makefile exports."""
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker


def database_url():
    return URL.create(
        "postgresql+psycopg",
        username=os.environ.get("PGUSER", "lab"),
        password=os.environ.get("PGPASSWORD", "lab"),
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "55432")),
        database=os.environ.get("PGDATABASE", "lab"),
    )


# Parallel query is off for the session so plans read the same here and on a CI service container.
engine = create_engine(database_url(), pool_size=5, connect_args={"options": "-c max_parallel_workers_per_gather=0"})
SessionFactory = sessionmaker(engine, expire_on_commit=False)
