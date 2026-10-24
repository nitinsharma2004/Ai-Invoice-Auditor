from __future__ import annotations


 

from collections.abc import Generator


 

from sqlalchemy import create_engine

from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


 

from backend.app.settings import DATABASE_URL


 

_engine_options = {"pool_pre_ping": True}

if isinstance(DATABASE_URL, str):

    uses_sqlite = DATABASE_URL.startswith("sqlite")

else:

    uses_sqlite = DATABASE_URL.drivername.startswith("sqlite")

if uses_sqlite:

    _engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_options)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)



 

class Base(DeclarativeBase):

    pass



 

def get_db() -> Generator[Session, None, None]:

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()


 