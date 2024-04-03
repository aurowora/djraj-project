import re
import unicodedata

__REGEX_SP_DASH = re.compile(r'[-\s]+', flags=re.RegexFlag.UNICODE)
__REGEX_BAD_CHARS = re.compile(r'[^\w.]', flags=re.RegexFlag.UNICODE)
__REGEX_DUP_DOTS = re.compile(r'\.{2,}', flags=re.RegexFlag.UNICODE)
__REGEX_LEADING_SP_DOT = re.compile(r'(^[.\s]+|[.\s]+$)', flags=re.RegexFlag.UNICODE)

MAX_NAME_LENGTH = 96


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
