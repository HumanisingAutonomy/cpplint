import re

from .block_info import (
    CloseExpression,
    IsBlockInNameSpace,
    IsDerivedFunction,
    IsForwardClassDeclaration,
    IsInitializerList,
    IsMacroDefinition,
    IsOutOfLineMethodDefinition,
    ReverseCloseExpression,
    _ClassInfo,
    _NamespaceInfo,
)
from .categories import _ERROR_CATEGORIES
from .check_language import CheckLanguage
from .check_style import CheckStyle
from .lintstate import LintState
from .regex import Match, ReplaceAll, Search


def ProcessLine(
    state: LintState,
    filename,
    file_extension,
    clean_lines,
    line,
    include_state,
    function_state,
    nesting_state,
    error,
    extra_check_functions=None,
):
    """Processes a single line in the file.

    Args:
      state: The current state of the linting
      filename: Filename of the file that is being processed.
      file_extension: The extension (dot not included) of the file.
      clean_lines: An array of strings, each representing a line of the file,
                   with comments stripped.
      line: Number of line being processed.
      include_state: An IncludeState instance in which the headers are inserted.
      function_state: A FunctionState instance which counts function lines, etc.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: A callable to which errors are reported, which takes 4 arguments:
             file_name, line number, error level, and message
      extra_check_functions: An array of additional check functions that will be
                             run on each source line. Each function takes 4
                             arguments: file_name, clean_lines, line, error
    """
    raw_lines = clean_lines.raw_lines
    ParseNolintSuppressions(state, filename, raw_lines[line], line, error)
    nesting_state.update(state, clean_lines, line, error)
    CheckForNamespaceIndentation(state, filename, nesting_state, clean_lines, line, error)
    if nesting_state.is_asm_block():
        return
    CheckForFunctionLengths(state, filename, clean_lines, line, function_state, error)
    CheckForMultilineCommentsAndStrings(state, filename, clean_lines, line, error)
    CheckStyle(state, filename, clean_lines, line, file_extension, nesting_state, error)
    CheckLanguage(
        state,
        filename,
        clean_lines,
        line,
        file_extension,
        include_state,
        nesting_state,
        error,
    )
    CheckForNonConstReference(state, filename, clean_lines, line, nesting_state, error)
    CheckForNonStandardConstructs(state, filename, clean_lines, line, nesting_state, error)
    CheckVlogArguments(state, filename, clean_lines, line, error)
    CheckPosixThreading(state, filename, clean_lines, line, error)
    CheckInvalidIncrement(state, filename, clean_lines, line, error)
    CheckMakePairUsesDeduction(state, filename, clean_lines, line, error)
    CheckRedundantVirtual(state, filename, clean_lines, line, error)
    CheckRedundantOverrideOrFinal(state, filename, clean_lines, line, error)
    if extra_check_functions:
        for check_fn in extra_check_functions:
            check_fn(filename, clean_lines, line, error)


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


def ParseNolintSuppressions(state: LintState, filename, raw_line, linenum, error):
    """Updates the global list of line error-suppressions.

    Parses any NOLINT comments on the current line, updating the global
    error_suppressions store.  Reports an error if the NOLINT comment
    was malformed.

    Args:
      filename: str, the name of the input file.
      raw_line: str, the line of input text, with comments.
      linenum: int, the number of the current line.
      error: function, an error handler.
    """
    matched = Search(r"\bNOLINT(NEXTLINE)?\b(\([^)]+\))?", raw_line)
    if matched:
        if matched.group(1):
            suppressed_line = linenum + 1
        else:
            suppressed_line = linenum
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
                        state,
                        filename,
                        linenum,
                        "readability/nolint",
                        5,
                        "Unknown NOLINT error category: %s" % category,
                    )


