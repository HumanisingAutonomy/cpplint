import re

from .regex import Match, Search

_RE_PATTERN_INCLUDE = re.compile(r'^\s*#\s*include\s*([<"])([^>"]*)[>"].*$')
# Match a single C style comment on the same line.
_RE_PATTERN_C_COMMENTS = r"/\*(?:[^*]|\*(?!/))*\*/"
# Matches multi-line C style comments.
# This RE is a bit more complicated than one might expect, because we
# have to take care of space removals tools so that we can handle comments inside
# statements better.
# The current rule is: We only clear spaces from both sides when we're at the
# end of the line. Otherwise, we try to remove spaces from the right side,
# if this doesn't work we try on left side but only if there's a non-character
# on the right.
_RE_PATTERN_CLEANSE_LINE_C_COMMENTS = re.compile(
    r"(\s*"
    + _RE_PATTERN_C_COMMENTS
    + r"\s*$|"
    + _RE_PATTERN_C_COMMENTS
    + r"\s+|"
    + r"\s+"
    + _RE_PATTERN_C_COMMENTS
    + r"(?=\W)|"
    + _RE_PATTERN_C_COMMENTS
    + r")"
)


class CleansedLines:
    """Holds 4 copies of all lines with different preprocessing applied to them.

    1) elided member contains lines without strings and comments.
    2) lines member contains lines without comments.
    3) raw_lines member contains all the lines without processing.
    4) lines_without_raw_strings member is same as raw_lines, but with C++11 raw
       strings removed.
    All these members are of <type 'list'>, and of the same length.

    Args:
        lines: A list of all the lines in a file
        file_name: the name of the file to which the lines belong.
    """

    # Matches standard C++ escape sequences per 2.13.2.3 of the C++ standard.
    _RE_PATTERN_CLEANSE_LINE_ESCAPES = re.compile(r'\\([abfnrtv?"\\\']|\d+|x[0-9a-fA-F]+)')

    def __init__(self, lines: list[str], file_name: str) -> None:
        self._file_name = file_name
        self.elided = []
        self.lines = []
        self.raw_lines = lines
        self._num_lines = len(lines)
        self.lines_without_raw_strings = cleanse_raw_strings(lines)
        # # pylint: disable=consider-using-enumerate
        for line_num in range(len(self.lines_without_raw_strings)):
            self.lines.append(cleanse_comments(self.lines_without_raw_strings[line_num]))
            elided = self.collapse_strings(self.lines_without_raw_strings[line_num])
            self.elided.append(cleanse_comments(elided))

    @property
    def file_name(self) -> str:
        """The name of the file from which the lines are derived."""
        return self._file_name

    def num_lines(self) -> int:
        """Returns the number of lines represented.

        Returns:
            The number of represented lines.
        """
        return self._num_lines

    @staticmethod
    def collapse_strings(elided: str) -> str:
        """Collapses strings and chars on a line to simple "" or '' blocks.

        We nix strings first so that we're not fooled by text like '"http://"'

        Args:
            elided: The line being processed.

        Returns:
            The line with collapsed strings.
        """
        if _RE_PATTERN_INCLUDE.match(elided):
            return elided

        # Remove escaped characters first to make quote/single quote collapsing
        # basic.  Things that look like escaped characters shouldn't occur
        # outside of strings and chars.
        elided = CleansedLines._RE_PATTERN_CLEANSE_LINE_ESCAPES.sub("", elided)

        # Replace quoted strings and digit separators.  Both single quotes
        # and double quotes are processed in the same loop, otherwise
        # nested quotes wouldn't work.
        collapsed = ""
        while True:
            # Find the first quote character
            match = Match(r'^([^\'"]*)([\'"])(.*)$', elided)
            if not match:
                collapsed += elided
                break
            head, quote, tail = match.groups()

            if quote == '"':
                # Collapse double quoted strings
                second_quote = tail.find('"')
                if second_quote >= 0:
                    collapsed += head + '""'
                    elided = tail[second_quote + 1:]
                else:
                    # Unmatched double quote, don't bother processing the rest
                    # of the line since this is probably a multiline string.
                    collapsed += elided
                    break
            else:
                # Found single quote, check nearby text to eliminate digit separators.
                #
                # There is no special handling for floating point here, because
                # the integer/fractional/exponent parts would all be parsed
                # correctly as int as there are digits on both sides of the
                # separator.  So we are fine as int as we don't see something
                # like "0.'3" (gcc 4.9.0 will not allow this literal).
                if Search(r"\b(?:0[bBxX]?|[1-9])[0-9a-fA-F]*$", head):
                    match_literal = Match(r"^((?:\'?[0-9a-zA-Z_])*)(.*)$", "'" + tail)
                    collapsed += head + match_literal.group(1).replace("'", "")
                    elided = match_literal.group(2)
                else:
                    second_quote = tail.find("'")
                    if second_quote >= 0:
                        collapsed += head + "''"
                        elided = tail[second_quote + 1:]
                    else:
                        # Unmatched single quote
                        collapsed += elided
                        break

        return collapsed


