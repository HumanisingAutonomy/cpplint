import itertools
import os
import re
import sys
import sysconfig
import unicodedata

from .categories import _ERROR_CATEGORIES
from .file_info import FileInfo, PathSplitToList
from .include_state import _IncludeState
from .lintstate import LintState
from .regex import Match, Search

# Pattern for matching FileInfo.BaseName() against test file name
_test_suffixes = ["_test", "_regtest", "_unittest"]
_TEST_FILE_SUFFIX = "(" + "|".join(_test_suffixes) + r")$"

# Matches the first component of a filename delimited by -s and _s. That is:
#  _RE_FIRST_COMPONENT.match('foo').group(0) == 'foo'
#  _RE_FIRST_COMPONENT.match('foo.cc').group(0) == 'foo'
#  _RE_FIRST_COMPONENT.match('foo-bar_baz.cc').group(0) == 'foo'
#  _RE_FIRST_COMPONENT.match('foo_bar-baz.cc').group(0) == 'foo'
_RE_FIRST_COMPONENT = re.compile(r"^[^-_.]+")

# Assertion macros.  These are defined in base/logging.h and
# testing/base/public/gunit.h.
_CHECK_MACROS = [
    "DCHECK",
    "CHECK",
    "EXPECT_TRUE",
    "ASSERT_TRUE",
    "EXPECT_FALSE",
    "ASSERT_FALSE",
]


# These constants define the current inline assembly state
_NO_ASM = 0  # Outside of inline assembly block
_INSIDE_ASM = 1  # Inside inline assembly block
_END_ASM = 2  # Last line of inline assembly block
_BLOCK_ASM = 3  # The whole block is an inline assembly block

# Match start of assembly blocks
_MATCH_ASM = re.compile(r"^\s*(?:asm|_asm|__asm|__asm__)" r"(?:\s+(volatile|__volatile__))?" r"\s*[{(]")

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


# The default list of categories suppressed for C (not C++) files.
_DEFAULT_C_SUPPRESSED_CATEGORIES = [
    "readability/casting",
]