def CheckForNamespaceIndentation(state, filename, nesting_state, clean_lines, line, error):
    is_namespace_indent_item = (
        len(nesting_state.stack) > 1
        and nesting_state.stack[-1].check_namespace_indentation
        and isinstance(nesting_state.previous_stack_top, _NamespaceInfo)
        and nesting_state.previous_stack_top == nesting_state.stack[-2]
    )

    if ShouldCheckNamespaceIndentation(nesting_state, is_namespace_indent_item, clean_lines.elided, line):
        CheckItemIndentationInNamespace(state, filename, clean_lines.elided, line, error)


def ShouldCheckNamespaceIndentation(nesting_state, is_namespace_indent_item, raw_lines_no_comments, linenum):
    """This method determines if we should apply our namespace indentation check.

    Args:
      nesting_state: The current nesting state.
      is_namespace_indent_item: If we just put a new class on the stack, True.
        If the top of the stack is not a class, or we did not recently
        add the class, False.
      raw_lines_no_comments: The lines without the comments.
      linenum: The current line number we are processing.

    Returns:
      True if we should apply our namespace indentation check. Currently, it
      only works for classes and namespaces inside of a namespace.
    """

    is_forward_declaration = IsForwardClassDeclaration(raw_lines_no_comments, linenum)

    if not (is_namespace_indent_item or is_forward_declaration):
        return False

    # If we are in a macro, we do not want to check the namespace indentation.
    if IsMacroDefinition(raw_lines_no_comments, linenum):
        return False

    return IsBlockInNameSpace(nesting_state, is_forward_declaration)


# Call this method if the line is directly inside of a namespace.
# If the line above is blank (excluding comments) or the start of
# an inner namespace, it cannot be indented.
def CheckItemIndentationInNamespace(state, filename, raw_lines_no_comments, linenum, error):
    line = raw_lines_no_comments[linenum]
    if Match(r"^\s+", line):
        error(
            state,
            filename,
            linenum,
            "runtime/indentation_namespace",
            4,
            "Do not indent within a namespace",
        )


def CheckForFunctionLengths(state: LintState, filename, clean_lines, linenum, function_state, error):
    """Reports for int function bodies.

    For an overview why this is done, see:
    https://google-styleguide.googlecode.com/svn/trunk/cppguide.xml#Write_Short_Functions

    Uses a simplistic algorithm assuming other style guidelines
    (especially spacing) are followed.
    Only checks unindented functions, so class members are unchecked.
    Trivial bodies are unchecked, so constructors with huge initializer lists
    may be missed.
    Blank/comment lines are not counted so as to avoid encouraging the removal
    of vertical space and comments just to get through a lint check.
    NOLINT *on the last line of a function* disables this check.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      function_state: Current function name and lines in body so far.
      error: The function to call with any errors found.
    """
    lines = clean_lines.lines
    line = lines[linenum]
    joined_line = ""

    starting_func = False
    regexp = r"(\w(\w|::|\*|\&|\s)*)\("  # decls * & space::name( ...
    match_result = Match(regexp, line)
    if match_result:
        # If the name is all caps and underscores, figure it's a macro and
        # ignore it, unless it's TEST or TEST_F.
        function_name = match_result.group(1).split()[-1]
        if function_name == "TEST" or function_name == "TEST_F" or (not Match(r"[A-Z_]+$", function_name)):
            starting_func = True

    if starting_func:
        body_found = False
        for start_linenum in range(linenum, clean_lines.num_lines()):
            start_line = lines[start_linenum]
            joined_line += " " + start_line.lstrip()
            if Search(r"(;|})", start_line):  # Declarations and trivial functions
                body_found = True
                break  # ... ignore
            if Search(r"{", start_line):
                body_found = True
                function = Search(r"((\w|:)*)\(", line).group(1)
                if Match(r"TEST", function):  # Handle TEST... macros
                    parameter_regexp = Search(r"(\(.*\))", joined_line)
                    if parameter_regexp:  # Ignore bad syntax
                        function += parameter_regexp.group(1)
                else:
                    function += "()"
                function_state.begin(function)
                break
        if not body_found:
            # No body for the function (or evidence of a non-function) was found.
            error(
                state,
                filename,
                linenum,
                "readability/fn_size",
                5,
                "Lint failed to find start of function body.",
            )
    elif Match(r"^\}\s*$", line):  # function end
        function_state.check(state, error, filename, linenum)
        function_state.end()
    elif not Match(r"^\s*$", line):
        function_state.count()  # Count non-blank/non-comment lines.


