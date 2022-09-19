import sysconfig
import sys
import unicodedata
import re

from ._cpplintstate import _CppLintState
from .categories import _ERROR_CATEGORIES
from .regex import Match, Search

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


# The default list of categories suppressed for C (not C++) files.
_DEFAULT_C_SUPPRESSED_CATEGORIES = [
    'readability/casting',
    ]

# The default list of categories suppressed for Linux Kernel files.
_DEFAULT_KERNEL_SUPPRESSED_CATEGORIES = [
    'whitespace/tab',
    ]


class _BlockInfo(object):
    """Stores information about a generic block of code."""

    def __init__(self, linenum, seen_open_brace):
        self.starting_linenum = linenum
        self.seen_open_brace = seen_open_brace
        self.open_parentheses = 0
        self.inline_asm = _NO_ASM
        self.check_namespace_indentation = False

    def CheckBegin(self, filename, clean_lines, linenum, error):
        """Run checks that applies to text up to the opening brace.

        This is mostly for checking the text after the class identifier
        and the "{", usually where the base class is specified.  For other
        blocks, there isn't much to check, so we always pass.

        Args:
          filename: The name of the current file.
          clean_lines: A CleansedLines instance containing the file.
          linenum: The number of the line to check.
          error: The function to call with any errors found.
        """
        pass

    def CheckEnd(self, filename, clean_lines, linenum, error):
        """Run checks that applies to text after the closing brace.

        This is mostly used for checking end of namespace comments.

        Args:
          filename: The name of the current file.
          clean_lines: A CleansedLines instance containing the file.
          linenum: The number of the line to check.
          error: The function to call with any errors found.
        """
        pass

    def IsBlockInfo(self):
        """Returns true if this block is a _BlockInfo.

        This is convenient for verifying that an object is an instance of
        a _BlockInfo, but not an instance of any of the derived classes.

        Returns:
          True for this class, False for derived classes.
        """
        return self.__class__ == _BlockInfo

class _ExternCInfo(_BlockInfo):
    """Stores information about an 'extern "C"' block."""

    def __init__(self, linenum):
        _BlockInfo.__init__(self, linenum, True)


class _ClassInfo(_BlockInfo):
    """Stores information about a class."""

    def __init__(self, name, class_or_struct, clean_lines, linenum):
        _BlockInfo.__init__(self, linenum, False)
        self.name = name
        self.is_derived = False
        self.check_namespace_indentation = True
        if class_or_struct == 'struct':
            self.access = 'public'
            self.is_struct = True
        else:
            self.access = 'private'
            self.is_struct = False

        # Remember initial indentation level for this class.  Using raw_lines here
        # instead of elided to account for leading comments.
        self.class_indent = GetIndentLevel(clean_lines.raw_lines[linenum])

        # Try to find the end of the class.  This will be confused by things like:
        #   class A {
        #   } *x = { ...
        #
        # But it's still good enough for CheckSectionSpacing.
        self.last_line = 0
        depth = 0
        for i in range(linenum, clean_lines.NumLines()):
            line = clean_lines.elided[i]
            depth += line.count('{') - line.count('}')
            if not depth:
                self.last_line = i
                break

    def CheckBegin(self, filename, clean_lines, linenum, error):
        # Look for a bare ':'
        if Search('(^|[^:]):($|[^:])', clean_lines.elided[linenum]):
            self.is_derived = True

    def CheckEnd(self, filename, clean_lines, linenum, error):
        # If there is a DISALLOW macro, it should appear near the end of
        # the class.
        seen_last_thing_in_class = False
        for i in range(linenum - 1, self.starting_linenum, -1):
            match = Search(
                r'\b(DISALLOW_COPY_AND_ASSIGN|DISALLOW_IMPLICIT_CONSTRUCTORS)\(' +
                self.name + r'\)',
                clean_lines.elided[i])
            if match:
                if seen_last_thing_in_class:
                    error(filename, i, 'readability/constructors', 3,
                          match.group(1) + ' should be the last thing in the class')
                break

            if not Match(r'^\s*$', clean_lines.elided[i]):
                seen_last_thing_in_class = True

        # Check that closing brace is aligned with beginning of the class.
        # Only do this if the closing brace is indented by only whitespaces.
        # This means we will not check single-line class definitions.
        indent = Match(r'^( *)\}', clean_lines.elided[linenum])
        if indent and len(indent.group(1)) != self.class_indent:
            if self.is_struct:
                parent = 'struct ' + self.name
            else:
                parent = 'class ' + self.name
            error(filename, linenum, 'whitespace/indent', 3,
                  'Closing brace should be aligned with beginning of %s' % parent)


