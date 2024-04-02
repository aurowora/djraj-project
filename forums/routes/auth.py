import base64
import binascii
import http.cookies
import math
import os
import re
from contextlib import suppress
from datetime import datetime, timezone, timedelta
from hmac import compare_digest
from typing import Optional, Tuple, Annotated, Sequence
from urllib.parse import urlencode

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from jwt import encode, decode, InvalidTokenError
from pydantic import BaseModel, Field
from pymysql import IntegrityError
from starlette import status
from starlette.responses import RedirectResponse

from forums.blocking import spawn_blocking
from forums.config import LoginConfig
from forums.db.users import UserRepository, get_user_repo, User

router = APIRouter()


_LOGIN_AUD = "djraj_proj.forums.auth"


class _JWTPayload(BaseModel):
    # rfc subject
    sub: str
    # rfc expiration of token
    exp: int
    # rfc "not before" of token
    nbf: int
    # rfc "audience"
    aud: Sequence[str]
    # app "csrf binding value"
    # if a user is authenticated during csrf verification, the value
    # in the csrf token must match the value in this struct or else
    # it fails csrf validation.
    csrf_secret: str


_LOGIN_OPTS = {
    'verify_signature': True,
    'require': ['sub', 'exp', 'nbf', 'aud'],
    'verify_aud': True,
    'verify_exp': True,
    'verify_nbf': True,
    'strict_aud': False
}

_CSRF_TOKEN_AUD = "djraj_proj.forums.csrf_token"


class _CSRFToken(BaseModel):
    exp: int
    nbf: int
    aud: Sequence[str]
    sub: Optional[str] = Field(default=None)
    csrf_secret: Optional[str] = Field(default=None)


_CSRF_OPTS = {
    'verify_signature': True,
    'require': ['exp', 'nbf', 'aud'],
    'verify_aud': True,
    'verify_nbf': True,
    'verify_exp': True,
    'strict_aud': False,
}


class RequestLogin(BaseModel):
    username: str
    password: str
    csrf_token: str


@router.post('/login')
async def login(req: Request, username: Annotated[str, Form()], password: Annotated[str, Form()],
                csrf_token: Annotated[str, Form()],
                user_repo: UserRepository = Depends(get_user_repo)) -> RedirectResponse:
    if not is_valid_username(username) or not (req.app.state.cfg.login.min_password_size <= len(password) <= 72):
        return RedirectResponse(url=f'/login?%s' % urlencode({'error': 'invalid username and/or password'}),
                                headers={'Cache-Control': 'no-store'},
                                status_code=status.HTTP_303_SEE_OTHER)

    csrf_verify(req, csrf_token)

    if (user := await user_repo.get_user_by_name(username)) is None:
        return RedirectResponse(url=f'/login?%s' % urlencode({'error': 'invalid username and/or password'}),
                                headers={'Cache-Control': 'no-store'},
                                status_code=status.HTTP_303_SEE_OTHER)

    if not await _verify_password(password, user.pw_hash):
        return RedirectResponse(url=f'/login?%s' % urlencode({'error': 'invalid username and/or password'}),
                                headers={'Cache-Control': 'no-store'},
                                status_code=status.HTTP_303_SEE_OTHER)

    # Login OK

    exp = datetime.now(tz=timezone.utc) + timedelta(seconds=req.app.state.cfg.login.login_ttl)
    jwt_val = _create_login_jwt(req.app.state.cfg.login.secret, user.username, exp)
    cval = _create_cookie(req.app.state.cfg.login, jwt_val, exp)

    return RedirectResponse(url='/', headers={'Set-Cookie': cval, 'Cache-Control': 'no-store'},
                            status_code=status.HTTP_303_SEE_OTHER)


