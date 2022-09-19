#!/usr/bin/env python
#
# Copyright (c) 2009 Google Inc. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#    * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above
# copyright notice, this list of conditions and the following disclaimer
# in the documentation and/or other materials provided with the
# distribution.
#    * Neither the name of Google Inc. nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Does google-lint on c++ files.

The goal of this script is to identify places in the code that *may*
be in non-compliance with google style.  It does not attempt to fix
up these problems -- the point is to educate.  It does also not
attempt to find all problems, or to ensure that everything it does
find is legitimately a problem.

In particular, we can get very confused by /* and // inside strings!
we do a small hack, which is to ignore //'s with "'s after them on the
same line, but it is far from perfect (in either direction).
"""

# cpplint predates fstrings
# pylint: disable=consider-using-f-string

# pylint: disable=invalid-name

import codecs
import copy
import itertools
import os
import re
import string
import sys
import sysconfig
from typing import Callable
import unicodedata

from ._cpplintstate import _CppLintState
from .cleansed_lines import CleansedLines, CleanseComments, _RE_PATTERN_INCLUDE
from .include_state import _IncludeState
from .file_info import FileInfo, _IsExtension
from .function_state import _FunctionState
from .regex import Match, Search, ReplaceAll
from .nesting_state import NestingState
from .block_info import (
    _ClassInfo,
    _NamespaceInfo,
    _ClassifyInclude,
    CloseExpression,
    ReverseCloseExpression,
    GetHeaderGuardCPPVariable,
    _TEST_FILE_SUFFIX
)

from .check_style import CheckStyle

# We categorize each error message we print.  Here are the categories.
# We want an explicit list so we can list them all in cpplint --filter=.
# If you add a new error message with a new category, add it to the list
# here!  cpplint_unittest.py should tell you if you forget to do this.
_ERROR_CATEGORIES = [
    'build/class',
    'build/c++11',
    'build/c++14',
    'build/c++tr1',
    'build/deprecated',
    'build/endif_comment',
    'build/explicit_make_pair',
    'build/forward_decl',
    'build/header_guard',
    'build/include',
    'build/include_subdir',
    'build/include_alpha',
    'build/include_order',
    'build/include_what_you_use',
    'build/namespaces_headers',
    'build/namespaces_literals',
    'build/namespaces',
    'build/printf_format',
    'build/storage_class',
    'legal/copyright',
    'readability/alt_tokens',
    'readability/braces',
    'readability/casting',
    'readability/check',
    'readability/constructors',
    'readability/fn_size',
    'readability/inheritance',
    'readability/multiline_comment',
    'readability/multiline_string',
    'readability/namespace',
    'readability/nolint',
    'readability/nul',
    'readability/strings',
    'readability/todo',
    'readability/utf8',
    'runtime/arrays',
    'runtime/casting',
    'runtime/explicit',
    'runtime/int',
    'runtime/init',
    'runtime/invalid_increment',
    'runtime/member_string_references',
    'runtime/memset',
    'runtime/indentation_namespace',
    'runtime/operator',
    'runtime/printf',
    'runtime/printf_format',
    'runtime/references',
    'runtime/string',
    'runtime/threadsafe_fn',
    'runtime/vlog',
    'whitespace/blank_line',
    'whitespace/braces',
    'whitespace/comma',
    'whitespace/comments',
    'whitespace/empty_conditional_body',
    'whitespace/empty_if_body',
    'whitespace/empty_loop_body',
    'whitespace/end_of_line',
    'whitespace/ending_newline',
    'whitespace/forcolon',
    'whitespace/indent',
    'whitespace/line_length',
    'whitespace/newline',
    'whitespace/operators',
    'whitespace/parens',
    'whitespace/semicolon',
    'whitespace/tab',
    'whitespace/todo',
    ]


# The default list of categories suppressed for C (not C++) files.
_DEFAULT_C_SUPPRESSED_CATEGORIES = [
    'readability/casting',
    ]

# The default list of categories suppressed for Linux Kernel files.
_DEFAULT_KERNEL_SUPPRESSED_CATEGORIES = [
    'whitespace/tab',
    ]

# We used to check for high-bit characters, but after much discussion we
# decided those were OK, as long as they were in UTF-8 and didn't represent
# hard-coded international strings, which belong in a separate i18n file.

# These headers are excluded from [build/include] and [build/include_order]
# checks:
# - Anything not following google file name conventions (containing an
#   uppercase character, such as Python.h or nsStringAPI.h, for example).
# - Lua headers.
_THIRD_PARTY_HEADERS_PATTERN = re.compile(
    r'^(?:[^/]*[A-Z][^/]*\.h|lua\.h|lauxlib\.h|lualib\.h)$')




# These constants define the current inline assembly state
_NO_ASM = 0       # Outside of inline assembly block
_INSIDE_ASM = 1   # Inside inline assembly block
_END_ASM = 2      # Last line of inline assembly block
_BLOCK_ASM = 3    # The whole block is an inline assembly block

# Match start of assembly blocks
_MATCH_ASM = re.compile(r'^\s*(?:asm|_asm|__asm|__asm__)'
                        r'(?:\s+(volatile|__volatile__))?'
                        r'\s*[{(]')

# Match strings that indicate we're working on a C (not C++) file.
_SEARCH_C_FILE = re.compile(r'\b(?:LINT_C_FILE|'
                            r'vim?:\s*.*(\s*|:)filetype=c(\s*|:|$))')

# Match string that indicates we're working on a Linux Kernel file.
_SEARCH_KERNEL_FILE = re.compile(r'\b(?:LINT_KERNEL_FILE)')

# Commands for sed to fix the problem
_SED_FIXUPS = {
  'Remove spaces around =': r's/ = /=/',
  'Remove spaces around !=': r's/ != /!=/',
  'Remove space before ( in if (': r's/if (/if(/',
  'Remove space before ( in for (': r's/for (/for(/',
  'Remove space before ( in while (': r's/while (/while(/',
  'Remove space before ( in switch (': r's/switch (/switch(/',
  'Should have a space between // and comment': r's/\/\//\/\/ /',
  'Missing space before {': r's/\([^ ]\){/\1 {/',
  'Tab found, replace by spaces': r's/\t/  /g',
  'Line ends in whitespace.  Consider deleting these extra spaces.': r's/\s*$//',
  'You don\'t need a ; after a }': r's/};/}/',
  'Missing space after ,': r's/,\([^ ]\)/, \1/g',
}




def ProcessGlobalSuppresions(lines):
    """Updates the list of global error suppressions.

    Parses any lint directives in the file that have global effect.

    Args:
      lines: An array of strings, each representing a line of the file, with the
             last element being empty if the file is terminated with a newline.
    """
    for line in lines:
        if _SEARCH_C_FILE.search(line):
            for category in _DEFAULT_C_SUPPRESSED_CATEGORIES:
                _cpplint_state._global_error_suppressions[category] = True
        if _SEARCH_KERNEL_FILE.search(line):
            for category in _DEFAULT_KERNEL_SUPPRESSED_CATEGORIES:
                _cpplint_state._global_error_suppressions[category] = True


def ResetNolintSuppressions():
    """Resets the set of NOLINT suppressions to empty."""
    _cpplint_state._error_suppressions.clear()
    _cpplint_state._global_error_suppressions.clear()


def IsErrorSuppressedByNolint(category, linenum):
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
    return (_cpplint_state._global_error_suppressions.get(category, False) or
            linenum in _cpplint_state._error_suppressions.get(category, set()) or
            linenum in _cpplint_state._error_suppressions.get(None, set()))

_cpplint_state = _CppLintState()

class _IncludeError(Exception):
    """Indicates a problem with the include order in a file."""
    pass

def _ShouldPrintError(state: _CppLintState, category, confidence, linenum):
    """If confidence >= verbose, category passes filter and is not suppressed."""

    # There are three ways we might decide not to print an error message:
    # a "NOLINT(category)" comment appears in the source,
    # the verbosity level isn't high enough, or the filters filter it out.
    if IsErrorSuppressedByNolint(category, linenum):
        return False

    if confidence < _cpplint_state.verbose_level:
        return False

    is_filtered = False
    for one_filter in state.filters:
        if one_filter.startswith('-'):
            if category.startswith(one_filter[1:]):
                is_filtered = True
        elif one_filter.startswith('+'):
            if category.startswith(one_filter[1:]):
                is_filtered = False
        else:
            raise ValueError(f"Filters must start with '+' or '-', {one_filter} does not.")
    if is_filtered:
        return False

    return True


def Error(filename, linenum, category, confidence, message):
    """Logs the fact we've found a lint error.

    We log where the error was found, and also our confidence in the error,
    that is, how certain we are this is a legitimate style regression, and
    not a misidentification or a use that's sometimes justified.

    False positives can be suppressed by the use of
    "cpplint(category)"  comments on the offending line.  These are
    parsed into _error_suppressions.

    Args:
      filename: The name of the file containing the error.
      linenum: The number of the line containing the error.
      category: A string used to describe the "category" this bug
        falls under: "whitespace", say, or "runtime".  Categories
        may have a hierarchy separated by slashes: "whitespace/indent".
      confidence: A number from 1-5 representing a confidence score for
        the error, with 5 meaning that we are certain of the problem,
        and 1 meaning that it could be a legitimate construct.
      message: The error message.
    """
    if _ShouldPrintError(_cpplint_state, category, confidence, linenum):
        _cpplint_state.IncrementErrorCount(category)
        if _cpplint_state.output_format == 'vs7':
            _cpplint_state.PrintError('%s(%s): error cpplint: [%s] %s [%d]\n' % (
                filename, linenum, category, message, confidence))
        elif _cpplint_state.output_format == 'eclipse':
            sys.stderr.write('%s:%s: warning: %s  [%s] [%d]\n' % (
                filename, linenum, message, category, confidence))
        elif _cpplint_state.output_format == 'junit':
            _cpplint_state.AddJUnitFailure(filename, linenum, message, category,
                confidence)
        elif _cpplint_state.output_format in ['sed', 'gsed']:
            if message in _SED_FIXUPS:
                sys.stdout.write(_cpplint_state.output_format + " -i '%s%s' %s # %s  [%s] [%d]\n" % (
                    linenum, _SED_FIXUPS[message], filename, message, category, confidence))
            else:
                sys.stderr.write('# %s:%s:  "%s"  [%s] [%d]\n' % (
                    filename, linenum, message, category, confidence))
        else:
            final_message = '%s:%s:  %s  [%s] [%d]\n' % (
                filename, linenum, message, category, confidence)
            sys.stderr.write(final_message)



def FindNextMultiLineCommentStart(lines, lineix):
    """Find the beginning marker for a multiline comment."""
    while lineix < len(lines):
        if lines[lineix].strip().startswith('/*'):
            # Only return this marker if the comment goes beyond this line
            if lines[lineix].strip().find('*/', 2) < 0:
                return lineix
        lineix += 1
    return len(lines)


