#! /usr/bin/env python3

from forums.config import load_config
from fastapi import FastAPI
import uvicorn

app = FastAPI()


@app.get('/')
async def hello(name: str = "world"):
    return {'msg': f'Hello, {name}!'}


if __name__ == '__main__':
    cfg = load_config()

    app.state.cfg = cfg

    uvicorn.run('forums.main:app', host=cfg.listen_ip, port=cfg.listen_port)