def CheckForMultilineCommentsAndStrings(state, filename, clean_lines, linenum, error):
    """Logs an error if we see /* ... */ or "..." that extend past one line.

    /* ... */ comments are legit inside macros, for one line.
    Otherwise, we prefer // comments, so it's ok to warn about the
    other.  Likewise, it's ok for strings to extend across multiple
    lines, as long as a line continuation character (backslash)
    terminates each line. Although not currently prohibited by the C++
    style guide, it's ugly and unnecessary. We don't do well with either
    in this lint program, so we warn about both.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # Remove all \\ (escaped backslashes) from the line. They are OK, and the
    # second (escaped) slash may trigger later \" detection erroneously.
    line = line.replace("\\\\", "")

    if line.count("/*") > line.count("*/"):
        error(
            state,
            filename,
            linenum,
            "readability/multiline_comment",
            5,
            "Complex multi-line /*...*/-style comment found. "
            "Lint may give bogus warnings.  "
            "Consider replacing these with //-style comments, "
            "with #if 0...#endif, "
            "or with more clearly structured multi-line comments.",
        )

    if (line.count('"') - line.count('\\"')) % 2:
        error(
            state,
            filename,
            linenum,
            "readability/multiline_string",
            5,
            'Multi-line string ("...") found.  This lint script doesn\'t '
            "do well with such strings, and may give bogus warnings.  "
            "Use C++11 raw strings or concatenation instead.",
        )


def CheckForNonConstReference(state, filename, clean_lines, linenum, nesting_state, error):
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
    if "&" not in line:
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
        if Match(r"\s*::(?:[\w<>]|::)+\s*&\s*\S", line):
            # previous_line\n + ::current_line
            previous = Search(
                r"\b((?:const\s*)?(?:[\w<>]|::)+[\w<>])\s*$",
                clean_lines.elided[linenum - 1],
            )
        elif Match(r"\s*[a-zA-Z_]([\w<>]|::)+\s*&\s*\S", line):
            # previous_line::\n + current_line
            previous = Search(
                r"\b((?:const\s*)?(?:[\w<>]|::)+::)\s*$",
                clean_lines.elided[linenum - 1],
            )
        if previous:
            line = previous.group(1) + line.lstrip()
        else:
            # Check for templated parameter that is split across multiple lines
            endpos = line.rfind(">")
            if endpos > -1:
                (_, startline, startpos) = ReverseCloseExpression(clean_lines, linenum, endpos)
                if startpos > -1 and startline < linenum:
                    # Found the matching < on an earlier line, collect all
                    # pieces up to current line.
                    line = ""
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
    if nesting_state.previous_stack_top and not (
        isinstance(nesting_state.previous_stack_top, _ClassInfo)
        or isinstance(nesting_state.previous_stack_top, _NamespaceInfo)
    ):
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
            if not Search(r"[),]\s*$", previous_line):
                break
            if Match(r"^\s*:\s+\S", previous_line):
                return

    # Avoid preprocessors
    if Search(r"\\\s*$", line):
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
    allowed_functions = r"(?:[sS]wap(?:<\w:+>)?|" r"operator\s*[<>][<>]|" r"static_assert|COMPILE_ASSERT" r")\s*\("
    if Search(allowed_functions, line):
        return
    elif not Search(r"\S+\([^)]*$", line):
        # Don't see an allowed function on this line.  Actually we
        # didn't see any function name on this line, so this is likely a
        # multi-line parameter list.  Try a bit harder to catch this case.
        for i in range(2):
            if linenum > i and Search(allowed_functions, clean_lines.elided[linenum - i - 1]):
                return

    # Patterns for matching call-by-reference parameters.
    #
    # Supports nested templates up to 2 levels deep using this messy pattern:
    #   < (?: < (?: < [^<>]*
    #               >
    #           |   [^<>] )*
    #         >
    #     |   [^<>] )*
    #   >
    _RE_PATTERN_IDENT = r"[_a-zA-Z]\w*"  # =~ [[:alpha:]][[:alnum:]]*
    _RE_PATTERN_TYPE = (
        r"(?:const\s+)?(?:typename\s+|class\s+|struct\s+|union\s+|enum\s+)?"
        r"(?:\w|"
        r"\s*<(?:<(?:<[^<>]*>|[^<>])*>|[^<>])*>|"
        r"::)+"
    )
    # A call-by-reference parameter ends with '& identifier'.
    _RE_PATTERN_REF_PARAM = re.compile(
        r"(" + _RE_PATTERN_TYPE + r"(?:\s*(?:\bconst\b|[*]))*\s*" r"&\s*" + _RE_PATTERN_IDENT + r")\s*(?:=[^,()]+)?[,)]"
    )
    # A call-by-const-reference parameter either ends with 'const& identifier'
    # or looks like 'const type& identifier' when 'type' is atomic.
    _RE_PATTERN_CONST_REF_PARAM = (
        r"(?:.*\s*\bconst\s*&\s*"
        + _RE_PATTERN_IDENT
        + r"|const\s+"
        + _RE_PATTERN_TYPE
        + r"\s*&\s*"
        + _RE_PATTERN_IDENT
        + r")"
    )
    # Stream types.
    _RE_PATTERN_REF_STREAM_PARAM = r"(?:.*stream\s*&\s*" + _RE_PATTERN_IDENT + r")"

    decls = ReplaceAll(r"{[^}]*}", " ", line)  # exclude function body
    for parameter in re.findall(_RE_PATTERN_REF_PARAM, decls):
        if not Match(_RE_PATTERN_CONST_REF_PARAM, parameter) and not Match(_RE_PATTERN_REF_STREAM_PARAM, parameter):
            error(
                state,
                filename,
                linenum,
                "runtime/references",
                2,
                "Is this a non-const reference? "
                "If so, make const or use a pointer: " + ReplaceAll(" *<", "<", parameter),
            )


def CheckForNonStandardConstructs(state, filename, clean_lines, linenum, nesting_state, error):
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
             file_name, line number, error level, and message
    """

    # Remove comments from the line, but leave in strings for now.
    line = clean_lines.lines[linenum]

    if Search(r'printf\s*\(.*".*%[-+ ]?\d*q', line):
        error(
            state,
            filename,
            linenum,
            "runtime/printf_format",
            3,
            "%q in format strings is deprecated.  Use %ll instead.",
        )

    if Search(r'printf\s*\(.*".*%\d+\$', line):
        error(
            state,
            filename,
            linenum,
            "runtime/printf_format",
            2,
            "%N$ formats are unconventional.  Try rewriting to avoid them.",
        )

    # Remove escaped backslashes before looking for undefined escapes.
    line = line.replace("\\\\", "")

    if Search(r'("|\').*\\(%|\[|\(|{)', line):
        error(
            state,
            filename,
            linenum,
            "build/printf_format",
            3,
            "%, [, (, and { are undefined character escapes.  Unescape them.",
        )

    # For the rest, work with both comments and strings removed.
    line = clean_lines.elided[linenum]

    if Search(
        r"\b(const|volatile|void|char|short|int|int"
        r"|float|double|signed|unsigned"
        r"|schar|u?int8|u?int16|u?int32|u?int64)"
        r"\s+(register|static|extern|typedef)\b",
        line,
    ):
        error(
            state,
            filename,
            linenum,
            "build/storage_class",
            5,
            "Storage-class specifier (static, extern, typedef, etc) should be " "at the beginning of the declaration.",
        )

    if Match(r"\s*#\s*endif\s*[^/\s]+", line):
        error(
            state,
            filename,
            linenum,
            "build/endif_comment",
            5,
            "Uncommented text after #endif is non-standard.  Use a comment.",
        )

    if Match(r"\s*class\s+(\w+\s*::\s*)+\w+\s*;", line):
        error(
            state,
            filename,
            linenum,
            "build/forward_decl",
            5,
            "Inner-style forward declarations are invalid.  Remove this line.",
        )

    if Search(r"(\w+|[+-]?\d+(\.\d*)?)\s*(<|>)\?=?\s*(\w+|[+-]?\d+)(\.\d*)?", line):
        error(
            state,
            filename,
            linenum,
            "build/deprecated",
            3,
            ">? and <? (max and min) operators are non-standard and deprecated.",
        )

    if Search(r"^\s*const\s*string\s*&\s*\w+\s*;", line):
        # TODO(unknown): Could it be expanded safely to arbitrary references,
        # without triggering too many false positives? The first
        # attempt triggered 5 warnings for mostly benign code in the regtest, hence
        # the restriction.
        # Here's the original regexp, for the reference:
        # type_name = r'\w+((\s*::\s*\w+)|(\s*<\s*\w+?\s*>))?'
        # r'\s*const\s*' + type_name + '\s*&\s*\w+\s*;'
        error(
            state,
            filename,
            linenum,
            "runtime/member_string_references",
            2,
            "const string& members are dangerous. It is much better to use "
            "alternatives, such as pointers or simple constants.",
        )

    # Everything else in this function operates on class declarations.
    # Return early if the top of the nesting stack is not a class, or if
    # the class head is not completed yet.
    classinfo = nesting_state.innermost_class()
    if not classinfo or not classinfo.seen_open_brace:
        return

    # The class may have been declared with namespace or classname qualifiers.
    # The constructor and destructor will not have those qualifiers.
    base_classname = classinfo.name.split("::")[-1]

    # Look for single-argument constructors that aren't marked explicit.
    # Technically a valid construct, but against style.
    explicit_constructor_match = Match(
        r"\s+(?:(?:inline|constexpr)\s+)*(explicit\s+)?"
        r"(?:(?:inline|constexpr)\s+)*%s\s*"
        r"\(((?:[^()]|\([^()]*\))*)\)" % re.escape(base_classname),
        line,
    )

    if explicit_constructor_match:
        is_marked_explicit = explicit_constructor_match.group(1)

        if not explicit_constructor_match.group(2):
            constructor_args = []
        else:
            constructor_args = explicit_constructor_match.group(2).split(",")

        # collapse arguments so that commas in template parameter lists and function
        # argument parameter lists don't split arguments in two
        i = 0
        while i < len(constructor_args):
            constructor_arg = constructor_args[i]
            while constructor_arg.count("<") > constructor_arg.count(">") or constructor_arg.count(
                "("
            ) > constructor_arg.count(")"):
                constructor_arg += "," + constructor_args[i + 1]
                del constructor_args[i + 1]
            constructor_args[i] = constructor_arg
            i += 1

        variadic_args = [arg for arg in constructor_args if "&&..." in arg]
        defaulted_args = [arg for arg in constructor_args if "=" in arg]
        noarg_constructor = (
            not constructor_args
            # empty arg list
            # 'void' arg specifier
            or (len(constructor_args) == 1 and constructor_args[0].strip() == "void")
        )
        onearg_constructor = (
            (len(constructor_args) == 1 and not noarg_constructor)  # exactly one arg
            or (
                # all but at most one arg defaulted
                len(constructor_args) >= 1
                and not noarg_constructor
                and len(defaulted_args) >= len(constructor_args) - 1
            )
            # variadic arguments with zero or one argument
            or (len(constructor_args) <= 2 and len(variadic_args) >= 1)
        )
        initializer_list_constructor = bool(
            onearg_constructor and Search(r"\bstd\s*::\s*initializer_list\b", constructor_args[0])
        )
        copy_constructor = bool(
            onearg_constructor
            and Match(
                r"((const\s+(volatile\s+)?)?|(volatile\s+(const\s+)?))?"
                r"%s(\s*<[^>]*>)?(\s+const)?\s*(?:<\w+>\s*)?&" % re.escape(base_classname),
                constructor_args[0].strip(),
            )
        )

        if not is_marked_explicit and onearg_constructor and not initializer_list_constructor and not copy_constructor:
            if defaulted_args or variadic_args:
                error(
                    state,
                    filename,
                    linenum,
                    "runtime/explicit",
                    5,
                    "Constructors callable with one argument " "should be marked explicit.",
                )
            else:
                error(
                    state,
                    filename,
                    linenum,
                    "runtime/explicit",
                    5,
                    "Single-parameter constructors should be marked explicit.",
                )
        elif is_marked_explicit and not onearg_constructor:
            if noarg_constructor:
                error(
                    state,
                    filename,
                    linenum,
                    "runtime/explicit",
                    5,
                    "Zero-parameter constructors should not be marked explicit.",
                )