def cleanse_comments(line):
    """Removes //-comments and single-line C-style /* */ comments.

    Args:
      line: A line of C++ source.

    Returns:
      The line with single-line comments removed.
    """
    comment_position = line.find("//")
    if comment_position != -1 and not _is_cpp_string(line[:comment_position]):
        line = line[:comment_position].rstrip()
    # get rid of /* ... */
    return _RE_PATTERN_CLEANSE_LINE_C_COMMENTS.sub("", line)


def cleanse_raw_strings(raw_lines):
    """Removes C++11 raw strings from lines.

      Before:
        static const char kData[] = R"(
            multi-line string
            )";

      After:
        static const char kData[] = ""
            (replaced by blank line)
            "";

    Args:
      raw_lines: list of raw lines.

    Returns:
      list of lines with C++11 raw strings replaced by empty strings.
    """

    delimiter = None
    lines_without_raw_strings = []
    for line in raw_lines:
        if delimiter:
            # Inside a raw string, look for the end
            end = line.find(delimiter)
            if end >= 0:
                # Found the end of the string, match leading space for this
                # line and resume copying the original lines, and also insert
                # a "" on the last line.
                leading_space = Match(r"^(\s*)\S", line)
                line = leading_space.group(1) + '""' + line[end + len(delimiter):]
                delimiter = None
            else:
                # Haven't found the end yet, append a blank line.
                line = '""'

        # Look for beginning of a raw string, and replace them with
        # empty strings.  This is done in a loop to handle multiple raw
        # strings on the same line.
        while delimiter is None:
            # Look for beginning of a raw string.
            # See 2.14.15 [lex.string] for syntax.
            #
            # Once we have matched a raw string, we check the prefix of the
            # line to make sure that the line is not part of a single line
            # comment.  It's done this way because we remove raw strings
            # before removing comments as opposed to removing comments
            # before removing raw strings.  This is because there are some
            # cpplint checks that requires the comments to be preserved, but
            # we don't want to check comments that are inside raw strings.
            matched = Match(r'^(.*?)\b(?:R|u8R|uR|UR|LR)"([^\s\\()]*)\((.*)$', line)
            if matched and not Match(r'^([^\'"]|\'(\\.|[^\'])*\'|"(\\.|[^"])*")*//', matched.group(1)):
                delimiter = ")" + matched.group(2) + '"'

                end = matched.group(3).find(delimiter)
                if end >= 0:
                    # Raw string ended on same line
                    line = matched.group(1) + '""' + matched.group(3)[end + len(delimiter):]
                    delimiter = None
                else:
                    # Start of a multi-line raw string
                    line = matched.group(1) + '""'
            else:
                break

        lines_without_raw_strings.append(line)

    # TODO(unknown): if delimiter is not None here, we might want to
    # emit a warning for unterminated string.
    return lines_without_raw_strings


def _is_cpp_string(line) -> bool:
    """Does line terminate so, that the next symbol is in string constant.

    This function does not consider single-line nor multi-line comments.

    Args:
      line: is a partial line of code starting from the 0..n.

    Returns:
      True, if next character appended to 'line' is inside a
      string constant.
    """

    line = line.replace(r"\\", "XX")  # after this, \\" does not match to \"
    return ((line.count('"') - line.count(r"\"") - line.count("'\"'")) & 1) == 1
