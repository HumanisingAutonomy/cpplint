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
