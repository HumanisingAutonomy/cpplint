import re
import string
from typing import Callable

from .block_info import (
    _CHECK_MACROS,
    CloseExpression,
    FindCheckMacro,
    FindEndOfExpressionInLine,
    GetHeaderGuardCPPVariable,
    GetIndentLevel,
    GetLineWidth,
    GetPreviousNonBlankLine,
    IsBlankLine,
    ReverseCloseExpression,
    _IsType,
)
from .error import (
    ParseNolintSuppressions
)
from .cleansed_lines import CleanseComments, CleansedLines
from .lintstate import LintState
from .regex import Match, ReplaceAll, Search


def CheckStyle(
    state: LintState,
    filename: str,
    clean_lines: CleansedLines,
    line_num: int,
    file_extension: str,
    nesting_state,
    error: Callable[[str, int, str, int, str], None],
):
    """Checks rules from the 'C++ style rules' section of cppguide.html.

    Most of these rules are hard to test (naming, comment style), but we
    do what we can.  In particular we check for 2-space indents, line lengths,
    tab usage, spaces inside code, etc.

    Args:
      state: The current state of linting.
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      line_num: The number of the line to check.
      file_extension: The extension (without the dot) of the filename.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: The function to call with any errors found.
    """

    # TODO: this function should just be a list of checks...

    # Don't use "elided" lines here, otherwise we can't check commented lines.
    # Don't want to use "raw" either, because we don't want to check inside C++11
    # raw strings,
    raw_lines = clean_lines.lines_without_raw_strings
    line = raw_lines[line_num]
    prev = raw_lines[line_num - 1] if line_num > 0 else ""

    if line.find("\t") != -1:
        error(
            state,
            filename,
            line_num,
            "whitespace/tab",
            1,
            "Tab found; better to use spaces",
        )

    # One or three blank spaces at the beginning of the line is weird; it's
    # hard to reconcile that with 2-space indents.
    # NOTE: here are the conditions rob pike used for his tests.  Mine aren't
    # as sophisticated, but it may be worth becoming so:  RLENGTH==initial_spaces
    # if(RLENGTH > 20) complain = 0;
    # if(match($0, " +(error|private|public|protected):")) complain = 0;
    # if(match(prev, "&& *$")) complain = 0;
    # if(match(prev, "\\|\\| *$")) complain = 0;
    # if(match(prev, "[\",=><] *$")) complain = 0;
    # if(match($0, " <<")) complain = 0;
    # if(match(prev, " +for \\(")) complain = 0;
    # if(prevodd && match(prevprev, " +for \\(")) complain = 0;
    scope_or_label_pattern = r"\s*(?:public|private|protected|signals)(?:\s+(?:slots\s*)?)?:\s*\\?$"
    classinfo = nesting_state.InnermostClass()
    initial_spaces = 0
    cleansed_line = clean_lines.elided[line_num]
    while initial_spaces < len(line) and line[initial_spaces] == " ":
        initial_spaces += 1
    # There are certain situations we allow one space, notably for
    # section labels, and also lines containing multi-line raw strings.
    # We also don't check for lines that look like continuation lines
    # (of lines ending in double quotes, commas, equals, or angle brackets)
    # because the rules for how to indent those are non-trivial.
    if (
        not Search(r'[",=><] *$', prev)
        and (initial_spaces == 1 or initial_spaces == 3)
        and not Match(scope_or_label_pattern, cleansed_line)
        and not (clean_lines.raw_lines[line_num] != line and Match(r'^\s*""', line))
    ):
        error(
            state,
            filename,
            line_num,
            "whitespace/indent",
            3,
            "Weird number of spaces at line-start.  " "Are you using a 2-space indent?",
        )

    if line and line[-1].isspace():
        error(
            state,
            filename,
            line_num,
            "whitespace/end_of_line",
            4,
            "Line ends in whitespace.  Consider deleting these extra spaces.",
        )

    # Check if the line is a header guard.
    is_header_guard = False
    if state.IsHeaderExtension(file_extension):
        cppvar = GetHeaderGuardCPPVariable(state, filename)
        if (
            line.startswith("#ifndef %s" % cppvar)
            or line.startswith("#define %s" % cppvar)
            or line.startswith("#endif  // %s" % cppvar)
        ):
            is_header_guard = True
    # #include lines and header guards can be long, since there's no clean way to
    # split them.
    #
    # URLs can be int too.  It's possible to split these, but it makes them
    # harder to cut&paste.
    #
    # The "$Id:...$" comment may also get very int without it being the
    # developers fault.
    #
    # Doxygen documentation copying can get pretty int when using an overloaded
    # function declaration
    if (
        not line.startswith("#include")
        and not is_header_guard
        and not Match(r"^\s*//.*http(s?)://\S*$", line)
        and not Match(r"^\s*//\s*[^\s]*$", line)
        and not Match(r"^// \$Id:.*#[0-9]+ \$$", line)
        and not Match(r"^\s*/// [@\\](copydoc|copydetails|copybrief) .*$", line)
    ):
        line_width = GetLineWidth(line)
        if line_width > state._line_length:
            error(
                state,
                filename,
                line_num,
                "whitespace/line_length",
                2,
                "Lines should be <= %i characters long" % state._line_length,
            )

    if (
        cleansed_line.count(";") > 1
        # allow simple single line lambdas
        and not Match(r"^[^{};]*\[[^\[\]]*\][^{}]*\{[^{}\n\r]*\}", line)
        # for loops are allowed two ;'s (and may run over two lines).
        and cleansed_line.find("for") == -1
        and (
            GetPreviousNonBlankLine(clean_lines, line_num)[0].find("for") == -1
            or GetPreviousNonBlankLine(clean_lines, line_num)[0].find(";") != -1
        )
        # It's ok to have many commands in a switch case that fits in 1 line
        and not (
            (cleansed_line.find("case ") != -1 or cleansed_line.find("default:") != -1)
            and cleansed_line.find("break;") != -1
        )
    ):
        error(
            state,
            filename,
            line_num,
            "whitespace/newline",
            0,
            "More than one command on the same line",
        )

    # Some more style checks
    CheckBraces(state, filename, clean_lines, line_num, error)
    CheckTrailingSemicolon(state, filename, clean_lines, line_num, error)
    CheckEmptyBlockBody(state, filename, clean_lines, line_num, error)
    CheckSpacing(state, filename, clean_lines, line_num, nesting_state, error)
    CheckOperatorSpacing(state, filename, clean_lines, line_num, error)
    CheckParenthesisSpacing(state, filename, clean_lines, line_num, error)
    CheckCommaSpacing(state, filename, clean_lines, line_num, error)
    CheckBracesSpacing(state, filename, clean_lines, line_num, nesting_state, error)
    CheckSpacingForFunctionCall(state, filename, clean_lines, line_num, error)
    CheckCheck(state, filename, clean_lines, line_num, error)
    CheckAltTokens(state, filename, clean_lines, line_num, error)
    classinfo = nesting_state.InnermostClass()
    if classinfo:
        CheckSectionSpacing(state, filename, clean_lines, classinfo, line_num, error)


