from ._cpplintstate import _CppLintState
from .regex import Match, Search
from .categories import _ERROR_CATEGORIES
from .block_info import _NamespaceInfo, IsForwardClassDeclaration, IsMacroDefinition, IsBlockInNameSpace

# These error categories are no longer enforced by cpplint, but for backwards-
# compatibility they may still appear in NOLINT comments.
_LEGACY_ERROR_CATEGORIES = [
    'readability/streams',
    'readability/function',
    ]

# These prefixes for categories should be ignored since they relate to other
# tools which also use the NOLINT syntax, e.g. clang-tidy.
_OTHER_NOLINT_CATEGORY_PREFIXES = [
    'clang-analyzer',
    ]

def ParseNolintSuppressions(state: _CppLintState, filename, raw_line, linenum, error):
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
    matched = Search(r'\bNOLINT(NEXTLINE)?\b(\([^)]+\))?', raw_line)
    if matched:
        if matched.group(1):
            suppressed_line = linenum + 1
        else:
            suppressed_line = linenum
        category = matched.group(2)
        if category in (None, '(*)'):  # => "suppress all"
            state._error_suppressions.setdefault(None, set()).add(suppressed_line)
        else:
            if category.startswith('(') and category.endswith(')'):
                category = category[1:-1]
                if category in _ERROR_CATEGORIES:
                   state._error_suppressions.setdefault(category, set()).add(suppressed_line)
                elif any(c for c in _OTHER_NOLINT_CATEGORY_PREFIXES if category.startswith(c)):
                    # Ignore any categories from other tools.
                    pass
                elif category not in _LEGACY_ERROR_CATEGORIES:
                    error(filename, linenum, 'readability/nolint', 5,
                          'Unknown NOLINT error category: %s' % category)

def CheckForNamespaceIndentation(filename, nesting_state, clean_lines, line,
                                 error):
    is_namespace_indent_item = (
        len(nesting_state.stack) > 1 and
        nesting_state.stack[-1].check_namespace_indentation and
        isinstance(nesting_state.previous_stack_top, _NamespaceInfo) and
        nesting_state.previous_stack_top == nesting_state.stack[-2])

    if ShouldCheckNamespaceIndentation(nesting_state, is_namespace_indent_item,
                                       clean_lines.elided, line):
        CheckItemIndentationInNamespace(filename, clean_lines.elided,
                                        line, error)

def ShouldCheckNamespaceIndentation(nesting_state, is_namespace_indent_item,
                                    raw_lines_no_comments, linenum):
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

    is_forward_declaration = IsForwardClassDeclaration(raw_lines_no_comments,
                                                       linenum)

    if not (is_namespace_indent_item or is_forward_declaration):
        return False

    # If we are in a macro, we do not want to check the namespace indentation.
    if IsMacroDefinition(raw_lines_no_comments, linenum):
        return False

    return IsBlockInNameSpace(nesting_state, is_forward_declaration)

# Call this method if the line is directly inside of a namespace.
# If the line above is blank (excluding comments) or the start of
# an inner namespace, it cannot be indented.
def CheckItemIndentationInNamespace(filename, raw_lines_no_comments, linenum,
                                    error):
    line = raw_lines_no_comments[linenum]
    if Match(r'^\s+', line):
        error(filename, linenum, 'runtime/indentation_namespace', 4,
              'Do not indent within a namespace')

def CheckForFunctionLengths(state: _CppLintState, filename, clean_lines, linenum,
                            function_state, error):
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
    joined_line = ''

    starting_func = False
    regexp = r'(\w(\w|::|\*|\&|\s)*)\('  # decls * & space::name( ...
    match_result = Match(regexp, line)
    if match_result:
        # If the name is all caps and underscores, figure it's a macro and
        # ignore it, unless it's TEST or TEST_F.
        function_name = match_result.group(1).split()[-1]
        if function_name == 'TEST' or function_name == 'TEST_F' or (
            not Match(r'[A-Z_]+$', function_name)):
            starting_func = True

    if starting_func:
        body_found = False
        for start_linenum in range(linenum, clean_lines.NumLines()):
            start_line = lines[start_linenum]
            joined_line += ' ' + start_line.lstrip()
            if Search(r'(;|})', start_line):  # Declarations and trivial functions
                body_found = True
                break                              # ... ignore
            if Search(r'{', start_line):
                body_found = True
                function = Search(r'((\w|:)*)\(', line).group(1)
                if Match(r'TEST', function):    # Handle TEST... macros
                    parameter_regexp = Search(r'(\(.*\))', joined_line)
                    if parameter_regexp:             # Ignore bad syntax
                        function += parameter_regexp.group(1)
                else:
                    function += '()'
                function_state.Begin(function)
                break
        if not body_found:
            # No body for the function (or evidence of a non-function) was found.
            error(filename, linenum, 'readability/fn_size', 5,
                  'Lint failed to find start of function body.')
    elif Match(r'^\}\s*$', line):  # function end
        function_state.Check(state, error, filename, linenum)
        function_state.End()
    elif not Match(r'^\s*$', line):
        function_state.Count()  # Count non-blank/non-comment lines.


def CheckForMultilineCommentsAndStrings(filename, clean_lines, linenum, error):
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
    line = line.replace('\\\\', '')

    if line.count('/*') > line.count('*/'):
        error(filename, linenum, 'readability/multiline_comment', 5,
              'Complex multi-line /*...*/-style comment found. '
              'Lint may give bogus warnings.  '
              'Consider replacing these with //-style comments, '
              'with #if 0...#endif, '
              'or with more clearly structured multi-line comments.')

    if (line.count('"') - line.count('\\"')) % 2:
        error(filename, linenum, 'readability/multiline_string', 5,
              'Multi-line string ("...") found.  This lint script doesn\'t '
              'do well with such strings, and may give bogus warnings.  '
              'Use C++11 raw strings or concatenation instead.')