async def current_user(req: Request, user_repo: UserRepository = Depends(get_user_repo)) -> User:
    """
    Retrieves the currently authenticated user. This coroutine is intended to be used as a dependency in the
    following manner:

    @router.get('/my-route')
    async def my_route(user: User = Depends(current_user)):
        pass

    It returns a user object if the user can be authenticated. Otherwise, it raises an HTTPException that
    FastAPI turns into a redirect response into the login page.
    """
    login_conf = req.app.state.cfg.login

    try:
        payload = _decode_login_jwt(login_conf.secret, req.cookies[login_conf.cookie_name])
        if user := await user_repo.get_user_by_name(payload.sub):
            return user

        # Still here?
        raise KeyError(f'no such user {payload.sub}')
    except (KeyError, InvalidTokenError) as e:
        # not logged in or login cookie failed validation
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={'Location': '/login',
                                     'Cache-Control': 'no-store',
                                     'Set-Cookie': _create_cookie(login_conf, '',
                                                                  datetime.fromtimestamp(0, tz=timezone.utc))},
                            detail='This route requires authentication.') from e


async def _assert_no_user(req: Request, user_repo: UserRepository = Depends(get_user_repo)):
    """
    Redirects the user to the index page if they have a valid login.

    Use as a dependency on the attribute. i.e.

    @router.get('/my-route', dependencies=[Depends(_assert_no_user)]
    async def my_route():
        pass
    """
    try:
        _ = await current_user(req, user_repo)
    except HTTPException:
        return None  # OK

    raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={'Location': '/', 'Cache-Control': 'no-store'},
                        detail='The user is already authenticated.')


class WhoAmIReply(BaseModel):
    user_id: int
    username: str
    display_name: str


@router.get('/whoami')
def whoami(user: User = Depends(current_user)) -> WhoAmIReply:
    return WhoAmIReply(user_id=user.user_id, username=user.username, display_name=user.display_name)


@router.post('/register')
async def register(req: Request, first_name: Annotated[str, Form()], last_name: Annotated[str, Form()],
                   username: Annotated[str, Form()], password: Annotated[str, Form()],
                   csrf_token: Annotated[str, Form()],
                   user_repo: UserRepository = Depends(get_user_repo)):
    if not is_valid_username(username):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={'Location': '/register?%s' % urlencode({
            'error': 'the provided username is not valid. Usernames may only contain alphanumeric symbols and the underscore'}),
                                                                            'Cache-Control': 'no-store'})

    display_name = f'{first_name} {last_name}'
    if not is_valid_display_name(display_name):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={'Location': '/register?%s' % urlencode({
            'error': 'the provided display name is not valid. Names must be less than 64 characters and contain only alphanumeric symbols'}),
                                                                            'Cache-Control': 'no-store'})

    if not (req.app.state.cfg.login.min_password_size <= len(password) <= 72):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={'Location': '/register?%s' % urlencode(
            {
                'error': f'the provided password is not valid. Passwords must be between {req.app.state.cfg.login.min_password_size} and 72 characters (inclusive)', }),
                                                                            'Cache-Control': 'no-store'})

    csrf_verify(req, csrf_token)

    hashed_pw = await _hash_password(password)
    new_user = User(username=username,
                    pw_hash=hashed_pw,
                    display_name=display_name,
                    flags=0,
                    user_id=None)

    try:
        await user_repo.put_user(new_user)
    except IntegrityError:
        # this user already exists
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={'Location': '/register?%s' % urlencode(
            {
                'error': 'the provided username is not valid. The username is already in use by another user or is reserved by the administrator.'
            }
        )})

    # Register OK, log them in
    exp = datetime.now(tz=timezone.utc) + timedelta(seconds=req.app.state.cfg.login.login_ttl)
    jwt_val = _create_login_jwt(req.app.state.cfg.login.secret, new_user.username, exp)
    cval = _create_cookie(req.app.state.cfg.login, jwt_val, exp)

    return RedirectResponse(url='/', headers={'Set-Cookie': cval, 'Cache-Control': 'no-store'},
                            status_code=status.HTTP_303_SEE_OTHER)


@router.get('/logout')
def logout(req: Request):
    exp = datetime.fromtimestamp(0, tz=timezone.utc)
    cval = _create_cookie(req.app.state.cfg.login, '', exp)
    return RedirectResponse(url='/', headers={'Set-Cookie': cval, 'Cache-Control': 'no-store'},
                            status_code=status.HTTP_303_SEE_OTHER)


