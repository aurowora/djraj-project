import re
import unicodedata
import filetype

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


def is_allowed_type(valid_types, buf: bytes) -> bool:
    """
    Returns whether the contents of buf correspond to a file type included in the valid_types list.

    Items in the valid_types list are specified as mime types (i.e. form type/subtype). For the contents
    of buf to be allowed by this function, the mime type it maps to either be exactly the same as an item
    in valid types or valid types must include a wild card that matches the type.

    If the type of the contents of buffer cannot be determined, it is taken to be of type application/octet-stream. As
    such, from a security standpoint, allowing application/octet-stream has similar implications to allowing */*

    Example:
        valid_types = ['audio/*'], buf contains bytes of type audio/mpeg -> accepted
        valid_types = ['image/jpeg'], buf contains bytes of type image/png -> rejected
        valid_types = ['audio/ogg'], buf contains bytes of type audio/ogg -> accepted
        valid_types = ['application/octet-stream'], buf contains bytes of an indeterminate type -> accepted
    """
    g = filetype.guess_mime(buf)
    if g is None:
        g = 'application/octet-stream'

    for t in valid_types:
        if _cmp_type(t, g):
            return True
    return False


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
