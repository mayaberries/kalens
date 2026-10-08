"""
Repository injection, vendored from pets-appts `app/api/dependencies/database.py`.

Identical except that the attribute the connection pool lives under is read
from Settings instead of being hardcoded to `_db` -- a host that names it
something else shouldn't have to rename to adopt this library.

This library never opens or closes the connection. The host's own lifespan
does that; all that happens here is reading the pool back off `app.state`.
"""
from typing import Callable, Type

from databases import Database
from fastapi import Depends
from starlette.requests import Request

from kalens.db.base import BaseRepository
from kalens.integration import get_settings


def get_database(request: Request) -> Database:
    return getattr(request.app.state, get_settings().database_state_attr)


def get_repository(Repo_type: Type[BaseRepository]) -> Callable:
    def get_repo(db: Database = Depends(get_database)) -> Type[BaseRepository]:
        return Repo_type(db)

    return get_repo
