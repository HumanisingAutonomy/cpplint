import re
import string

from .regex import Match, Search
from .block_info import (
    IsBlankLine,
    GetIndentLevel,
    GetPreviousNonBlankLine,
    GetLineWidth,
    CloseExpression,
    ReverseCloseExpression,
    ParseNolintSuppressions
)
from .cleansed_lines import CleanseComments
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


# Pattern that matches only complete whitespace, possibly across multiple lines.
_EMPTY_CONDITIONAL_BODY_PATTERN = re.compile(r'^\s*$', re.DOTALL)

def CheckEmptyBlockBody(filename, clean_lines, linenum, error):
    """Look for empty loop/conditional body with only a single semicolon.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """

    # Search for loop keywords at the beginning of the line.  Because only
    # whitespaces are allowed before the keywords, this will also ignore most
    # do-while-loops, since those lines should start with closing brace.
    #
    # We also check "if" blocks here, since an empty conditional block
    # is likely an error.
    line = clean_lines.elided[linenum]
    matched = Match(r'\s*(for|while|if)\s*\(', line)
    if matched:
        # Find the end of the conditional expression.
        (end_line, end_linenum, end_pos) = CloseExpression(
            clean_lines, linenum, line.find('('))

        # Output warning if what follows the condition expression is a semicolon.
        # No warning for all other cases, including whitespace or newline, since we
        # have a separate check for semicolons preceded by whitespace.
        if end_pos >= 0 and Match(r';', end_line[end_pos:]):
            if matched.group(1) == 'if':
                error(filename, end_linenum, 'whitespace/empty_conditional_body', 5,
                      'Empty conditional bodies should use {}')
            else:
                error(filename, end_linenum, 'whitespace/empty_loop_body', 5,
                      'Empty loop bodies should use {} or continue')

        # Check for if statements that have completely empty bodies (no comments)
        # and no else clauses.
        if end_pos >= 0 and matched.group(1) == 'if':
            # Find the position of the opening { for the if statement.
            # Return without logging an error if it has no brackets.
            opening_linenum = end_linenum
            opening_line_fragment = end_line[end_pos:]
            # Loop until EOF or find anything that's not whitespace or opening {.
            while not Search(r'^\s*\{', opening_line_fragment):
                if Search(r'^(?!\s*$)', opening_line_fragment):
                    # Conditional has no brackets.
                    return
                opening_linenum += 1
                if opening_linenum == len(clean_lines.elided):
                    # Couldn't find conditional's opening { or any code before EOF.
                    return
                opening_line_fragment = clean_lines.elided[opening_linenum]
            # Set opening_line (opening_line_fragment may not be entire opening line).
            opening_line = clean_lines.elided[opening_linenum]

            # Find the position of the closing }.
            opening_pos = opening_line_fragment.find('{')
            if opening_linenum == end_linenum:
                # We need to make opening_pos relative to the start of the entire line.
                opening_pos += end_pos
            (closing_line, closing_linenum, closing_pos) = CloseExpression(
                clean_lines, opening_linenum, opening_pos)
            if closing_pos < 0:
                return

            # Now construct the body of the conditional. This consists of the portion
            # of the opening line after the {, all lines until the closing line,
            # and the portion of the closing line before the }.
            if (clean_lines.raw_lines[opening_linenum] !=
                CleanseComments(clean_lines.raw_lines[opening_linenum])):
                # Opening line ends with a comment, so conditional isn't empty.
                return
            if closing_linenum > opening_linenum:
                # Opening line after the {. Ignore comments here since we checked above.
                bodylist = list(opening_line[opening_pos+1:])
                # All lines until closing line, excluding closing line, with comments.
                bodylist.extend(clean_lines.raw_lines[opening_linenum+1:closing_linenum])
                # Closing line before the }. Won't (and can't) have comments.
                bodylist.append(clean_lines.elided[closing_linenum][:closing_pos-1])
                body = '\n'.join(bodylist)
            else:
                # If statement has brackets and fits on a single line.
                body = opening_line[opening_pos+1:closing_pos-1]

            # Check if the body is empty
            if not _EMPTY_CONDITIONAL_BODY_PATTERN.search(body):
                return
            # The body is empty. Now make sure there's not an else clause.
            current_linenum = closing_linenum
            current_line_fragment = closing_line[closing_pos:]
            # Loop until EOF or find anything that's not whitespace or else clause.
            while Search(r'^\s*$|^(?=\s*else)', current_line_fragment):
                if Search(r'^(?=\s*else)', current_line_fragment):
                    # Found an else clause, so don't log an error.
                    return
                current_linenum += 1
                if current_linenum == len(clean_lines.elided):
                    break
                current_line_fragment = clean_lines.elided[current_linenum]

            # The body is empty and there's no else clause until EOF or other code.
            error(filename, end_linenum, 'whitespace/empty_if_body', 4,
                  ('If statement had no body and no else clause'))


