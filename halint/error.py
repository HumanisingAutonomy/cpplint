import re
import sys
from typing import Callable

from .categories import _ERROR_CATEGORIES
from .lintstate import LintState
from .regex import Search

ErrorLogger = Callable[[LintState, str, int, str, int, str], None]

# Commands for sed to fix the problem
_SED_FIXUPS = {
    "Remove spaces around =": r"s/ = /=/",
    "Remove spaces around !=": r"s/ != /!=/",
    "Remove space before ( in if (": r"s/if (/if(/",
    "Remove space before ( in for (": r"s/for (/for(/",
    "Remove space before ( in while (": r"s/while (/while(/",
    "Remove space before ( in switch (": r"s/switch (/switch(/",
    "Should have a space between // and comment": r"s/\/\//\/\/ /",
    "Missing space before {": r"s/\([^ ]\){/\1 {/",
    "Tab found, replace by spaces": r"s/\t/  /g",
    "Line ends in whitespace.  Consider deleting these extra spaces.": r"s/\s*$//",
    "You don't need a ; after a }": r"s/};/}/",
    "Missing space after ,": r"s/,\([^ ]\)/, \1/g",
}

# The default list of categories suppressed for C (not C++) files.
_DEFAULT_C_SUPPRESSED_CATEGORIES = [
    "readability/casting",
]

# The default list of categories suppressed for Linux Kernel files.
_DEFAULT_KERNEL_SUPPRESSED_CATEGORIES = [
    "whitespace/tab",
]

# Match strings that indicate we're working on a C (not C++) file.
_SEARCH_C_FILE = re.compile(r"\b(?:LINT_C_FILE|" r"vim?:\s*.*(\s*|:)filetype=c(\s*|:|$))")

# Match string that indicates we're working on a Linux Kernel file.
_SEARCH_KERNEL_FILE = re.compile(r"\b(?:LINT_KERNEL_FILE)")

# These error categories are no longer enforced by cpplint, but for backwards-
# compatibility they may still appear in NOLINT comments.
_LEGACY_ERROR_CATEGORIES = [
    "readability/streams",
    "readability/function",
]

# These prefixes for categories should be ignored since they relate to other
# tools which also use the NOLINT syntax, e.g. clang-tidy.
_OTHER_NOLINT_CATEGORY_PREFIXES = [
    "clang-analyzer",
]


def ProcessGlobalSuppresions(state: LintState, lines: list[str]):
    """Updates the list of global error suppressions.

    Parses any lint directives in the file that have global effect.

    Args:
      state: The current state of the linting process
      lines: An array of strings, each representing a line of the file, with the
             last element being empty if the file is terminated with a newline.
    """
    for line in lines:
        if _SEARCH_C_FILE.search(line):
            for category in _DEFAULT_C_SUPPRESSED_CATEGORIES:
                state._global_error_suppressions[category] = True
        if _SEARCH_KERNEL_FILE.search(line):
            for category in _DEFAULT_KERNEL_SUPPRESSED_CATEGORIES:
                state._global_error_suppressions[category] = True


def IsErrorSuppressedByNolint(state: LintState, category: str, linenum: int):
    """Returns true if the specified error category is suppressed on this line.

    Consults the global error_suppressions map populated by
    ParseNolintSuppressions/ProcessGlobalSuppresions/ResetNolintSuppressions.

    Args:
      category: str, the category of the error.
      linenum: int, the current line number.
    Returns:
      bool, True iff the error should be suppressed due to a NOLINT comment or
      global suppression.
    """
    return (
        state._global_error_suppressions.get(category, False)
        or linenum in state._error_suppressions.get(category, set())
        or linenum in state._error_suppressions.get(None, set())
    )


def _ShouldPrintError(state: LintState, category, confidence, linenum):
    """If confidence >= verbose, category passes filter and is not suppressed."""

    # There are three ways we might decide not to print an error message:
    # a "NOLINT(category)" comment appears in the source,
    # the verbosity level isn't high enough, or the filters filter it out.
    if IsErrorSuppressedByNolint(state, category, linenum):
        return False

    if confidence < state.verbose_level:
        return False

    is_filtered = False
    for one_filter in state.filters:
        if one_filter.startswith("-"):
            if category.startswith(one_filter[1:]):
                is_filtered = True
        elif one_filter.startswith("+"):
            if category.startswith(one_filter[1:]):
                is_filtered = False
        else:
            raise ValueError(state, f"Filters must start with '+' or '-', {one_filter} does not.")
    if is_filtered:
        return False

    return True