def FindNextMultiLineCommentEnd(lines, lineix):
    """We are inside a comment, find the end marker."""
    while lineix < len(lines):
        if lines[lineix].strip().endswith('*/'):
            return lineix
        lineix += 1
    return len(lines)


def RemoveMultiLineCommentsFromRange(lines, begin, end):
    """Clears a range of lines for multi-line comments."""
    # Having // <empty> comments makes the lines non-empty, so we will not get
    # unnecessary blank line warnings later in the code.
    for i in range(begin, end):
        lines[i] = '/**/'


def RemoveMultiLineComments(filename, lines, error):
    """Removes multiline (c-style) comments from lines."""
    lineix = 0
    while lineix < len(lines):
        lineix_begin = FindNextMultiLineCommentStart(lines, lineix)
        if lineix_begin >= len(lines):
            return
        lineix_end = FindNextMultiLineCommentEnd(lines, lineix_begin)
        if lineix_end >= len(lines):
            error(filename, lineix_begin + 1, 'readability/multiline_comment', 5,
                  'Could not find end of multi-line comment')
            return
        RemoveMultiLineCommentsFromRange(lines, lineix_begin, lineix_end + 1)
        lineix = lineix_end + 1


def FindStartOfExpressionInLine(line, endpos, stack):
    """Find position at the matching start of current expression.

    This is almost the reverse of FindEndOfExpressionInLine, but note
    that the input position and returned position differs by 1.

    Args:
      line: a CleansedLines line.
      endpos: start searching at this position.
      stack: nesting stack at endpos.

    Returns:
      On finding matching start: (index at matching start, None)
      On finding an unclosed expression: (-1, None)
      Otherwise: (-1, new stack at beginning of this line)
    """
    i = endpos
    while i >= 0:
        char = line[i]
        if char in ')]}':
            # Found end of expression, push to expression stack
            stack.append(char)
        elif char == '>':
            # Found potential end of template argument list.
            #
            # Ignore it if it's a "->" or ">=" or "operator>"
            if (i > 0 and
                (line[i - 1] == '-' or
                 Match(r'\s>=\s', line[i - 1:]) or
                 Search(r'\boperator\s*$', line[0:i]))):
                i -= 1
            else:
                stack.append('>')
        elif char == '<':
            # Found potential start of template argument list
            if i > 0 and line[i - 1] == '<':
                # Left shift operator
                i -= 1
            else:
                # If there is a matching '>', we can pop the expression stack.
                # Otherwise, ignore this '<' since it must be an operator.
                if stack and stack[-1] == '>':
                    stack.pop()
                    if not stack:
                        return (i, None)
        elif char in '([{':
            # Found start of expression.
            #
            # If there are any unmatched '>' on the stack, they must be
            # operators.  Remove those.
            while stack and stack[-1] == '>':
                stack.pop()
            if not stack:
                return (-1, None)
            if ((char == '(' and stack[-1] == ')') or
                (char == '[' and stack[-1] == ']') or
                (char == '{' and stack[-1] == '}')):
                stack.pop()
                if not stack:
                    return (i, None)
            else:
                # Mismatched parentheses
                return (-1, None)
        elif char == ';':
            # Found something that look like end of statements.  If we are currently
            # expecting a '<', the matching '>' must have been an operator, since
            # template argument list should not contain statements.
            while stack and stack[-1] == '>':
                stack.pop()
            if not stack:
                return (-1, None)

        i -= 1

    return (-1, stack)



def CheckForCopyright(filename, lines, error):
    """Logs an error if no Copyright message appears at the top of the file."""

    # We'll say it should occur by line 10. Don't forget there's a
    # placeholder line at the front.
    for line in range(1, min(len(lines), 11)):
        if re.search(r'Copyright', lines[line], re.I): break
    else:                       # means no copyright line was found
        error(filename, 0, 'legal/copyright', 5,
              'No copyright message found.  '
              'You should have a line: "Copyright [year] <Copyright Owner>"')


def GetIndentLevel(line):
    """Return the number of leading spaces in line.

    Args:
      line: A string to check.

    Returns:
      An integer count of leading spaces, possibly zero.
    """
    indent = Match(r'^( *)\S', line)
    if indent:
        return len(indent.group(1))
    else:
        return 0


def CheckForHeaderGuard(filename, clean_lines, error):
    """Checks that the file contains a header guard.

    Logs an error if no #ifndef header guard is present.  For other
    headers, checks that the full pathname is used.

    Args:
      filename: The name of the C++ header file.
      clean_lines: A CleansedLines instance containing the file.
      error: The function to call with any errors found.
    """

    # Don't check for header guards if there are error suppression
    # comments somewhere in this file.
    #
    # Because this is silencing a warning for a nonexistent line, we
    # only support the very specific NOLINT(build/header_guard) syntax,
    # and not the general NOLINT or NOLINT(*) syntax.
    raw_lines = clean_lines.lines_without_raw_strings
    for i in raw_lines:
        if Search(r'//\s*NOLINT\(build/header_guard\)', i):
            return

    # Allow pragma once instead of header guards
    for i in raw_lines:
        if Search(r'^\s*#pragma\s+once', i):
            return

    cppvar = GetHeaderGuardCPPVariable(_cpplint_state, filename)

    ifndef = ''
    ifndef_linenum = 0
    define = ''
    endif = ''
    endif_linenum = 0
    for linenum, line in enumerate(raw_lines):
        linesplit = line.split()
        if len(linesplit) >= 2:
            # find the first occurrence of #ifndef and #define, save arg
            if not ifndef and linesplit[0] == '#ifndef':
                # set ifndef to the header guard presented on the #ifndef line.
                ifndef = linesplit[1]
                ifndef_linenum = linenum
            if not define and linesplit[0] == '#define':
                define = linesplit[1]
        # find the last occurrence of #endif, save entire line
        if line.startswith('#endif'):
            endif = line
            endif_linenum = linenum

    if not ifndef or not define or ifndef != define:
        error(filename, 0, 'build/header_guard', 5,
              'No #ifndef header guard found, suggested CPP variable is: %s' %
              cppvar)
        return

    # The guard should be PATH_FILE_H_, but we also allow PATH_FILE_H__
    # for backward compatibility.
    if ifndef != cppvar:
        error_level = 0
        if ifndef != cppvar + '_':
            error_level = 5

        ParseNolintSuppressions(_cpplint_state, filename, raw_lines[ifndef_linenum], ifndef_linenum,
                                error)
        error(filename, ifndef_linenum, 'build/header_guard', error_level,
              '#ifndef header guard has wrong style, please use: %s' % cppvar)

    # Check for "//" comments on endif line.
    ParseNolintSuppressions(_cpplint_state, filename, raw_lines[endif_linenum], endif_linenum,
                            error)
    match = Match(r'#endif\s*//\s*' + cppvar + r'(_)?\b', endif)
    if match:
        if match.group(1) == '_':
            # Issue low severity warning for deprecated double trailing underscore
            error(filename, endif_linenum, 'build/header_guard', 0,
                  '#endif line should be "#endif  // %s"' % cppvar)
        return

    # Didn't find the corresponding "//" comment.  If this file does not
    # contain any "//" comments at all, it could be that the compiler
    # only wants "/**/" comments, look for those instead.
    no_single_line_comments = True
    for i in range(1, len(raw_lines) - 1):
        line = raw_lines[i]
        if Match(r'^(?:(?:\'(?:\.|[^\'])*\')|(?:"(?:\.|[^"])*")|[^\'"])*//', line):
            no_single_line_comments = False
            break

    if no_single_line_comments:
        match = Match(r'#endif\s*/\*\s*' + cppvar + r'(_)?\s*\*/', endif)
        if match:
            if match.group(1) == '_':
                # Low severity warning for double trailing underscore
                error(filename, endif_linenum, 'build/header_guard', 0,
                      '#endif line should be "#endif  /* %s */"' % cppvar)
            return

    # Didn't find anything
    error(filename, endif_linenum, 'build/header_guard', 5,
          '#endif line should be "#endif  // %s"' % cppvar)


def CheckHeaderFileIncluded(filename, include_state, error):
    """Logs an error if a source file does not include its header."""

    # Do not check test files
    fileinfo = FileInfo(filename)
    if Search(_TEST_FILE_SUFFIX, fileinfo.BaseName()):
        return

    for ext in _cpplint_state.GetHeaderExtensions():
        basefilename = filename[0:len(filename) - len(fileinfo.Extension())]
        headerfile = basefilename + '.' + ext
        if not os.path.exists(headerfile):
            continue
        headername = FileInfo(headerfile).RepositoryName(_cpplint_state._repository)
        first_include = None
        include_uses_unix_dir_aliases = False
        for section_list in include_state.include_list:
            for f in section_list:
                include_text = f[0]
                if "./" in include_text:
                    include_uses_unix_dir_aliases = True
                if headername in include_text or include_text in headername:
                    return
                if not first_include:
                    first_include = f[1]

        message = '%s should include its header file %s' % (fileinfo.RepositoryName(_cpplint_state._repository), headername)
        if include_uses_unix_dir_aliases:
            message += ". Relative paths like . and .. are not allowed."

        error(filename, first_include, 'build/include', 5, message)


def CheckForBadCharacters(filename, lines, error):
    """Logs an error for each line containing bad characters.

    Two kinds of bad characters:

    1. str replacement characters: These indicate that either the file
    contained invalid UTF-8 (likely) or str replacement characters (which
    it shouldn't).  Note that it's possible for this to throw off line
    numbering if the invalid UTF-8 occurred adjacent to a newline.

    2. NUL bytes.  These are problematic for some tools.

    Args:
      filename: The name of the current file.
      lines: An array of strings, each representing a line of the file.
      error: The function to call with any errors found.
    """
    for linenum, line in enumerate(lines):
        if '\ufffd' in line:
            error(filename, linenum, 'readability/utf8', 5,
                  'Line contains invalid UTF-8 (or Unicode replacement character).')
        if '\0' in line:
            error(filename, linenum, 'readability/nul', 5, 'Line contains NUL byte.')


def CheckForNewlineAtEOF(filename, lines, error):
    """Logs an error if there is no newline char at the end of the file.

    Args:
      filename: The name of the current file.
      lines: An array of strings, each representing a line of the file.
      error: The function to call with any errors found.
    """

    # The array lines() was created by adding two newlines to the
    # original file (go figure), then splitting on \n.
    # To verify that the file ends in \n, we just have to make sure the
    # last-but-two element of lines() exists and is empty.
    if len(lines) < 3 or lines[-2]:
        error(filename, len(lines) - 2, 'whitespace/ending_newline', 5,
              'Could not find a newline character at the end of the file.')



