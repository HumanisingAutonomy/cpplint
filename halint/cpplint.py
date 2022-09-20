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
import os
import re
from typing import Callable

from .block_info import (
    _TEST_FILE_SUFFIX,
    GetHeaderGuardCPPVariable,
    ReverseCloseExpression,
    FindNextMultiLineCommentStart,
    FindNextMultiLineCommentEnd
)
from .check_line import ProcessLine
from .cleansed_lines import _RE_PATTERN_INCLUDE, CleanseComments, CleansedLines
from .error import (
    ErrorLogger,
    ParseNolintSuppressions,
    ProcessGlobalSuppresions,
    ResetNolintSuppressions
)
from .file_info import FileInfo, _IsExtension
from .function_state import _FunctionState
from .include_state import _IncludeState
from .lintstate import LintState
from .nesting_state import NestingState
from .regex import Match, Search





def RemoveMultiLineCommentsFromRange(lines, begin, end):
    """Clears a range of lines for multi-line comments."""
    # Having // <empty> comments makes the lines non-empty, so we will not get
    # unnecessary blank line warnings later in the code.
    for i in range(begin, end):
        lines[i] = "/**/"


def RemoveMultiLineComments(state, filename, lines, error):
    """Removes multiline (c-style) comments from lines."""
    lineix = 0
    while lineix < len(lines):
        lineix_begin = FindNextMultiLineCommentStart(lines, lineix)
        if lineix_begin >= len(lines):
            return
        lineix_end = FindNextMultiLineCommentEnd(lines, lineix_begin)
        if lineix_end >= len(lines):
            error(
                state,
                filename,
                lineix_begin + 1,
                "readability/multiline_comment",
                5,
                "Could not find end of multi-line comment",
            )
            return
        RemoveMultiLineCommentsFromRange(lines, lineix_begin, lineix_end + 1)
        lineix = lineix_end + 1


def CheckForCopyright(state, filename, lines, error):
    """Logs an error if no Copyright message appears at the top of the file."""

    # We'll say it should occur by line 10. Don't forget there's a
    # placeholder line at the front.
    for line in range(1, min(len(lines), 11)):
        if re.search(r"Copyright", lines[line], re.I):
            break
    else:  # means no copyright line was found
        error(
            state,
            filename,
            0,
            "legal/copyright",
            5,
            "No copyright message found.  " 'You should have a line: "Copyright [year] <Copyright Owner>"',
        )


def GetIndentLevel(line):
    """Return the number of leading spaces in line.

    Args:
      line: A string to check.

    Returns:
      An integer count of leading spaces, possibly zero.
    """
    indent = Match(r"^( *)\S", line)
    if indent:
        return len(indent.group(1))
    else:
        return 0