def CheckBraces(state: LintState, filename, clean_lines, line_num, error):
    """Looks for misplaced braces (e.g. at the end of line).

    Args:
      state: The current state of the linting process.
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      line_num: The number of the line to check.
      error: The function to call with any errors found.
    """

    line = clean_lines.elided[line_num]  # get rid of comments and strings

    if Match(r"\s*{\s*$", line):
        # We allow an open brace to start a line in the case where someone is using
        # braces in a block to explicitly create a new scope, which is commonly used
        # to control the lifetime of stack-allocated variables.  Braces are also
        # used for brace initializers inside function calls.  We don't detect this
        # perfectly: we just don't complain if the last non-whitespace character on
        # the previous non-blank line is ',', ';', ':', '(', '{', or '}', or if the
        # previous line starts a preprocessor block. We also allow a brace on the
        # following line if it is part of an array initialization and would not fit
        # within the 80 character limit of the preceding line.
        prevline = GetPreviousNonBlankLine(clean_lines, line_num)[0]
        if (
            not Search(r"[,;:}{(]\s*$", prevline)
            and not Match(r"\s*#", prevline)
            and not (GetLineWidth(prevline) > state._line_length - 2 and "[]" in prevline)
        ):
            error(
                state,
                filename,
                line_num,
                "whitespace/braces",
                4,
                "{ should almost always be at the end of the previous line",
            )

    # An else clause should be on the same line as the preceding closing brace.
    if Match(r"\s*else\b\s*(?:if\b|\{|$)", line):
        prevline = GetPreviousNonBlankLine(clean_lines, line_num)[0]
        if Match(r"\s*}\s*$", prevline):
            error(
                state,
                filename,
                line_num,
                "whitespace/newline",
                4,
                "An else should appear on the same line as the preceding }",
            )

    # If braces come on one side of an else, they should be on both.
    # However, we have to worry about "else if" that spans multiple lines!
    if Search(r"else if\s*\(", line):  # could be multi-line if
        brace_on_left = bool(Search(r"}\s*else if\s*\(", line))
        # find the ( after the if
        pos = line.find("else if")
        pos = line.find("(", pos)
        if pos > 0:
            (endline, _, endpos) = CloseExpression(clean_lines, line_num, pos)
            brace_on_right = endline[endpos:].find("{") != -1
            if brace_on_left != brace_on_right:  # must be brace after if
                error(
                    state,
                    filename,
                    line_num,
                    "readability/braces",
                    5,
                    "If an else has a brace on one side, it should have it on both",
                )
    elif Search(r"}\s*else[^{]*$", line) or Match(r"[^}]*else\s*{", line):
        error(
            state,
            filename,
            line_num,
            "readability/braces",
            5,
            "If an else has a brace on one side, it should have it on both",
        )

    # Likewise, an else should never have the else clause on the same line
    if Search(r"\belse [^\s{]", line) and not Search(r"\belse if\b", line):
        error(
            state,
            filename,
            line_num,
            "whitespace/newline",
            4,
            "Else clause should never be on same line as else (use 2 lines)",
        )

    # In the same way, a do/while should never be on one line
    if Match(r"\s*do [^\s{]", line):
        error(
            state,
            filename,
            line_num,
            "whitespace/newline",
            4,
            "do/while clauses should not be on a single line",
        )

    # Check single-line if/else bodies. The style guide says 'curly braces are not
    # required for single-line statements'. We additionally allow multi-line,
    # single statements, but we reject anything with more than one semicolon in
    # it. This means that the first semicolon after the if should be at the end of
    # its line, and the line after that should have an indent level equal to or
    # lower than the if. We also check for ambiguous if/else nesting without
    # braces.
    if_else_match = Search(r"\b(if\s*(|constexpr)\s*\(|else\b)", line)
    if if_else_match and not Match(r"\s*#", line):
        if_indent = GetIndentLevel(line)
        endline, endlinenum, endpos = line, line_num, if_else_match.end()
        if_match = Search(r"\bif\s*(|constexpr)\s*\(", line)
        if if_match:
            # This could be a multiline if condition, so find the end first.
            pos = if_match.end() - 1
            (endline, endlinenum, endpos) = CloseExpression(clean_lines, line_num, pos)
        # Check for an opening brace, either directly after the if or on the next
        # line. If found, this isn't a single-statement conditional.
        if not Match(r"\s*{", endline[endpos:]) and not (
            Match(r"\s*$", endline[endpos:])
            and endlinenum < (len(clean_lines.elided) - 1)
            and Match(r"\s*{", clean_lines.elided[endlinenum + 1])
        ):
            while endlinenum < len(clean_lines.elided) and ";" not in clean_lines.elided[endlinenum][endpos:]:
                endlinenum += 1
                endpos = 0
            if endlinenum < len(clean_lines.elided):
                endline = clean_lines.elided[endlinenum]
                # We allow a mix of whitespace and closing braces (e.g. for one-liner
                # methods) and a single \ after the semicolon (for macros)
                endpos = endline.find(";")
                if not Match(r";[\s}]*(\\?)$", endline[endpos:]):
                    # Semicolon isn't the last character, there's something trailing.
                    # Output a warning if the semicolon is not contained inside
                    # a lambda expression.
                    if not Match(r"^[^{};]*\[[^\[\]]*\][^{}]*\{[^{}]*\}\s*\)*[;,]\s*$", endline):
                        error(
                            state,
                            filename,
                            line_num,
                            "readability/braces",
                            4,
                            "If/else bodies with multiple statements require braces",
                        )
                elif endlinenum < len(clean_lines.elided) - 1:
                    # Make sure the next line is dedented
                    next_line = clean_lines.elided[endlinenum + 1]
                    next_indent = GetIndentLevel(next_line)
                    # With ambiguous nested if statements, this will error out on the
                    # if that *doesn't* match the else, regardless of whether it's the
                    # inner one or outer one.
                    if if_match and Match(r"\s*else\b", next_line) and next_indent != if_indent:
                        error(
                            state,
                            filename,
                            line_num,
                            "readability/braces",
                            4,
                            "Else clause should be indented at the same level as if. "
                            "Ambiguous nested if/else chains require braces.",
                        )
                    elif next_indent > if_indent:
                        error(
                            state,
                            filename,
                            line_num,
                            "readability/braces",
                            4,
                            "If/else bodies with multiple statements require braces",
                        )


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
    match = Match(r"^(.*\)\s*)\{", line)
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
        closing_brace_pos = match.group(1).rfind(")")
        opening_parenthesis = ReverseCloseExpression(clean_lines, linenum, closing_brace_pos)
        if opening_parenthesis[2] > -1:
            line_prefix = opening_parenthesis[0][0 : opening_parenthesis[2]]
            macro = Search(r"\b([A-Z_][A-Z0-9_]*)\s*$", line_prefix)
            func = Match(r"^(.*\])\s*$", line_prefix)
            if (
                (
                    macro
                    and macro.group(1)
                    not in (
                        "TEST",
                        "TEST_F",
                        "MATCHER",
                        "MATCHER_P",
                        "TYPED_TEST",
                        "EXCLUSIVE_LOCKS_REQUIRED",
                        "SHARED_LOCKS_REQUIRED",
                        "LOCKS_EXCLUDED",
                        "INTERFACE_DEF",
                    )
                )
                or (func and not Search(r"\boperator\s*\[\s*\]", func.group(1)))
                or Search(r"\b(?:struct|union)\s+alignas\s*$", line_prefix)
                or Search(r"\bdecltype$", line_prefix)
                or Search(r"\s+=\s*$", line_prefix)
            ):
                match = None
        if match and opening_parenthesis[1] > 1 and Search(r"\]\s*$", clean_lines.elided[opening_parenthesis[1] - 1]):
            # Multi-line lambda-expression
            match = None

    else:
        # Try matching cases 2-3.
        match = Match(r"^(.*(?:else|\)\s*const)\s*)\{", line)
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
            if prevline and Search(r"[;{}]\s*$", prevline):
                match = Match(r"^(\s*)\{", line)

    # Check matching closing brace
    if match:
        (endline, endlinenum, endpos) = CloseExpression(clean_lines, linenum, len(match.group(1)))
        if endpos > -1 and Match(r"^\s*;", endline[endpos:]):
            # Current {} pair is eligible for semicolon check, and we have found
            # the redundant semicolon, output warning here.
            #
            # Note: because we are scanning forward for opening braces, and
            # outputting warnings for the matching closing brace, if there are
            # nested blocks with trailing semicolons, we will get the error
            # messages in reversed order.

            # We need to check the line forward for NOLINT
            raw_lines = clean_lines.raw_lines
            ParseNolintSuppressions(state, filename, raw_lines[endlinenum - 1], endlinenum - 1, error)
            ParseNolintSuppressions(state, filename, raw_lines[endlinenum], endlinenum, error)

            error(
                state,
                filename,
                endlinenum,
                "readability/braces",
                4,
                "You don't need a ; after a }",
            )