class _NamespaceInfo(_BlockInfo):
    """Stores information about a namespace."""

    def __init__(self, name, linenum):
        _BlockInfo.__init__(self, linenum, False)
        self.name = name or ''
        self.check_namespace_indentation = True

    def CheckEnd(self, filename, clean_lines, linenum, error):
        """Check end of namespace comments."""
        line = clean_lines.raw_lines[linenum]

        # Check how many lines is enclosed in this namespace.  Don't issue
        # warning for missing namespace comments if there aren't enough
        # lines.  However, do apply checks if there is already an end of
        # namespace comment and it's incorrect.
        #
        # TODO(unknown): We always want to check end of namespace comments
        # if a namespace is large, but sometimes we also want to apply the
        # check if a short namespace contained nontrivial things (something
        # other than forward declarations).  There is currently no logic on
        # deciding what these nontrivial things are, so this check is
        # triggered by namespace size only, which works most of the time.
        if (linenum - self.starting_linenum < 10
            and not Match(r'^\s*};*\s*(//|/\*).*\bnamespace\b', line)):
            return

        # Look for matching comment at end of namespace.
        #
        # Note that we accept C style "/* */" comments for terminating
        # namespaces, so that code that terminate namespaces inside
        # preprocessor macros can be cpplint clean.
        #
        # We also accept stuff like "// end of namespace <name>." with the
        # period at the end.
        #
        # Besides these, we don't accept anything else, otherwise we might
        # get false negatives when existing comment is a substring of the
        # expected namespace.
        if self.name:
            # Named namespace
            if not Match((r'^\s*};*\s*(//|/\*).*\bnamespace\s+' +
                          re.escape(self.name) + r'[\*/\.\\\s]*$'),
                         line):
                error(filename, linenum, 'readability/namespace', 5,
                      'Namespace should be terminated with "// namespace %s"' %
                      self.name)
        else:
            # Anonymous namespace
            if not Match(r'^\s*};*\s*(//|/\*).*\bnamespace[\*/\.\\\s]*$', line):
                # If "// namespace anonymous" or "// anonymous namespace (more text)",
                # mention "// anonymous namespace" as an acceptable form
                if Match(r'^\s*}.*\b(namespace anonymous|anonymous namespace)\b', line):
                    error(filename, linenum, 'readability/namespace', 5,
                          'Anonymous namespace should be terminated with "// namespace"'
                          ' or "// anonymous namespace"')
                else:
                    error(filename, linenum, 'readability/namespace', 5,
                          'Anonymous namespace should be terminated with "// namespace"')


class _PreprocessorInfo(object):
    """Stores checkpoints of nesting stacks when #if/#else is seen."""

    def __init__(self, stack_before_if):
        # The entire nesting stack before #if
        self.stack_before_if = stack_before_if

        # The entire nesting stack up to #else
        self.stack_before_else = []

        # Whether we have already seen #else or #elif
        self.seen_else = False


class _ExternCInfo(_BlockInfo):
    """Stores information about an 'extern "C"' block."""

    def __init__(self, linenum):
        _BlockInfo.__init__(self, linenum, True)