def ParseNolintSuppressions(state: LintState, filename, raw_line, line_num, error):
    """Updates the global list of line error-suppressions.

    Parses any NOLINT comments on the current line, updating the global
    error_suppressions store.  Reports an error if the NOLINT comment
    was malformed.

    Args:
      state: THe current state of the linting process
      filename: str, the name of the input file.
      raw_line: str, the line of input text, with comments.
      line_num: int, the number of the current line.
      error: function, an error handler.
    """
    matched = Search(r"\bNOLINT(NEXTLINE)?\b(\([^)]+\))?", raw_line)
    if matched:
        if matched.group(1):
            suppressed_line = line_num + 1
        else:
            suppressed_line = line_num
        category = matched.group(2)
        if category in (None, "(*)"):  # => "suppress all"
            state._error_suppressions.setdefault(None, set()).add(suppressed_line)
        else:
            if category.startswith("(") and category.endswith(")"):
                category = category[1:-1]
                if category in _ERROR_CATEGORIES:
                    state._error_suppressions.setdefault(category, set()).add(suppressed_line)
                elif any(c for c in _OTHER_NOLINT_CATEGORY_PREFIXES if category.startswith(c)):
                    # Ignore any categories from other tools.
                    pass
                elif category not in _LEGACY_ERROR_CATEGORIES:
                    error(
                        filename,
                        line_num,
                        "readability/nolint",
                        5,
                        "Unknown NOLINT error category: %s" % category,
                        )


def ProcessGlobalSuppresions(state: LintState, lines):
    """Updates the list of global error suppressions.

    Parses any lint directives in the file that have global effect.

    Args:
      lines: An array of strings, each representing a line of the file, with the
             last element being empty if the file is terminated with a newline.
    """
    for line in lines:
        if _SEARCH_C_FILE.search(line):
            for category in _DEFAULT_C_SUPPRESSED_CATEGORIES:
                state._global_error_suppressions[category] = True
        if _SEARCH_KERNEL_FILE.search(line):
            for category in _DEFAULT_KERNEL_SUPPRESSED_CATEGORIES:
                state._global_error_suppressions[category] = True


def ResetNolintSuppressions(state: LintState):
    """Resets the set of NOLINT suppressions to empty."""
    state._error_suppressions.clear()
    state._global_error_suppressions.clear()


def IsErrorSuppressedByNolint(state: LintState, category, linenum):
    """Returns true if the specified error category is suppressed on this line.

    Consults the global error_suppressions map populated by
    ParseNolintSuppressions/ProcessGlobalSuppresions/ResetNolintSuppressions.

    Args:
      category: str, the category of the error.
      linenum: int, the current line number.
    Returns:
      bool, True iff the error should be suppressed due to a NOLINT comment or
      global suppression.
    """
    return (
        state._global_error_suppressions.get(category, False)
        or linenum in state._error_suppressions.get(category, set())
        or linenum in state._error_suppressions.get(None, set())
    )
def Error(
    state: LintState,
    filename: str,
    line_num: int,
    category: str,
    confidence: int,
    message: str,
):
    """Logs the fact we've found a lint error.

    We log where the error was found, and also our confidence in the error,
    that is, how certain we are this is a legitimate style regression, and
    not a misidentification or a use that's sometimes justified.

    False positives can be suppressed by the use of
    "cpplint(category)"  comments on the offending line.  These are
    parsed into _error_suppressions.

    Args:
      state: The current state of the linting process.
      filename: The name of the file containing the error.
      line_num: The number of the line containing the error.
      category: A string used to describe the "category" this bug
        falls under: "whitespace", say, or "runtime".  Categories
        may have a hierarchy separated by slashes: "whitespace/indent".
      confidence: A number from 1-5 representing a confidence score for
        the error, with 5 meaning that we are certain of the problem,
        and 1 meaning that it could be a legitimate construct.
      message: The error message.
    """
    if _ShouldPrintError(state, category, confidence, line_num):
        state.IncrementErrorCount(category)
        if state.output_format == "vs7":
            state.PrintError(
                state,
                "%s(%s): error cpplint: [%s] %s [%d]\n" % (filename, line_num, category, message, confidence),
            )
        elif state.output_format == "eclipse":
            sys.stderr.write("%s:%s: warning: %s  [%s] [%d]\n" % (filename, line_num, message, category, confidence))
        elif state.output_format == "junit":
            state.AddJUnitFailure(filename, line_num, message, category, confidence)
        elif state.output_format in ["sed", "gsed"]:
            if message in _SED_FIXUPS:
                sys.stdout.write(
                    state.output_format
                    + " -i '%s%s' %s # %s  [%s] [%d]\n"
                    % (
                        line_num,
                        _SED_FIXUPS[message],
                        filename,
                        message,
                        category,
                        confidence,
                    )
                )
            else:
                sys.stderr.write('# %s:%s:  "%s"  [%s] [%d]\n' % (filename, line_num, message, category, confidence))
        else:
            final_message = "%s:%s:  %s  [%s] [%d]\n" % (
                filename,
                line_num,
                message,
                category,
                confidence,
            )
            sys.stderr.write(final_message)