# Pattern that matches only complete whitespace, possibly across multiple lines.
_EMPTY_CONDITIONAL_BODY_PATTERN = re.compile(r"^\s*$", re.DOTALL)


def CheckEmptyBlockBody(state, filename, clean_lines, linenum, error):
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
    matched = Match(r"\s*(for|while|if)\s*\(", line)
    if matched:
        # Find the end of the conditional expression.
        (end_line, end_linenum, end_pos) = CloseExpression(clean_lines, linenum, line.find("("))

        # Output warning if what follows the condition expression is a semicolon.
        # No warning for all other cases, including whitespace or newline, since we
        # have a separate check for semicolons preceded by whitespace.
        if end_pos >= 0 and Match(r";", end_line[end_pos:]):
            if matched.group(1) == "if":
                error(
                    state,
                    filename,
                    end_linenum,
                    "whitespace/empty_conditional_body",
                    5,
                    "Empty conditional bodies should use {}",
                )
            else:
                error(
                    state,
                    filename,
                    end_linenum,
                    "whitespace/empty_loop_body",
                    5,
                    "Empty loop bodies should use {} or continue",
                )

        # Check for if statements that have completely empty bodies (no comments)
        # and no else clauses.
        if end_pos >= 0 and matched.group(1) == "if":
            # Find the position of the opening { for the if statement.
            # Return without logging an error if it has no brackets.
            opening_linenum = end_linenum
            opening_line_fragment = end_line[end_pos:]
            # Loop until EOF or find anything that's not whitespace or opening {.
            while not Search(r"^\s*\{", opening_line_fragment):
                if Search(r"^(?!\s*$)", opening_line_fragment):
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
            opening_pos = opening_line_fragment.find("{")
            if opening_linenum == end_linenum:
                # We need to make opening_pos relative to the start of the entire line.
                opening_pos += end_pos
            (closing_line, closing_linenum, closing_pos) = CloseExpression(clean_lines, opening_linenum, opening_pos)
            if closing_pos < 0:
                return

            # Now construct the body of the conditional. This consists of the portion
            # of the opening line after the {, all lines until the closing line,
            # and the portion of the closing line before the }.
            if clean_lines.raw_lines[opening_linenum] != CleanseComments(clean_lines.raw_lines[opening_linenum]):
                # Opening line ends with a comment, so conditional isn't empty.
                return
            if closing_linenum > opening_linenum:
                # Opening line after the {. Ignore comments here since we checked above.
                bodylist = list(opening_line[opening_pos + 1 :])
                # All lines until closing line, excluding closing line, with comments.
                bodylist.extend(clean_lines.raw_lines[opening_linenum + 1 : closing_linenum])
                # Closing line before the }. Won't (and can't) have comments.
                bodylist.append(clean_lines.elided[closing_linenum][: closing_pos - 1])
                body = "\n".join(bodylist)
            else:
                # If statement has brackets and fits on a single line.
                body = opening_line[opening_pos + 1 : closing_pos - 1]

            # Check if the body is empty
            if not _EMPTY_CONDITIONAL_BODY_PATTERN.search(body):
                return
            # The body is empty. Now make sure there's not an else clause.
            current_linenum = closing_linenum
            current_line_fragment = closing_line[closing_pos:]
            # Loop until EOF or find anything that's not whitespace or else clause.
            while Search(r"^\s*$|^(?=\s*else)", current_line_fragment):
                if Search(r"^(?=\s*else)", current_line_fragment):
                    # Found an else clause, so don't log an error.
                    return
                current_linenum += 1
                if current_linenum == len(clean_lines.elided):
                    break
                current_line_fragment = clean_lines.elided[current_linenum]

            # The body is empty and there's no else clause until EOF or other code.
            error(
                state,
                filename,
                end_linenum,
                "whitespace/empty_if_body",
                4,
                ("If statement had no body and no else clause"),
            )


