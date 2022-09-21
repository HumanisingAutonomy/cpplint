import os
import re
from typing import Callable

from .block_info import (
    CloseExpression,
    ExpectingFunctionArgs,
    _ClassifyInclude,
    _GetTextInside,
)
from .cleansed_lines import _RE_PATTERN_INCLUDE, CleansedLines
from .file_info import FileInfo
from .include_state import IncludeState
from .lintstate import LintState
from ._nesting_state import NestingState
from .regex import Match, Search


def CheckLanguage(
    state: LintState,
    filename: str,
    clean_lines: CleansedLines,
    linenum: int,
    file_extension: str,
    include_state: IncludeState,
    nesting_state: NestingState,
    error: Callable[[str, int, str, int, str], None],
):
    """Checks rules from the 'C++ language rules' section of cppguide.html.

    Some of these rules are hard to test (function overloading, using
    uint32 inappropriately), but we do the best we can.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      file_extension: The extension (without the dot) of the file_name.
      include_state: An IncludeState instance in which the headers are inserted.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: The function to call with any errors found.
    """

    # TODO: This should just be a list of checks

    # If the line is empty or consists of entirely a comment, no need to
    # check it.
    line = clean_lines.elided[linenum]
    if not line:
        return

    match = _RE_PATTERN_INCLUDE.search(line)
    if match:
        CheckIncludeLine(state, filename, clean_lines, linenum, include_state, error)
        return

    # Reset include state across preprocessor directives.  This is meant
    # to silence warnings for conditional includes.
    match = Match(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b", line)
    if match:
        include_state.reset_section(match.group(1))

    # Perform other checks now that we are sure that this is not an include line
    CheckCasts(state, filename, clean_lines, linenum, error)
    CheckGlobalStatic(state, filename, clean_lines, linenum, error)
    CheckPrintf(state, filename, clean_lines, linenum, error)

    if state.IsHeaderExtension(file_extension):
        # TODO(unknown): check that 1-arg constructors are explicit.
        #                How to tell it's a constructor?
        #                (handled in CheckForNonStandardConstructs for now)
        # TODO(unknown): check that classes declare or disable copy/assign
        #                (level 1 error)
        pass

    # Check if people are using the verboten C basic types.  The only exception
    # we regularly allow is "unsigned short port" for port.
    if Search(r"\bshort port\b", line):
        if not Search(r"\bunsigned short port\b", line):
            error(
                state,
                filename,
                linenum,
                "runtime/int",
                4,
                'Use "unsigned short" for ports, not "short"',
            )
    else:
        match = Search(r"\b(short|long(?! +double)|long long)\b", line)
        if match:
            error(
                state,
                filename,
                linenum,
                "runtime/int",
                4,
                "Use int16/int64/etc, rather than the C type %s" % match.group(1),
            )

    # Check if some verboten operator overloading is going on
    # TODO(unknown): catch out-of-line unary operator&:
    #   class X {};
    #   int operator&(const X& x) { return 42; }  // unary operator&
    # The trick is it's hard to tell apart from binary operator&:
    #   class Y { int operator&(const Y& x) { return 23; } }; // binary operator&
    if Search(r"\boperator\s*&\s*\(\s*\)", line):
        error(
            state,
            filename,
            linenum,
            "runtime/operator",
            4,
            "Unary operator& is dangerous.  Do not use it.",
        )

    # Check for suspicious usage of "if" like
    # } if (a == b) {
    if Search(r"\}\s*if\s*\(", line):
        error(
            state,
            filename,
            linenum,
            "readability/braces",
            4,
            'Did you mean "else if"? If not, start a new line for "if".',
        )

    # Check for potential format string bugs like printf(foo).
    # We constrain the pattern not to pick things like DocidForPrintf(foo).
    # Not perfect but it can catch printf(foo.c_str()) and printf(foo->c_str())
    # TODO(unknown): Catch the following case. Need to change the calling
    # convention of the whole function to process multiple line to handle it.
    #   printf(
    #       boy_this_is_a_really_int_variable_that_cannot_fit_on_the_prev_line);
    printf_args = _GetTextInside(line, r"(?i)\b(string)?printf\s*\(")
    if printf_args:
        match = Match(r"([\w.\->()]+)$", printf_args)
        if match and match.group(1) != "__VA_ARGS__":
            function_name = re.search(r"\b((?:string)?printf)\s*\(", line, re.I).group(1)
            error(
                state,
                filename,
                linenum,
                "runtime/printf",
                4,
                'Potential format string bug. Do %s("%%s", %s) instead.' % (function_name, match.group(1)),
            )

    # Check for potential memset bugs like memset(buf, sizeof(buf), 0).
    match = Search(r"memset\s*\(([^,]*),\s*([^,]*),\s*0\s*\)", line)
    if match and not Match(r"^''|-?[0-9]+|0x[0-9A-Fa-f]$", match.group(2)):
        error(
            state,
            filename,
            linenum,
            "runtime/memset",
            4,
            'Did you mean "memset(%s, 0, %s)"?' % (match.group(1), match.group(2)),
        )

    if Search(r"\busing namespace\b", line):
        if Search(r"\bliterals\b", line):
            error(
                state,
                filename,
                linenum,
                "build/namespaces_literals",
                5,
                "Do not use namespace using-directives.  " "Use using-declarations instead.",
            )
        else:
            error(
                state,
                filename,
                linenum,
                "build/namespaces",
                5,
                "Do not use namespace using-directives.  " "Use using-declarations instead.",
            )

    # Detect variable-length arrays.
    match = Match(r"\s*(.+::)?(\w+) [a-z]\w*\[(.+)];", line)
    if match and match.group(2) != "return" and match.group(2) != "delete" and match.group(3).find("]") == -1:
        # Split the size using space and arithmetic operators as delimiters.
        # If any of the resulting tokens are not compile time constants then
        # report the error.
        tokens = re.split(r"\s|\+|\-|\*|\/|<<|>>]", match.group(3))
        is_const = True
        skip_next = False
        for tok in tokens:
            if skip_next:
                skip_next = False
                continue

            if Search(r"sizeof\(.+\)", tok):
                continue
            if Search(r"arraysize\(\w+\)", tok):
                continue

            tok = tok.lstrip("(")
            tok = tok.rstrip(")")
            if not tok:
                continue
            if Match(r"\d+", tok):
                continue
            if Match(r"0[xX][0-9a-fA-F]+", tok):
                continue
            if Match(r"k[A-Z0-9]\w*", tok):
                continue
            if Match(r"(.+::)?k[A-Z0-9]\w*", tok):
                continue
            if Match(r"(.+::)?[A-Z][A-Z0-9_]*", tok):
                continue
            # A catch all for tricky sizeof cases, including 'sizeof expression',
            # 'sizeof(*type)', 'sizeof(const type)', 'sizeof(struct StructName)'
            # requires skipping the next token because we split on ' ' and '*'.
            if tok.startswith("sizeof"):
                skip_next = True
                continue
            is_const = False
            break
        if not is_const:
            error(
                state,
                filename,
                linenum,
                "runtime/arrays",
                1,
                "Do not use variable-length arrays.  Use an appropriately named "
                "('k' followed by CamelCase) compile-time constant for the size.",
            )

    # Check for use of unnamed namespaces in header files.  Registration
    # macros are typically OK, so we allow use of "namespace {" on lines
    # that end with backslashes.
    if state.IsHeaderExtension(file_extension) and Search(r"\bnamespace\s*{", line) and line[-1] != "\\":
        error(
            state,
            filename,
            linenum,
            "build/namespaces_headers",
            4,
            "Do not use unnamed namespaces in header files.  See "
            "https://google-styleguide.googlecode.com/svn/trunk/cppguide.xml#Namespaces"
            " for more information.",
        )


def CheckIncludeLine(state, filename, clean_lines, linenum, include_state, error):
    """Check rules that are applicable to #include lines.

    Strings on #include lines are NOT removed from elided line, to make
    certain tasks easier. However, to prevent false positives, checks
    applicable to #include lines in CheckLanguage must be put here.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      include_state: An IncludeState instance in which the headers are inserted.
      error: The function to call with any errors found.
    """
    fileinfo = FileInfo(filename)
    line = clean_lines.lines[linenum]

    # These headers are excluded from [build/include] and [build/include_order]
    # checks:
    # - Anything not following google file name conventions (containing an
    #   uppercase character, such as Python.h or nsStringAPI.h, for example).
    # - Lua headers.
    _THIRD_PARTY_HEADERS_PATTERN = re.compile(r"^(?:[^/]*[A-Z][^/]*\.h|lua\.h|lauxlib\.h|lualib\.h)$")
    # "include" should use the new style "foo/bar.h" instead of just "bar.h"
    # Only do this check if the included header follows google naming
    # conventions.  If not, assume that it's a 3rd party API that
    # requires special include conventions.
    #
    # We also make an exception for Lua headers, which follow google
    # naming convention but not the include convention.
    match = Match(r'#include\s*"([^/]+\.(.*))"', line)
    if match:
        if state.IsHeaderExtension(match.group(2)) and not _THIRD_PARTY_HEADERS_PATTERN.match(match.group(1)):
            error(
                state,
                filename,
                linenum,
                "build/include_subdir",
                4,
                "Include the directory when naming header files",
            )

    # we shouldn't include a file more than once. actually, there are a
    # handful of instances where doing so is okay, but in general it's
    # not.
    match = _RE_PATTERN_INCLUDE.search(line)
    if match:
        include = match.group(2)
        used_angle_brackets = match.group(1) == "<"
        duplicate_line = include_state.find_header(include)
        if duplicate_line >= 0:
            error(
                state,
                filename,
                linenum,
                "build/include",
                4,
                '"%s" already included at %s:%s' % (include, filename, duplicate_line),
            )
            return

        for extension in state.GetNonHeaderExtensions():
            if include.endswith("." + extension) and os.path.dirname(
                fileinfo.repository_name(state._repository)
            ) != os.path.dirname(include):
                error(
                    state,
                    filename,
                    linenum,
                    "build/include",
                    4,
                    "Do not include ." + extension + " files from other packages",
                )
                return

        # We DO want to include a 3rd party looking header if it matches the
        # file_name. Otherwise we get an erroneous error "...should include its
        # header" error later.
        third_src_header = False
        for ext in state.GetHeaderExtensions():
            basefilename = filename[0 : len(filename) - len(fileinfo.extension())]
            headerfile = basefilename + "." + ext
            headername = FileInfo(headerfile).repository_name(state._repository)
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
            error_message = include_state.check_next_include_order(
                _ClassifyInclude(state, fileinfo, include, used_angle_brackets, state._include_order)
            )
            if error_message:
                error(
                    state,
                    filename,
                    linenum,
                    "build/include_order",
                    4,
                    "%s. Should be: %s.h, c system, c++ system, other." % (error_message, fileinfo.base_name()),
                )
            canonical_include = include_state.canonicalize_alphabetical_order(include)
            if not include_state.is_in_alphabetical_order(clean_lines, linenum, canonical_include):
                error(
                    state,
                    filename,
                    linenum,
                    "build/include_alpha",
                    4,
                    'Include "%s" not in alphabetical order' % include,
                )
            include_state.set_last_header(canonical_include)


def CheckCasts(state, filename, clean_lines, linenum, error):
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
        r"(\bnew\s+(?:const\s+)?|\S<\s*(?:const\s+)?)?\b"
        r"(int|float|double|bool|char|int32|uint32|int64|uint64)"
        r"(\([^)].*)",
        line,
    )
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
        if Match(r"\([^()]+\)\s*\[", match.group(3)):
            return

        # Other things to ignore:
        # - Function pointers
        # - Casts to pointer types
        # - Placement new
        # - Alias declarations
        matched_funcptr = match.group(3)
        if (
            matched_new_or_template is None
            and not (
                matched_funcptr
                and (
                    Match(r"\((?:[^() ]+::\s*\*\s*)?[^() ]+\)\s*\(", matched_funcptr)
                    or matched_funcptr.startswith("(*)")
                )
            )
            and not Match(r"\s*using\s+\S+\s*=\s*" + matched_type, line)
            and not Search(r"new\(\S+\)\s*" + matched_type, line)
        ):
            error(
                state,
                filename,
                linenum,
                "readability/casting",
                4,
                "Using deprecated casting style.  " "Use static_cast<%s>(...) instead" % matched_type,
            )

    if not expecting_function:
        CheckCStyleCast(
            state,
            filename,
            clean_lines,
            linenum,
            "static_cast",
            r"\((int|float|double|bool|char|u?int(16|32|64)|size_t)\)",
            error,
        )

    # This doesn't catch all cases. Consider (const char * const)"hello".
    #
    # (char *) "foo" should always be a const_cast (reinterpret_cast won't
    # compile).
    if CheckCStyleCast(
        state,
        filename,
        clean_lines,
        linenum,
        "const_cast",
        r'\((char\s?\*+\s?)\)\s*"',
        error,
    ):
        pass
    else:
        # Check pointer casts for other than string constants
        CheckCStyleCast(
            state,
            filename,
            clean_lines,
            linenum,
            "reinterpret_cast",
            r"\((\w+\s?\*+\s?)\)",
            error,
        )

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
        r"(?:[^\w]&\(([^)*][^)]*)\)[\w(])|" r"(?:[^\w]&(static|dynamic|down|reinterpret)_cast\b)",
        line,
    )
    if match:
        # Try a better error message when the & is bound to something
        # dereferenced by the casted pointer, as opposed to the casted
        # pointer itself.
        parenthesis_error = False
        match = Match(r"^(.*&(?:static|dynamic|down|reinterpret)_cast\b)<", line)
        if match:
            _, y1, x1 = CloseExpression(clean_lines, linenum, len(match.group(1)))
            if x1 >= 0 and clean_lines.elided[y1][x1] == "(":
                _, y2, x2 = CloseExpression(clean_lines, y1, x1)
                if x2 >= 0:
                    extended_line = clean_lines.elided[y2][x2:]
                    if y2 < clean_lines.num_lines() - 1:
                        extended_line += clean_lines.elided[y2 + 1]
                    if Match(r"\s*(?:->|\[)", extended_line):
                        parenthesis_error = True

        if parenthesis_error:
            error(
                state,
                filename,
                linenum,
                "readability/casting",
                4,
                (
                    "Are you taking an address of something dereferenced "
                    "from a cast?  Wrapping the dereferenced expression in "
                    "parentheses will make the binding more obvious"
                ),
            )
        else:
            error(
                state,
                filename,
                linenum,
                "runtime/casting",
                4,
                (
                    "Are you taking an address of a cast?  "
                    "This is dangerous: could be a temp var.  "
                    "Take the address before doing the cast, rather than after"
                ),
            )