# (non-threadsafe name, thread-safe alternative, validation pattern)
#
# The validation pattern is used to eliminate false positives such as:
#  _rand();               // false positive due to substring match.
#  ->rand();              // some member function rand().
#  ACMRandom rand(seed);  // some variable named rand.
#  ISAACRandom rand();    // another variable named rand.
#
# Basically we require the return value of these functions to be used
# in some expression context on the same line by matching on some
# operator before the function name.  This eliminates constructors and
# member function calls.
_UNSAFE_FUNC_PREFIX = r'(?:[-+*/=%^&|(<]\s*|>\s+)'
_THREADING_LIST = (
    ('asctime(', 'asctime_r(', _UNSAFE_FUNC_PREFIX + r'asctime\([^)]+\)'),
    ('ctime(', 'ctime_r(', _UNSAFE_FUNC_PREFIX + r'ctime\([^)]+\)'),
    ('getgrgid(', 'getgrgid_r(', _UNSAFE_FUNC_PREFIX + r'getgrgid\([^)]+\)'),
    ('getgrnam(', 'getgrnam_r(', _UNSAFE_FUNC_PREFIX + r'getgrnam\([^)]+\)'),
    ('getlogin(', 'getlogin_r(', _UNSAFE_FUNC_PREFIX + r'getlogin\(\)'),
    ('getpwnam(', 'getpwnam_r(', _UNSAFE_FUNC_PREFIX + r'getpwnam\([^)]+\)'),
    ('getpwuid(', 'getpwuid_r(', _UNSAFE_FUNC_PREFIX + r'getpwuid\([^)]+\)'),
    ('gmtime(', 'gmtime_r(', _UNSAFE_FUNC_PREFIX + r'gmtime\([^)]+\)'),
    ('localtime(', 'localtime_r(', _UNSAFE_FUNC_PREFIX + r'localtime\([^)]+\)'),
    ('rand(', 'rand_r(', _UNSAFE_FUNC_PREFIX + r'rand\(\)'),
    ('strtok(', 'strtok_r(',
     _UNSAFE_FUNC_PREFIX + r'strtok\([^)]+\)'),
    ('ttyname(', 'ttyname_r(', _UNSAFE_FUNC_PREFIX + r'ttyname\([^)]+\)'),
    )


def CheckPosixThreading(filename, clean_lines, linenum, error):
    """Checks for calls to thread-unsafe functions.

    Much code has been originally written without consideration of
    multi-threading. Also, engineers are relying on their old experience;
    they have learned posix before threading extensions were added. These
    tests guide the engineers to use thread-safe functions (when using
    posix directly).

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]
    for single_thread_func, multithread_safe_func, pattern in _THREADING_LIST:
        # Additional pattern matching check to confirm that this is the
        # function we are looking for
        if Search(pattern, line):
            error(filename, linenum, 'runtime/threadsafe_fn', 2,
                  'Consider using ' + multithread_safe_func +
                  '...) instead of ' + single_thread_func +
                  '...) for improved thread safety.')


def CheckVlogArguments(filename, clean_lines, linenum, error):
    """Checks that VLOG() is only used for defining a logging level.

    For example, VLOG(2) is correct. VLOG(INFO), VLOG(WARNING), VLOG(ERROR), and
    VLOG(FATAL) are not.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]
    if Search(r'\bVLOG\((INFO|ERROR|WARNING|DFATAL|FATAL)\)', line):
        error(filename, linenum, 'runtime/vlog', 5,
              'VLOG() should be used with numeric verbosity level.  '
              'Use LOG() if you want symbolic severity levels.')

# Matches invalid increment: *count++, which moves pointer instead of
# incrementing a value.
_RE_PATTERN_INVALID_INCREMENT = re.compile(
    r'^\s*\*\w+(\+\+|--);')