def CheckVlogArguments(state, filename, clean_lines, linenum, error):
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
    if Search(r"\bVLOG\((INFO|ERROR|WARNING|DFATAL|FATAL)\)", line):
        error(
            state,
            filename,
            linenum,
            "runtime/vlog",
            5,
            "VLOG() should be used with numeric verbosity level.  " "Use LOG() if you want symbolic severity levels.",
        )


def CheckPosixThreading(state, filename, clean_lines, linenum, error):
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
    _UNSAFE_FUNC_PREFIX = r"(?:[-+*/=%^&|(<]\s*|>\s+)"
    _THREADING_LIST = (
        ("asctime(", "asctime_r(", _UNSAFE_FUNC_PREFIX + r"asctime\([^)]+\)"),
        ("ctime(", "ctime_r(", _UNSAFE_FUNC_PREFIX + r"ctime\([^)]+\)"),
        ("getgrgid(", "getgrgid_r(", _UNSAFE_FUNC_PREFIX + r"getgrgid\([^)]+\)"),
        ("getgrnam(", "getgrnam_r(", _UNSAFE_FUNC_PREFIX + r"getgrnam\([^)]+\)"),
        ("getlogin(", "getlogin_r(", _UNSAFE_FUNC_PREFIX + r"getlogin\(\)"),
        ("getpwnam(", "getpwnam_r(", _UNSAFE_FUNC_PREFIX + r"getpwnam\([^)]+\)"),
        ("getpwuid(", "getpwuid_r(", _UNSAFE_FUNC_PREFIX + r"getpwuid\([^)]+\)"),
        ("gmtime(", "gmtime_r(", _UNSAFE_FUNC_PREFIX + r"gmtime\([^)]+\)"),
        ("localtime(", "localtime_r(", _UNSAFE_FUNC_PREFIX + r"localtime\([^)]+\)"),
        ("rand(", "rand_r(", _UNSAFE_FUNC_PREFIX + r"rand\(\)"),
        ("strtok(", "strtok_r(", _UNSAFE_FUNC_PREFIX + r"strtok\([^)]+\)"),
        ("ttyname(", "ttyname_r(", _UNSAFE_FUNC_PREFIX + r"ttyname\([^)]+\)"),
    )

    line = clean_lines.elided[linenum]
    for single_thread_func, multithread_safe_func, pattern in _THREADING_LIST:
        # Additional pattern matching check to confirm that this is the
        # function we are looking for
        if Search(pattern, line):
            error(
                state,
                filename,
                linenum,
                "runtime/threadsafe_fn",
                2,
                "Consider using "
                + multithread_safe_func
                + "...) instead of "
                + single_thread_func
                + "...) for improved thread safety.",
            )