def CheckForHeaderGuard(
    state: LintState,
    filename: str,
    clean_lines: CleansedLines,
    error: Callable[[LintState, str, int, str, int, str], None],
):
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
        if Search(r"//\s*NOLINT\(build/header_guard\)", i):
            return

    # Allow pragma once instead of header guards
    for i in raw_lines:
        if Search(r"^\s*#pragma\s+once", i):
            return

    cppvar = GetHeaderGuardCPPVariable(state, filename)

    ifndef = ""
    ifndef_linenum = 0
    define = ""
    endif = ""
    endif_linenum = 0
    for linenum, line in enumerate(raw_lines):
        linesplit = line.split()
        if len(linesplit) >= 2:
            # find the first occurrence of #ifndef and #define, save arg
            if not ifndef and linesplit[0] == "#ifndef":
                # set ifndef to the header guard presented on the #ifndef line.
                ifndef = linesplit[1]
                ifndef_linenum = linenum
            if not define and linesplit[0] == "#define":
                define = linesplit[1]
        # find the last occurrence of #endif, save entire line
        if line.startswith("#endif"):
            endif = line
            endif_linenum = linenum

    if not ifndef or not define or ifndef != define:
        error(
            state,
            filename,
            0,
            "build/header_guard",
            5,
            "No #ifndef header guard found, suggested CPP variable is: %s" % cppvar,
        )
        return

    # The guard should be PATH_FILE_H_, but we also allow PATH_FILE_H__
    # for backward compatibility.
    if ifndef != cppvar:
        error_level = 0
        if ifndef != cppvar + "_":
            error_level = 5

        ParseNolintSuppressions(state, filename, raw_lines[ifndef_linenum], ifndef_linenum, error)
        error(
            state,
            filename,
            ifndef_linenum,
            "build/header_guard",
            error_level,
            "#ifndef header guard has wrong style, please use: %s" % cppvar,
        )

    # Check for "//" comments on endif line.
    ParseNolintSuppressions(state, filename, raw_lines[endif_linenum], endif_linenum, error)
    match = Match(r"#endif\s*//\s*" + cppvar + r"(_)?\b", endif)
    if match:
        if match.group(1) == "_":
            # Issue low severity warning for deprecated double trailing underscore
            error(
                state,
                filename,
                endif_linenum,
                "build/header_guard",
                0,
                '#endif line should be "#endif  // %s"' % cppvar,
            )
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
        match = Match(r"#endif\s*/\*\s*" + cppvar + r"(_)?\s*\*/", endif)
        if match:
            if match.group(1) == "_":
                # Low severity warning for double trailing underscore
                error(
                    state,
                    filename,
                    endif_linenum,
                    "build/header_guard",
                    0,
                    '#endif line should be "#endif  /* %s */"' % cppvar,
                )
            return

    # Didn't find anything
    error(
        state,
        filename,
        endif_linenum,
        "build/header_guard",
        5,
        '#endif line should be "#endif  // %s"' % cppvar,
    )


def CheckHeaderFileIncluded(state: LintState, filename: int, include_state: _IncludeState, error: ErrorLogger):
    """Logs an error if a source file does not include its header."""

    # Do not check test files
    fileinfo = FileInfo(filename)
    if Search(_TEST_FILE_SUFFIX, fileinfo.BaseName()):
        return

    for ext in state.GetHeaderExtensions():
        basefilename = filename[0 : len(filename) - len(fileinfo.Extension())]
        headerfile = basefilename + "." + ext
        if not os.path.exists(headerfile):
            continue
        headername = FileInfo(headerfile).RepositoryName(state._repository)
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

        message = "%s should include its header file %s" % (
            fileinfo.RepositoryName(state._repository),
            headername,
        )
        if include_uses_unix_dir_aliases:
            message += ". Relative paths like . and .. are not allowed."

        error(state, filename, first_include, "build/include", 5, message)


def CheckForBadCharacters(state, filename, lines, error):
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
        if "\ufffd" in line:
            error(
                state,
                filename,
                linenum,
                "readability/utf8",
                5,
                "Line contains invalid UTF-8 (or Unicode replacement character).",
            )
        if "\0" in line:
            error(
                state,
                filename,
                linenum,
                "readability/nul",
                5,
                "Line contains NUL byte.",
            )


def CheckForNewlineAtEOF(state, filename, lines, error):
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
        error(
            state,
            filename,
            len(lines) - 2,
            "whitespace/ending_newline",
            5,
            "Could not find a newline character at the end of the file.",
        )


def IsMacroDefinition(clean_lines, linenum):
    if Search(r"^#define", clean_lines[linenum]):
        return True

    if linenum > 0 and Search(r"\\$", clean_lines[linenum - 1]):
        return True

    return False


def IsForwardClassDeclaration(clean_lines, linenum):
    return Match(r"^\s*(\btemplate\b)*.*class\s+\w+;\s*$", clean_lines[linenum])