def CheckInvalidIncrement(filename, clean_lines, linenum, error):
    """Checks for invalid increment *count++.

    For example following function:
    void increment_counter(int* count) {
      *count++;
    }
    is invalid, because it effectively does count++, moving pointer, and should
    be replaced with ++*count, (*count)++ or *count += 1.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]
    if _RE_PATTERN_INVALID_INCREMENT.match(line):
        error(filename, linenum, 'runtime/invalid_increment', 5,
              'Changing pointer instead of value (or unused value of operator*).')


def IsMacroDefinition(clean_lines, linenum):
    if Search(r'^#define', clean_lines[linenum]):
        return True

    if linenum > 0 and Search(r'\\$', clean_lines[linenum - 1]):
        return True

    return False


def IsForwardClassDeclaration(clean_lines, linenum):
    return Match(r'^\s*(\btemplate\b)*.*class\s+\w+;\s*$', clean_lines[linenum])


def CheckForNonStandardConstructs(filename, clean_lines, linenum,
                                  nesting_state, error):
    r"""Logs an error if we see certain non-ANSI constructs ignored by gcc-2.

    Complain about several constructs which gcc-2 accepts, but which are
    not standard C++.  Warning about these in lint is one way to ease the
    transition to new compilers.
    - put storage class first (e.g. "static const" instead of "const static").
    - "%lld" instead of %qd" in printf-type functions.
    - "%1$d" is non-standard in printf-type functions.
    - "\%" is an undefined character escape sequence.
    - text after #endif is not allowed.
    - invalid inner-style forward declaration.
    - >? and <? operators, and their >?= and <?= cousins.

    Additionally, check for constructor/destructor style violations and reference
    members, as it is very convenient to do so while checking for
    gcc-2 compliance.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: A callable to which errors are reported, which takes 4 arguments:
             filename, line number, error level, and message
    """

    # Remove comments from the line, but leave in strings for now.
    line = clean_lines.lines[linenum]

    if Search(r'printf\s*\(.*".*%[-+ ]?\d*q', line):
        error(filename, linenum, 'runtime/printf_format', 3,
              '%q in format strings is deprecated.  Use %ll instead.')

    if Search(r'printf\s*\(.*".*%\d+\$', line):
        error(filename, linenum, 'runtime/printf_format', 2,
              '%N$ formats are unconventional.  Try rewriting to avoid them.')

    # Remove escaped backslashes before looking for undefined escapes.
    line = line.replace('\\\\', '')

    if Search(r'("|\').*\\(%|\[|\(|{)', line):
        error(filename, linenum, 'build/printf_format', 3,
              '%, [, (, and { are undefined character escapes.  Unescape them.')

    # For the rest, work with both comments and strings removed.
    line = clean_lines.elided[linenum]

    if Search(r'\b(const|volatile|void|char|short|int|int'
              r'|float|double|signed|unsigned'
              r'|schar|u?int8|u?int16|u?int32|u?int64)'
              r'\s+(register|static|extern|typedef)\b',
              line):
        error(filename, linenum, 'build/storage_class', 5,
              'Storage-class specifier (static, extern, typedef, etc) should be '
              'at the beginning of the declaration.')

    if Match(r'\s*#\s*endif\s*[^/\s]+', line):
        error(filename, linenum, 'build/endif_comment', 5,
              'Uncommented text after #endif is non-standard.  Use a comment.')

    if Match(r'\s*class\s+(\w+\s*::\s*)+\w+\s*;', line):
        error(filename, linenum, 'build/forward_decl', 5,
              'Inner-style forward declarations are invalid.  Remove this line.')

    if Search(r'(\w+|[+-]?\d+(\.\d*)?)\s*(<|>)\?=?\s*(\w+|[+-]?\d+)(\.\d*)?',
              line):
        error(filename, linenum, 'build/deprecated', 3,
              '>? and <? (max and min) operators are non-standard and deprecated.')

    if Search(r'^\s*const\s*string\s*&\s*\w+\s*;', line):
        # TODO(unknown): Could it be expanded safely to arbitrary references,
        # without triggering too many false positives? The first
        # attempt triggered 5 warnings for mostly benign code in the regtest, hence
        # the restriction.
        # Here's the original regexp, for the reference:
        # type_name = r'\w+((\s*::\s*\w+)|(\s*<\s*\w+?\s*>))?'
        # r'\s*const\s*' + type_name + '\s*&\s*\w+\s*;'
        error(filename, linenum, 'runtime/member_string_references', 2,
              'const string& members are dangerous. It is much better to use '
              'alternatives, such as pointers or simple constants.')

    # Everything else in this function operates on class declarations.
    # Return early if the top of the nesting stack is not a class, or if
    # the class head is not completed yet.
    classinfo = nesting_state.InnermostClass()
    if not classinfo or not classinfo.seen_open_brace:
        return

    # The class may have been declared with namespace or classname qualifiers.
    # The constructor and destructor will not have those qualifiers.
    base_classname = classinfo.name.split('::')[-1]

    # Look for single-argument constructors that aren't marked explicit.
    # Technically a valid construct, but against style.
    explicit_constructor_match = Match(
        r'\s+(?:(?:inline|constexpr)\s+)*(explicit\s+)?'
        r'(?:(?:inline|constexpr)\s+)*%s\s*'
        r'\(((?:[^()]|\([^()]*\))*)\)'
        % re.escape(base_classname),
        line)

    if explicit_constructor_match:
        is_marked_explicit = explicit_constructor_match.group(1)

        if not explicit_constructor_match.group(2):
            constructor_args = []
        else:
            constructor_args = explicit_constructor_match.group(2).split(',')

        # collapse arguments so that commas in template parameter lists and function
        # argument parameter lists don't split arguments in two
        i = 0
        while i < len(constructor_args):
            constructor_arg = constructor_args[i]
            while (constructor_arg.count('<') > constructor_arg.count('>') or
                   constructor_arg.count('(') > constructor_arg.count(')')):
                constructor_arg += ',' + constructor_args[i + 1]
                del constructor_args[i + 1]
            constructor_args[i] = constructor_arg
            i += 1

        variadic_args = [arg for arg in constructor_args if '&&...' in arg]
        defaulted_args = [arg for arg in constructor_args if '=' in arg]
        noarg_constructor = (not constructor_args or  # empty arg list
                             # 'void' arg specifier
                             (len(constructor_args) == 1 and
                              constructor_args[0].strip() == 'void'))
        onearg_constructor = ((len(constructor_args) == 1 and  # exactly one arg
                               not noarg_constructor) or
                              # all but at most one arg defaulted
                              (len(constructor_args) >= 1 and
                               not noarg_constructor and
                               len(defaulted_args) >= len(constructor_args) - 1) or
                              # variadic arguments with zero or one argument
                              (len(constructor_args) <= 2 and
                               len(variadic_args) >= 1))
        initializer_list_constructor = bool(
            onearg_constructor and
            Search(r'\bstd\s*::\s*initializer_list\b', constructor_args[0]))
        copy_constructor = bool(
            onearg_constructor and
            Match(r'((const\s+(volatile\s+)?)?|(volatile\s+(const\s+)?))?'
                  r'%s(\s*<[^>]*>)?(\s+const)?\s*(?:<\w+>\s*)?&'
                  % re.escape(base_classname), constructor_args[0].strip()))

        if (not is_marked_explicit and
            onearg_constructor and
            not initializer_list_constructor and
            not copy_constructor):
            if defaulted_args or variadic_args:
                error(filename, linenum, 'runtime/explicit', 5,
                      'Constructors callable with one argument '
                      'should be marked explicit.')
            else:
                error(filename, linenum, 'runtime/explicit', 5,
                      'Single-parameter constructors should be marked explicit.')
        elif is_marked_explicit and not onearg_constructor:
            if noarg_constructor:
                error(filename, linenum, 'runtime/explicit', 5,
                      'Zero-parameter constructors should not be marked explicit.')


from .check_lines import (
    ParseNolintSuppressions,
    CheckForNamespaceIndentation,
    CheckForFunctionLengths,
    CheckForMultilineCommentsAndStrings
)

def ProcessLine(state: _CppLintState,filename, file_extension, clean_lines, line,
                include_state, function_state, nesting_state, error,
                extra_check_functions=None):
    """Processes a single line in the file.

    Args:
      filename: Filename of the file that is being processed.
      file_extension: The extension (dot not included) of the file.
      clean_lines: An array of strings, each representing a line of the file,
                   with comments stripped.
      line: Number of line being processed.
      include_state: An _IncludeState instance in which the headers are inserted.
      function_state: A _FunctionState instance which counts function lines, etc.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: A callable to which errors are reported, which takes 4 arguments:
             filename, line number, error level, and message
      extra_check_functions: An array of additional check functions that will be
                             run on each source line. Each function takes 4
                             arguments: filename, clean_lines, line, error
    """
    raw_lines = clean_lines.raw_lines
    ParseNolintSuppressions(state, filename, raw_lines[line], line, error)
    nesting_state.Update(filename, clean_lines, line, error)
    CheckForNamespaceIndentation(filename, nesting_state, clean_lines, line,
                                 error)
    if nesting_state.InAsmBlock(): return
    CheckForFunctionLengths(state, filename, clean_lines, line, function_state, error)
    CheckForMultilineCommentsAndStrings(filename, clean_lines, line, error)
    CheckStyle(state, filename, clean_lines, line, file_extension, nesting_state, error)
    CheckLanguage(filename, clean_lines, line, file_extension, include_state,
                  nesting_state, error)
    CheckForNonConstReference(filename, clean_lines, line, nesting_state, error)
    CheckForNonStandardConstructs(filename, clean_lines, line,
                                  nesting_state, error)
    CheckVlogArguments(filename, clean_lines, line, error)
    CheckPosixThreading(filename, clean_lines, line, error)
    CheckInvalidIncrement(filename, clean_lines, line, error)
    CheckMakePairUsesDeduction(filename, clean_lines, line, error)
    CheckRedundantVirtual(filename, clean_lines, line, error)
    CheckRedundantOverrideOrFinal(filename, clean_lines, line, error)
    if extra_check_functions:
        for check_fn in extra_check_functions:
            check_fn(filename, clean_lines, line, error)


def IsDecltype(clean_lines, linenum, column):
    """Check if the token ending on (linenum, column) is decltype().

    Args:
      clean_lines: A CleansedLines instance containing the file.
      linenum: the number of the line to check.
      column: end column of the token to check.
    Returns:
      True if this token is decltype() expression, False otherwise.
    """
    (text, _, start_col) = ReverseCloseExpression(clean_lines, linenum, column)
    if start_col < 0:
        return False
    if Search(r'\bdecltype\s*$', text[0:start_col]):
        return True
    return False





def CheckIncludeLine(filename, clean_lines, linenum, include_state, error):
    """Check rules that are applicable to #include lines.

    Strings on #include lines are NOT removed from elided line, to make
    certain tasks easier. However, to prevent false positives, checks
    applicable to #include lines in CheckLanguage must be put here.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      include_state: An _IncludeState instance in which the headers are inserted.
      error: The function to call with any errors found.
    """
    fileinfo = FileInfo(filename)
    line = clean_lines.lines[linenum]

    # "include" should use the new style "foo/bar.h" instead of just "bar.h"
    # Only do this check if the included header follows google naming
    # conventions.  If not, assume that it's a 3rd party API that
    # requires special include conventions.
    #
    # We also make an exception for Lua headers, which follow google
    # naming convention but not the include convention.
    match = Match(r'#include\s*"([^/]+\.(.*))"', line)
    if match:
        if (_cpplint_state.IsHeaderExtension(match.group(2)) and
            not _THIRD_PARTY_HEADERS_PATTERN.match(match.group(1))):
            error(filename, linenum, 'build/include_subdir', 4,
                  'Include the directory when naming header files')

    # we shouldn't include a file more than once. actually, there are a
    # handful of instances where doing so is okay, but in general it's
    # not.
    match = _RE_PATTERN_INCLUDE.search(line)
    if match:
        include = match.group(2)
        used_angle_brackets = (match.group(1) == '<')
        duplicate_line = include_state.FindHeader(include)
        if duplicate_line >= 0:
            error(filename, linenum, 'build/include', 4,
                  '"%s" already included at %s:%s' %
                  (include, filename, duplicate_line))
            return

        for extension in _cpplint_state.GetNonHeaderExtensions():
            if (include.endswith('.' + extension) and
                os.path.dirname(fileinfo.RepositoryName(_cpplint_state._repository)) != os.path.dirname(include)):
                error(filename, linenum, 'build/include', 4,
                      'Do not include .' + extension + ' files from other packages')
                return

        # We DO want to include a 3rd party looking header if it matches the
        # filename. Otherwise we get an erroneous error "...should include its
        # header" error later.
        third_src_header = False
        for ext in _cpplint_state.GetHeaderExtensions():
            basefilename = filename[0:len(filename) - len(fileinfo.Extension())]
            headerfile = basefilename + '.' + ext
            headername = FileInfo(headerfile).RepositoryName(_cpplint_state._repository)
            if headername in include or include in headername:
                third_src_header = True
                break

        if third_src_header or not _THIRD_PARTY_HEADERS_PATTERN.match(include):
            include_state.include_list[-1].append((include, linenum))

            # We want to ensure that headers appear in the right order:
            # 1) for foo.cc, foo.h  (preferred location)
            # 2) c system files
            # 3) cpp system files
            # 4) for foo.cc, foo.h  (deprecated location)
            # 5) other google headers
            #
            # We classify each include statement as one of those 5 types
            # using a number of techniques. The include_state object keeps
            # track of the highest type seen, and complains if we see a
            # lower type after that.
            error_message = include_state.CheckNextIncludeOrder(
                _ClassifyInclude(_cpplint_state, fileinfo, include, used_angle_brackets, _cpplint_state._include_order))
            if error_message:
                error(filename, linenum, 'build/include_order', 4,
                      '%s. Should be: %s.h, c system, c++ system, other.' %
                      (error_message, fileinfo.BaseName()))
            canonical_include = include_state.CanonicalizeAlphabeticalOrder(include)
            if not include_state.IsInAlphabeticalOrder(
                clean_lines, linenum, canonical_include):
                error(filename, linenum, 'build/include_alpha', 4,
                      'Include "%s" not in alphabetical order' % include)
            include_state.SetLastHeader(canonical_include)



def _GetTextInside(text, start_pattern):
    r"""Retrieves all the text between matching open and close parentheses.

    Given a string of lines and a regular expression string, retrieve all the text
    following the expression and between opening punctuation symbols like
    (, [, or {, and the matching close-punctuation symbol. This properly nested
    occurrences of the punctuations, so for the text like
      printf(a(), b(c()));
    a call to _GetTextInside(text, r'printf\(') will return 'a(), b(c())'.
    start_pattern must match string having an open punctuation symbol at the end.

    Args:
      text: The lines to extract text. Its comments and strings must be elided.
             It can be single line and can span multiple lines.
      start_pattern: The regexp string indicating where to start extracting
                     the text.
    Returns:
      The extracted text.
      None if either the opening string or ending punctuation could not be found.
    """
    # TODO(unknown): Audit cpplint.py to see what places could be profitably
    # rewritten to use _GetTextInside (and use inferior regexp matching today).

    # Give opening punctuations to get the matching close-punctuations.
    matching_punctuation = {'(': ')', '{': '}', '[': ']'}
    closing_punctuation = set(matching_punctuation.values())

    # Find the position to start extracting text.
    match = re.search(start_pattern, text, re.M)
    if not match:  # start_pattern not found in text.
        return None
    start_position = match.end(0)

    assert start_position > 0, (
        'start_pattern must ends with an opening punctuation.')
    assert text[start_position - 1] in matching_punctuation, (
        'start_pattern must ends with an opening punctuation.')
    # Stack of closing punctuations we expect to have in text after position.
    punctuation_stack = [matching_punctuation[text[start_position - 1]]]
    position = start_position
    while punctuation_stack and position < len(text):
        if text[position] == punctuation_stack[-1]:
            punctuation_stack.pop()
        elif text[position] in closing_punctuation:
            # A closing punctuation without matching opening punctuations.
            return None
        elif text[position] in matching_punctuation:
            punctuation_stack.append(matching_punctuation[text[position]])
        position += 1
    if punctuation_stack:
        # Opening punctuations left without matching close-punctuations.
        return None
    # punctuations match.
    return text[start_position:position - 1]


# Patterns for matching call-by-reference parameters.
#
# Supports nested templates up to 2 levels deep using this messy pattern:
#   < (?: < (?: < [^<>]*
#               >
#           |   [^<>] )*
#         >
#     |   [^<>] )*
#   >
_RE_PATTERN_IDENT = r'[_a-zA-Z]\w*'  # =~ [[:alpha:]][[:alnum:]]*
_RE_PATTERN_TYPE = (
    r'(?:const\s+)?(?:typename\s+|class\s+|struct\s+|union\s+|enum\s+)?'
    r'(?:\w|'
    r'\s*<(?:<(?:<[^<>]*>|[^<>])*>|[^<>])*>|'
    r'::)+')
# A call-by-reference parameter ends with '& identifier'.
_RE_PATTERN_REF_PARAM = re.compile(
    r'(' + _RE_PATTERN_TYPE + r'(?:\s*(?:\bconst\b|[*]))*\s*'
    r'&\s*' + _RE_PATTERN_IDENT + r')\s*(?:=[^,()]+)?[,)]')
# A call-by-const-reference parameter either ends with 'const& identifier'
# or looks like 'const type& identifier' when 'type' is atomic.
_RE_PATTERN_CONST_REF_PARAM = (
    r'(?:.*\s*\bconst\s*&\s*' + _RE_PATTERN_IDENT +
    r'|const\s+' + _RE_PATTERN_TYPE + r'\s*&\s*' + _RE_PATTERN_IDENT + r')')
# Stream types.
_RE_PATTERN_REF_STREAM_PARAM = (
    r'(?:.*stream\s*&\s*' + _RE_PATTERN_IDENT + r')')


def CheckLanguage(filename, clean_lines, linenum, file_extension,
                  include_state, nesting_state, error):
    """Checks rules from the 'C++ language rules' section of cppguide.html.

    Some of these rules are hard to test (function overloading, using
    uint32 inappropriately), but we do the best we can.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      file_extension: The extension (without the dot) of the filename.
      include_state: An _IncludeState instance in which the headers are inserted.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: The function to call with any errors found.
    """
    # If the line is empty or consists of entirely a comment, no need to
    # check it.
    line = clean_lines.elided[linenum]
    if not line:
        return

    match = _RE_PATTERN_INCLUDE.search(line)
    if match:
        CheckIncludeLine(filename, clean_lines, linenum, include_state, error)
        return

    # Reset include state across preprocessor directives.  This is meant
    # to silence warnings for conditional includes.
    match = Match(r'^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b', line)
    if match:
        include_state.ResetSection(match.group(1))


    # Perform other checks now that we are sure that this is not an include line
    CheckCasts(filename, clean_lines, linenum, error)
    CheckGlobalStatic(filename, clean_lines, linenum, error)
    CheckPrintf(filename, clean_lines, linenum, error)

    if _cpplint_state.IsHeaderExtension(file_extension):
        # TODO(unknown): check that 1-arg constructors are explicit.
        #                How to tell it's a constructor?
        #                (handled in CheckForNonStandardConstructs for now)
        # TODO(unknown): check that classes declare or disable copy/assign
        #                (level 1 error)
        pass

    # Check if people are using the verboten C basic types.  The only exception
    # we regularly allow is "unsigned short port" for port.
    if Search(r'\bshort port\b', line):
        if not Search(r'\bunsigned short port\b', line):
            error(filename, linenum, 'runtime/int', 4,
                  'Use "unsigned short" for ports, not "short"')
    else:
        match = Search(r'\b(short|long(?! +double)|long long)\b', line)
        if match:
            error(filename, linenum, 'runtime/int', 4,
                  'Use int16/int64/etc, rather than the C type %s' % match.group(1))

    # Check if some verboten operator overloading is going on
    # TODO(unknown): catch out-of-line unary operator&:
    #   class X {};
    #   int operator&(const X& x) { return 42; }  // unary operator&
    # The trick is it's hard to tell apart from binary operator&:
    #   class Y { int operator&(const Y& x) { return 23; } }; // binary operator&
    if Search(r'\boperator\s*&\s*\(\s*\)', line):
        error(filename, linenum, 'runtime/operator', 4,
              'Unary operator& is dangerous.  Do not use it.')

    # Check for suspicious usage of "if" like
    # } if (a == b) {
    if Search(r'\}\s*if\s*\(', line):
        error(filename, linenum, 'readability/braces', 4,
              'Did you mean "else if"? If not, start a new line for "if".')

    # Check for potential format string bugs like printf(foo).
    # We constrain the pattern not to pick things like DocidForPrintf(foo).
    # Not perfect but it can catch printf(foo.c_str()) and printf(foo->c_str())
    # TODO(unknown): Catch the following case. Need to change the calling
    # convention of the whole function to process multiple line to handle it.
    #   printf(
    #       boy_this_is_a_really_int_variable_that_cannot_fit_on_the_prev_line);
    printf_args = _GetTextInside(line, r'(?i)\b(string)?printf\s*\(')
    if printf_args:
        match = Match(r'([\w.\->()]+)$', printf_args)
        if match and match.group(1) != '__VA_ARGS__':
            function_name = re.search(r'\b((?:string)?printf)\s*\(',
                                      line, re.I).group(1)
            error(filename, linenum, 'runtime/printf', 4,
                  'Potential format string bug. Do %s("%%s", %s) instead.'
                  % (function_name, match.group(1)))

    # Check for potential memset bugs like memset(buf, sizeof(buf), 0).
    match = Search(r'memset\s*\(([^,]*),\s*([^,]*),\s*0\s*\)', line)
    if match and not Match(r"^''|-?[0-9]+|0x[0-9A-Fa-f]$", match.group(2)):
        error(filename, linenum, 'runtime/memset', 4,
              'Did you mean "memset(%s, 0, %s)"?'
              % (match.group(1), match.group(2)))

    if Search(r'\busing namespace\b', line):
        if Search(r'\bliterals\b', line):
            error(filename, linenum, 'build/namespaces_literals', 5,
                  'Do not use namespace using-directives.  '
                  'Use using-declarations instead.')
        else:
            error(filename, linenum, 'build/namespaces', 5,
                  'Do not use namespace using-directives.  '
                  'Use using-declarations instead.')

    # Detect variable-length arrays.
    match = Match(r'\s*(.+::)?(\w+) [a-z]\w*\[(.+)];', line)
    if (match and match.group(2) != 'return' and match.group(2) != 'delete' and
        match.group(3).find(']') == -1):
        # Split the size using space and arithmetic operators as delimiters.
        # If any of the resulting tokens are not compile time constants then
        # report the error.
        tokens = re.split(r'\s|\+|\-|\*|\/|<<|>>]', match.group(3))
        is_const = True
        skip_next = False
        for tok in tokens:
            if skip_next:
                skip_next = False
                continue

            if Search(r'sizeof\(.+\)', tok): continue
            if Search(r'arraysize\(\w+\)', tok): continue

            tok = tok.lstrip('(')
            tok = tok.rstrip(')')
            if not tok: continue
            if Match(r'\d+', tok): continue
            if Match(r'0[xX][0-9a-fA-F]+', tok): continue
            if Match(r'k[A-Z0-9]\w*', tok): continue
            if Match(r'(.+::)?k[A-Z0-9]\w*', tok): continue
            if Match(r'(.+::)?[A-Z][A-Z0-9_]*', tok): continue
            # A catch all for tricky sizeof cases, including 'sizeof expression',
            # 'sizeof(*type)', 'sizeof(const type)', 'sizeof(struct StructName)'
            # requires skipping the next token because we split on ' ' and '*'.
            if tok.startswith('sizeof'):
                skip_next = True
                continue
            is_const = False
            break
        if not is_const:
            error(filename, linenum, 'runtime/arrays', 1,
                  'Do not use variable-length arrays.  Use an appropriately named '
                  "('k' followed by CamelCase) compile-time constant for the size.")

    # Check for use of unnamed namespaces in header files.  Registration
    # macros are typically OK, so we allow use of "namespace {" on lines
    # that end with backslashes.
    if (_cpplint_state.IsHeaderExtension(file_extension)
        and Search(r'\bnamespace\s*{', line)
        and line[-1] != '\\'):
        error(filename, linenum, 'build/namespaces_headers', 4,
              'Do not use unnamed namespaces in header files.  See '
              'https://google-styleguide.googlecode.com/svn/trunk/cppguide.xml#Namespaces'
              ' for more information.')


def CheckGlobalStatic(filename, clean_lines, linenum, error):
    """Check for unsafe global or static objects.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # Match two lines at a time to support multiline declarations
    if linenum + 1 < clean_lines.NumLines() and not Search(r'[;({]', line):
        line += clean_lines.elided[linenum + 1].strip()

    # Check for people declaring static/global STL strings at the top level.
    # This is dangerous because the C++ language does not guarantee that
    # globals with constructors are initialized before the first access, and
    # also because globals can be destroyed when some threads are still running.
    # TODO(unknown): Generalize this to also find static unique_ptr instances.
    # TODO(unknown): File bugs for clang-tidy to find these.
    match = Match(
        r'((?:|static +)(?:|const +))(?::*std::)?string( +const)? +'
        r'([a-zA-Z0-9_:]+)\b(.*)',
        line)

    # Remove false positives:
    # - String pointers (as opposed to values).
    #    string *pointer
    #    const string *pointer
    #    string const *pointer
    #    string *const pointer
    #
    # - Functions and template specializations.
    #    string Function<Type>(...
    #    string Class<Type>::Method(...
    #
    # - Operators.  These are matched separately because operator names
    #   cross non-word boundaries, and trying to match both operators
    #   and functions at the same time would decrease accuracy of
    #   matching identifiers.
    #    string Class::operator*()
    if (match and
        not Search(r'\bstring\b(\s+const)?\s*[\*\&]\s*(const\s+)?\w', line) and
        not Search(r'\boperator\W', line) and
        not Match(r'\s*(<.*>)?(::[a-zA-Z0-9_]+)*\s*\(([^"]|$)', match.group(4))):
        if Search(r'\bconst\b', line):
            error(filename, linenum, 'runtime/string', 4,
                  'For a static/global string constant, use a C style string '
                  'instead: "%schar%s %s[]".' %
                  (match.group(1), match.group(2) or '', match.group(3)))
        else:
            error(filename, linenum, 'runtime/string', 4,
                  'Static/global string variables are not permitted.')

    if (Search(r'\b([A-Za-z0-9_]*_)\(\1\)', line) or
        Search(r'\b([A-Za-z0-9_]*_)\(CHECK_NOTNULL\(\1\)\)', line)):
        error(filename, linenum, 'runtime/init', 4,
              'You seem to be initializing a member variable with itself.')


def CheckPrintf(filename, clean_lines, linenum, error):
    """Check for printf related issues.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # When snprintf is used, the second argument shouldn't be a literal.
    match = Search(r'snprintf\s*\(([^,]*),\s*([0-9]*)\s*,', line)
    if match and match.group(2) != '0':
        # If 2nd arg is zero, snprintf is used to calculate size.
        error(filename, linenum, 'runtime/printf', 3,
              'If you can, use sizeof(%s) instead of %s as the 2nd arg '
              'to snprintf.' % (match.group(1), match.group(2)))

    # Check if some verboten C functions are being used.
    if Search(r'\bsprintf\s*\(', line):
        error(filename, linenum, 'runtime/printf', 5,
              'Never use sprintf. Use snprintf instead.')
    match = Search(r'\b(strcpy|strcat)\s*\(', line)
    if match:
        error(filename, linenum, 'runtime/printf', 4,
              'Almost always, snprintf is better than %s' % match.group(1))


def IsDerivedFunction(clean_lines, linenum):
    """Check if current line contains an inherited function.

    Args:
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
    Returns:
      True if current line contains a function with "override"
      virt-specifier.
    """
    # Scan back a few lines for start of current function
    for i in range(linenum, max(-1, linenum - 10), -1):
        match = Match(r'^([^()]*\w+)\(', clean_lines.elided[i])
        if match:
            # Look for "override" after the matching closing parenthesis
            line, _, closing_paren = CloseExpression(
                clean_lines, i, len(match.group(1)))
            return (closing_paren >= 0 and
                    Search(r'\boverride\b', line[closing_paren:]))
    return False


def IsOutOfLineMethodDefinition(clean_lines, linenum):
    """Check if current line contains an out-of-line method definition.

    Args:
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
    Returns:
      True if current line contains an out-of-line method definition.
    """
    # Scan back a few lines for start of current function
    for i in range(linenum, max(-1, linenum - 10), -1):
        if Match(r'^([^()]*\w+)\(', clean_lines.elided[i]):
            return Match(r'^[^()]*\w+::\w+\(', clean_lines.elided[i]) is not None
    return False


def IsInitializerList(clean_lines, linenum):
    """Check if current line is inside constructor initializer list.

    Args:
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
    Returns:
      True if current line appears to be inside constructor initializer
      list, False otherwise.
    """
    for i in range(linenum, 1, -1):
        line = clean_lines.elided[i]
        if i == linenum:
            remove_function_body = Match(r'^(.*)\{\s*$', line)
            if remove_function_body:
                line = remove_function_body.group(1)

        if Search(r'\s:\s*\w+[({]', line):
            # A lone colon tend to indicate the start of a constructor
            # initializer list.  It could also be a ternary operator, which
            # also tend to appear in constructor initializer lists as
            # opposed to parameter lists.
            return True
        if Search(r'\}\s*,\s*$', line):
            # A closing brace followed by a comma is probably the end of a
            # brace-initialized member in constructor initializer list.
            return True
        if Search(r'[{};]\s*$', line):
            # Found one of the following:
            # - A closing brace or semicolon, probably the end of the previous
            #   function.
            # - An opening brace, probably the start of current class or namespace.
            #
            # Current line is probably not inside an initializer list since
            # we saw one of those things without seeing the starting colon.
            return False

    # Got to the beginning of the file without seeing the start of
    # constructor initializer list.
    return False


def CheckForNonConstReference(filename, clean_lines, linenum,
                              nesting_state, error):
    """Check for non-const references.

    Separate from CheckLanguage since it scans backwards from current
    line, instead of scanning forward.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: The function to call with any errors found.
    """
    # Do nothing if there is no '&' on current line.
    line = clean_lines.elided[linenum]
    if '&' not in line:
        return

    # If a function is inherited, current function doesn't have much of
    # a choice, so any non-const references should not be blamed on
    # derived function.
    if IsDerivedFunction(clean_lines, linenum):
        return

    # Don't warn on out-of-line method definitions, as we would warn on the
    # in-line declaration, if it isn't marked with 'override'.
    if IsOutOfLineMethodDefinition(clean_lines, linenum):
        return

    # int type names may be broken across multiple lines, usually in one
    # of these forms:
    #   intType
    #       ::intTypeContinued &identifier
    #   intType::
    #       intTypeContinued &identifier
    #   intType<
    #       ...>::intTypeContinued &identifier
    #
    # If we detected a type split across two lines, join the previous
    # line to current line so that we can match const references
    # accordingly.
    #
    # Note that this only scans back one line, since scanning back
    # arbitrary number of lines would be expensive.  If you have a type
    # that spans more than 2 lines, please use a typedef.
    if linenum > 1:
        previous = None
        if Match(r'\s*::(?:[\w<>]|::)+\s*&\s*\S', line):
            # previous_line\n + ::current_line
            previous = Search(r'\b((?:const\s*)?(?:[\w<>]|::)+[\w<>])\s*$',
                              clean_lines.elided[linenum - 1])
        elif Match(r'\s*[a-zA-Z_]([\w<>]|::)+\s*&\s*\S', line):
            # previous_line::\n + current_line
            previous = Search(r'\b((?:const\s*)?(?:[\w<>]|::)+::)\s*$',
                              clean_lines.elided[linenum - 1])
        if previous:
            line = previous.group(1) + line.lstrip()
        else:
            # Check for templated parameter that is split across multiple lines
            endpos = line.rfind('>')
            if endpos > -1:
                (_, startline, startpos) = ReverseCloseExpression(
                    clean_lines, linenum, endpos)
                if startpos > -1 and startline < linenum:
                    # Found the matching < on an earlier line, collect all
                    # pieces up to current line.
                    line = ''
                    for i in range(startline, linenum + 1):
                        line += clean_lines.elided[i].strip()

    # Check for non-const references in function parameters.  A single '&' may
    # found in the following places:
    #   inside expression: binary & for bitwise AND
    #   inside expression: unary & for taking the address of something
    #   inside declarators: reference parameter
    # We will exclude the first two cases by checking that we are not inside a
    # function body, including one that was just introduced by a trailing '{'.
    # TODO(unknown): Doesn't account for 'catch(Exception& e)' [rare].
    if (nesting_state.previous_stack_top and
        not (isinstance(nesting_state.previous_stack_top, _ClassInfo) or
             isinstance(nesting_state.previous_stack_top, _NamespaceInfo))):
        # Not at toplevel, not within a class, and not within a namespace
        return

    # Avoid initializer lists.  We only need to scan back from the
    # current line for something that starts with ':'.
    #
    # We don't need to check the current line, since the '&' would
    # appear inside the second set of parentheses on the current line as
    # opposed to the first set.
    if linenum > 0:
        for i in range(linenum - 1, max(0, linenum - 10), -1):
            previous_line = clean_lines.elided[i]
            if not Search(r'[),]\s*$', previous_line):
                break
            if Match(r'^\s*:\s+\S', previous_line):
                return

    # Avoid preprocessors
    if Search(r'\\\s*$', line):
        return

    # Avoid constructor initializer lists
    if IsInitializerList(clean_lines, linenum):
        return

    # We allow non-const references in a few standard places, like functions
    # called "swap()" or iostream operators like "<<" or ">>".  Do not check
    # those function parameters.
    #
    # We also accept & in static_assert, which looks like a function but
    # it's actually a declaration expression.
    allowed_functions = (r'(?:[sS]wap(?:<\w:+>)?|'
                             r'operator\s*[<>][<>]|'
                             r'static_assert|COMPILE_ASSERT'
                             r')\s*\(')
    if Search(allowed_functions, line):
        return
    elif not Search(r'\S+\([^)]*$', line):
        # Don't see an allowed function on this line.  Actually we
        # didn't see any function name on this line, so this is likely a
        # multi-line parameter list.  Try a bit harder to catch this case.
        for i in range(2):
            if (linenum > i and
                Search(allowed_functions, clean_lines.elided[linenum - i - 1])):
                return

    decls = ReplaceAll(r'{[^}]*}', ' ', line)  # exclude function body
    for parameter in re.findall(_RE_PATTERN_REF_PARAM, decls):
        if (not Match(_RE_PATTERN_CONST_REF_PARAM, parameter) and
            not Match(_RE_PATTERN_REF_STREAM_PARAM, parameter)):
            error(filename, linenum, 'runtime/references', 2,
                  'Is this a non-const reference? '
                  'If so, make const or use a pointer: ' +
                  ReplaceAll(' *<', '<', parameter))


def CheckCasts(filename, clean_lines, linenum, error):
    """Various cast related checks.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # Check to see if they're using an conversion function cast.
    # I just try to capture the most common basic types, though there are more.
    # Parameterless conversion functions, such as bool(), are allowed as they are
    # probably a member operator declaration or default constructor.
    match = Search(
        r'(\bnew\s+(?:const\s+)?|\S<\s*(?:const\s+)?)?\b'
        r'(int|float|double|bool|char|int32|uint32|int64|uint64)'
        r'(\([^)].*)', line)
    expecting_function = ExpectingFunctionArgs(clean_lines, linenum)
    if match and not expecting_function:
        matched_type = match.group(2)

        # matched_new_or_template is used to silence two false positives:
        # - New operators
        # - Template arguments with function types
        #
        # For template arguments, we match on types immediately following
        # an opening bracket without any spaces.  This is a fast way to
        # silence the common case where the function type is the first
        # template argument.  False negative with less-than comparison is
        # avoided because those operators are usually followed by a space.
        #
        #   function<double(double)>   // bracket + no space = false positive
        #   value < double(42)         // bracket + space = true positive
        matched_new_or_template = match.group(1)

        # Avoid arrays by looking for brackets that come after the closing
        # parenthesis.
        if Match(r'\([^()]+\)\s*\[', match.group(3)):
            return

        # Other things to ignore:
        # - Function pointers
        # - Casts to pointer types
        # - Placement new
        # - Alias declarations
        matched_funcptr = match.group(3)
        if (matched_new_or_template is None and
            not (matched_funcptr and
                 (Match(r'\((?:[^() ]+::\s*\*\s*)?[^() ]+\)\s*\(',
                        matched_funcptr) or
                  matched_funcptr.startswith('(*)'))) and
            not Match(r'\s*using\s+\S+\s*=\s*' + matched_type, line) and
            not Search(r'new\(\S+\)\s*' + matched_type, line)):
            error(filename, linenum, 'readability/casting', 4,
                  'Using deprecated casting style.  '
                  'Use static_cast<%s>(...) instead' %
                  matched_type)

    if not expecting_function:
        CheckCStyleCast(filename, clean_lines, linenum, 'static_cast',
                        r'\((int|float|double|bool|char|u?int(16|32|64)|size_t)\)', error)

    # This doesn't catch all cases. Consider (const char * const)"hello".
    #
    # (char *) "foo" should always be a const_cast (reinterpret_cast won't
    # compile).
    if CheckCStyleCast(filename, clean_lines, linenum, 'const_cast',
                       r'\((char\s?\*+\s?)\)\s*"', error):
        pass
    else:
        # Check pointer casts for other than string constants
        CheckCStyleCast(filename, clean_lines, linenum, 'reinterpret_cast',
                        r'\((\w+\s?\*+\s?)\)', error)

    # In addition, we look for people taking the address of a cast.  This
    # is dangerous -- casts can assign to temporaries, so the pointer doesn't
    # point where you think.
    #
    # Some non-identifier character is required before the '&' for the
    # expression to be recognized as a cast.  These are casts:
    #   expression = &static_cast<int*>(temporary());
    #   function(&(int*)(temporary()));
    #
    # This is not a cast:
    #   reference_type&(int* function_param);
    match = Search(
        r'(?:[^\w]&\(([^)*][^)]*)\)[\w(])|'
        r'(?:[^\w]&(static|dynamic|down|reinterpret)_cast\b)', line)
    if match:
        # Try a better error message when the & is bound to something
        # dereferenced by the casted pointer, as opposed to the casted
        # pointer itself.
        parenthesis_error = False
        match = Match(r'^(.*&(?:static|dynamic|down|reinterpret)_cast\b)<', line)
        if match:
            _, y1, x1 = CloseExpression(clean_lines, linenum, len(match.group(1)))
            if x1 >= 0 and clean_lines.elided[y1][x1] == '(':
                _, y2, x2 = CloseExpression(clean_lines, y1, x1)
                if x2 >= 0:
                    extended_line = clean_lines.elided[y2][x2:]
                    if y2 < clean_lines.NumLines() - 1:
                        extended_line += clean_lines.elided[y2 + 1]
                    if Match(r'\s*(?:->|\[)', extended_line):
                        parenthesis_error = True

        if parenthesis_error:
            error(filename, linenum, 'readability/casting', 4,
                  ('Are you taking an address of something dereferenced '
                   'from a cast?  Wrapping the dereferenced expression in '
                   'parentheses will make the binding more obvious'))
        else:
            error(filename, linenum, 'runtime/casting', 4,
                  ('Are you taking an address of a cast?  '
                   'This is dangerous: could be a temp var.  '
                   'Take the address before doing the cast, rather than after'))


def CheckCStyleCast(filename, clean_lines, linenum, cast_type, pattern, error):
    """Checks for a C-style cast by looking for the pattern.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      cast_type: The string for the C++ cast to recommend.  This is either
        reinterpret_cast, static_cast, or const_cast, depending.
      pattern: The regular expression used to find C-style casts.
      error: The function to call with any errors found.

    Returns:
      True if an error was emitted.
      False otherwise.
    """
    line = clean_lines.elided[linenum]
    match = Search(pattern, line)
    if not match:
        return False

    # Exclude lines with keywords that tend to look like casts
    context = line[0:match.start(1) - 1]
    if Match(r'.*\b(?:sizeof|alignof|alignas|[_A-Z][_A-Z0-9]*)\s*$', context):
        return False

    # Try expanding current context to see if we one level of
    # parentheses inside a macro.
    if linenum > 0:
        for i in range(linenum - 1, max(0, linenum - 5), -1):
            context = clean_lines.elided[i] + context
    if Match(r'.*\b[_A-Z][_A-Z0-9]*\s*\((?:\([^()]*\)|[^()])*$', context):
        return False

    # operator++(int) and operator--(int)
    if (context.endswith(' operator++') or context.endswith(' operator--') or
        context.endswith('::operator++') or context.endswith('::operator--')):
        return False

    # A single unnamed argument for a function tends to look like old style cast.
    # If we see those, don't issue warnings for deprecated casts.
    remainder = line[match.end(0):]
    if Match(r'^\s*(?:;|const\b|throw\b|final\b|override\b|[=>{),]|->)',
             remainder):
        return False

    # At this point, all that should be left is actual casts.
    error(filename, linenum, 'readability/casting', 4,
          'Using C-style cast.  Use %s<%s>(...) instead' %
          (cast_type, match.group(1)))

    return True


def ExpectingFunctionArgs(clean_lines, linenum):
    """Checks whether where function type arguments are expected.

    Args:
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.

    Returns:
      True if the line at 'linenum' is inside something that expects arguments
      of function types.
    """
    line = clean_lines.elided[linenum]
    return (Match(r'^\s*MOCK_(CONST_)?METHOD\d+(_T)?\(', line) or
            (linenum >= 2 and
             (Match(r'^\s*MOCK_(?:CONST_)?METHOD\d+(?:_T)?\((?:\S+,)?\s*$',
                    clean_lines.elided[linenum - 1]) or
              Match(r'^\s*MOCK_(?:CONST_)?METHOD\d+(?:_T)?\(\s*$',
                    clean_lines.elided[linenum - 2]) or
              Search(r'\bstd::m?function\s*\<\s*$',
                     clean_lines.elided[linenum - 1]))))


_HEADERS_CONTAINING_TEMPLATES = (
    ('<deque>', ('deque',)),
    ('<functional>', ('unary_function', 'binary_function',
                      'plus', 'minus', 'multiplies', 'divides', 'modulus',
                      'negate',
                      'equal_to', 'not_equal_to', 'greater', 'less',
                      'greater_equal', 'less_equal',
                      'logical_and', 'logical_or', 'logical_not',
                      'unary_negate', 'not1', 'binary_negate', 'not2',
                      'bind1st', 'bind2nd',
                      'pointer_to_unary_function',
                      'pointer_to_binary_function',
                      'ptr_fun',
                      'mem_fun_t', 'mem_fun', 'mem_fun1_t', 'mem_fun1_ref_t',
                      'mem_fun_ref_t',
                      'const_mem_fun_t', 'const_mem_fun1_t',
                      'const_mem_fun_ref_t', 'const_mem_fun1_ref_t',
                      'mem_fun_ref',
                     )),
    ('<limits>', ('numeric_limits',)),
    ('<list>', ('list',)),
    ('<map>', ('multimap',)),
    ('<memory>', ('allocator', 'make_shared', 'make_unique', 'shared_ptr',
                  'unique_ptr', 'weak_ptr')),
    ('<queue>', ('queue', 'priority_queue',)),
    ('<set>', ('multiset',)),
    ('<stack>', ('stack',)),
    ('<string>', ('char_traits', 'basic_string',)),
    ('<tuple>', ('tuple',)),
    ('<unordered_map>', ('unordered_map', 'unordered_multimap')),
    ('<unordered_set>', ('unordered_set', 'unordered_multiset')),
    ('<utility>', ('pair',)),
    ('<vector>', ('vector',)),

    # gcc extensions.
    # Note: std::hash is their hash, ::hash is our hash
    ('<hash_map>', ('hash_map', 'hash_multimap',)),
    ('<hash_set>', ('hash_set', 'hash_multiset',)),
    ('<slist>', ('slist',)),
    )

_HEADERS_MAYBE_TEMPLATES = (
    ('<algorithm>', ('copy', 'max', 'min', 'min_element', 'sort',
                     'transform',
                    )),
    ('<utility>', ('forward', 'make_pair', 'move', 'swap')),
    )

_RE_PATTERN_STRING = re.compile(r'\bstring\b')

_re_pattern_headers_maybe_templates = []
for _header, _templates in _HEADERS_MAYBE_TEMPLATES:
    for _template in _templates:
        # Match max<type>(..., ...), max(..., ...), but not foo->max, foo.max or
        # 'type::max()'.
        _re_pattern_headers_maybe_templates.append(
            (re.compile(r'[^>.]\b' + _template + r'(<.*?>)?\([^\)]'),
                _template,
                _header))
# Match set<type>, but not foo->set<type>, foo.set<type>
_re_pattern_headers_maybe_templates.append(
    (re.compile(r'[^>.]\bset\s*\<'),
        'set<>',
        '<set>'))
# Match 'map<type> var' and 'std::map<type>(...)', but not 'map<type>(...)''
_re_pattern_headers_maybe_templates.append(
    (re.compile(r'(std\b::\bmap\s*\<)|(^(std\b::\b)map\b\(\s*\<)'),
        'map<>',
        '<map>'))

# Other scripts may reach in and modify this pattern.
_re_pattern_templates = []
for _header, _templates in _HEADERS_CONTAINING_TEMPLATES:
    for _template in _templates:
        _re_pattern_templates.append(
            (re.compile(r'(\<|\b)' + _template + r'\s*\<'),
             _template + '<>',
             _header))


def FilesBelongToSameModule(filename_cc, filename_h):
    """Check if these two filenames beint to the same module.

    The concept of a 'module' here is a as follows:
    foo.h, foo-inl.h, foo.cc, foo_test.cc and foo_unittest.cc beint to the
    same 'module' if they are in the same directory.
    some/path/public/xyzzy and some/path/internal/xyzzy are also considered
    to beint to the same module here.

    If the filename_cc contains a inter path than the filename_h, for example,
    '/absolute/path/to/base/sysinfo.cc', and this file would include
    'base/sysinfo.h', this function also produces the prefix needed to open the
    header. This is used by the caller of this function to more robustly open the
    header file. We don't have access to the real include paths in this context,
    so we need this guesswork here.

    Known bugs: tools/base/bar.cc and base/bar.h beint to the same module
    according to this implementation. Because of this, this function gives
    some false positives. This should be sufficiently rare in practice.

    Args:
      filename_cc: is the path for the source (e.g. .cc) file
      filename_h: is the path for the header path

    Returns:
      Tuple with a bool and a string:
      bool: True if filename_cc and filename_h beint to the same module.
      string: the additional prefix needed to open the header file.
    """
    fileinfo_cc = FileInfo(filename_cc)
    if not fileinfo_cc.Extension().lstrip('.') in _cpplint_state.GetNonHeaderExtensions():
        return (False, '')

    fileinfo_h = FileInfo(filename_h)
    if not _cpplint_state.IsHeaderExtension(fileinfo_h.Extension().lstrip('.')):
        return (False, '')

    filename_cc = filename_cc[:-(len(fileinfo_cc.Extension()))]
    matched_test_suffix = Search(_TEST_FILE_SUFFIX, fileinfo_cc.BaseName())
    if matched_test_suffix:
        filename_cc = filename_cc[:-len(matched_test_suffix.group(1))]

    filename_cc = filename_cc.replace('/public/', '/')
    filename_cc = filename_cc.replace('/internal/', '/')

    filename_h = filename_h[:-(len(fileinfo_h.Extension()))]
    if filename_h.endswith('-inl'):
        filename_h = filename_h[:-len('-inl')]
    filename_h = filename_h.replace('/public/', '/')
    filename_h = filename_h.replace('/internal/', '/')

    files_beint_to_same_module = filename_cc.endswith(filename_h)
    common_path = ''
    if files_beint_to_same_module:
        common_path = filename_cc[:-len(filename_h)]
    return files_beint_to_same_module, common_path


def UpdateIncludeState(filename, include_dict, io=codecs):
    """Fill up the include_dict with new includes found from the file.

    Args:
      filename: the name of the header to read.
      include_dict: a dictionary in which the headers are inserted.
      io: The io factory to use to read the file. Provided for testability.

    Returns:
      True if a header was successfully added. False otherwise.
    """
    headerfile = None
    try:
        with io.open(filename, 'r', 'utf8', 'replace') as headerfile:
            linenum = 0
            for line in headerfile:
                linenum += 1
                clean_line = CleanseComments(line)
                match = _RE_PATTERN_INCLUDE.search(clean_line)
                if match:
                    include = match.group(2)
                    include_dict.setdefault(include, linenum)
        return True
    except IOError:
        return False



def CheckForIncludeWhatYouUse(filename, clean_lines, include_state, error,
                              io=codecs):
    """Reports for missing stl includes.

    This function will output warnings to make sure you are including the headers
    necessary for the stl containers and functions that you use. We only give one
    reason to include a header. For example, if you use both equal_to<> and
    less<> in a .h file, only one (the latter in the file) of these will be
    reported as a reason to include the <functional>.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      include_state: An _IncludeState instance.
      error: The function to call with any errors found.
      io: The IO factory to use to read the header file. Provided for unittest
          injection.
    """
    required = {}  # A map of header name to linenumber and the template entity.
                   # Example of required: { '<functional>': (1219, 'less<>') }

    for linenum in range(clean_lines.NumLines()):
        line = clean_lines.elided[linenum]
        if not line or line[0] == '#':
            continue

        # String is special -- it is a non-templatized type in STL.
        matched = _RE_PATTERN_STRING.search(line)
        if matched:
            # Don't warn about strings in non-STL namespaces:
            # (We check only the first match per line; good enough.)
            prefix = line[:matched.start()]
            if prefix.endswith('std::') or not prefix.endswith('::'):
                required['<string>'] = (linenum, 'string')

        for pattern, template, header in _re_pattern_headers_maybe_templates:
            if pattern.search(line):
                required[header] = (linenum, template)

        # The following function is just a speed up, no semantics are changed.
        if not '<' in line:  # Reduces the cpu time usage by skipping lines.
            continue

        for pattern, template, header in _re_pattern_templates:
            matched = pattern.search(line)
            if matched:
                # Don't warn about IWYU in non-STL namespaces:
                # (We check only the first match per line; good enough.)
                prefix = line[:matched.start()]
                if prefix.endswith('std::') or not prefix.endswith('::'):
                    required[header] = (linenum, template)

    # The policy is that if you #include something in foo.h you don't need to
    # include it again in foo.cc. Here, we will look at possible includes.
    # Let's flatten the include_state include_list and copy it into a dictionary.
    include_dict = dict([item for sublist in include_state.include_list
                         for item in sublist])

    # Did we find the header for this file (if any) and successfully load it?
    header_found = False

    # Use the absolute path so that matching works properly.
    abs_filename = FileInfo(filename).FullName()

    # For Emacs's flymake.
    # If cpplint is invoked from Emacs's flymake, a temporary file is generated
    # by flymake and that file name might end with '_flymake.cc'. In that case,
    # restore original file name here so that the corresponding header file can be
    # found.
    # e.g. If the file name is 'foo_flymake.cc', we should search for 'foo.h'
    # instead of 'foo_flymake.h'
    abs_filename = re.sub(r'_flymake\.cc$', '.cc', abs_filename)

    # include_dict is modified during iteration, so we iterate over a copy of
    # the keys.
    header_keys = list(include_dict.keys())
    for header in header_keys:
        (same_module, common_path) = FilesBelongToSameModule(abs_filename, header)
        fullpath = common_path + header
        if same_module and UpdateIncludeState(fullpath, include_dict, io):
            header_found = True

    # If we can't find the header file for a .cc, assume it's because we don't
    # know where to look. In that case we'll give up as we're not sure they
    # didn't include it in the .h file.
    # TODO(unknown): Do a better job of finding .h files so we are confident that
    # not having the .h file means there isn't one.
    if not header_found:
        for extension in _cpplint_state.GetNonHeaderExtensions():
            if filename.endswith('.' + extension):
                return

    # All the lines have been processed, report the errors found.
    for required_header_unstripped in sorted(required, key=required.__getitem__):
        template = required[required_header_unstripped][1]
        if required_header_unstripped.strip('<>"') not in include_dict:
            error(filename, required[required_header_unstripped][0],
                  'build/include_what_you_use', 4,
                  'Add #include ' + required_header_unstripped + ' for ' + template)


_RE_PATTERN_EXPLICIT_MAKEPAIR = re.compile(r'\bmake_pair\s*<')


def CheckMakePairUsesDeduction(filename, clean_lines, linenum, error):
    """Check that make_pair's template arguments are deduced.

    G++ 4.6 in C++11 mode fails badly if make_pair's template arguments are
    specified explicitly, and such use isn't intended in any case.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]
    match = _RE_PATTERN_EXPLICIT_MAKEPAIR.search(line)
    if match:
        error(filename, linenum, 'build/explicit_make_pair',
              4,  # 4 = high confidence
              'For C++11-compatibility, omit template arguments from make_pair'
              ' OR use pair directly OR if appropriate, construct a pair directly')


def CheckRedundantVirtual(filename, clean_lines, linenum, error):
    """Check if line contains a redundant "virtual" function-specifier.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    # Look for "virtual" on current line.
    line = clean_lines.elided[linenum]
    virtual = Match(r'^(.*)(\bvirtual\b)(.*)$', line)
    if not virtual: return

    # Ignore "virtual" keywords that are near access-specifiers.  These
    # are only used in class base-specifier and do not apply to member
    # functions.
    if (Search(r'\b(public|protected|private)\s+$', virtual.group(1)) or
        Match(r'^\s+(public|protected|private)\b', virtual.group(3))):
        return

    # Ignore the "virtual" keyword from virtual base classes.  Usually
    # there is a column on the same line in these cases (virtual base
    # classes are rare in google3 because multiple inheritance is rare).
    if Match(r'^.*[^:]:[^:].*$', line): return

    # Look for the next opening parenthesis.  This is the start of the
    # parameter list (possibly on the next line shortly after virtual).
    # TODO(unknown): doesn't work if there are virtual functions with
    # decltype() or other things that use parentheses, but csearch suggests
    # that this is rare.
    end_col = -1
    end_line = -1
    start_col = len(virtual.group(2))
    for start_line in range(linenum, min(linenum + 3, clean_lines.NumLines())):
        line = clean_lines.elided[start_line][start_col:]
        parameter_list = Match(r'^([^(]*)\(', line)
        if parameter_list:
            # Match parentheses to find the end of the parameter list
            (_, end_line, end_col) = CloseExpression(
                clean_lines, start_line, start_col + len(parameter_list.group(1)))
            break
        start_col = 0

    if end_col < 0:
        return  # Couldn't find end of parameter list, give up

    # Look for "override" or "final" after the parameter list
    # (possibly on the next few lines).
    for i in range(end_line, min(end_line + 3, clean_lines.NumLines())):
        line = clean_lines.elided[i][end_col:]
        match = Search(r'\b(override|final)\b', line)
        if match:
            error(filename, linenum, 'readability/inheritance', 4,
                  ('"virtual" is redundant since function is '
                   'already declared as "%s"' % match.group(1)))

        # Set end_col to check whole lines after we are done with the
        # first line.
        end_col = 0
        if Search(r'[^\w]\s*$', line):
            break


def CheckRedundantOverrideOrFinal(filename, clean_lines, linenum, error):
    """Check if line contains a redundant "override" or "final" virt-specifier.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    # Look for closing parenthesis nearby.  We need one to confirm where
    # the declarator ends and where the virt-specifier starts to avoid
    # false positives.
    line = clean_lines.elided[linenum]
    declarator_end = line.rfind(')')
    if declarator_end >= 0:
        fragment = line[declarator_end:]
    else:
        if linenum > 1 and clean_lines.elided[linenum - 1].rfind(')') >= 0:
            fragment = line
        else:
            return

    # Check that at most one of "override" or "final" is present, not both
    if Search(r'\boverride\b', fragment) and Search(r'\bfinal\b', fragment):
        error(filename, linenum, 'readability/inheritance', 4,
              ('"override" is redundant since function is '
               'already declared as "final"'))




# Returns true if we are at a new block, and it is directly
# inside of a namespace.

def FlagCxx11Features(filename, clean_lines, linenum, error):
    """Flag those c++11 features that we only allow in certain places.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    include = Match(r'\s*#\s*include\s+[<"]([^<"]+)[">]', line)

    # Flag unapproved C++ TR1 headers.
    if include and include.group(1).startswith('tr1/'):
        error(filename, linenum, 'build/c++tr1', 5,
              ('C++ TR1 headers such as <%s> are unapproved.') % include.group(1))

    # Flag unapproved C++11 headers.
    if include and include.group(1) in ('cfenv',
                                        'condition_variable',
                                        'fenv.h',
                                        'future',
                                        'mutex',
                                        'thread',
                                        'chrono',
                                        'ratio',
                                        'regex',
                                        'system_error',
                                       ):
        error(filename, linenum, 'build/c++11', 5,
              ('<%s> is an unapproved C++11 header.') % include.group(1))

    # The only place where we need to worry about C++11 keywords and library
    # features in preprocessor directives is in macro definitions.
    if Match(r'\s*#', line) and not Match(r'\s*#\s*define\b', line): return

    # These are classes and free functions.  The classes are always
    # mentioned as std::*, but we only catch the free functions if
    # they're not found by ADL.  They're alphabetical by header.
    for top_name in (
        # type_traits
        'alignment_of',
        'aligned_union',
        ):
        if Search(r'\bstd::%s\b' % top_name, line):
            error(filename, linenum, 'build/c++11', 5,
                  ('std::%s is an unapproved C++11 class or function.  Send c-style '
                   'an example of where it would make your code more readable, and '
                   'they may let you use it.') % top_name)


def FlagCxx14Features(filename, clean_lines, linenum, error):
    """Flag those C++14 features that we restrict.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    include = Match(r'\s*#\s*include\s+[<"]([^<"]+)[">]', line)

    # Flag unapproved C++14 headers.
    if include and include.group(1) in ('scoped_allocator', 'shared_mutex'):
        error(filename, linenum, 'build/c++14', 5,
              ('<%s> is an unapproved C++14 header.') % include.group(1))


def ProcessFileData(filename: str, file_extension: str, lines: list[str], error: Callable[[str, int, int, str],None],
                    extra_check_functions=None) -> None:
    """Performs lint checks and reports any errors to the given error function.

    Args:
      filename: Filename of the file that is being processed.
      file_extension: The extension (dot not included) of the file.
      lines: An array of strings, each representing a line of the file, with the
             last element being empty if the file is terminated with a newline.
      error: A callable to which errors are reported, which takes 4 arguments:
             filename, line number, error level, and message
      extra_check_functions: An array of additional check functions that will be
                             run on each source line. Each function takes 4
                             arguments: filename, clean_lines, line, error
    """
    lines = (['// marker so line numbers and indices both start at 1'] + lines +
             ['// marker so line numbers end in a known way'])

    include_state = _IncludeState()
    function_state = _FunctionState()
    nesting_state = NestingState()

    ResetNolintSuppressions()

    CheckForCopyright(filename, lines, error)
    ProcessGlobalSuppresions(lines)
    RemoveMultiLineComments(filename, lines, error)
    clean_lines = CleansedLines(lines)

    if _cpplint_state.IsHeaderExtension(file_extension):
        CheckForHeaderGuard(filename, clean_lines, error)

    for line in range(clean_lines.NumLines()):
        ProcessLine(_cpplint_state, filename, file_extension, clean_lines, line,
                    include_state, function_state, nesting_state, error,
                    extra_check_functions)
        FlagCxx11Features(filename, clean_lines, line, error)
    nesting_state.CheckCompletedBlocks(filename, error)

    CheckForIncludeWhatYouUse(filename, clean_lines, include_state, error)

    # Check that the .cc file has included its header if it exists.
    if _IsExtension(file_extension, _cpplint_state.GetNonHeaderExtensions()):
        CheckHeaderFileIncluded(filename, include_state, error)

    # We check here rather than inside ProcessLine so that we see raw
    # lines rather than "cleaned" lines.
    CheckForBadCharacters(filename, lines, error)

    CheckForNewlineAtEOF(filename, lines, error)


