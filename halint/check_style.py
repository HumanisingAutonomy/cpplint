from .regex import Match, Search
from .block_info import (
    GetIndentLevel,
    GetPreviousNonBlankLine,
    GetLineWidth,
    CloseExpression,
    ReverseCloseExpression,
    ParseNolintSuppressions
)
from ._cpplintstate import _CppLintState

def CheckBraces(state: _CppLintState ,filename, clean_lines, linenum, error):
    """Looks for misplaced braces (e.g. at the end of line).

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """

    line = clean_lines.elided[linenum]        # get rid of comments and strings

    if Match(r'\s*{\s*$', line):
        # We allow an open brace to start a line in the case where someone is using
        # braces in a block to explicitly create a new scope, which is commonly used
        # to control the lifetime of stack-allocated variables.  Braces are also
        # used for brace initializers inside function calls.  We don't detect this
        # perfectly: we just don't complain if the last non-whitespace character on
        # the previous non-blank line is ',', ';', ':', '(', '{', or '}', or if the
        # previous line starts a preprocessor block. We also allow a brace on the
        # following line if it is part of an array initialization and would not fit
        # within the 80 character limit of the preceding line.
        prevline = GetPreviousNonBlankLine(clean_lines, linenum)[0]
        if (not Search(r'[,;:}{(]\s*$', prevline) and
            not Match(r'\s*#', prevline) and
            not (GetLineWidth(prevline) > state._line_length - 2 and '[]' in prevline)):
            error(filename, linenum, 'whitespace/braces', 4,
                  '{ should almost always be at the end of the previous line')

    # An else clause should be on the same line as the preceding closing brace.
    if Match(r'\s*else\b\s*(?:if\b|\{|$)', line):
        prevline = GetPreviousNonBlankLine(clean_lines, linenum)[0]
        if Match(r'\s*}\s*$', prevline):
            error(filename, linenum, 'whitespace/newline', 4,
                  'An else should appear on the same line as the preceding }')

    # If braces come on one side of an else, they should be on both.
    # However, we have to worry about "else if" that spans multiple lines!
    if Search(r'else if\s*\(', line):       # could be multi-line if
        brace_on_left = bool(Search(r'}\s*else if\s*\(', line))
        # find the ( after the if
        pos = line.find('else if')
        pos = line.find('(', pos)
        if pos > 0:
            (endline, _, endpos) = CloseExpression(clean_lines, linenum, pos)
            brace_on_right = endline[endpos:].find('{') != -1
            if brace_on_left != brace_on_right:    # must be brace after if
                error(filename, linenum, 'readability/braces', 5,
                      'If an else has a brace on one side, it should have it on both')
    elif Search(r'}\s*else[^{]*$', line) or Match(r'[^}]*else\s*{', line):
        error(filename, linenum, 'readability/braces', 5,
              'If an else has a brace on one side, it should have it on both')

    # Likewise, an else should never have the else clause on the same line
    if Search(r'\belse [^\s{]', line) and not Search(r'\belse if\b', line):
        error(filename, linenum, 'whitespace/newline', 4,
              'Else clause should never be on same line as else (use 2 lines)')

    # In the same way, a do/while should never be on one line
    if Match(r'\s*do [^\s{]', line):
        error(filename, linenum, 'whitespace/newline', 4,
              'do/while clauses should not be on a single line')

    # Check single-line if/else bodies. The style guide says 'curly braces are not
    # required for single-line statements'. We additionally allow multi-line,
    # single statements, but we reject anything with more than one semicolon in
    # it. This means that the first semicolon after the if should be at the end of
    # its line, and the line after that should have an indent level equal to or
    # lower than the if. We also check for ambiguous if/else nesting without
    # braces.
    if_else_match = Search(r'\b(if\s*(|constexpr)\s*\(|else\b)', line)
    if if_else_match and not Match(r'\s*#', line):
        if_indent = GetIndentLevel(line)
        endline, endlinenum, endpos = line, linenum, if_else_match.end()
        if_match = Search(r'\bif\s*(|constexpr)\s*\(', line)
        if if_match:
            # This could be a multiline if condition, so find the end first.
            pos = if_match.end() - 1
            (endline, endlinenum, endpos) = CloseExpression(clean_lines, linenum, pos)
        # Check for an opening brace, either directly after the if or on the next
        # line. If found, this isn't a single-statement conditional.
        if (not Match(r'\s*{', endline[endpos:])
            and not (Match(r'\s*$', endline[endpos:])
                     and endlinenum < (len(clean_lines.elided) - 1)
                     and Match(r'\s*{', clean_lines.elided[endlinenum + 1]))):
            while (endlinenum < len(clean_lines.elided)
                   and ';' not in clean_lines.elided[endlinenum][endpos:]):
                endlinenum += 1
                endpos = 0
            if endlinenum < len(clean_lines.elided):
                endline = clean_lines.elided[endlinenum]
                # We allow a mix of whitespace and closing braces (e.g. for one-liner
                # methods) and a single \ after the semicolon (for macros)
                endpos = endline.find(';')
                if not Match(r';[\s}]*(\\?)$', endline[endpos:]):
                    # Semicolon isn't the last character, there's something trailing.
                    # Output a warning if the semicolon is not contained inside
                    # a lambda expression.
                    if not Match(r'^[^{};]*\[[^\[\]]*\][^{}]*\{[^{}]*\}\s*\)*[;,]\s*$',
                                 endline):
                        error(filename, linenum, 'readability/braces', 4,
                              'If/else bodies with multiple statements require braces')
                elif endlinenum < len(clean_lines.elided) - 1:
                    # Make sure the next line is dedented
                    next_line = clean_lines.elided[endlinenum + 1]
                    next_indent = GetIndentLevel(next_line)
                    # With ambiguous nested if statements, this will error out on the
                    # if that *doesn't* match the else, regardless of whether it's the
                    # inner one or outer one.
                    if (if_match and Match(r'\s*else\b', next_line)
                        and next_indent != if_indent):
                        error(filename, linenum, 'readability/braces', 4,
                              'Else clause should be indented at the same level as if. '
                              'Ambiguous nested if/else chains require braces.')
                    elif next_indent > if_indent:
                        error(filename, linenum, 'readability/braces', 4,
                              'If/else bodies with multiple statements require braces')