def CheckCStyleCast(state, filename, clean_lines, linenum, cast_type, pattern, error):
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
    context = line[0 : match.start(1) - 1]
    if Match(r".*\b(?:sizeof|alignof|alignas|[_A-Z][_A-Z0-9]*)\s*$", context):
        return False

    # Try expanding current context to see if we one level of
    # parentheses inside a macro.
    if linenum > 0:
        for i in range(linenum - 1, max(0, linenum - 5), -1):
            context = clean_lines.elided[i] + context
    if Match(r".*\b[_A-Z][_A-Z0-9]*\s*\((?:\([^()]*\)|[^()])*$", context):
        return False

    # operator++(int) and operator--(int)
    if (
        context.endswith(" operator++")
        or context.endswith(" operator--")
        or context.endswith("::operator++")
        or context.endswith("::operator--")
    ):
        return False

    # A single unnamed argument for a function tends to look like old style cast.
    # If we see those, don't issue warnings for deprecated casts.
    remainder = line[match.end(0) :]
    if Match(r"^\s*(?:;|const\b|throw\b|final\b|override\b|[=>{),]|->)", remainder):
        return False

    # At this point, all that should be left is actual casts.
    error(
        state,
        filename,
        linenum,
        "readability/casting",
        4,
        "Using C-style cast.  Use %s<%s>(...) instead" % (cast_type, match.group(1)),
    )

    return True