__VALIDATE_USERNAME = re.compile(r'^[0-9A-Za-z_]+$', flags=re.RegexFlag.UNICODE)
# TODO: This regex probably needs to support more characters than just ASCII
__VALIDATE_DISPLAY_NAME = re.compile(r'^[\w_ ]+$', flags=re.RegexFlag.UNICODE)
is_valid_display_name = lambda disp: (0 < len(disp) < 64) and __VALIDATE_DISPLAY_NAME.match(disp) is not None
is_valid_username = lambda username: (0 < len(username) <= 64) and __VALIDATE_USERNAME.match(username) is not None


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
        return await spawn_blocking(PasswordHasher().verify, hashed, password)
    except VerifyMismatchError:
        return False


def _create_login_jwt(secret: str, username: str, valid_until: datetime) -> str:
    current_time = int(math.floor(datetime.now(tz=timezone.utc).timestamp()))
    expire_time = int(math.floor(valid_until.astimezone(tz=timezone.utc).timestamp()))
    payload = _JWTPayload(sub=username, exp=expire_time, nbf=current_time, aud=[_LOGIN_AUD, ],
                          csrf_secret=base64.urlsafe_b64encode(os.urandom(16)).decode('utf-8')).model_dump()
    return encode(payload, secret, algorithm="HS256")


def _decode_login_jwt(secret: str, jwt: str) -> _JWTPayload:
    return _JWTPayload(**decode(jwt, secret, algorithms=["HS256"], audience=[_LOGIN_AUD, ], options=_LOGIN_OPTS))


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
    c[conf.cookie_name]["expires"] = exp.strftime(
        f"{_WKDAYS[exp.isoweekday() - 1]}, %d {_MONTHS[exp.month - 1]} %Y %H:%M:%S GMT")

    return c.output(header='', sep='').strip(' \r\n')


def generate_csrf_token(req: Request) -> str:
    """
    Produces a CSRF token that can be used to protect forms.

    Intended to be injected as a dependency into routes that require it, e.g.

    def x(csrf_token: str = Depends(generate_csrf_token))
    """
    user, csrf_secret = _extract_from_cookie(req)
    now = datetime.now(tz=timezone.utc)

    token = _CSRFToken(
        exp=int(math.floor((now + timedelta(hours=24)).timestamp())),
        nbf=int(math.floor(now.timestamp())),
        aud=[_CSRF_TOKEN_AUD, ],
        sub=user,
        csrf_secret=csrf_secret
    ).model_dump(exclude_none=True)

    return encode(token, req.app.state.cfg.login.secret, algorithm="HS256")


def csrf_verify(req: Request, token: str):
    """
    Checks that the CSRF token is valid.

    :raises: HTTPException if the token is not valid or could not be verified.
    :returns None:
    """
    user, csrf_secret = _extract_from_cookie(req)

    try:
        token = _CSRFToken(**decode(token, req.app.state.cfg.login.secret,
                                    algorithms=["HS256"],
                                    audience=[_CSRF_TOKEN_AUD, ],
                                    options=_CSRF_OPTS))
    except InvalidTokenError as exc:
        print(exc)
        raise HTTPException(status_code=403, detail="csrf token validation failed") from exc

    if ((token.sub is None) != (token.csrf_secret is None)) or (
            token.sub and (token.sub != user or not _ct_eq(token.csrf_secret, csrf_secret))):
        raise HTTPException(status_code=403, detail="csrf token validation failed")


def _extract_from_cookie(req: Request) -> Tuple[str | None, str | None]:
    login_conf = req.app.state.cfg.login
    with suppress(KeyError, InvalidTokenError):
        j = _decode_login_jwt(login_conf.secret, req.cookies[login_conf.cookie_name])
        return j.sub, j.csrf_secret
    return None, None


def _ct_eq(a: str, b: str) -> bool:
    """
    Compares the two base64 operands in constant time

    Returns true if they are equal
    Returns false if they are not equal or the base64 encoding is invalid.
    """
    try:
        a = base64.urlsafe_b64decode(a.encode('utf-8'))
        b = base64.urlsafe_b64decode(b.encode('utf-8'))

        return compare_digest(a, b)
    except binascii.Error:
        return False