class _ClassInfo(_BlockInfo):
    """Stores information about a class."""

    def __init__(self, name, class_or_struct, clean_lines, linenum):
        _BlockInfo.__init__(self, linenum, False)
        self.name = name
        self.is_derived = False
        self.check_namespace_indentation = True
        if class_or_struct == 'struct':
            self.access = 'public'
            self.is_struct = True
        else:
            self.access = 'private'
            self.is_struct = False

        # Remember initial indentation level for this class.  Using raw_lines here
        # instead of elided to account for leading comments.
        self.class_indent = GetIndentLevel(clean_lines.raw_lines[linenum])

        # Try to find the end of the class.  This will be confused by things like:
        #   class A {
        #   } *x = { ...
        #
        # But it's still good enough for CheckSectionSpacing.
        self.last_line = 0
        depth = 0
        for i in range(linenum, clean_lines.NumLines()):
            line = clean_lines.elided[i]
            depth += line.count('{') - line.count('}')
            if not depth:
                self.last_line = i
                break

    def CheckBegin(self, filename, clean_lines, linenum, error):
        # Look for a bare ':'
        if Search('(^|[^:]):($|[^:])', clean_lines.elided[linenum]):
            self.is_derived = True

    def CheckEnd(self, filename, clean_lines, linenum, error):
        # If there is a DISALLOW macro, it should appear near the end of
        # the class.
        seen_last_thing_in_class = False
        for i in range(linenum - 1, self.starting_linenum, -1):
            match = Search(
                r'\b(DISALLOW_COPY_AND_ASSIGN|DISALLOW_IMPLICIT_CONSTRUCTORS)\(' +
                self.name + r'\)',
                clean_lines.elided[i])
            if match:
                if seen_last_thing_in_class:
                    error(filename, i, 'readability/constructors', 3,
                          match.group(1) + ' should be the last thing in the class')
                break

            if not Match(r'^\s*$', clean_lines.elided[i]):
                seen_last_thing_in_class = True

        # Check that closing brace is aligned with beginning of the class.
        # Only do this if the closing brace is indented by only whitespaces.
        # This means we will not check single-line class definitions.
        indent = Match(r'^( *)\}', clean_lines.elided[linenum])
        if indent and len(indent.group(1)) != self.class_indent:
            if self.is_struct:
                parent = 'struct ' + self.name
            else:
                parent = 'class ' + self.name
            error(filename, linenum, 'whitespace/indent', 3,
                  'Closing brace should be aligned with beginning of %s' % parent)


class _NamespaceInfo(_BlockInfo):
    """Stores information about a namespace."""

    def __init__(self, name, linenum):
        _BlockInfo.__init__(self, linenum, False)
        self.name = name or ''
        self.check_namespace_indentation = True

    def CheckEnd(self, filename, clean_lines, linenum, error):
        """Check end of namespace comments."""
        line = clean_lines.raw_lines[linenum]

        # Check how many lines is enclosed in this namespace.  Don't issue
        # warning for missing namespace comments if there aren't enough
        # lines.  However, do apply checks if there is already an end of
        # namespace comment and it's incorrect.
        #
        # TODO(unknown): We always want to check end of namespace comments
        # if a namespace is large, but sometimes we also want to apply the
        # check if a short namespace contained nontrivial things (something
        # other than forward declarations).  There is currently no logic on
        # deciding what these nontrivial things are, so this check is
        # triggered by namespace size only, which works most of the time.
        if (linenum - self.starting_linenum < 10
            and not Match(r'^\s*};*\s*(//|/\*).*\bnamespace\b', line)):
            return

        # Look for matching comment at end of namespace.
        #
        # Note that we accept C style "/* */" comments for terminating
        # namespaces, so that code that terminate namespaces inside
        # preprocessor macros can be cpplint clean.
        #
        # We also accept stuff like "// end of namespace <name>." with the
        # period at the end.
        #
        # Besides these, we don't accept anything else, otherwise we might
        # get false negatives when existing comment is a substring of the
        # expected namespace.
        if self.name:
            # Named namespace
            if not Match((r'^\s*};*\s*(//|/\*).*\bnamespace\s+' +
                          re.escape(self.name) + r'[\*/\.\\\s]*$'),
                         line):
                error(filename, linenum, 'readability/namespace', 5,
                      'Namespace should be terminated with "// namespace %s"' %
                      self.name)
        else:
            # Anonymous namespace
            if not Match(r'^\s*};*\s*(//|/\*).*\bnamespace[\*/\.\\\s]*$', line):
                # If "// namespace anonymous" or "// anonymous namespace (more text)",
                # mention "// anonymous namespace" as an acceptable form
                if Match(r'^\s*}.*\b(namespace anonymous|anonymous namespace)\b', line):
                    error(filename, linenum, 'readability/namespace', 5,
                          'Anonymous namespace should be terminated with "// namespace"'
                          ' or "// anonymous namespace"')
                else:
                    error(filename, linenum, 'readability/namespace', 5,
                          'Anonymous namespace should be terminated with "// namespace"')


