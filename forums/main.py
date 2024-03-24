#! /usr/bin/env python3
import asyncio
import logging

import aiomysql
from forums.config import load_config
from fastapi import FastAPI
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
cfg = load_config()
app.state.cfg = cfg


if __name__ == '__main__':
    uvicorn.run('forums.main:app', host=cfg.listen_ip, port=cfg.listen_port)