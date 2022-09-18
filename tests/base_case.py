from abc import ABC
import codecs
import re
import os

import pytest

import halint.cpplint as cpplint

from .utils.error_collector import ErrorCollector

class CpplintTestBase(ABC):
    """Provides some useful helper functions for cpplint tests."""

    def setUp(self):
        # Allow subclasses to cheat os.path.abspath called in FileInfo class.
        self.os_path_abspath_orig = os.path.abspath

    def tearDown(self):
        os.path.abspath = self.os_path_abspath_orig

    # Perform lint on single line of input and return the error message.
    def PerformSingleLineLint(self, code):
        error_collector = ErrorCollector()
        lines = code.split('\n')
        cpplint.RemoveMultiLineComments('foo.h', lines, error_collector)
        clean_lines = cpplint.CleansedLines(lines)
        include_state = cpplint._IncludeState()
        function_state = cpplint._FunctionState()
        nesting_state = cpplint.NestingState()
        cpplint.ProcessLine(cpplint._cpplint_state, 'foo.cc', 'cc', clean_lines, 0,
                            include_state, function_state,
                            nesting_state, error_collector)
        # Single-line lint tests are allowed to fail the 'unlintable function'
        # check.
        error_collector.RemoveIfPresent(
            'Lint failed to find start of function body.')
        return error_collector.Results()

    # Perform lint over multiple lines and return the error message.
    def PerformMultiLineLint(self, code):
        error_collector = ErrorCollector()
        lines = code.split('\n')
        cpplint.RemoveMultiLineComments('foo.h', lines, error_collector)
        lines = cpplint.CleansedLines(lines)
        nesting_state = cpplint.NestingState()
        for i in range(lines.NumLines()):
            nesting_state.Update('foo.h', lines, i, error_collector)
            cpplint.CheckStyle('foo.h', lines, i, 'h', nesting_state,
                               error_collector)
            cpplint.CheckForNonStandardConstructs('foo.h', lines, i,
                                                  nesting_state, error_collector)
        nesting_state.CheckCompletedBlocks('foo.h', error_collector)
        return error_collector.Results()

    # Similar to PerformMultiLineLint, but calls CheckLanguage instead of
    # CheckForNonStandardConstructs
    def PerformLanguageRulesCheck(self, file_name, code):
        error_collector = ErrorCollector()
        include_state = cpplint._IncludeState()
        nesting_state = cpplint.NestingState()
        lines = code.split('\n')
        cpplint.RemoveMultiLineComments(file_name, lines, error_collector)
        lines = cpplint.CleansedLines(lines)
        ext = file_name[file_name.rfind('.') + 1:]
        for i in range(lines.NumLines()):
            cpplint.CheckLanguage(file_name, lines, i, ext, include_state,
                                  nesting_state, error_collector)
        return error_collector.Results()

    def PerformFunctionLengthsCheck(self, code):
        """Perform Lint function length check on block of code and return warnings.

        Builds up an array of lines corresponding to the code and strips comments
        using cpplint functions.

        Establishes an error collector and invokes the function length checking
        function following cpplint's pattern.

        Args:
          code: C++ source code expected to generate a warning message.

        Returns:
          The accumulated errors.
        """
        file_name = 'foo.cc'
        error_collector = ErrorCollector()
        function_state = cpplint._FunctionState()
        lines = code.split('\n')
        cpplint.RemoveMultiLineComments(file_name, lines, error_collector)
        lines = cpplint.CleansedLines(lines)
        for i in range(lines.NumLines()):
            cpplint.CheckForFunctionLengths(cpplint._cpplint_state, file_name, lines, i,
                                            function_state, error_collector)
        return error_collector.Results()

    def PerformIncludeWhatYouUse(self, code, filename='foo.h', io=codecs):
        # First, build up the include state.
        error_collector = ErrorCollector()
        include_state = cpplint._IncludeState()
        nesting_state = cpplint.NestingState()
        lines = code.split('\n')
        cpplint.RemoveMultiLineComments(filename, lines, error_collector)
        lines = cpplint.CleansedLines(lines)
        for i in range(lines.NumLines()):
            cpplint.CheckLanguage(filename, lines, i, '.h', include_state,
                                  nesting_state, error_collector)
        # We could clear the error_collector here, but this should
        # also be fine, since our IncludeWhatYouUse unittests do not
        # have language problems.

        # Second, look for missing includes.
        cpplint.CheckForIncludeWhatYouUse(filename, lines, include_state,
                                          error_collector, io)
        return error_collector.Results()

    # Perform lint and compare the error message with "expected_message".
    def TestLint(self, code, expected_message):
        assert expected_message == self.PerformSingleLineLint(code)

    def TestMultiLineLint(self, code, expected_message):
        assert expected_message == self.PerformMultiLineLint(code)

    def TestMultiLineLintRE(self, code, expected_message_re):
        message = self.PerformMultiLineLint(code)
        if not re.search(expected_message_re, message):
            self.fail('Message was:\n' + message + 'Expected match to "' +
                      expected_message_re + '"')

    def TestLanguageRulesCheck(self, file_name, code, expected_message):
        assert expected_message == self.PerformLanguageRulesCheck(file_name, code)

    def TestIncludeWhatYouUse(self, code, expected_message):
        assert expected_message == self.PerformIncludeWhatYouUse(code)

    def TestBlankLinesCheck(self, lines, start_errors, end_errors):
        for extension in ['c', 'cc', 'cpp', 'cxx', 'c++', 'cu']:
            self.doTestBlankLinesCheck(lines, start_errors, end_errors, extension)

    def doTestBlankLinesCheck(self, lines, start_errors, end_errors, extension):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.' + extension, extension, lines, error_collector)
        assert start_errors == error_collector.Results().count(
            'Redundant blank line at the start of a code block '
            'should be deleted.  [whitespace/blank_line] [2]')
        assert end_errors == error_collector.Results().count(
            'Redundant blank line at the end of a code block '
            'should be deleted.  [whitespace/blank_line] [3]')

    def TrimExtraIndent(self, text_block):
        """Trim a uniform amount of whitespace off of each line in a string.
        Compute the minimum indent on all non blank lines and trim that from each, so
        that the block of text has no extra indentation.
        Args:
            text_block: a multiline string
        Returns:
            text_block with the common whitespace indent of each line removed.
        """

        def CountLeadingWhitespace(s):
            count = 0
            for c in s:
                if not c.isspace():
                    break
                count += 1
            return count
        # find the minimum indent (except for blank lines)
        min_indent = min([CountLeadingWhitespace(line)
                            for line in text_block.split('\n') if line])
        return '\n'.join([line[min_indent:] for line in text_block.split('\n')])
