from .regex import Match, Search
from .block_info import (
    GetIndentLevel,
    GetPreviousNonBlankLine,
    GetLineWidth,
    CloseExpression
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