def CheckTrailingSemicolon(state, filename, clean_lines, linenum, error):
    """Looks for redundant trailing semicolon.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """

    line = clean_lines.elided[linenum]

    # Block bodies should not be followed by a semicolon.  Due to C++11
    # brace initialization, there are more places where semicolons are
    # required than not, so we explicitly list the allowed rules rather
    # than listing the disallowed ones.  These are the places where "};"
    # should be replaced by just "}":
    # 1. Some flavor of block following closing parenthesis:
    #    for (;;) {};
    #    while (...) {};
    #    switch (...) {};
    #    Function(...) {};
    #    if (...) {};
    #    if (...) else if (...) {};
    #
    # 2. else block:
    #    if (...) else {};
    #
    # 3. const member function:
    #    Function(...) const {};
    #
    # 4. Block following some statement:
    #    x = 42;
    #    {};
    #
    # 5. Block at the beginning of a function:
    #    Function(...) {
    #      {};
    #    }
    #
    #    Note that naively checking for the preceding "{" will also match
    #    braces inside multi-dimensional arrays, but this is fine since
    #    that expression will not contain semicolons.
    #
    # 6. Block following another block:
    #    while (true) {}
    #    {};
    #
    # 7. End of namespaces:
    #    namespace {};
    #
    #    These semicolons seems far more common than other kinds of
    #    redundant semicolons, possibly due to people converting classes
    #    to namespaces.  For now we do not warn for this case.
    #
    # Try matching case 1 first.
    match = Match(r'^(.*\)\s*)\{', line)
    if match:
        # Matched closing parenthesis (case 1).  Check the token before the
        # matching opening parenthesis, and don't warn if it looks like a
        # macro.  This avoids these false positives:
        #  - macro that defines a base class
        #  - multi-line macro that defines a base class
        #  - macro that defines the whole class-head
        #
        # But we still issue warnings for macros that we know are safe to
        # warn, specifically:
        #  - TEST, TEST_F, TEST_P, MATCHER, MATCHER_P
        #  - TYPED_TEST
        #  - INTERFACE_DEF
        #  - EXCLUSIVE_LOCKS_REQUIRED, SHARED_LOCKS_REQUIRED, LOCKS_EXCLUDED:
        #
        # We implement a list of safe macros instead of a list of
        # unsafe macros, even though the latter appears less frequently in
        # google code and would have been easier to implement.  This is because
        # the downside for getting the allowed checks wrong means some extra
        # semicolons, while the downside for getting disallowed checks wrong
        # would result in compile errors.
        #
        # In addition to macros, we also don't want to warn on
        #  - Compound literals
        #  - Lambdas
        #  - alignas specifier with anonymous structs
        #  - decltype
        closing_brace_pos = match.group(1).rfind(')')
        opening_parenthesis = ReverseCloseExpression(
            clean_lines, linenum, closing_brace_pos)
        if opening_parenthesis[2] > -1:
            line_prefix = opening_parenthesis[0][0:opening_parenthesis[2]]
            macro = Search(r'\b([A-Z_][A-Z0-9_]*)\s*$', line_prefix)
            func = Match(r'^(.*\])\s*$', line_prefix)
            if ((macro and
                 macro.group(1) not in (
                     'TEST', 'TEST_F', 'MATCHER', 'MATCHER_P', 'TYPED_TEST',
                     'EXCLUSIVE_LOCKS_REQUIRED', 'SHARED_LOCKS_REQUIRED',
                     'LOCKS_EXCLUDED', 'INTERFACE_DEF')) or
                (func and not Search(r'\boperator\s*\[\s*\]', func.group(1))) or
                Search(r'\b(?:struct|union)\s+alignas\s*$', line_prefix) or
                Search(r'\bdecltype$', line_prefix) or
                Search(r'\s+=\s*$', line_prefix)):
                match = None
        if (match and
            opening_parenthesis[1] > 1 and
            Search(r'\]\s*$', clean_lines.elided[opening_parenthesis[1] - 1])):
            # Multi-line lambda-expression
            match = None

    else:
        # Try matching cases 2-3.
        match = Match(r'^(.*(?:else|\)\s*const)\s*)\{', line)
        if not match:
            # Try matching cases 4-6.  These are always matched on separate lines.
            #
            # Note that we can't simply concatenate the previous line to the
            # current line and do a single match, otherwise we may output
            # duplicate warnings for the blank line case:
            #   if (cond) {
            #     // blank line
            #   }
            prevline = GetPreviousNonBlankLine(clean_lines, linenum)[0]
            if prevline and Search(r'[;{}]\s*$', prevline):
                match = Match(r'^(\s*)\{', line)

    # Check matching closing brace
    if match:
        (endline, endlinenum, endpos) = CloseExpression(
            clean_lines, linenum, len(match.group(1)))
        if endpos > -1 and Match(r'^\s*;', endline[endpos:]):
            # Current {} pair is eligible for semicolon check, and we have found
            # the redundant semicolon, output warning here.
            #
            # Note: because we are scanning forward for opening braces, and
            # outputting warnings for the matching closing brace, if there are
            # nested blocks with trailing semicolons, we will get the error
            # messages in reversed order.

            # We need to check the line forward for NOLINT
            raw_lines = clean_lines.raw_lines
            ParseNolintSuppressions(state, filename, raw_lines[endlinenum-1], endlinenum-1,
                                    error)
            ParseNolintSuppressions(state, filename, raw_lines[endlinenum], endlinenum,
                                    error)

            error(filename, endlinenum, 'readability/braces', 4,
                  "You don't need a ; after a }")
