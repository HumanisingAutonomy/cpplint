import sre_compile

_regexp_compile_cache = {}


def Match(pattern, s):
    """Matches the string with the pattern, caching the compiled regexp."""
    # The regexp compilation caching is inlined in both Match and Search for
    # performance reasons; factoring it out into a separate function turns out
    # to be noticeably expensive.
    if pattern not in _regexp_compile_cache:
        _regexp_compile_cache[pattern] = sre_compile.compile(pattern)
    return _regexp_compile_cache[pattern].match(s)


def ReplaceAll(pattern, rep, s):
    """Replaces instances of pattern in a string with a replacement.

    The compiled regex is kept in a cache shared by Match and Search.

    Args:
      pattern: regex pattern
      rep: replacement text
      s: search string

    Returns:
      string with replacements made (or original string if no replacements)
    """
    if pattern not in _regexp_compile_cache:
        _regexp_compile_cache[pattern] = sre_compile.compile(pattern)
    return _regexp_compile_cache[pattern].sub(rep, s)


def Search(pattern, s):
    """Searches the string for the pattern, caching the compiled regexp."""
    if pattern not in _regexp_compile_cache:
        _regexp_compile_cache[pattern] = sre_compile.compile(pattern)
    return _regexp_compile_cache[pattern].search(s)
