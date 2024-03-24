import os
import tomllib
from typing import Optional

from pydantic import BaseModel, Field


class LoginConfig(BaseModel):
    # The secret key to use for signing session cookies
    # This should be a longish random value. The security of the login system depends on
    # the security of this value.
    secret: str
    # The name of the cookie to use
    cookie_name: str = Field(default='auth')
    # The domain attribute to use for the cookie
    cookie_domain: str = Field(default='localhost')
    # The path attribute to use for the cookie
    cookie_path: Optional[str] = Field(default=None)
    # Whether the secure attribute is set on the cookie
    cookie_secure: bool = Field(default=True)
    # Whether the httpOnly attribute is set on the cookie
    cookie_http_only: bool = Field(default=True)
    # Which same site value to use for the cookie. Is one of: strict, lax, or none
    cookie_same_site: str = Field(default="strict", pattern="^(strict|lax|none)$")
    # How long the auth cookie (and therefore the user session) should live
    login_ttl: int = Field(default=60 * 60 * 24 * 7, gt=60)


class Config(BaseModel):
    # The IP address to bind to.
    listen_ip: str = Field(default='127.0.0.1')
    # The port to listen on.
    listen_port: int = Field(default=8080, gt=0, le=65565)
    # The database configuration. This attributes are passed to
    # aiomysql's connect. See https://aiomysql.readthedocs.io/en/stable/connection.html#connection
    db: dict = Field(default_factory=dict)
    # Configures authentication
    login: LoginConfig


def load_config() -> Config:
    """
    Loads the configuration file from disk and returns an instance of Config.
    It looks for the file specified by the environment variable FORUMS_CONFIG
    if it is set. If it is not set, it looks for config.toml in the PWD. If
    a suitable file is not found or the file contains syntax errors, this function
    raises an Exception.
    """

    path = os.environ['FORUMS_CONFIG'] if 'FORUMS_CONFIG' in os.environ else 'config.toml'
    with open(path, 'rb') as fh:
        return Config(**tomllib.load(fh))