def CheckGlobalStatic(state, filename, clean_lines, linenum, error):
    """Check for unsafe global or static objects.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # Match two lines at a time to support multiline declarations
    if linenum + 1 < clean_lines.num_lines() and not Search(r"[;({]", line):
        line += clean_lines.elided[linenum + 1].strip()

    # Check for people declaring static/global STL strings at the top level.
    # This is dangerous because the C++ language does not guarantee that
    # globals with constructors are initialized before the first access, and
    # also because globals can be destroyed when some threads are still running.
    # TODO(unknown): Generalize this to also find static unique_ptr instances.
    # TODO(unknown): File bugs for clang-tidy to find these.
    match = Match(
        r"((?:|static +)(?:|const +))(?::*std::)?string( +const)? +" r"([a-zA-Z0-9_:]+)\b(.*)",
        line,
    )

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
    if (
        match
        and not Search(r"\bstring\b(\s+const)?\s*[\*\&]\s*(const\s+)?\w", line)
        and not Search(r"\boperator\W", line)
        and not Match(r'\s*(<.*>)?(::[a-zA-Z0-9_]+)*\s*\(([^"]|$)', match.group(4))
    ):
        if Search(r"\bconst\b", line):
            error(
                state,
                filename,
                linenum,
                "runtime/string",
                4,
                "For a static/global string constant, use a C style string "
                'instead: "%schar%s %s[]".' % (match.group(1), match.group(2) or "", match.group(3)),
            )
        else:
            error(
                state,
                filename,
                linenum,
                "runtime/string",
                4,
                "Static/global string variables are not permitted.",
            )

    if Search(r"\b([A-Za-z0-9_]*_)\(\1\)", line) or Search(r"\b([A-Za-z0-9_]*_)\(CHECK_NOTNULL\(\1\)\)", line):
        error(
            state,
            filename,
            linenum,
            "runtime/init",
            4,
            "You seem to be initializing a member variable with itself.",
        )


def CheckPrintf(state, filename, clean_lines, linenum, error):
    """Check for printf related issues.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # When snprintf is used, the second argument shouldn't be a literal.
    match = Search(r"snprintf\s*\(([^,]*),\s*([0-9]*)\s*,", line)
    if match and match.group(2) != "0":
        # If 2nd arg is zero, snprintf is used to calculate size.
        error(
            state,
            filename,
            linenum,
            "runtime/printf",
            3,
            "If you can, use sizeof(%s) instead of %s as the 2nd arg "
            "to snprintf." % (match.group(1), match.group(2)),
        )

    # Check if some verboten C functions are being used.
    if Search(r"\bsprintf\s*\(", line):
        error(
            state,
            filename,
            linenum,
            "runtime/printf",
            5,
            "Never use sprintf. Use snprintf instead.",
        )
    match = Search(r"\b(strcpy|strcat)\s*\(", line)
    if match:
        error(
            state,
            filename,
            linenum,
            "runtime/printf",
            4,
            "Almost always, snprintf is better than %s" % match.group(1),
        )