def CheckSpacing(state, filename, clean_lines, linenum, nesting_state, error):
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
    if IsBlankLine(line) and not nesting_state.InNamespaceBody() and not nesting_state.InExternC():
        elided = clean_lines.elided
        prev_line = elided[linenum - 1]
        prevbrace = prev_line.rfind("{")
        # TODO(unknown): Don't complain if line before blank line, and line after,
        #                both start with alnums and are indented the same amount.
        #                This ignores whitespace at the start of a namespace block
        #                because those are not usually indented.
        if prevbrace != -1 and prev_line[prevbrace:].find("}") == -1:
            # OK, we have a blank line at the start of a code block.  Before we
            # complain, we check if it is an exception to the rule: The previous
            # non-empty line has the parameters of a function header that are indented
            # 4 spaces (because they did not fit in a 80 column line when placed on
            # the same line as the function name).  We also check for the case where
            # the previous line is indented 6 spaces, which may happen when the
            # initializers of a constructor do not fit into a 80 column line.
            exception = False
            if Match(r" {6}\w", prev_line):  # Initializer list?
                # We are looking for the opening column of initializer list, which
                # should be indented 4 spaces to cause 6 space indentation afterwards.
                search_position = linenum - 2
                while search_position >= 0 and Match(r" {6}\w", elided[search_position]):
                    search_position -= 1
                exception = search_position >= 0 and elided[search_position][:5] == "    :"
            else:
                # Search for the function arguments or an initializer list.  We use a
                # simple heuristic here: If the line is indented 4 spaces; and we have a
                # closing paren, without the opening paren, followed by an opening brace
                # or colon (for initializer lists) we assume that it is the last line of
                # a function header.  If we have a colon indented 4 spaces, it is an
                # initializer list.
                exception = Match(r" {4}\w[^\(]*\)\s*(const\s*)?(\{\s*$|:)", prev_line) or Match(r" {4}:", prev_line)

            if not exception:
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/blank_line",
                    2,
                    "Redundant blank line at the start of a code block " "should be deleted.",
                )
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
            if next_line and Match(r"\s*}", next_line) and next_line.find("} else ") == -1:
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/blank_line",
                    3,
                    "Redundant blank line at the end of a code block " "should be deleted.",
                )

        matched = Match(r"\s*(public|protected|private):", prev_line)
        if matched:
            error(
                state,
                filename,
                linenum,
                "whitespace/blank_line",
                3,
                'Do not leave a blank line after "%s:"' % matched.group(1),
            )

    # Next, check comments
    next_line_start = 0
    if linenum + 1 < clean_lines.NumLines():
        next_line = raw[linenum + 1]
        next_line_start = len(next_line) - len(next_line.lstrip())

    # TODO: checks should not call other checks.
    CheckComment(state, line, filename, linenum, next_line_start, error)

    # get rid of comments and strings
    line = clean_lines.elided[linenum]

    # You shouldn't have spaces before your brackets, except for C++11 attributes
    # or maybe after 'delete []', 'return []() {};', or 'auto [abc, ...] = ...;'.
    if Search(r"\w\s+\[(?!\[)", line) and not Search(r"(?:auto&?|delete|return)\s+\[", line):
        error(state, filename, linenum, "whitespace/braces", 5, "Extra space before [")

    # In range-based for, we wanted spaces before and after the colon, but
    # not around "::" tokens that might appear.
    if Search(r"for *\(.*[^:]:[^: ]", line) or Search(r"for *\(.*[^: ]:[^:]", line):
        error(
            state,
            filename,
            linenum,
            "whitespace/forcolon",
            2,
            "Missing space around colon in range-based for loop",
        )


def CheckComment(state, line, filename, linenum, next_line_start, error):
    """Checks for common mistakes in comments.

    Args:
      line: The line in question.
      filename: The name of the current file.
      linenum: The number of the line to check.
      next_line_start: The first non-whitespace column of the next line.
      error: The function to call with any errors found.
    """

    _RE_PATTERN_TODO = re.compile(r"^//(\s*)TODO(\(.+?\))?:?(\s|$)?")

    commentpos = line.find("//")
    if commentpos != -1:
        # Check if the // may be in quotes.  If so, ignore it
        if re.sub(r"\\.", "", line[0:commentpos]).count('"') % 2 == 0:
            # Allow one space for new scopes, two spaces otherwise:
            if not (Match(r"^.*{ *//", line) and next_line_start == commentpos) and (
                (commentpos >= 1 and line[commentpos - 1] not in string.whitespace)
                or (commentpos >= 2 and line[commentpos - 2] not in string.whitespace)
            ):
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/comments",
                    2,
                    "At least two spaces is best between code and comments",
                )

            # Checks for common mistakes in TODO comments.
            comment = line[commentpos:]
            match = _RE_PATTERN_TODO.match(comment)
            if match:
                # One whitespace is correct; zero whitespace is handled elsewhere.
                leading_whitespace = match.group(1)
                if len(leading_whitespace) > 1:
                    error(
                        state,
                        filename,
                        linenum,
                        "whitespace/todo",
                        2,
                        "Too many spaces before TODO",
                    )

                username = match.group(2)
                if not username:
                    error(
                        state,
                        filename,
                        linenum,
                        "readability/todo",
                        2,
                        "Missing username in TODO; it should look like " '"// TODO(my_username): Stuff."',
                    )

                middle_whitespace = match.group(3)
                # Comparisons made explicit for correctness -- pylint: disable=g-explicit-bool-comparison
                if middle_whitespace != " " and middle_whitespace != "":
                    error(
                        state,
                        filename,
                        linenum,
                        "whitespace/todo",
                        2,
                        "TODO(my_username) should be followed by a space",
                    )

            # If the comment contains an alphanumeric character, there
            # should be a space somewhere between it and the // unless
            # it's a /// or //! Doxygen comment.
            if Match(r"//[^ ]*\w", comment) and not Match(r"(///|//\!)(\s+|$)", comment):
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/comments",
                    4,
                    "Should have a space between // and comment",
                )


