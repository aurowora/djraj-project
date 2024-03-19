import math
import re
from typing import Optional

from jwt import encode, decode
from urllib.parse import urlencode

from pydantic import BaseModel
from datetime import datetime, timezone, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from starlette.responses import RedirectResponse

from forums.blocking import spawn_blocking
from forums.config import LoginConfig
import http.cookies
from fastapi import APIRouter, Depends, Request

from forums.db.users import UserRepository, get_user_repo

router = APIRouter()


class RequestLogin(BaseModel):
    username: str
    password: str
    csrf_token: str


@router.post('/login')
async def login(req: Request, login_params: RequestLogin, user_repo: UserRepository = Depends(get_user_repo)) -> RedirectResponse:
    if not _is_valid_username(login_params.username) or not (0 < len(login_params.password) <= 72):
        return RedirectResponse(url=f'/login?%s' % urlencode({'error': 'invalid username and/or password'}), headers={'Cache-Control': 'no-store'})

    # TODO, check CSRF token

    if (user := await user_repo.get_user_by_name(login_params.username)) is None:
        return RedirectResponse(url=f'/login?%s' % urlencode({'error': 'invalid username and/or password'}), headers={'Cache-Control': 'no-store'})

    if not await _verify_password(login_params.password, user.pw_hash):
        return RedirectResponse(url=f'/login?%s' % urlencode({'error': 'invalid username and/or password'}), headers={'Cache-Control': 'no-store'})

    # Login OK

    exp = datetime.now(tz=timezone.utc) + timedelta(seconds=req.app.state.cfg.login.login_ttl)
    jwt_val = _create_jwt(req.app.state.cfg.login.secret, user.username, exp)
    cval = _create_cookie(req.app.state.cfg.login, jwt_val, exp)

    return RedirectResponse(url='/', headers={'Set-Cookie': cval, 'Cache-Control': 'no-store'})


__VALIDATE_USERNAME = re.compile(r'^[0-9A-Za-z_]+$', flags=re.RegexFlag.UNICODE)


def _is_valid_username(username: str) -> bool:
    return (0 < len(username) <= 64) and __VALIDATE_USERNAME.match(username) is not None


async def _hash_password(password: str) -> str:
    """
    Produces a password hash for the given password.
    """
    return await spawn_blocking(PasswordHasher().hash, password)


async def _verify_password(password: str, hashed: str) -> bool:
    """
    Determines whether the password matches the given password hash.

    :returns: True if the password matches the hash, false otherwise.
    """
    try:
        return await spawn_blocking(PasswordHasher().verify(hashed, password))
    except VerifyMismatchError:
        return False


class _JWTPayload(BaseModel):
    sub: str
    exp: int
    nbf: int


def _create_jwt(secret: str, username: str, valid_until: datetime) -> str:
    current_time = int(math.floor(datetime.now(tz=timezone.utc).timestamp()))
    expire_time = int(math.floor(valid_until.astimezone(tz=timezone.utc).timestamp()))

    payload = _JWTPayload(sub=username, exp=expire_time, nbf=current_time).model_dump()
    return encode(payload, secret, algorithm="HS256")


_WKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _create_cookie(conf: LoginConfig, value: str, exp: Optional[datetime] = None) -> str:
    c = http.cookies.SimpleCookie()

    c[conf.cookie_name] = value
    c[conf.cookie_name]["domain"] = conf.cookie_domain
    if conf.cookie_path:
        c[conf.cookie_name]["path"] = conf.cookie_path

    if conf.cookie_same_site == "strict":
        c[conf.cookie_name]["samesite"] = "Strict"
    elif conf.cookie_same_site == "lax":
        c[conf.cookie_name]["samesite"] = "Lax"

    if conf.cookie_secure:
        c[conf.cookie_name]["secure"] = True
    if conf.cookie_http_only:
        c[conf.cookie_name]["httponly"] = True

    if not exp:
        exp = datetime.now(tz=timezone.utc) + timedelta(seconds=conf.login_ttl)

    # There are format codes, but they break the RFC when you change the system locale
    c[conf.cookie_name]["expires"] = exp.strftime("{}, %d {} %Y %H:%M:%S GMT") % (
        _WKDAYS[exp.isoweekday() - 1],
        _MONTHS[exp.month - 1]
    )

    return c.output()
