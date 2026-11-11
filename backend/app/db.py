from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from .config import settings

class Base(DeclarativeBase):
    pass

@lru_cache
def engine():
    return create_engine(settings().database_url, pool_pre_ping=True)

def session():
    with Session(engine()) as db:
        yield db
