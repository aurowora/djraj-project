from pydantic import BaseModel, Field
import os, tomllib


class Config(BaseModel):
    # The IP address to bind to.
    listen_ip: str = Field(default='127.0.0.1')
    # The port to listen on.
    listen_port: int = Field(default=8080, gt=0, le=65565)


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