class _PreprocessorInfo(object):
    """Stores checkpoints of nesting stacks when #if/#else is seen."""

    def __init__(self, stack_before_if):
        # The entire nesting stack before #if
        self.stack_before_if = stack_before_if

        # The entire nesting stack up to #else
        self.stack_before_else = []

        # Whether we have already seen #else or #elif
        self.seen_else = False

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

def CloseExpression(clean_lines, linenum, pos):
    """If input points to ( or { or [ or <, finds the position that closes it.

    If lines[linenum][pos] points to a '(' or '{' or '[' or '<', finds the
    linenum/pos that correspond to the closing of the expression.

    TODO(unknown): cpplint spends a fair bit of time matching parentheses.
    Ideally we would want to index all opening and closing parentheses once
    and have CloseExpression be just a simple lookup, but due to preprocessor
    tricks, this is not so easy.

    Args:
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      pos: A position on the line.

    Returns:
      A tuple (line, linenum, pos) pointer *past* the closing brace, or
      (line, len(lines), -1) if we never find a close.  Note we ignore
      strings and comments when matching; and the line we return is the
      'cleansed' line at linenum.
    """

    line = clean_lines.elided[linenum]
    if (line[pos] not in '({[<') or Match(r'<[<=]', line[pos:]):
        return (line, clean_lines.NumLines(), -1)

    # Check first line
    (end_pos, stack) = FindEndOfExpressionInLine(line, pos, [])
    if end_pos > -1:
        return (line, linenum, end_pos)

    # Continue scanning forward
    while stack and linenum < clean_lines.NumLines() - 1:
        linenum += 1
        line = clean_lines.elided[linenum]
        (end_pos, stack) = FindEndOfExpressionInLine(line, 0, stack)
        if end_pos > -1:
            return (line, linenum, end_pos)

    # Did not find end of expression before end of file, give up
    return (line, clean_lines.NumLines(), -1)


