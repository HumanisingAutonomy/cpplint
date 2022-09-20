import copy

from .block_info import (
    _BlockInfo, _NamespaceInfo, _ExternCInfo, _ClassInfo, _PreprocessorInfo,
    _NO_ASM, _END_ASM, _MATCH_ASM, _INSIDE_ASM, _BLOCK_ASM,
    CloseExpression,
)
from .cpplint import _CppLintState
from .error import ErrorLogger
from .cleansed_lines import CleansedLines
from .regex import Match


class NestingState(object):
    """Holds states related to parsing braces."""

    def __init__(self):
        # Stack for tracking all braces.  An object is pushed whenever we
        # see a "{", and popped when we see a "}".  Only 3 types of
        # objects are possible:
        # - _ClassInfo: a class or struct.
        # - _NamespaceInfo: a namespace.
        # - _BlockInfo: some other type of block.
        self.stack = []

        # Top of the previous stack before each Update().
        #
        # Because the nesting_stack is updated at the end of each line, we
        # had to do some convoluted checks to find out what is the current
        # scope at the beginning of the line.  This check is simplified by
        # saving the previous top of nesting stack.
        #
        # We could save the full stack, but we only need the top.  Copying
        # the full nesting stack would slow down cpplint by ~10%.
        self.previous_stack_top = []

        # Stack of _PreprocessorInfo objects.
        self.pp_stack = []

    def SeenOpenBrace(self):
        """Check if we have seen the opening brace for the innermost block.

        Returns:
          True if we have seen the opening brace, False if the innermost
          block is still expecting an opening brace.
        """
        return (not self.stack) or self.stack[-1].seen_open_brace

    def InNamespaceBody(self):
        """Check if we are currently one level inside a namespace body.

        Returns:
          True if top of the stack is a namespace block, False otherwise.
        """
        return self.stack and isinstance(self.stack[-1], _NamespaceInfo)

    def InExternC(self):
        """Check if we are currently one level inside an 'extern "C"' block.

        Returns:
          True if top of the stack is an extern block, False otherwise.
        """
        return self.stack and isinstance(self.stack[-1], _ExternCInfo)

    def InClassDeclaration(self):
        """Check if we are currently one level inside a class or struct declaration.

        Returns:
          True if top of the stack is a class/struct, False otherwise.
        """
        return self.stack and isinstance(self.stack[-1], _ClassInfo)

    def InAsmBlock(self):
        """Check if we are currently one level inside an inline ASM block.

        Returns:
          True if the top of the stack is a block containing inline ASM.
        """
        return self.stack and self.stack[-1].inline_asm != _NO_ASM

    def InTemplateArgumentList(self, clean_lines, linenum, pos):
        """Check if current position is inside template argument list.

        Args:
          clean_lines: A CleansedLines instance containing the file.
          linenum: The number of the line to check.
          pos: position just after the suspected template argument.
        Returns:
          True if (linenum, pos) is inside template arguments.
        """
        while linenum < clean_lines.NumLines():
            # Find the earliest character that might indicate a template argument
            line = clean_lines.elided[linenum]
            match = Match(r'^[^{};=\[\]\.<>]*(.)', line[pos:])
            if not match:
                linenum += 1
                pos = 0
                continue
            token = match.group(1)
            pos += len(match.group(0))

            # These things do not look like template argument list:
            #   class Suspect {
            #   class Suspect x; }
            if token in ('{', '}', ';'): return False

            # These things look like template argument list:
            #   template <class Suspect>
            #   template <class Suspect = default_value>
            #   template <class Suspect[]>
            #   template <class Suspect...>
            if token in ('>', '=', '[', ']', '.'): return True

            # Check if token is an unmatched '<'.
            # If not, move on to the next character.
            if token != '<':
                pos += 1
                if pos >= len(line):
                    linenum += 1
                    pos = 0
                continue

            # We can't be sure if we just find a single '<', and need to
            # find the matching '>'.
            (_, end_line, end_pos) = CloseExpression(clean_lines, linenum, pos - 1)
            if end_pos < 0:
                # Not sure if template argument list or syntax error in file
                return False
            linenum = end_line
            pos = end_pos
        return False

    def UpdatePreprocessor(self, line):
        """Update preprocessor stack.

        We need to handle preprocessors due to classes like this:
          #ifdef SWIG
          struct ResultDetailsPageElementExtensionPoint {
          #else
          struct ResultDetailsPageElementExtensionPoint : public Extension {
          #endif

        We make the following assumptions (good enough for most files):
        - Preprocessor condition evaluates to true from #if up to first
          #else/#elif/#endif.

        - Preprocessor condition evaluates to false from #else/#elif up
          to #endif.  We still perform lint checks on these lines, but
          these do not affect nesting stack.

        Args:
          line: current line to check.
        """
        if Match(r'^\s*#\s*(if|ifdef|ifndef)\b', line):
            # Beginning of #if block, save the nesting stack here.  The saved
            # stack will allow us to restore the parsing state in the #else case.
            self.pp_stack.append(_PreprocessorInfo(copy.deepcopy(self.stack)))
        elif Match(r'^\s*#\s*(else|elif)\b', line):
            # Beginning of #else block
            if self.pp_stack:
                if not self.pp_stack[-1].seen_else:
                    # This is the first #else or #elif block.  Remember the
                    # whole nesting stack up to this point.  This is what we
                    # keep after the #endif.
                    self.pp_stack[-1].seen_else = True
                    self.pp_stack[-1].stack_before_else = copy.deepcopy(self.stack)

                # Restore the stack to how it was before the #if
                self.stack = copy.deepcopy(self.pp_stack[-1].stack_before_if)
            else:
                # TODO(unknown): unexpected #else, issue warning?
                pass
        elif Match(r'^\s*#\s*endif\b', line):
            # End of #if or #else blocks.
            if self.pp_stack:
                # If we saw an #else, we will need to restore the nesting
                # stack to its former state before the #else, otherwise we
                # will just continue from where we left off.
                if self.pp_stack[-1].seen_else:
                    # Here we can just use a shallow copy since we are the last
                    # reference to it.
                    self.stack = self.pp_stack[-1].stack_before_else
                # Drop the corresponding #if
                self.pp_stack.pop()
            else:
                # TODO(unknown): unexpected #endif, issue warning?
                pass

    # TODO(unknown): Update() is too long, but we will refactor later.
    def Update(self, state: _CppLintState, filename: str, clean_lines: CleansedLines, linenum: int, error: ErrorLogger):
        """Update nesting state with current line.

        Args:
          filename: The name of the current file.
          clean_lines: A CleansedLines instance containing the file.
          linenum: The number of the line to check.
          error: The function to call with any errors found.
        """
        line = clean_lines.elided[linenum]

        # Remember top of the previous nesting stack.
        #
        # The stack is always pushed/popped and not modified in place, so
        # we can just do a shallow copy instead of copy.deepcopy.  Using
        # deepcopy would slow down cpplint by ~28%.
        if self.stack:
            self.previous_stack_top = self.stack[-1]
        else:
            self.previous_stack_top = None

        # Update pp_stack
        self.UpdatePreprocessor(line)

        # Count parentheses.  This is to avoid adding struct arguments to
        # the nesting stack.
        if self.stack:
            inner_block = self.stack[-1]
            depth_change = line.count('(') - line.count(')')
            inner_block.open_parentheses += depth_change

            # Also check if we are starting or ending an inline assembly block.
            if inner_block.inline_asm in (_NO_ASM, _END_ASM):
                if (depth_change != 0 and
                    inner_block.open_parentheses == 1 and
                    _MATCH_ASM.match(line)):
                    # Enter assembly block
                    inner_block.inline_asm = _INSIDE_ASM
                else:
                    # Not entering assembly block.  If previous line was _END_ASM,
                    # we will now shift to _NO_ASM state.
                    inner_block.inline_asm = _NO_ASM
            elif (inner_block.inline_asm == _INSIDE_ASM and
                  inner_block.open_parentheses == 0):
                # Exit assembly block
                inner_block.inline_asm = _END_ASM

        # Consume namespace declaration at the beginning of the line.  Do
        # this in a loop so that we catch same line declarations like this:
        #   namespace proto2 { namespace bridge { class MessageSet; } }
        while True:
            # Match start of namespace.  The "\b\s*" below catches namespace
            # declarations even if it weren't followed by a whitespace, this
            # is so that we don't confuse our namespace checker.  The
            # missing spaces will be flagged by CheckSpacing.
            namespace_decl_match = Match(r'^\s*namespace\b\s*([:\w]+)?(.*)$', line)
            if not namespace_decl_match:
                break

            new_namespace = _NamespaceInfo(namespace_decl_match.group(1), linenum)
            self.stack.append(new_namespace)

            line = namespace_decl_match.group(2)
            if line.find('{') != -1:
                new_namespace.seen_open_brace = True
                line = line[line.find('{') + 1:]

        # Look for a class declaration in whatever is left of the line
        # after parsing namespaces.  The regexp accounts for decorated classes
        # such as in:
        #   class LOCKABLE API Object {
        #   };
        class_decl_match = Match(
            r'^(\s*(?:template\s*<[\w\s<>,:=]*>\s*)?'
            r'(class|struct)\s+(?:[a-zA-Z0-9_]+\s+)*(\w+(?:::\w+)*))'
            r'(.*)$', line)
        if (class_decl_match and
            (not self.stack or self.stack[-1].open_parentheses == 0)):
            # We do not want to accept classes that are actually template arguments:
            #   template <class Ignore1,
            #             class Ignore2 = Default<Args>,
            #             template <Args> class Ignore3>
            #   void Function() {};
            #
            # To avoid template argument cases, we scan forward and look for
            # an unmatched '>'.  If we see one, assume we are inside a
            # template argument list.
            end_declaration = len(class_decl_match.group(1))
            if not self.InTemplateArgumentList(clean_lines, linenum, end_declaration):
                self.stack.append(_ClassInfo(
                    class_decl_match.group(3), class_decl_match.group(2),
                    clean_lines, linenum))
                line = class_decl_match.group(4)

        # If we have not yet seen the opening brace for the innermost block,
        # run checks here.
        if not self.SeenOpenBrace():
            self.stack[-1].CheckBegin(filename, clean_lines, linenum, error)

        # Update access control if we are inside a class/struct
        if self.stack and isinstance(self.stack[-1], _ClassInfo):
            classinfo = self.stack[-1]
            access_match = Match(
                r'^(.*)\b(public|private|protected|signals)(\s+(?:slots\s*)?)?'
                r':(?:[^:]|$)',
                line)
            if access_match:
                classinfo.access = access_match.group(2)

                # Check that access keywords are indented +1 space.  Skip this
                # check if the keywords are not preceded by whitespaces.
                indent = access_match.group(1)
                if (len(indent) != classinfo.class_indent + 1 and
                    Match(r'^\s*$', indent)):
                    if classinfo.is_struct:
                        parent = 'struct ' + classinfo.name
                    else:
                        parent = 'class ' + classinfo.name
                    slots = ''
                    if access_match.group(3):
                        slots = access_match.group(3)
                    error(state, filename, linenum, 'whitespace/indent', 3,
                          '%s%s: should be indented +1 space inside %s' % (
                              access_match.group(2), slots, parent))

        # Consume braces or semicolons from what's left of the line
        while True:
            # Match first brace, semicolon, or closed parenthesis.
            matched = Match(r'^[^{;)}]*([{;)}])(.*)$', line)
            if not matched:
                break

            token = matched.group(1)
            if token == '{':
                # If namespace or class hasn't seen a opening brace yet, mark
                # namespace/class head as complete.  Push a new block onto the
                # stack otherwise.
                if not self.SeenOpenBrace():
                    self.stack[-1].seen_open_brace = True
                elif Match(r'^extern\s*"[^"]*"\s*\{', line):
                    self.stack.append(_ExternCInfo(linenum))
                else:
                    self.stack.append(_BlockInfo(linenum, True))
                    if _MATCH_ASM.match(line):
                        self.stack[-1].inline_asm = _BLOCK_ASM

            elif token == ';' or token == ')':
                # If we haven't seen an opening brace yet, but we already saw
                # a semicolon, this is probably a forward declaration.  Pop
                # the stack for these.
                #
                # Similarly, if we haven't seen an opening brace yet, but we
                # already saw a closing parenthesis, then these are probably
                # function arguments with extra "class" or "struct" keywords.
                # Also pop these stack for these.
                if not self.SeenOpenBrace():
                    self.stack.pop()
            else:  # token == '}'
                # Perform end of block checks and pop the stack.
                if self.stack:
                    self.stack[-1].CheckEnd(state, filename, clean_lines, linenum, error)
                    self.stack.pop()
            line = matched.group(2)

    def InnermostClass(self):
        """Get class info on the top of the stack.

        Returns:
          A _ClassInfo object if we are inside a class, or None otherwise.
        """
        for i in range(len(self.stack), 0, -1):
            classinfo = self.stack[i - 1]
            if isinstance(classinfo, _ClassInfo):
                return classinfo
        return None

    def CheckCompletedBlocks(self, state, filename, error):
        """Checks that all classes and namespaces have been completely parsed.

        Call this when all lines in a file have been processed.
        Args:
          filename: The name of the current file.
          error: The function to call with any errors found.
        """
        # Note: This test can result in false positives if #ifdef constructs
        # get in the way of brace matching. See the testBuildClass test in
        # cpplint_unittest.py for an example of this.
        for obj in self.stack:
            if isinstance(obj, _ClassInfo):
                error(state, filename, obj.starting_linenum, 'build/class', 5,
                      'Failed to find complete declaration of class %s' %
                      obj.name)
            elif isinstance(obj, _NamespaceInfo):
                error(state, filename, obj.starting_linenum, 'build/namespaces', 5,
                      'Failed to find complete declaration of namespace %s' %
                      obj.name)