def CheckOperatorSpacing(state, filename, clean_lines, linenum, error):
    """Checks for horizontal spacing around operators.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # Don't try to do spacing checks for operator methods.  Do this by
    # replacing the troublesome characters with something else,
    # preserving column position for all other characters.
    #
    # The replacement is done repeatedly to avoid false positives from
    # operators that call operators.
    while True:
        match = Match(r"^(.*\boperator\b)(\S+)(\s*\(.*)$", line)
        if match:
            line = match.group(1) + ("_" * len(match.group(2))) + match.group(3)
        else:
            break

    # We allow no-spaces around = within an if: "if ( (a=Foo()) == 0 )".
    # Otherwise not.  Note we only check for non-spaces on *both* sides;
    # sometimes people put non-spaces on one side when aligning ='s among
    # many lines (not that this is behavior that I approve of...)
    if (
        (Search(r"[\w.]=", line) or Search(r"=[\w.]", line))
        and not Search(r"\b(if|while|for) ", line)
        # Operators taken from [lex.operators] in C++11 standard.
        and not Search(r"(>=|<=|==|!=|&=|\^=|\|=|\+=|\*=|\/=|\%=)", line)
        and not Search(r"operator=", line)
    ):
        error(
            state,
            filename,
            linenum,
            "whitespace/operators",
            4,
            "Missing spaces around =",
        )

    # It's ok not to have spaces around binary operators like + - * /, but if
    # there's too little whitespace, we get concerned.  It's hard to tell,
    # though, so we punt on this one for now.  TODO.

    # You should always have whitespace around binary operators.
    #
    # Check <= and >= first to avoid false positives with < and >, then
    # check non-include lines for spacing around < and >.
    #
    # If the operator is followed by a comma, assume it's be used in a
    # macro context and don't do any checks.  This avoids false
    # positives.
    #
    # Note that && is not included here.  This is because there are too
    # many false positives due to RValue references.
    match = Search(r"[^<>=!\s](==|!=|<=|>=|\|\|)[^<>=!\s,;\)]", line)
    if match:
        error(
            state,
            filename,
            linenum,
            "whitespace/operators",
            3,
            "Missing spaces around %s" % match.group(1),
        )
    elif not Match(r"#.*include", line):
        # Look for < that is not surrounded by spaces.  This is only
        # triggered if both sides are missing spaces, even though
        # technically should should flag if at least one side is missing a
        # space.  This is done to avoid some false positives with shifts.
        match = Match(r"^(.*[^\s<])<[^\s=<,]", line)
        if match:
            (_, _, end_pos) = CloseExpression(clean_lines, linenum, len(match.group(1)))
            if end_pos <= -1:
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/operators",
                    3,
                    "Missing spaces around <",
                )

        # Look for > that is not surrounded by spaces.  Similar to the
        # above, we only trigger if both sides are missing spaces to avoid
        # false positives with shifts.
        match = Match(r"^(.*[^-\s>])>[^\s=>,]", line)
        if match:
            (_, _, start_pos) = ReverseCloseExpression(clean_lines, linenum, len(match.group(1)))
            if start_pos <= -1:
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/operators",
                    3,
                    "Missing spaces around >",
                )

    # We allow no-spaces around << when used like this: 10<<20, but
    # not otherwise (particularly, not when used as streams)
    #
    # We also allow operators following an opening parenthesis, since
    # those tend to be macros that deal with operators.
    match = Search(r"(operator|[^\s(<])(?:L|UL|LL|ULL|l|ul|ll|ull)?<<([^\s,=<])", line)
    if (
        match
        and not (match.group(1).isdigit() and match.group(2).isdigit())
        and not (match.group(1) == "operator" and match.group(2) == ";")
    ):
        error(
            state,
            filename,
            linenum,
            "whitespace/operators",
            3,
            "Missing spaces around <<",
        )

    # We allow no-spaces around >> for almost anything.  This is because
    # C++11 allows ">>" to close nested templates, which accounts for
    # most cases when ">>" is not followed by a space.
    #
    # We still warn on ">>" followed by alpha character, because that is
    # likely due to ">>" being used for right shifts, e.g.:
    #   value >> alpha
    #
    # When ">>" is used to close templates, the alphanumeric letter that
    # follows would be part of an identifier, and there should still be
    # a space separating the template type and the identifier.
    #   type<type<type>> alpha
    match = Search(r">>[a-zA-Z_]", line)
    if match:
        error(
            state,
            filename,
            linenum,
            "whitespace/operators",
            3,
            "Missing spaces around >>",
        )

    # There shouldn't be space around unary operators
    match = Search(r"(!\s|~\s|[\s]--[\s;]|[\s]\+\+[\s;])", line)
    if match:
        error(
            state,
            filename,
            linenum,
            "whitespace/operators",
            4,
            "Extra space for operator %s" % match.group(1),
        )


def CheckParenthesisSpacing(state, filename, clean_lines, linenum, error):
    """Checks for horizontal spacing around parentheses.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # No spaces after an if, while, switch, or for
    match = Search(r" (if\(|for\(|while\(|switch\()", line)
    if match:
        error(
            state,
            filename,
            linenum,
            "whitespace/parens",
            5,
            "Missing space before ( in %s" % match.group(1),
        )

    # For if/for/while/switch, the left and right parens should be
    # consistent about how many spaces are inside the parens, and
    # there should either be zero or one spaces inside the parens.
    # We don't want: "if ( foo)" or "if ( foo   )".
    # Exception: "for ( ; foo; bar)" and "for (foo; bar; )" are allowed.
    match = Search(r"\b(if|for|while|switch)\s*" r"\(([ ]*)(.).*[^ ]+([ ]*)\)\s*{\s*$", line)
    if match:
        if len(match.group(2)) != len(match.group(4)):
            if not (
                match.group(3) == ";"
                and len(match.group(2)) == 1 + len(match.group(4))
                or not match.group(2)
                and Search(r"\bfor\s*\(.*; \)", line)
            ):
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/parens",
                    5,
                    "Mismatching spaces inside () in %s" % match.group(1),
                )
        if len(match.group(2)) not in [0, 1]:
            error(
                state,
                filename,
                linenum,
                "whitespace/parens",
                5,
                "Should have zero or one spaces inside ( and ) in %s" % match.group(1),
            )