def FindEndOfExpressionInLine(line, startpos, stack):
    """Find the position just after the end of current parenthesized expression.

    Args:
      line: a CleansedLines line.
      startpos: start searching at this position.
      stack: nesting stack at startpos.

    Returns:
      On finding matching end: (index just after matching end, None)
      On finding an unclosed expression: (-1, None)
      Otherwise: (-1, new stack at end of this line)
    """
    for i in range(startpos, len(line)):
        char = line[i]
        if char in '([{':
            # Found start of parenthesized expression, push to expression stack
            stack.append(char)
        elif char == '<':
            # Found potential start of template argument list
            if i > 0 and line[i - 1] == '<':
                # Left shift operator
                if stack and stack[-1] == '<':
                    stack.pop()
                    if not stack:
                        return (-1, None)
            elif i > 0 and Search(r'\boperator\s*$', line[0:i]):
                # operator<, don't add to stack
                continue
            else:
                # Tentative start of template argument list
                stack.append('<')
        elif char in ')]}':
            # Found end of parenthesized expression.
            #
            # If we are currently expecting a matching '>', the pending '<'
            # must have been an operator.  Remove them from expression stack.
            while stack and stack[-1] == '<':
                stack.pop()
            if not stack:
                return (-1, None)
            if ((stack[-1] == '(' and char == ')') or
                (stack[-1] == '[' and char == ']') or
                (stack[-1] == '{' and char == '}')):
                stack.pop()
                if not stack:
                    return (i + 1, None)
            else:
                # Mismatched parentheses
                return (-1, None)
        elif char == '>':
            # Found potential end of template argument list.

            # Ignore "->" and operator functions
            if (i > 0 and
                (line[i - 1] == '-' or Search(r'\boperator\s*$', line[0:i - 1]))):
                continue

            # Pop the stack if there is a matching '<'.  Otherwise, ignore
            # this '>' since it must be an operator.
            if stack:
                if stack[-1] == '<':
                    stack.pop()
                    if not stack:
                        return (i + 1, None)
        elif char == ';':
            # Found something that look like end of statements.  If we are currently
            # expecting a '>', the matching '<' must have been an operator, since
            # template argument list should not contain statements.
            while stack and stack[-1] == '<':
                stack.pop()
            if not stack:
                return (-1, None)

    # Did not find end of expression or unbalanced parentheses on this line
    return (-1, stack)

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

def IsMacroDefinition(clean_lines, linenum):
    if Search(r'^#define', clean_lines[linenum]):
        return True

    if linenum > 0 and Search(r'\\$', clean_lines[linenum - 1]):
        return True

    return False


def IsForwardClassDeclaration(clean_lines, linenum):
    return Match(r'^\s*(\btemplate\b)*.*class\s+\w+;\s*$', clean_lines[linenum])

def ParseNolintSuppressions(state: _CppLintState ,filename, raw_line, linenum, error):
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


def ProcessGlobalSuppresions(state: _CppLintState, lines):
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


def ResetNolintSuppressions(state: _CppLintState):
    """Resets the set of NOLINT suppressions to empty."""
    state._error_suppressions.clear()
    state._global_error_suppressions.clear()


def IsErrorSuppressedByNolint(state: _CppLintState, category, linenum):
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
    return (state._global_error_suppressions.get(category, False) or
            linenum in state._error_suppressions.get(category, set()) or
            linenum in state._error_suppressions.get(None, set()))


def IsBlockInNameSpace(nesting_state, is_forward_declaration):
    """Checks that the new block is directly in a namespace.

    Args:
      nesting_state: The _NestingState object that contains info about our state.
      is_forward_declaration: If the class is a forward declared class.
    Returns:
      Whether or not the new block is directly in a namespace.
    """
    if is_forward_declaration:
        return len(nesting_state.stack) >= 1 and (
          isinstance(nesting_state.stack[-1], _NamespaceInfo))


    return (len(nesting_state.stack) > 1 and
            nesting_state.stack[-1].check_namespace_indentation and
            isinstance(nesting_state.stack[-2], _NamespaceInfo))

def GetPreviousNonBlankLine(clean_lines, linenum):
    """Return the most recent non-blank line and its line number.

    Args:
      clean_lines: A CleansedLines instance containing the file contents.
      linenum: The number of the line to check.

    Returns:
      A tuple with two elements.  The first element is the contents of the last
      non-blank line before the current line, or the empty string if this is the
      first non-blank line.  The second is the line number of that line, or -1
      if this is the first non-blank line.
    """

    prevlinenum = linenum - 1
    while prevlinenum >= 0:
        prevline = clean_lines.elided[prevlinenum]
        if not IsBlankLine(prevline):     # if not a blank line...
            return (prevline, prevlinenum)
        prevlinenum -= 1
    return ('', -1)

def IsBlankLine(line):
    """Returns true if the given line is blank.

    We consider a line to be blank if the line is empty or consists of
    only white spaces.

    Args:
      line: A line of a string.

    Returns:
      True, if the given line is blank.
    """
    return not line or line.isspace()