def CheckInvalidIncrement(state, filename, clean_lines, linenum, error):
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

    # Matches invalid increment: *count++, which moves pointer instead of
    # incrementing a value.
    _RE_PATTERN_INVALID_INCREMENT = re.compile(r"^\s*\*\w+(\+\+|--);")

    line = clean_lines.elided[linenum]
    if _RE_PATTERN_INVALID_INCREMENT.match(line):
        error(
            state,
            filename,
            linenum,
            "runtime/invalid_increment",
            5,
            "Changing pointer instead of value (or unused value of operator*).",
        )


def CheckMakePairUsesDeduction(state, filename, clean_lines, linenum, error):
    """Check that make_pair's template arguments are deduced.

    G++ 4.6 in C++11 mode fails badly if make_pair's template arguments are
    specified explicitly, and such use isn't intended in any case.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """

    _RE_PATTERN_EXPLICIT_MAKEPAIR = re.compile(r"\bmake_pair\s*<")

    line = clean_lines.elided[linenum]
    match = _RE_PATTERN_EXPLICIT_MAKEPAIR.search(line)
    if match:
        error(
            state,
            filename,
            linenum,
            "build/explicit_make_pair",
            4,  # 4 = high confidence
            "For C++11-compatibility, omit template arguments from make_pair"
            " OR use pair directly OR if appropriate, construct a pair directly",
        )


