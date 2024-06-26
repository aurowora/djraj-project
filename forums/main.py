#! /usr/bin/env python3
import asyncio
import logging

import aiomysql
from starlette import status
from starlette.requests import Request
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from forums.config import load_config
from fastapi import FastAPI, HTTPException
import uvicorn
from contextlib import asynccontextmanager, suppress

from forums.routes import router


@asynccontextmanager
async def lifespan(a: FastAPI):
    """
    This function contains code that should be run during startup (before the yield)
    and code that should be run during shutdown (after the yield).

    It is called automatically by FastAPI
    """
    # force autocommit and charset
    a.state.cfg.db["autocommit"] = True
    a.state.cfg.db["charset"] = "utf8mb4"
    # must not exist
    with suppress(KeyError):
        del a.state.cfg.db["loop"]

    # Create mysql connection pool
    a.state.db = await aiomysql.create_pool(**cfg.db, loop=asyncio.get_running_loop())

    yield

    a.state.db.close()
    await a.state.db.wait_closed()


app = FastAPI(lifespan=lifespan)
app.include_router(router())
app.mount('/static', StaticFiles(directory='static'), name='static')
cfg = load_config()
app.state.cfg = cfg
app.state.tpl = Jinja2Templates(directory='templates')


@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    if request.method.upper() != 'POST':
        return await call_next(request)

    storage_conf = request.app.state.cfg.storage

    try:
        length = int(request.headers['Content-Length'])

        if length > storage_conf.max_file_size:
            return Response(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, content='Request body is too large.')
    except KeyError:
        return Response(status_code=status.HTTP_411_LENGTH_REQUIRED, content='Please include the Content-Length'
                                                                             ' header for file uploads.')
    except ValueError:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content='Please include the Content-Length'
                                                                         ' header for file uploads.')
    return await call_next(request)


if __name__ == '__main__':
    uvicorn.run('forums.main:app', host=cfg.listen_ip, port=cfg.listen_port)