def IsDecltype(clean_lines, linenum, column):
    """Check if the token ending on (line_num, column) is decltype().

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
    if Search(r"\bdecltype\s*$", text[0:start_col]):
        return True
    return False


_HEADERS_CONTAINING_TEMPLATES = (
    ("<deque>", ("deque",)),
    (
        "<functional>",
        (
            "unary_function",
            "binary_function",
            "plus",
            "minus",
            "multiplies",
            "divides",
            "modulus",
            "negate",
            "equal_to",
            "not_equal_to",
            "greater",
            "less",
            "greater_equal",
            "less_equal",
            "logical_and",
            "logical_or",
            "logical_not",
            "unary_negate",
            "not1",
            "binary_negate",
            "not2",
            "bind1st",
            "bind2nd",
            "pointer_to_unary_function",
            "pointer_to_binary_function",
            "ptr_fun",
            "mem_fun_t",
            "mem_fun",
            "mem_fun1_t",
            "mem_fun1_ref_t",
            "mem_fun_ref_t",
            "const_mem_fun_t",
            "const_mem_fun1_t",
            "const_mem_fun_ref_t",
            "const_mem_fun1_ref_t",
            "mem_fun_ref",
        ),
    ),
    ("<limits>", ("numeric_limits",)),
    ("<list>", ("list",)),
    ("<map>", ("multimap",)),
    (
        "<memory>",
        (
            "allocator",
            "make_shared",
            "make_unique",
            "shared_ptr",
            "unique_ptr",
            "weak_ptr",
        ),
    ),
    (
        "<queue>",
        (
            "queue",
            "priority_queue",
        ),
    ),
    ("<set>", ("multiset",)),
    ("<stack>", ("stack",)),
    (
        "<string>",
        (
            "char_traits",
            "basic_string",
        ),
    ),
    ("<tuple>", ("tuple",)),
    ("<unordered_map>", ("unordered_map", "unordered_multimap")),
    ("<unordered_set>", ("unordered_set", "unordered_multiset")),
    ("<utility>", ("pair",)),
    ("<vector>", ("vector",)),
    # gcc extensions.
    # Note: std::hash is their hash, ::hash is our hash
    (
        "<hash_map>",
        (
            "hash_map",
            "hash_multimap",
        ),
    ),
    (
        "<hash_set>",
        (
            "hash_set",
            "hash_multiset",
        ),
    ),
    ("<slist>", ("slist",)),
)

_HEADERS_MAYBE_TEMPLATES = (
    (
        "<algorithm>",
        (
            "copy",
            "max",
            "min",
            "min_element",
            "sort",
            "transform",
        ),
    ),
    ("<utility>", ("forward", "make_pair", "move", "swap")),
)

_RE_PATTERN_STRING = re.compile(r"\bstring\b")

_re_pattern_headers_maybe_templates = []
for _header, _templates in _HEADERS_MAYBE_TEMPLATES:
    for _template in _templates:
        # Match max<type>(..., ...), max(..., ...), but not foo->max, foo.max or
        # 'type::max()'.
        _re_pattern_headers_maybe_templates.append(
            (
                re.compile(r"[^>.]\b" + _template + r"(<.*?>)?\([^\)]"),
                _template,
                _header,
            )
        )
# Match set<type>, but not foo->set<type>, foo.set<type>
_re_pattern_headers_maybe_templates.append((re.compile(r"[^>.]\bset\s*\<"), "set<>", "<set>"))
# Match 'map<type> var' and 'std::map<type>(...)', but not 'map<type>(...)''
_re_pattern_headers_maybe_templates.append(
    (re.compile(r"(std\b::\bmap\s*\<)|(^(std\b::\b)map\b\(\s*\<)"), "map<>", "<map>")
)

# Other scripts may reach in and modify this pattern.
_re_pattern_templates = []
for _header, _templates in _HEADERS_CONTAINING_TEMPLATES:
    for _template in _templates:
        _re_pattern_templates.append((re.compile(r"(\<|\b)" + _template + r"\s*\<"), _template + "<>", _header))


def FilesBelongToSameModule(state: LintState, filename_cc: str, filename_h: str):
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
    if not fileinfo_cc.Extension().lstrip(".") in state.GetNonHeaderExtensions():
        return (False, "")

    fileinfo_h = FileInfo(filename_h)
    if not state.IsHeaderExtension(fileinfo_h.Extension().lstrip(".")):
        return (False, "")

    filename_cc = filename_cc[: -(len(fileinfo_cc.Extension()))]
    matched_test_suffix = Search(_TEST_FILE_SUFFIX, fileinfo_cc.BaseName())
    if matched_test_suffix:
        filename_cc = filename_cc[: -len(matched_test_suffix.group(1))]

    filename_cc = filename_cc.replace("/public/", "/")
    filename_cc = filename_cc.replace("/internal/", "/")

    filename_h = filename_h[: -(len(fileinfo_h.Extension()))]
    if filename_h.endswith("-inl"):
        filename_h = filename_h[: -len("-inl")]
    filename_h = filename_h.replace("/public/", "/")
    filename_h = filename_h.replace("/internal/", "/")

    files_beint_to_same_module = filename_cc.endswith(filename_h)
    common_path = ""
    if files_beint_to_same_module:
        common_path = filename_cc[: -len(filename_h)]
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
        with io.open(filename, "r", "utf8", "replace") as headerfile:
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


def CheckForIncludeWhatYouUse(
    state: LintState,
    filename: str,
    clean_lines: CleansedLines,
    include_state: _IncludeState,
    error: ErrorLogger,
    io=codecs,
):
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
        if not line or line[0] == "#":
            continue

        # String is special -- it is a non-templatized type in STL.
        matched = _RE_PATTERN_STRING.search(line)
        if matched:
            # Don't warn about strings in non-STL namespaces:
            # (We check only the first match per line; good enough.)
            prefix = line[: matched.start()]
            if prefix.endswith("std::") or not prefix.endswith("::"):
                required["<string>"] = (linenum, "string")

        for pattern, template, header in _re_pattern_headers_maybe_templates:
            if pattern.search(line):
                required[header] = (linenum, template)

        # The following function is just a speed up, no semantics are changed.
        if "<" not in line:  # Reduces the cpu time usage by skipping lines.
            continue

        for pattern, template, header in _re_pattern_templates:
            matched = pattern.search(line)
            if matched:
                # Don't warn about IWYU in non-STL namespaces:
                # (We check only the first match per line; good enough.)
                prefix = line[: matched.start()]
                if prefix.endswith("std::") or not prefix.endswith("::"):
                    required[header] = (linenum, template)

    # The policy is that if you #include something in foo.h you don't need to
    # include it again in foo.cc. Here, we will look at possible includes.
    # Let's flatten the include_state include_list and copy it into a dictionary.
    include_dict = dict([item for sublist in include_state.include_list for item in sublist])

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
    abs_filename = re.sub(r"_flymake\.cc$", ".cc", abs_filename)

    # include_dict is modified during iteration, so we iterate over a copy of
    # the keys.
    header_keys = list(include_dict.keys())
    for header in header_keys:
        (same_module, common_path) = FilesBelongToSameModule(state, abs_filename, header)
        fullpath = common_path + header
        if same_module and UpdateIncludeState(fullpath, include_dict, io):
            header_found = True

    # If we can't find the header file for a .cc, assume it's because we don't
    # know where to look. In that case we'll give up as we're not sure they
    # didn't include it in the .h file.
    # TODO(unknown): Do a better job of finding .h files so we are confident that
    # not having the .h file means there isn't one.
    if not header_found:
        for extension in state.GetNonHeaderExtensions():
            if filename.endswith("." + extension):
                return

    # All the lines have been processed, report the errors found.
    for required_header_unstripped in sorted(required, key=required.__getitem__):
        template = required[required_header_unstripped][1]
        if required_header_unstripped.strip('<>"') not in include_dict:
            error(
                state,
                filename,
                required[required_header_unstripped][0],
                "build/include_what_you_use",
                4,
                "Add #include " + required_header_unstripped + " for " + template,
            )


# Returns true if we are at a new block, and it is directly
# inside of a namespace.


def FlagCxx11Features(state, filename, clean_lines, linenum, error):
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
    if include and include.group(1).startswith("tr1/"):
        error(
            state,
            filename,
            linenum,
            "build/c++tr1",
            5,
            ("C++ TR1 headers such as <%s> are unapproved.") % include.group(1),
        )

    # Flag unapproved C++11 headers.
    if include and include.group(1) in (
        "cfenv",
        "condition_variable",
        "fenv.h",
        "future",
        "mutex",
        "thread",
        "chrono",
        "ratio",
        "regex",
        "system_error",
    ):
        error(
            state,
            filename,
            linenum,
            "build/c++11",
            5,
            ("<%s> is an unapproved C++11 header.") % include.group(1),
        )

    # The only place where we need to worry about C++11 keywords and library
    # features in preprocessor directives is in macro definitions.
    if Match(r"\s*#", line) and not Match(r"\s*#\s*define\b", line):
        return

    # These are classes and free functions.  The classes are always
    # mentioned as std::*, but we only catch the free functions if
    # they're not found by ADL.  They're alphabetical by header.
    for top_name in (
        # type_traits
        "alignment_of",
        "aligned_union",
    ):
        if Search(r"\bstd::%s\b" % top_name, line):
            error(
                state,
                filename,
                linenum,
                "build/c++11",
                5,
                (
                    "std::%s is an unapproved C++11 class or function.  Send c-style "
                    "an example of where it would make your code more readable, and "
                    "they may let you use it."
                )
                % top_name,
            )


def FlagCxx14Features(
    state: LintState,
    filename: str,
    clean_lines: CleansedLines,
    linenum: int,
    error: ErrorLogger,
):
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
    if include and include.group(1) in ("scoped_allocator", "shared_mutex"):
        error(
            state,
            filename,
            linenum,
            "build/c++14",
            5,
            ("<%s> is an unapproved C++14 header.") % include.group(1),
        )


def ProcessFileData(
    state: LintState,
    filename: str,
    file_extension: str,
    lines: list[str],
    error: ErrorLogger,
    extra_check_functions=None,
) -> None:
    """Performs lint checks and reports any errors to the given error function.

    Args:
      state: The state of the current linting process.
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
    lines = (
        ["// marker so line numbers and indices both start at 1"]
        + lines
        + ["// marker so line numbers end in a known way"]
    )

    include_state = _IncludeState()
    function_state = _FunctionState()
    nesting_state = NestingState()

    ResetNolintSuppressions(state)

    CheckForCopyright(state, filename, lines, error)
    ProcessGlobalSuppresions(state, lines)
    RemoveMultiLineComments(state, filename, lines, error)
    clean_lines = CleansedLines(lines)

    if state.IsHeaderExtension(file_extension):
        CheckForHeaderGuard(state, filename, clean_lines, error)

    for line in range(clean_lines.NumLines()):
        ProcessLine(
            state,
            filename,
            file_extension,
            clean_lines,
            line,
            include_state,
            function_state,
            nesting_state,
            error,
            extra_check_functions,
        )
        FlagCxx11Features(state, filename, clean_lines, line, error)
    nesting_state.CheckCompletedBlocks(state, filename, error)

    CheckForIncludeWhatYouUse(state, filename, clean_lines, include_state, error)

    # Check that the .cc file has included its header if it exists.
    if _IsExtension(file_extension, state.GetNonHeaderExtensions()):
        CheckHeaderFileIncluded(state, filename, include_state, error)

    # We check here rather than inside ProcessLine so that we see raw
    # lines rather than "cleaned" lines.
    CheckForBadCharacters(state, filename, lines, error)

    CheckForNewlineAtEOF(state, filename, lines, error)