def CheckCommaSpacing(state, filename, clean_lines, linenum, error):
    """Checks for horizontal spacing near commas and semicolons.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    raw = clean_lines.lines_without_raw_strings
    line = clean_lines.elided[linenum]

    # You should always have a space after a comma (either as fn arg or operator)
    #
    # This does not apply when the non-space character following the
    # comma is another comma, since the only time when that happens is
    # for empty macro arguments.
    #
    # We run this check in two passes: first pass on elided lines to
    # verify that lines contain missing whitespaces, second pass on raw
    # lines to confirm that those missing whitespaces are not due to
    # elided comments.
    if Search(r",[^,\s]", ReplaceAll(r"\boperator\s*,\s*\(", "F(", line)) and Search(r",[^,\s]", raw[linenum]):
        error(state, filename, linenum, "whitespace/comma", 3, "Missing space after ,")

    # You should always have a space after a semicolon
    # except for few corner cases
    # TODO(unknown): clarify if 'if (1) { return 1;}' is requires one more
    # space after ;
    if Search(r";[^\s};\\)/]", line):
        error(state, filename, linenum, "whitespace/semicolon", 3, "Missing space after ;")


def CheckBracesSpacing(state, filename, clean_lines, linenum, nesting_state, error):
    """Checks for horizontal spacing near commas.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      nesting_state: A NestingState instance which maintains information about
                     the current stack of nested blocks being parsed.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # Except after an opening paren, or after another opening brace (in case of
    # an initializer list, for instance), you should have spaces before your
    # braces when they are delimiting blocks, classes, namespaces etc.
    # And since you should never have braces at the beginning of a line,
    # this is an easy test.  Except that braces used for initialization don't
    # follow the same rule; we often don't want spaces before those.
    match = Match(r"^(.*[^ ({>]){", line)

    if match:
        # Try a bit harder to check for brace initialization.  This
        # happens in one of the following forms:
        #   Constructor() : initializer_list_{} { ... }
        #   Constructor{}.MemberFunction()
        #   Type variable{};
        #   FunctionCall(type{}, ...);
        #   LastArgument(..., type{});
        #   LOG(INFO) << type{} << " ...";
        #   map_of_type[{...}] = ...;
        #   ternary = expr ? new type{} : nullptr;
        #   OuterTemplate<InnerTemplateConstructor<Type>{}>
        #
        # We check for the character following the closing brace, and
        # silence the warning if it's one of those listed above, i.e.
        # "{.;,)<>]:".
        #
        # To account for nested initializer list, we allow any number of
        # closing braces up to "{;,)<".  We can't simply silence the
        # warning on first sight of closing brace, because that would
        # cause false negatives for things that are not initializer lists.
        #   Silence this:         But not this:
        #     Outer{                if (...) {
        #       Inner{...}            if (...){  // Missing space before {
        #     };                    }
        #
        # There is a false negative with this approach if people inserted
        # spurious semicolons, e.g. "if (cond){};", but we will catch the
        # spurious semicolon with a separate check.
        leading_text = match.group(1)
        (endline, endlinenum, endpos) = CloseExpression(clean_lines, linenum, len(match.group(1)))
        trailing_text = ""
        if endpos > -1:
            trailing_text = endline[endpos:]
        for offset in range(endlinenum + 1, min(endlinenum + 3, clean_lines.NumLines() - 1)):
            trailing_text += clean_lines.elided[offset]
        # We also suppress warnings for `uint64_t{expression}` etc., as the style
        # guide recommends brace initialization for integral types to avoid
        # overflow/truncation.
        if not Match(r"^[\s}]*[{.;,)<>\]:]", trailing_text) and not _IsType(clean_lines, nesting_state, leading_text):
            error(
                state,
                filename,
                linenum,
                "whitespace/braces",
                5,
                "Missing space before {",
            )

    # Make sure '} else {' has spaces.
    if Search(r"}else", line):
        error(
            state,
            filename,
            linenum,
            "whitespace/braces",
            5,
            "Missing space before else",
        )

    # You shouldn't have a space before a semicolon at the end of the line.
    # There's a special case for "for" since the style guide allows space before
    # the semicolon there.
    if Search(r":\s*;\s*$", line):
        error(
            state,
            filename,
            linenum,
            "whitespace/semicolon",
            5,
            "Semicolon defining empty statement. Use {} instead.",
        )
    elif Search(r"^\s*;\s*$", line):
        error(
            state,
            filename,
            linenum,
            "whitespace/semicolon",
            5,
            "Line contains only semicolon. If this should be an empty statement, " "use {} instead.",
        )
    elif Search(r"\s+;\s*$", line) and not Search(r"\bfor\b", line):
        error(
            state,
            filename,
            linenum,
            "whitespace/semicolon",
            5,
            "Extra space before last semicolon. If this should be an empty " "statement, use {} instead.",
        )


