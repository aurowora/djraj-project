import math
from typing import Optional

from jwt import encode, decode

from pydantic import BaseModel
from datetime import datetime, timezone, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from forums.blocking import spawn_blocking
from forums.config import LoginConfig
import http.cookies


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
    flags: int


def _create_jwt(secret: str, username: str, user_flags: int, valid_for: int) -> str:
    current_time = int(math.floor(datetime.now(tz=timezone.utc).timestamp()))
    expire_time = current_time + valid_for

    payload = _JWTPayload(sub=username, exp=expire_time, nbf=current_time, flags=user_flags).model_dump()
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

    c[conf.cookie_name]["expires"] = exp.strftime("{}, %d {} %Y %H:%M:%S GMT") % (
        _WKDAYS[exp.isoweekday() - 1],
        _MONTHS[exp.month - 1]
    )

    return c.output()