# The default list of categories suppressed for Linux Kernel files.
_DEFAULT_KERNEL_SUPPRESSED_CATEGORIES = [
    "whitespace/tab",
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

    def CheckEnd(self, state: LintState, filename, clean_lines, linenum, error):
        """Run checks that applies to text after the closing brace.

        This is mostly used for checking end of namespace comments.

        Args:
          state: The current state of the linting process
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
        if class_or_struct == "struct":
            self.access = "public"
            self.is_struct = True
        else:
            self.access = "private"
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
            depth += line.count("{") - line.count("}")
            if not depth:
                self.last_line = i
                break

    def CheckBegin(self, filename, clean_lines, linenum, error):
        # Look for a bare ':'
        if Search("(^|[^:]):($|[^:])", clean_lines.elided[linenum]):
            self.is_derived = True

    def CheckEnd(self, state: LintState, filename, clean_lines, linenum, error):
        # If there is a DISALLOW macro, it should appear near the end of
        # the class.
        seen_last_thing_in_class = False
        for i in range(linenum - 1, self.starting_linenum, -1):
            match = Search(
                r"\b(DISALLOW_COPY_AND_ASSIGN|DISALLOW_IMPLICIT_CONSTRUCTORS)\(" + self.name + r"\)",
                clean_lines.elided[i],
            )
            if match:
                if seen_last_thing_in_class:
                    error(
                        state,
                        filename,
                        i,
                        "readability/constructors",
                        3,
                        match.group(1) + " should be the last thing in the class",
                    )
                break

            if not Match(r"^\s*$", clean_lines.elided[i]):
                seen_last_thing_in_class = True

        # Check that closing brace is aligned with beginning of the class.
        # Only do this if the closing brace is indented by only whitespaces.
        # This means we will not check single-line class definitions.
        indent = Match(r"^( *)\}", clean_lines.elided[linenum])
        if indent and len(indent.group(1)) != self.class_indent:
            if self.is_struct:
                parent = "struct " + self.name
            else:
                parent = "class " + self.name
            error(
                state,
                filename,
                linenum,
                "whitespace/indent",
                3,
                "Closing brace should be aligned with beginning of %s" % parent,
            )


class _NamespaceInfo(_BlockInfo):
    """Stores information about a namespace."""

    def __init__(self, name, linenum):
        _BlockInfo.__init__(self, linenum, False)
        self.name = name or ""
        self.check_namespace_indentation = True

    def CheckEnd(self, state: LintState, filename, clean_lines, linenum, error):
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
        if linenum - self.starting_linenum < 10 and not Match(r"^\s*};*\s*(//|/\*).*\bnamespace\b", line):
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
            if not Match(
                (r"^\s*};*\s*(//|/\*).*\bnamespace\s+" + re.escape(self.name) + r"[\*/\.\\\s]*$"),
                line,
            ):
                error(
                    state,
                    filename,
                    linenum,
                    "readability/namespace",
                    5,
                    'Namespace should be terminated with "// namespace %s"' % self.name,
                )
        else:
            # Anonymous namespace
            if not Match(r"^\s*};*\s*(//|/\*).*\bnamespace[\*/\.\\\s]*$", line):
                # If "// namespace anonymous" or "// anonymous namespace (more text)",
                # mention "// anonymous namespace" as an acceptable form
                if Match(r"^\s*}.*\b(namespace anonymous|anonymous namespace)\b", line):
                    error(
                        state,
                        filename,
                        linenum,
                        "readability/namespace",
                        5,
                        'Anonymous namespace should be terminated with "// namespace"' ' or "// anonymous namespace"',
                    )
                else:
                    error(
                        state,
                        filename,
                        linenum,
                        "readability/namespace",
                        5,
                        'Anonymous namespace should be terminated with "// namespace"',
                    )


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
    indent = Match(r"^( *)\S", line)
    if indent:
        return len(indent.group(1))
    else:
        return 0


def GetHeaderGuardCPPVariable(state, filename):
    """Returns the CPP variable that should be used as a header guard.

    Args:
      filename: The name of a C++ header file.

    Returns:
      The CPP variable that should be used as a header guard in the
      named file.

    """

    # Restores original filename in case that cpplint is invoked from Emacs's
    # flymake.
    filename = re.sub(r"_flymake\.h$", ".h", filename)
    filename = re.sub(r"/\.flymake/([^/]*)$", r"/\1", filename)
    # Replace 'c++' with 'cpp'.
    filename = filename.replace("C++", "cpp").replace("c++", "cpp")

    fileinfo = FileInfo(filename)
    file_path_from_root = fileinfo.RepositoryName(state._repository)

    def FixupPathFromRoot():
        if state._root_debug:
            sys.stderr.write(
                "\n_root fixup, _root = '%s', repository name = '%s'\n"
                % (state._root, fileinfo.RepositoryName(state._repository))
            )

        # Process the file path with the --root flag if it was set.
        if not state._root:
            if state._root_debug:
                sys.stderr.write("_root unspecified\n")
            return file_path_from_root

        def StripListPrefix(lst, prefix):
            # f(['x', 'y'], ['w, z']) -> None  (not a valid prefix)
            if lst[: len(prefix)] != prefix:
                return None
            # f(['a, 'b', 'c', 'd'], ['a', 'b']) -> ['c', 'd']
            return lst[(len(prefix)) :]

        # root behavior:
        #   --root=subdir , lstrips subdir from the header guard
        maybe_path = StripListPrefix(PathSplitToList(file_path_from_root), PathSplitToList(state._root))

        if state._root_debug:
            sys.stderr.write(
                ("_root lstrip (maybe_path=%s, file_path_from_root=%s," + " _root=%s)\n")
                % (maybe_path, file_path_from_root, state._root)
            )

        if maybe_path:
            return os.path.join(*maybe_path)

        #   --root=.. , will prepend the outer directory to the header guard
        full_path = fileinfo.FullName()
        # adapt slashes for windows
        root_abspath = os.path.abspath(state._root).replace("\\", "/")

        maybe_path = StripListPrefix(PathSplitToList(full_path), PathSplitToList(root_abspath))

        if state._root_debug:
            sys.stderr.write(
                ("_root prepend (maybe_path=%s, full_path=%s, " + "root_abspath=%s)\n")
                % (maybe_path, full_path, root_abspath)
            )

        if maybe_path:
            return os.path.join(*maybe_path)

        if state._root_debug:
            sys.stderr.write("_root ignore, returning %s\n" % (file_path_from_root))

        #   --root=FAKE_DIR is ignored
        return file_path_from_root

    file_path_from_root = FixupPathFromRoot()
    return re.sub(r"[^a-zA-Z0-9]", "_", file_path_from_root).upper() + "_"


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
        if char in ")]}":
            # Found end of expression, push to expression stack
            stack.append(char)
        elif char == ">":
            # Found potential end of template argument list.
            #
            # Ignore it if it's a "->" or ">=" or "operator>"
            if i > 0 and (
                line[i - 1] == "-" or Match(r"\s>=\s", line[i - 1 :]) or Search(r"\boperator\s*$", line[0:i])
            ):
                i -= 1
            else:
                stack.append(">")
        elif char == "<":
            # Found potential start of template argument list
            if i > 0 and line[i - 1] == "<":
                # Left shift operator
                i -= 1
            else:
                # If there is a matching '>', we can pop the expression stack.
                # Otherwise, ignore this '<' since it must be an operator.
                if stack and stack[-1] == ">":
                    stack.pop()
                    if not stack:
                        return (i, None)
        elif char in "([{":
            # Found start of expression.
            #
            # If there are any unmatched '>' on the stack, they must be
            # operators.  Remove those.
            while stack and stack[-1] == ">":
                stack.pop()
            if not stack:
                return (-1, None)
            if (
                (char == "(" and stack[-1] == ")")
                or (char == "[" and stack[-1] == "]")
                or (char == "{" and stack[-1] == "}")
            ):
                stack.pop()
                if not stack:
                    return (i, None)
            else:
                # Mismatched parentheses
                return (-1, None)
        elif char == ";":
            # Found something that look like end of statements.  If we are currently
            # expecting a '<', the matching '>' must have been an operator, since
            # template argument list should not contain statements.
            while stack and stack[-1] == ">":
                stack.pop()
            if not stack:
                return (-1, None)

        i -= 1

    return (-1, stack)


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
        if char in "([{":
            # Found start of parenthesized expression, push to expression stack
            stack.append(char)
        elif char == "<":
            # Found potential start of template argument list
            if i > 0 and line[i - 1] == "<":
                # Left shift operator
                if stack and stack[-1] == "<":
                    stack.pop()
                    if not stack:
                        return (-1, None)
            elif i > 0 and Search(r"\boperator\s*$", line[0:i]):
                # operator<, don't add to stack
                continue
            else:
                # Tentative start of template argument list
                stack.append("<")
        elif char in ")]}":
            # Found end of parenthesized expression.
            #
            # If we are currently expecting a matching '>', the pending '<'
            # must have been an operator.  Remove them from expression stack.
            while stack and stack[-1] == "<":
                stack.pop()
            if not stack:
                return (-1, None)
            if (
                (stack[-1] == "(" and char == ")")
                or (stack[-1] == "[" and char == "]")
                or (stack[-1] == "{" and char == "}")
            ):
                stack.pop()
                if not stack:
                    return (i + 1, None)
            else:
                # Mismatched parentheses
                return (-1, None)
        elif char == ">":
            # Found potential end of template argument list.

            # Ignore "->" and operator functions
            if i > 0 and (line[i - 1] == "-" or Search(r"\boperator\s*$", line[0 : i - 1])):
                continue

            # Pop the stack if there is a matching '<'.  Otherwise, ignore
            # this '>' since it must be an operator.
            if stack:
                if stack[-1] == "<":
                    stack.pop()
                    if not stack:
                        return (i + 1, None)
        elif char == ";":
            # Found something that look like end of statements.  If we are currently
            # expecting a '>', the matching '<' must have been an operator, since
            # template argument list should not contain statements.
            while stack and stack[-1] == "<":
                stack.pop()
            if not stack:
                return (-1, None)

    # Did not find end of expression or unbalanced parentheses on this line
    return (-1, stack)


def FindCheckMacro(line):
    """Find a replaceable CHECK-like macro.

    Args:
      line: line to search on.
    Returns:
      (macro name, start position), or (None, -1) if no replaceable
      macro is found.
    """
    for macro in _CHECK_MACROS:
        i = line.find(macro)
        if i >= 0:
            # Find opening parenthesis.  Do a regular expression match here
            # to make sure that we are matching the expected CHECK macro, as
            # opposed to some other macro that happens to contain the CHECK
            # substring.
            matched = Match(r"^(.*\b" + macro + r"\s*)\(", line)
            if not matched:
                continue
            return (macro, len(matched.group(1)))
    return (None, -1)


def IsMacroDefinition(clean_lines, linenum):
    if Search(r"^#define", clean_lines[linenum]):
        return True

    if linenum > 0 and Search(r"\\$", clean_lines[linenum - 1]):
        return True

    return False


def IsForwardClassDeclaration(clean_lines, linenum):
    return Match(r"^\s*(\btemplate\b)*.*class\s+\w+;\s*$", clean_lines[linenum])


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
                        filename,
                        linenum,
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


def IsBlockInNameSpace(nesting_state, is_forward_declaration):
    """Checks that the new block is directly in a namespace.

    Args:
      nesting_state: The _NestingState object that contains info about our state.
      is_forward_declaration: If the class is a forward declared class.
    Returns:
      Whether or not the new block is directly in a namespace.
    """
    if is_forward_declaration:
        return len(nesting_state.stack) >= 1 and (isinstance(nesting_state.stack[-1], _NamespaceInfo))

    return (
        len(nesting_state.stack) > 1
        and nesting_state.stack[-1].check_namespace_indentation
        and isinstance(nesting_state.stack[-2], _NamespaceInfo)
    )


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
        match = Match(r"^([^()]*\w+)\(", clean_lines.elided[i])
        if match:
            # Look for "override" after the matching closing parenthesis
            line, _, closing_paren = CloseExpression(clean_lines, i, len(match.group(1)))
            return closing_paren >= 0 and Search(r"\boverride\b", line[closing_paren:])
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
        if Match(r"^([^()]*\w+)\(", clean_lines.elided[i]):
            return Match(r"^[^()]*\w+::\w+\(", clean_lines.elided[i]) is not None
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
            remove_function_body = Match(r"^(.*)\{\s*$", line)
            if remove_function_body:
                line = remove_function_body.group(1)

        if Search(r"\s:\s*\w+[({]", line):
            # A lone colon tend to indicate the start of a constructor
            # initializer list.  It could also be a ternary operator, which
            # also tend to appear in constructor initializer lists as
            # opposed to parameter lists.
            return True
        if Search(r"\}\s*,\s*$", line):
            # A closing brace followed by a comma is probably the end of a
            # brace-initialized member in constructor initializer list.
            return True
        if Search(r"[{};]\s*$", line):
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
        if not IsBlankLine(prevline):  # if not a blank line...
            return (prevline, prevlinenum)
        prevlinenum -= 1
    return ("", -1)


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
    matching_punctuation = {"(": ")", "{": "}", "[": "]"}
    closing_punctuation = set(matching_punctuation.values())

    # Find the position to start extracting text.
    match = re.search(start_pattern, text, re.M)
    if not match:  # start_pattern not found in text.
        return None
    start_position = match.end(0)

    assert start_position > 0, "start_pattern must ends with an opening punctuation."
    assert text[start_position - 1] in matching_punctuation, "start_pattern must ends with an opening punctuation."
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
    return text[start_position : position - 1]


def _IsType(clean_lines, nesting_state, expr):
    """Check if expression looks like a type name, returns true if so.

    Args:
      clean_lines: A CleansedLines instance containing the file.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      expr: The expression to check.
    Returns:
      True, if token looks like a type.
    """
    # Type names
    _TYPES = re.compile(
        r"^(?:"
        # [dcl.type.simple]
        r"(char(16_t|32_t)?)|wchar_t|"
        r"bool|short|int|int|signed|unsigned|float|double|"
        # [support.types]
        r"(ptrdiff_t|size_t|max_align_t|nullptr_t)|"
        # [cstdint.syn]
        r"(u?int(_fast|_least)?(8|16|32|64)_t)|"
        r"(u?int(max|ptr)_t)|"
        r")$"
    )

    # Keep only the last token in the expression
    last_word = Match(r"^.*(\b\S+)$", expr)
    if last_word:
        token = last_word.group(1)
    else:
        token = expr

    # Match native types and stdint types
    if _TYPES.match(token):
        return True

    # Try a bit harder to match templated types.  Walk up the nesting
    # stack until we find something that resembles a typename
    # declaration for what we are looking for.
    typename_pattern = r"\b(?:typename|class|struct)\s+" + re.escape(token) + r"\b"
    block_index = len(nesting_state.stack) - 1
    while block_index >= 0:
        if isinstance(nesting_state.stack[block_index], _NamespaceInfo):
            return False

        # Found where the opening brace is.  We want to scan from this
        # line up to the beginning of the function, minus a few lines.
        #   template <typename Type1,  // stop scanning here
        #             ...>
        #   class C
        #     : public ... {  // start scanning here
        last_line = nesting_state.stack[block_index].starting_linenum

        next_block_start = 0
        if block_index > 0:
            next_block_start = nesting_state.stack[block_index - 1].starting_linenum
        first_line = last_line
        while first_line >= next_block_start:
            if clean_lines.elided[first_line].find("template") >= 0:
                break
            first_line -= 1
        if first_line < next_block_start:
            # Didn't find any "template" keyword before reaching the next block,
            # there are probably no template things to check for this block
            block_index -= 1
            continue

        # Look for typename in the specified range
        for i in range(first_line, last_line + 1, 1):
            if Search(typename_pattern, clean_lines.elided[i]):
                return True
        block_index -= 1

    return False


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
        for uc in unicodedata.normalize("NFC", line):
            if unicodedata.east_asian_width(uc) in ("W", "F"):
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
    if (line[pos] not in "({[<") or Match(r"<[<=]", line[pos:]):
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
    if line[pos] not in ")}]>":
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


# C++ headers
_CPP_HEADERS = frozenset(
    [
        # Legacy
        "algobase.h",
        "algo.h",
        "alloc.h",
        "builtinbuf.h",
        "bvector.h",
        "complex.h",
        "defalloc.h",
        "deque.h",
        "editbuf.h",
        "fstream.h",
        "function.h",
        "hash_map",
        "hash_map.h",
        "hash_set",
        "hash_set.h",
        "hashtable.h",
        "heap.h",
        "indstream.h",
        "iomanip.h",
        "iostream.h",
        "istream.h",
        "iterator.h",
        "list.h",
        "map.h",
        "multimap.h",
        "multiset.h",
        "ostream.h",
        "pair.h",
        "parsestream.h",
        "pfstream.h",
        "procbuf.h",
        "pthread_alloc",
        "pthread_alloc.h",
        "rope",
        "rope.h",
        "ropeimpl.h",
        "set.h",
        "slist",
        "slist.h",
        "stack.h",
        "stdiostream.h",
        "stl_alloc.h",
        "stl_relops.h",
        "streambuf.h",
        "stream.h",
        "strfile.h",
        "strstream.h",
        "tempbuf.h",
        "tree.h",
        "type_traits.h",
        "vector.h",
        # 17.6.1.2 C++ library headers
        "algorithm",
        "array",
        "atomic",
        "bitset",
        "chrono",
        "codecvt",
        "complex",
        "condition_variable",
        "deque",
        "exception",
        "forward_list",
        "fstream",
        "functional",
        "future",
        "initializer_list",
        "iomanip",
        "ios",
        "iosfwd",
        "iostream",
        "istream",
        "iterator",
        "limits",
        "list",
        "locale",
        "map",
        "memory",
        "mutex",
        "new",
        "numeric",
        "ostream",
        "queue",
        "random",
        "ratio",
        "regex",
        "scoped_allocator",
        "set",
        "sstream",
        "stack",
        "stdexcept",
        "streambuf",
        "string",
        "strstream",
        "system_error",
        "thread",
        "tuple",
        "typeindex",
        "typeinfo",
        "type_traits",
        "unordered_map",
        "unordered_set",
        "utility",
        "valarray",
        "vector",
        # 17.6.1.2 C++14 headers
        "shared_mutex",
        # 17.6.1.2 C++17 headers
        "any",
        "charconv",
        "codecvt",
        "execution",
        "filesystem",
        "memory_resource",
        "optional",
        "string_view",
        "variant",
        # 17.6.1.2 C++ headers for C library facilities
        "cassert",
        "ccomplex",
        "cctype",
        "cerrno",
        "cfenv",
        "cfloat",
        "cinttypes",
        "ciso646",
        "climits",
        "clocale",
        "cmath",
        "csetjmp",
        "csignal",
        "cstdalign",
        "cstdarg",
        "cstdbool",
        "cstddef",
        "cstdint",
        "cstdio",
        "cstdlib",
        "cstring",
        "ctgmath",
        "ctime",
        "cuchar",
        "cwchar",
        "cwctype",
    ]
)

# C headers
_C_HEADERS = frozenset(
    [
        # System C headers
        "assert.h",
        "complex.h",
        "ctype.h",
        "errno.h",
        "fenv.h",
        "float.h",
        "inttypes.h",
        "iso646.h",
        "limits.h",
        "locale.h",
        "math.h",
        "setjmp.h",
        "signal.h",
        "stdalign.h",
        "stdarg.h",
        "stdatomic.h",
        "stdbool.h",
        "stddef.h",
        "stdint.h",
        "stdio.h",
        "stdlib.h",
        "stdnoreturn.h",
        "string.h",
        "tgmath.h",
        "threads.h",
        "time.h",
        "uchar.h",
        "wchar.h",
        "wctype.h",
        # additional POSIX C headers
        "aio.h",
        "arpa/inet.h",
        "cpio.h",
        "dirent.h",
        "dlfcn.h",
        "fcntl.h",
        "fmtmsg.h",
        "fnmatch.h",
        "ftw.h",
        "glob.h",
        "grp.h",
        "iconv.h",
        "langinfo.h",
        "libgen.h",
        "monetary.h",
        "mqueue.h",
        "ndbm.h",
        "net/if.h",
        "netdb.h",
        "netinet/in.h",
        "netinet/tcp.h",
        "nl_types.h",
        "poll.h",
        "pthread.h",
        "pwd.h",
        "regex.h",
        "sched.h",
        "search.h",
        "semaphore.h",
        "setjmp.h",
        "signal.h",
        "spawn.h",
        "strings.h",
        "stropts.h",
        "syslog.h",
        "tar.h",
        "termios.h",
        "trace.h",
        "ulimit.h",
        "unistd.h",
        "utime.h",
        "utmpx.h",
        "wordexp.h",
        # additional GNUlib headers
        "a.out.h",
        "aliases.h",
        "alloca.h",
        "ar.h",
        "argp.h",
        "argz.h",
        "byteswap.h",
        "crypt.h",
        "endian.h",
        "envz.h",
        "err.h",
        "error.h",
        "execinfo.h",
        "fpu_control.h",
        "fstab.h",
        "fts.h",
        "getopt.h",
        "gshadow.h",
        "ieee754.h",
        "ifaddrs.h",
        "libintl.h",
        "mcheck.h",
        "mntent.h",
        "obstack.h",
        "paths.h",
        "printf.h",
        "pty.h",
        "resolv.h",
        "shadow.h",
        "sysexits.h",
        "ttyent.h",
        # Additional linux glibc headers
        "dlfcn.h",
        "elf.h",
        "features.h",
        "gconv.h",
        "gnu-versions.h",
        "lastlog.h",
        "libio.h",
        "link.h",
        "malloc.h",
        "memory.h",
        "netash/ash.h",
        "netatalk/at.h",
        "netax25/ax25.h",
        "neteconet/ec.h",
        "netipx/ipx.h",
        "netiucv/iucv.h",
        "netpacket/packet.h",
        "netrom/netrom.h",
        "netrose/rose.h",
        "nfs/nfs.h",
        "nl_types.h",
        "nss.h",
        "re_comp.h",
        "regexp.h",
        "sched.h",
        "sgtty.h",
        "stab.h",
        "stdc-predef.h",
        "stdio_ext.h",
        "syscall.h",
        "termio.h",
        "thread_db.h",
        "ucontext.h",
        "ustat.h",
        "utmp.h",
        "values.h",
        "wait.h",
        "xlocale.h",
        # Hardware specific headers
        "arm_neon.h",
        "emmintrin.h",
        "xmmintin.h",
    ]
)

# Folders of C libraries so commonly used in C++,
# that they have parity with standard C libraries.
C_STANDARD_HEADER_FOLDERS = frozenset(
    [
        # standard C library
        "sys",
        # glibc for linux
        "arpa",
        "asm-generic",
        "bits",
        "gnu",
        "net",
        "netinet",
        "protocols",
        "rpc",
        "rpcsvc",
        "scsi",
        # linux kernel header
        "drm",
        "linux",
        "misc",
        "mtd",
        "rdma",
        "sound",
        "video",
        "xen",
    ]
)


def _ClassifyInclude(state, fileinfo, include, used_angle_brackets, include_order="default"):
    """Figures out what kind of header 'include' is.

    Args:
      fileinfo: The current file cpplint is running over. A FileInfo instance.
      include: The path to a #included file.
      used_angle_brackets: True if the #include used <> rather than "".
      include_order: "default" or other value allowed in program arguments

    Returns:
      One of the _XXX_HEADER constants.

    For example:
      >>> _ClassifyInclude(FileInfo('foo/foo.cc'), 'stdio.h', True)
      _C_SYS_HEADER
      >>> _ClassifyInclude(FileInfo('foo/foo.cc'), 'string', True)
      _CPP_SYS_HEADER
      >>> _ClassifyInclude(FileInfo('foo/foo.cc'), 'foo/foo.h', True, "standardcfirst")
      _OTHER_SYS_HEADER
      >>> _ClassifyInclude(FileInfo('foo/foo.cc'), 'foo/foo.h', False)
      _LIKELY_MY_HEADER
      >>> _ClassifyInclude(FileInfo('foo/foo_unknown_extension.cc'),
      ...                  'bar/foo_other_ext.h', False)
      _POSSIBLE_MY_HEADER
      >>> _ClassifyInclude(FileInfo('foo/foo.cc'), 'foo/bar.h', False)
      _OTHER_HEADER
    """
    # This is a list of all standard c++ header files, except
    # those already checked for above.
    is_cpp_header = include in _CPP_HEADERS

    # Mark include as C header if in list or in a known folder for standard-ish C headers.
    is_std_c_header = (include_order == "default") or (
        include in _C_HEADERS
        # additional linux glibc header folders
        or Search(r"(?:%s)\/.*\.h" % "|".join(C_STANDARD_HEADER_FOLDERS), include)
    )

    # Headers with C++ extensions shouldn't be considered C system headers
    include_ext = os.path.splitext(include)[1]
    is_system = used_angle_brackets and include_ext not in [
        ".hh",
        ".hpp",
        ".hxx",
        ".h++",
    ]

    if is_system:
        if is_cpp_header:
            return _IncludeState._CPP_SYS_HEADER
        if is_std_c_header:
            return _IncludeState._C_SYS_HEADER
        else:
            return _IncludeState._OTHER_SYS_HEADER

    # If the target file and the include we're checking share a
    # basename when we drop common extensions, and the include
    # lives in . , then it's likely to be owned by the target file.
    target_dir, target_base = os.path.split(_DropCommonSuffixes(state, fileinfo.RepositoryName(state._repository)))
    include_dir, include_base = os.path.split(_DropCommonSuffixes(state, include))
    target_dir_pub = os.path.normpath(target_dir + "/../public")
    target_dir_pub = target_dir_pub.replace("\\", "/")
    if target_base == include_base and (include_dir == target_dir or include_dir == target_dir_pub):
        return _IncludeState._LIKELY_MY_HEADER

    # If the target and include share some initial basename
    # component, it's possible the target is implementing the
    # include, so it's allowed to be first, but we'll never
    # complain if it's not there.
    target_first_component = _RE_FIRST_COMPONENT.match(target_base)
    include_first_component = _RE_FIRST_COMPONENT.match(include_base)
    if (
        target_first_component
        and include_first_component
        and target_first_component.group(0) == include_first_component.group(0)
    ):
        return _IncludeState._POSSIBLE_MY_HEADER

    return _IncludeState._OTHER_HEADER


def _DropCommonSuffixes(state, filename):
    """Drops common suffixes like _test.cc or -inl.h from filename.

    For example:
      >>> _DropCommonSuffixes('foo/foo-inl.h')
      'foo/foo'
      >>> _DropCommonSuffixes('foo/bar/foo.cc')
      'foo/bar/foo'
      >>> _DropCommonSuffixes('foo/foo_internal.h')
      'foo/foo'
      >>> _DropCommonSuffixes('foo/foo_unusualinternal.h')
      'foo/foo_unusualinternal'

    Args:
      filename: The input filename.

    Returns:
      The filename with the common suffix removed.
    """
    for suffix in itertools.chain(
        (
            "%s.%s" % (test_suffix.lstrip("_"), ext)
            for test_suffix, ext in itertools.product(_test_suffixes, state.GetNonHeaderExtensions())
        ),
        (
            "%s.%s" % (suffix, ext)
            for suffix, ext in itertools.product(["inl", "imp", "internal"], state.GetHeaderExtensions())
        ),
    ):
        if filename.endswith(suffix) and len(filename) > len(suffix) and filename[-len(suffix) - 1] in ("-", "_"):
            return filename[: -len(suffix) - 1]
    return os.path.splitext(filename)[0]


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
    return Match(r"^\s*MOCK_(CONST_)?METHOD\d+(_T)?\(", line) or (
        linenum >= 2
        and (
            Match(
                r"^\s*MOCK_(?:CONST_)?METHOD\d+(?:_T)?\((?:\S+,)?\s*$",
                clean_lines.elided[linenum - 1],
            )
            or Match(
                r"^\s*MOCK_(?:CONST_)?METHOD\d+(?:_T)?\(\s*$",
                clean_lines.elided[linenum - 2],
            )
            or Search(r"\bstd::m?function\s*\<\s*$", clean_lines.elided[linenum - 1])
        )
    )