def CheckRedundantVirtual(state, filename, clean_lines, linenum, error):
    """Check if line contains a redundant "virtual" function-specifier.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    # Look for "virtual" on current line.
    line = clean_lines.elided[linenum]
    virtual = Match(r"^(.*)(\bvirtual\b)(.*)$", line)
    if not virtual:
        return

    # Ignore "virtual" keywords that are near access-specifiers.  These
    # are only used in class base-specifier and do not apply to member
    # functions.
    if Search(r"\b(public|protected|private)\s+$", virtual.group(1)) or Match(
        r"^\s+(public|protected|private)\b", virtual.group(3)
    ):
        return

    # Ignore the "virtual" keyword from virtual base classes.  Usually
    # there is a column on the same line in these cases (virtual base
    # classes are rare in google3 because multiple inheritance is rare).
    if Match(r"^.*[^:]:[^:].*$", line):
        return

    # Look for the next opening parenthesis.  This is the start of the
    # parameter list (possibly on the next line shortly after virtual).
    # TODO(unknown): doesn't work if there are virtual functions with
    # decltype() or other things that use parentheses, but csearch suggests
    # that this is rare.
    end_col = -1
    end_line = -1
    start_col = len(virtual.group(2))
    for start_line in range(linenum, min(linenum + 3, clean_lines.num_lines())):
        line = clean_lines.elided[start_line][start_col:]
        parameter_list = Match(r"^([^(]*)\(", line)
        if parameter_list:
            # Match parentheses to find the end of the parameter list
            (_, end_line, end_col) = CloseExpression(clean_lines, start_line, start_col + len(parameter_list.group(1)))
            break
        start_col = 0

    if end_col < 0:
        return  # Couldn't find end of parameter list, give up

    # Look for "override" or "final" after the parameter list
    # (possibly on the next few lines).
    for i in range(end_line, min(end_line + 3, clean_lines.num_lines())):
        line = clean_lines.elided[i][end_col:]
        match = Search(r"\b(override|final)\b", line)
        if match:
            error(
                state,
                filename,
                linenum,
                "readability/inheritance",
                4,
                ('"virtual" is redundant since function is ' 'already declared as "%s"' % match.group(1)),
            )

        # Set end_col to check whole lines after we are done with the
        # first line.
        end_col = 0
        if Search(r"[^\w]\s*$", line):
            break


def CheckRedundantOverrideOrFinal(state, filename, clean_lines, linenum, error):
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
    declarator_end = line.rfind(")")
    if declarator_end >= 0:
        fragment = line[declarator_end:]
    else:
        if linenum > 1 and clean_lines.elided[linenum - 1].rfind(")") >= 0:
            fragment = line
        else:
            return

    # Check that at most one of "override" or "final" is present, not both
    if Search(r"\boverride\b", fragment) and Search(r"\bfinal\b", fragment):
        error(
            state,
            filename,
            linenum,
            "readability/inheritance",
            4,
            ('"override" is redundant since function is ' 'already declared as "final"'),
        )
