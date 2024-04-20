import re
import unicodedata
from typing import Optional
import os
import aiofiles

import filetype
from fastapi import HTTPException, UploadFile
from starlette import status
from starlette.requests import Request
import logging

from forums.config import StorageConfig

__REGEX_SP_DASH = re.compile(r'[-\s]+', flags=re.RegexFlag.UNICODE)
__REGEX_BAD_CHARS = re.compile(r'[^\w.]', flags=re.RegexFlag.UNICODE)
__REGEX_DUP_DOTS = re.compile(r'\.{2,}', flags=re.RegexFlag.UNICODE)
__REGEX_LEADING_SP_DOT = re.compile(r'(^[.\s]+|[.\s]+$)', flags=re.RegexFlag.UNICODE)

MAX_NAME_LENGTH = 96


def _cmp_type(conf_type, r_type) -> bool:
    """
    Returns whether r_type matches conf_type.
    """
    (conf_type, conf_subtype) = conf_type.split('/')
    (r_type, r_subtype) = r_type.split('/')

    return (conf_type == '*' or conf_type == r_type) and (conf_subtype == '*' or conf_subtype == r_subtype)


def is_allowed_type(valid_types, buf: UploadFile) -> bool:
    return True


def escape_filename(filename: str) -> str:
    """
    Transforms filename such that it is safe to pass to io library calls.

    raises ValueError if the transformation fails
    """

    # apply unicode normalization
    filename = unicodedata.normalize('NFKC', filename)

    # remove leading/trailing dots and whitespace
    filename = __REGEX_LEADING_SP_DOT.sub('', filename)

    # replace all spaces and dashes with the underscore
    filename = __REGEX_SP_DASH.sub('_', filename)

    # remove all characters that aren't word chars
    filename = __REGEX_BAD_CHARS.sub('', filename.lower())

    filename = __REGEX_DUP_DOTS.sub('.', filename)

    # replace duplicate dots with a single dot
    if not (0 < len(filename) <= MAX_NAME_LENGTH):
        raise ValueError('Invalid filename')

    return filename


__REGEX_REWRITE_FNAME = re.compile(r'^(.+)\.(\w{1,4})$', flags=re.UNICODE)


def _next_name(filename: str, i: int = 0):
    if i == 0:
        return filename

    if m := __REGEX_REWRITE_FNAME.match(filename):
        return f'{m.groups()[0]}.{i}.{m.groups()[1]}'
    else:
        return f'{filename}.{i}'


MAX_OPEN_ATTEMPTS = 100


async def create_next_file(path, topic: int, filename: str, post: Optional[int] = None):
    base_path = os.path.join(path, 'attachments', str(topic))
    if post is not None:
        base_path = os.path.join(base_path, str(post))

    os.makedirs(base_path, exist_ok=True)

    i = 0
    while i < MAX_OPEN_ATTEMPTS:
        try:
            # x maps to O_CREAT
            fname = _next_name(filename, i)
            fpath = os.path.join(base_path, fname)
            fd = await aiofiles.open(fpath, 'xb')
            return fd, fname, fpath
        except FileExistsError:
            pass
        i += 1

    raise Exception(f'could not find an unused filename after {MAX_OPEN_ATTEMPTS} attempts')