def CheckSpacing(filename, clean_lines, linenum, nesting_state, error):
    """Checks for the correctness of various spacing issues in the code.

    Things we check for: spaces around operators, spaces after
    if/for/while/switch, no spaces around parens in function calls, two
    spaces between code and comment, don't start a block with a blank
    line, don't end a function with a blank line, don't add a blank line
    after public/protected/private, don't have too many blank lines in a row.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: The function to call with any errors found.
    """

    # Don't use "elided" lines here, otherwise we can't check commented lines.
    # Don't want to use "raw" either, because we don't want to check inside C++11
    # raw strings,
    raw = clean_lines.lines_without_raw_strings
    line = raw[linenum]

    # Before nixing comments, check if the line is blank for no good
    # reason.  This includes the first line after a block is opened, and
    # blank lines at the end of a function (ie, right before a line like '}'
    #
    # Skip all the blank line checks if we are immediately inside a
    # namespace body.  In other words, don't issue blank line warnings
    # for this block:
    #   namespace {
    #
    #   }
    #
    # A warning about missing end of namespace comments will be issued instead.
    #
    # Also skip blank line checks for 'extern "C"' blocks, which are formatted
    # like namespaces.
    if (IsBlankLine(line) and
        not nesting_state.InNamespaceBody() and
        not nesting_state.InExternC()):
        elided = clean_lines.elided
        prev_line = elided[linenum - 1]
        prevbrace = prev_line.rfind('{')
        # TODO(unknown): Don't complain if line before blank line, and line after,
        #                both start with alnums and are indented the same amount.
        #                This ignores whitespace at the start of a namespace block
        #                because those are not usually indented.
        if prevbrace != -1 and prev_line[prevbrace:].find('}') == -1:
            # OK, we have a blank line at the start of a code block.  Before we
            # complain, we check if it is an exception to the rule: The previous
            # non-empty line has the parameters of a function header that are indented
            # 4 spaces (because they did not fit in a 80 column line when placed on
            # the same line as the function name).  We also check for the case where
            # the previous line is indented 6 spaces, which may happen when the
            # initializers of a constructor do not fit into a 80 column line.
            exception = False
            if Match(r' {6}\w', prev_line):  # Initializer list?
                # We are looking for the opening column of initializer list, which
                # should be indented 4 spaces to cause 6 space indentation afterwards.
                search_position = linenum-2
                while (search_position >= 0
                       and Match(r' {6}\w', elided[search_position])):
                    search_position -= 1
                exception = (search_position >= 0
                             and elided[search_position][:5] == '    :')
            else:
                # Search for the function arguments or an initializer list.  We use a
                # simple heuristic here: If the line is indented 4 spaces; and we have a
                # closing paren, without the opening paren, followed by an opening brace
                # or colon (for initializer lists) we assume that it is the last line of
                # a function header.  If we have a colon indented 4 spaces, it is an
                # initializer list.
                exception = (Match(r' {4}\w[^\(]*\)\s*(const\s*)?(\{\s*$|:)',
                                   prev_line)
                             or Match(r' {4}:', prev_line))

            if not exception:
                error(filename, linenum, 'whitespace/blank_line', 2,
                      'Redundant blank line at the start of a code block '
                      'should be deleted.')
        # Ignore blank lines at the end of a block in a int if-else
        # chain, like this:
        #   if (condition1) {
        #     // Something followed by a blank line
        #
        #   } else if (condition2) {
        #     // Something else
        #   }
        if linenum + 1 < clean_lines.NumLines():
            next_line = raw[linenum + 1]
            if (next_line
                and Match(r'\s*}', next_line)
                and next_line.find('} else ') == -1):
                error(filename, linenum, 'whitespace/blank_line', 3,
                      'Redundant blank line at the end of a code block '
                      'should be deleted.')

        matched = Match(r'\s*(public|protected|private):', prev_line)
        if matched:
            error(filename, linenum, 'whitespace/blank_line', 3,
                  'Do not leave a blank line after "%s:"' % matched.group(1))

    # Next, check comments
    next_line_start = 0
    if linenum + 1 < clean_lines.NumLines():
        next_line = raw[linenum + 1]
        next_line_start = len(next_line) - len(next_line.lstrip())

    #TODO: checks should not call other checks.
    CheckComment(line, filename, linenum, next_line_start, error)

    # get rid of comments and strings
    line = clean_lines.elided[linenum]

    # You shouldn't have spaces before your brackets, except for C++11 attributes
    # or maybe after 'delete []', 'return []() {};', or 'auto [abc, ...] = ...;'.
    if (Search(r'\w\s+\[(?!\[)', line) and
        not Search(r'(?:auto&?|delete|return)\s+\[', line)):
        error(filename, linenum, 'whitespace/braces', 5,
              'Extra space before [')

    # In range-based for, we wanted spaces before and after the colon, but
    # not around "::" tokens that might appear.
    if (Search(r'for *\(.*[^:]:[^: ]', line) or
        Search(r'for *\(.*[^: ]:[^:]', line)):
        error(filename, linenum, 'whitespace/forcolon', 2,
              'Missing space around colon in range-based for loop')