def GetLineWidth(line):
    """Determines the width of the line in column positions.

    Args:
      line: A string, which may be a str string.

    Returns:
      The width of the line in column positions, accounting for str
      combining characters and wide characters.
    """
    if isinstance(line, str):
        width = 0
        for uc in unicodedata.normalize('NFC', line):
            if unicodedata.east_asian_width(uc) in ('W', 'F'):
                width += 2
            elif not unicodedata.combining(uc):
                # Issue 337
                # https://mail.python.org/pipermail/python-list/2012-August/628809.html
                if (sys.version_info.major, sys.version_info.minor) <= (3, 2):
                    # https://github.com/python/cpython/blob/2.7/Include/strobject.h#L81
                    is_wide_build = sysconfig.get_config_var("Py_str_SIZE") >= 4
                    # https://github.com/python/cpython/blob/2.7/Objects/strobject.c#L564
                    is_low_surrogate = 0xDC00 <= ord(uc) <= 0xDFFF
                    if not is_wide_build and is_low_surrogate:
                        width -= 1

                width += 1
        return width
    else:
        return len(line)

def CloseExpression(clean_lines, linenum, pos):
    """If input points to ( or { or [ or <, finds the position that closes it.

    If lines[linenum][pos] points to a '(' or '{' or '[' or '<', finds the
    linenum/pos that correspond to the closing of the expression.

    TODO(unknown): cpplint spends a fair bit of time matching parentheses.
    Ideally we would want to index all opening and closing parentheses once
    and have CloseExpression be just a simple lookup, but due to preprocessor
    tricks, this is not so easy.

    Args:
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      pos: A position on the line.

    Returns:
      A tuple (line, linenum, pos) pointer *past* the closing brace, or
      (line, len(lines), -1) if we never find a close.  Note we ignore
      strings and comments when matching; and the line we return is the
      'cleansed' line at linenum.
    """

    line = clean_lines.elided[linenum]
    if (line[pos] not in '({[<') or Match(r'<[<=]', line[pos:]):
        return (line, clean_lines.NumLines(), -1)

    # Check first line
    (end_pos, stack) = FindEndOfExpressionInLine(line, pos, [])
    if end_pos > -1:
        return (line, linenum, end_pos)

    # Continue scanning forward
    while stack and linenum < clean_lines.NumLines() - 1:
        linenum += 1
        line = clean_lines.elided[linenum]
        (end_pos, stack) = FindEndOfExpressionInLine(line, 0, stack)
        if end_pos > -1:
            return (line, linenum, end_pos)

    # Did not find end of expression before end of file, give up
    return (line, clean_lines.NumLines(), -1)

def ReverseCloseExpression(clean_lines, linenum, pos):
    """If input points to ) or } or ] or >, finds the position that opens it.

    If lines[linenum][pos] points to a ')' or '}' or ']' or '>', finds the
    linenum/pos that correspond to the opening of the expression.

    Args:
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      pos: A position on the line.

    Returns:
      A tuple (line, linenum, pos) pointer *at* the opening brace, or
      (line, 0, -1) if we never find the matching opening brace.  Note
      we ignore strings and comments when matching; and the line we
      return is the 'cleansed' line at linenum.
    """
    line = clean_lines.elided[linenum]
    if line[pos] not in ')}]>':
        return (line, 0, -1)

    # Check last line
    (start_pos, stack) = FindStartOfExpressionInLine(line, pos, [])
    if start_pos > -1:
        return (line, linenum, start_pos)

    # Continue scanning backward
    while stack and linenum > 0:
        linenum -= 1
        line = clean_lines.elided[linenum]
        (start_pos, stack) = FindStartOfExpressionInLine(line, len(line) - 1, stack)
        if start_pos > -1:
            return (line, linenum, start_pos)

    # Did not find start of expression before beginning of file, give up
    return (line, 0, -1)