def CheckSpacingForFunctionCall(state, filename, clean_lines, linenum, error):
    """Checks for the correctness of various spacing around function calls.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    line = clean_lines.elided[linenum]

    # Since function calls often occur inside if/for/while/switch
    # expressions - which have their own, more liberal conventions - we
    # first see if we should be looking inside such an expression for a
    # function call, to which we can apply more strict standards.
    fncall = line  # if there's no control flow construct, look at whole line
    for pattern in (
        r"\bif\s*\((.*)\)\s*{",
        r"\bfor\s*\((.*)\)\s*{",
        r"\bwhile\s*\((.*)\)\s*[{;]",
        r"\bswitch\s*\((.*)\)\s*{",
    ):
        match = Search(pattern, line)
        if match:
            fncall = match.group(1)  # look inside the parens for function calls
            break

    # Except in if/for/while/switch, there should never be space
    # immediately inside parens (eg "f( 3, 4 )").  We make an exception
    # for nested parens ( (a+b) + c ).  Likewise, there should never be
    # a space before a ( when it's a function argument.  I assume it's a
    # function argument when the char before the whitespace is legal in
    # a function name (alnum + _) and we're not starting a macro. Also ignore
    # pointers and references to arrays and functions coz they're too tricky:
    # we use a very simple way to recognize these:
    # " (something)(maybe-something)" or
    # " (something)(maybe-something," or
    # " (something)[something]"
    # Note that we assume the contents of [] to be short enough that
    # they'll never need to wrap.
    if (  # Ignore control structures.
        not Search(r"\b(if|elif|for|while|switch|return|new|delete|catch|sizeof)\b", fncall)
        # Ignore pointers/references to functions.
        and not Search(r" \([^)]+\)\([^)]*(\)|,$)", fncall)
        # Ignore pointers/references to arrays.
        and not Search(r" \([^)]+\)\[[^\]]+\]", fncall)
    ):
        if Search(r"\w\s*\(\s(?!\s*\\$)", fncall):  # a ( used for a fn call
            error(
                state,
                filename,
                linenum,
                "whitespace/parens",
                4,
                "Extra space after ( in function call",
            )
        elif Search(r"\(\s+(?!(\s*\\)|\()", fncall):
            error(state, filename, linenum, "whitespace/parens", 2, "Extra space after (")
        if (
            Search(r"\w\s+\(", fncall)
            and not Search(r"_{0,2}asm_{0,2}\s+_{0,2}volatile_{0,2}\s+\(", fncall)
            and not Search(r"#\s*define|typedef|using\s+\w+\s*=", fncall)
            and not Search(r"\w\s+\((\w+::)*\*\w+\)\(", fncall)
            and not Search(r"\bcase\s+\(", fncall)
        ):
            # TODO(unknown): Space after an operator function seem to be a common
            # error, silence those for now by restricting them to highest verbosity.
            if Search(r"\boperator_*\b", line):
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/parens",
                    0,
                    "Extra space before ( in function call",
                )
            else:
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/parens",
                    4,
                    "Extra space before ( in function call",
                )
        # If the ) is followed only by a newline or a { + newline, assume it's
        # part of a control statement (if/while/etc), and don't complain
        if Search(r"[^)]\s+\)\s*[^{\s]", fncall):
            # If the closing parenthesis is preceded by only whitespaces,
            # try to give a more descriptive error message.
            if Search(r"^\s+\)", fncall):
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/parens",
                    2,
                    "Closing ) should be moved to the previous line",
                )
            else:
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/parens",
                    2,
                    "Extra space before )",
                )


def CheckCheck(state, filename, clean_lines, linenum, error):
    """Checks the use of CHECK and EXPECT macros.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """

    # Replacement macros for CHECK/DCHECK/EXPECT_TRUE/EXPECT_FALSE
    _CHECK_REPLACEMENT = dict([(macro_var, {}) for macro_var in _CHECK_MACROS])

    for op, replacement in [
        ("==", "EQ"),
        ("!=", "NE"),
        (">=", "GE"),
        (">", "GT"),
        ("<=", "LE"),
        ("<", "LT"),
    ]:
        _CHECK_REPLACEMENT["DCHECK"][op] = "DCHECK_%s" % replacement
        _CHECK_REPLACEMENT["CHECK"][op] = "CHECK_%s" % replacement
        _CHECK_REPLACEMENT["EXPECT_TRUE"][op] = "EXPECT_%s" % replacement
        _CHECK_REPLACEMENT["ASSERT_TRUE"][op] = "ASSERT_%s" % replacement

    for op, inv_replacement in [
        ("==", "NE"),
        ("!=", "EQ"),
        (">=", "LT"),
        (">", "LE"),
        ("<=", "GT"),
        ("<", "GE"),
    ]:
        _CHECK_REPLACEMENT["EXPECT_FALSE"][op] = "EXPECT_%s" % inv_replacement
        _CHECK_REPLACEMENT["ASSERT_FALSE"][op] = "ASSERT_%s" % inv_replacement

    # Decide the set of replacement macros that should be suggested
    lines = clean_lines.elided
    (check_macro, start_pos) = FindCheckMacro(lines[linenum])
    if not check_macro:
        return

    # Find end of the boolean expression by matching parentheses
    (last_line, end_line, end_pos) = CloseExpression(clean_lines, linenum, start_pos)
    if end_pos < 0:
        return

    # If the check macro is followed by something other than a
    # semicolon, assume users will log their own custom error messages
    # and don't suggest any replacements.
    if not Match(r"\s*;", last_line[end_pos:]):
        return

    if linenum == end_line:
        expression = lines[linenum][start_pos + 1 : end_pos - 1]
    else:
        expression = lines[linenum][start_pos + 1 :]
        for i in range(linenum + 1, end_line):
            expression += lines[i]
        expression += last_line[0 : end_pos - 1]

    # Parse expression so that we can take parentheses into account.
    # This avoids false positives for inputs like "CHECK((a < 4) == b)",
    # which is not replaceable by CHECK_LE.
    lhs = ""
    rhs = ""
    operator = None
    while expression:
        matched = Match(
            r"^\s*(<<|<<=|>>|>>=|->\*|->|&&|\|\||" r"==|!=|>=|>|<=|<|\()(.*)$",
            expression,
        )
        if matched:
            token = matched.group(1)
            if token == "(":
                # Parenthesized operand
                expression = matched.group(2)
                (end, _) = FindEndOfExpressionInLine(expression, 0, ["("])
                if end < 0:
                    return  # Unmatched parenthesis
                lhs += "(" + expression[0:end]
                expression = expression[end:]
            elif token in ("&&", "||"):
                # Logical and/or operators.  This means the expression
                # contains more than one term, for example:
                #   CHECK(42 < a && a < b);
                #
                # These are not replaceable with CHECK_LE, so bail out early.
                return
            elif token in ("<<", "<<=", ">>", ">>=", "->*", "->"):
                # Non-relational operator
                lhs += token
                expression = matched.group(2)
            else:
                # Relational operator
                operator = token
                rhs = matched.group(2)
                break
        else:
            # Unparenthesized operand.  Instead of appending to lhs one character
            # at a time, we do another regular expression match to consume several
            # characters at once if possible.  Trivial benchmark shows that this
            # is more efficient when the operands are inter than a single
            # character, which is generally the case.
            matched = Match(r"^([^-=!<>()&|]+)(.*)$", expression)
            if not matched:
                matched = Match(r"^(\s*\S)(.*)$", expression)
                if not matched:
                    break
            lhs += matched.group(1)
            expression = matched.group(2)

    # Only apply checks if we got all parts of the boolean expression
    if not (lhs and operator and rhs):
        return

    # Check that rhs do not contain logical operators.  We already know
    # that lhs is fine since the loop above parses out && and ||.
    if rhs.find("&&") > -1 or rhs.find("||") > -1:
        return

    # At least one of the operands must be a constant literal.  This is
    # to avoid suggesting replacements for unprintable things like
    # CHECK(variable != iterator)
    #
    # The following pattern matches decimal, hex integers, strings, and
    # characters (in that order).
    lhs = lhs.strip()
    rhs = rhs.strip()
    match_constant = r'^([-+]?(\d+|0[xX][0-9a-fA-F]+)[lLuU]{0,3}|".*"|\'.*\')$'
    if Match(match_constant, lhs) or Match(match_constant, rhs):
        # Note: since we know both lhs and rhs, we can provide a more
        # descriptive error message like:
        #   Consider using CHECK_EQ(x, 42) instead of CHECK(x == 42)
        # Instead of:
        #   Consider using CHECK_EQ instead of CHECK(a == b)
        #
        # We are still keeping the less descriptive message because if lhs
        # or rhs gets int, the error message might become unreadable.
        error(
            state,
            filename,
            linenum,
            "readability/check",
            2,
            "Consider using %s instead of %s(a %s b)"
            % (_CHECK_REPLACEMENT[check_macro][operator], check_macro, operator),
        )


def CheckAltTokens(state, filename, clean_lines, linenum, error):
    """Check alternative keywords being used in boolean expressions.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """

    # Alternative tokens and their replacements.  For full list, see section 2.5
    # Alternative tokens [lex.digraph] in the C++ standard.
    #
    # Digraphs (such as '%:') are not included here since it's a mess to
    # match those on a word boundary.
    _ALT_TOKEN_REPLACEMENT = {
        "and": "&&",
        "bitor": "|",
        "or": "||",
        "xor": "^",
        "compl": "~",
        "bitand": "&",
        "and_eq": "&=",
        "or_eq": "|=",
        "xor_eq": "^=",
        "not": "!",
        "not_eq": "!=",
    }

    # Compile regular expression that matches all the above keywords.  The "[ =()]"
    # bit is meant to avoid matching these keywords outside of boolean expressions.
    #
    # False positives include C-style multi-line comments and multi-line strings
    # but those have always been troublesome for cpplint.
    _ALT_TOKEN_REPLACEMENT_PATTERN = re.compile(r"[ =()](" + ("|".join(_ALT_TOKEN_REPLACEMENT.keys())) + r")(?=[ (]|$)")

    line = clean_lines.elided[linenum]

    # Avoid preprocessor lines
    if Match(r"^\s*#", line):
        return

    # Last ditch effort to avoid multi-line comments.  This will not help
    # if the comment started before the current line or ended after the
    # current line, but it catches most of the false positives.  At least,
    # it provides a way to workaround this warning for people who use
    # multi-line comments in preprocessor macros.
    #
    # TODO(unknown): remove this once cpplint has better support for
    # multi-line comments.
    if line.find("/*") >= 0 or line.find("*/") >= 0:
        return

    for match in _ALT_TOKEN_REPLACEMENT_PATTERN.finditer(line):
        error(
            state,
            filename,
            linenum,
            "readability/alt_tokens",
            2,
            "Use operator %s instead of %s" % (_ALT_TOKEN_REPLACEMENT[match.group(1)], match.group(1)),
        )


def CheckSectionSpacing(state, filename, clean_lines, class_info, linenum, error):
    """Checks for additional blank line issues related to sections.

    Currently the only thing checked here is blank line before protected/private.

    Args:
      filename: The name of the current file.
      clean_lines: A CleansedLines instance containing the file.
      class_info: A _ClassInfo objects.
      linenum: The number of the line to check.
      error: The function to call with any errors found.
    """
    # Skip checks if the class is small, where small means 25 lines or less.
    # 25 lines seems like a good cutoff since that's the usual height of
    # terminals, and any class that can't fit in one screen can't really
    # be considered "small".
    #
    # Also skip checks if we are on the first line.  This accounts for
    # classes that look like
    #   class Foo { public: ... };
    #
    # If we didn't find the end of the class, last_line would be zero,
    # and the check will be skipped by the first condition.
    if class_info.last_line - class_info.starting_line_num <= 24 or linenum <= class_info.starting_line_num:
        return

    matched = Match(r"\s*(public|protected|private):", clean_lines.lines[linenum])
    if matched:
        # Issue warning if the line before public/protected/private was
        # not a blank line, but don't do this if the previous line contains
        # "class" or "struct".  This can happen two ways:
        #  - We are at the beginning of the class.
        #  - We are forward-declaring an inner class that is semantically
        #    private, but needed to be public for implementation reasons.
        # Also ignores cases where the previous line ends with a backslash as can be
        # common when defining classes in C macros.
        prev_line = clean_lines.lines[linenum - 1]
        if (
            not IsBlankLine(prev_line)
            and not Search(r"\b(class|struct)\b", prev_line)
            and not Search(r"\\$", prev_line)
        ):
            # Try a bit harder to find the beginning of the class.  This is to
            # account for multi-line base-specifier lists, e.g.:
            #   class Derived
            #       : public Base {
            end_class_head = class_info.starting_line_num
            for i in range(class_info.starting_line_num, linenum):
                if Search(r"\{\s*$", clean_lines.lines[i]):
                    end_class_head = i
                    break
            if end_class_head < linenum - 1:
                error(
                    state,
                    filename,
                    linenum,
                    "whitespace/blank_line",
                    3,
                    '"%s:" should be preceded by a blank line' % matched.group(1),
                )