def CheckComment(line, filename, linenum, next_line_start, error):
    """Checks for common mistakes in comments.

    Args:
      line: The line in question.
      filename: The name of the current file.
      linenum: The number of the line to check.
      next_line_start: The first non-whitespace column of the next line.
      error: The function to call with any errors found.
    """

    _RE_PATTERN_TODO = re.compile(r'^//(\s*)TODO(\(.+?\))?:?(\s|$)?')

    commentpos = line.find('//')
    if commentpos != -1:
        # Check if the // may be in quotes.  If so, ignore it
        if re.sub(r'\\.', '', line[0:commentpos]).count('"') % 2 == 0:
            # Allow one space for new scopes, two spaces otherwise:
            if (not (Match(r'^.*{ *//', line) and next_line_start == commentpos) and
                ((commentpos >= 1 and
                  line[commentpos-1] not in string.whitespace) or
                 (commentpos >= 2 and
                  line[commentpos-2] not in string.whitespace))):
                error(filename, linenum, 'whitespace/comments', 2,
                      'At least two spaces is best between code and comments')

            # Checks for common mistakes in TODO comments.
            comment = line[commentpos:]
            match = _RE_PATTERN_TODO.match(comment)
            if match:
                # One whitespace is correct; zero whitespace is handled elsewhere.
                leading_whitespace = match.group(1)
                if len(leading_whitespace) > 1:
                    error(filename, linenum, 'whitespace/todo', 2,
                          'Too many spaces before TODO')

                username = match.group(2)
                if not username:
                    error(filename, linenum, 'readability/todo', 2,
                          'Missing username in TODO; it should look like '
                          '"// TODO(my_username): Stuff."')

                middle_whitespace = match.group(3)
                # Comparisons made explicit for correctness -- pylint: disable=g-explicit-bool-comparison
                if middle_whitespace != ' ' and middle_whitespace != '':
                    error(filename, linenum, 'whitespace/todo', 2,
                          'TODO(my_username) should be followed by a space')

            # If the comment contains an alphanumeric character, there
            # should be a space somewhere between it and the // unless
            # it's a /// or //! Doxygen comment.
            if (Match(r'//[^ ]*\w', comment) and
                not Match(r'(///|//\!)(\s+|$)', comment)):
                error(filename, linenum, 'whitespace/comments', 4,
                      'Should have a space between // and comment')
