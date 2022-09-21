import codecs
import os
import pathlib
import re
from abc import ABC
from typing import Optional, Union

from halint.check_language import CheckLanguage
from halint.check_line import (
    CheckForFunctionLengths,
    CheckForNonStandardConstructs,
    ProcessLine,
)
from halint.check_style import CheckStyle
from halint.cleansed_lines import CleansedLines
from halint.cpplint import (
    CheckForIncludeWhatYouUse,
    ProcessFileData,
    RemoveMultiLineComments,
)
from halint.function_state import FunctionState
from halint.include_state import IncludeState
from halint.lintstate import LintState
from halint import NestingState

from .utils.error_collector import ErrorCollector


class CpplintTestBase(ABC):
    """Provides some useful helper functions for cpplint tests."""

    def setUp(self):
        # Allow subclasses to cheat os.path.abspath called in FileInfo class.
        self.os_path_abspath_orig = os.path.abspath

    def tearDown(self):
        os.path.abspath = self.os_path_abspath_orig

    # Perform lint on single line of input and return the error message.
    def PerformSingleLineLint(self, state, code):
        error_collector = ErrorCollector()
        lines = code.split("\n")
        RemoveMultiLineComments(state, "foo.h", lines, error_collector)
        clean_lines = CleansedLines(lines, "foo.h")
        include_state = IncludeState()
        function_state = FunctionState()
        nesting_state = NestingState()
        ProcessLine(
            state,
            "foo.cc",
            "cc",
            clean_lines,
            0,
            include_state,
            function_state,
            nesting_state,
            error_collector,
        )
        # Single-line lint tests are allowed to fail the 'unlintable function'
        # check.
        error_collector.RemoveIfPresent("Lint failed to find start of function body.")
        return error_collector.Results()

    # Perform lint over multiple lines and return the error message.
    def PerformMultiLineLint(self, state: LintState, code: str):
        FILE_NAME = "foo.h"
        error_collector = ErrorCollector()
        lines = code.split("\n")
        RemoveMultiLineComments(state, FILE_NAME, lines, error_collector)
        lines = CleansedLines(lines, FILE_NAME)
        nesting_state = NestingState()
        for i in range(lines.num_lines()):
            nesting_state.update(state, lines, i, error_collector)
            CheckStyle(state, FILE_NAME, lines, i, "h", nesting_state, error_collector)
            CheckForNonStandardConstructs(state, FILE_NAME, lines, i, nesting_state, error_collector)
        nesting_state.check_completed_blocks(state, FILE_NAME, error_collector)
        return error_collector.Results()

    # Similar to PerformMultiLineLint, but calls CheckLanguage instead of
    # CheckForNonStandardConstructs
    def PerformLanguageRulesCheck(self, state: LintState, file_name, code):
        error_collector = ErrorCollector()
        include_state = IncludeState()
        nesting_state = NestingState()
        lines = code.split("\n")
        RemoveMultiLineComments(state, file_name, lines, error_collector)
        lines = CleansedLines(lines, file_name)
        ext = file_name[file_name.rfind(".") + 1 :]
        for i in range(lines.num_lines()):
            CheckLanguage(
                state,
                file_name,
                lines,
                i,
                ext,
                include_state,
                nesting_state,
                error_collector,
            )
        return error_collector.Results()

    def PerformFunctionLengthsCheck(self, state: LintState, code: str):
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
        file_name = "foo.cc"
        error_collector = ErrorCollector()
        function_state = FunctionState()
        lines = code.split("\n")
        RemoveMultiLineComments(state, file_name, lines, error_collector)
        lines = CleansedLines(lines, file_name)
        for i in range(lines.num_lines()):
            CheckForFunctionLengths(state, file_name, lines, i, function_state, error_collector)
        return error_collector.Results()

    def PerformIncludeWhatYouUse(self, state: LintState, code: str, file_name: str = "foo.h", io=codecs):
        # First, build up the include state.
        error_collector = ErrorCollector()
        include_state = IncludeState()
        nesting_state = NestingState()
        lines = code.split("\n")
        RemoveMultiLineComments(state, file_name, lines, error_collector)
        lines = CleansedLines(lines, file_name)
        file_extension = pathlib.Path(file_name).suffix
        for i in range(lines.num_lines()):
            CheckLanguage(
                state,
                file_name,
                lines,
                i,
                file_extension,
                include_state,
                nesting_state,
                error_collector,
            )
        # We could clear the error_collector here, but this should
        # also be fine, since our IncludeWhatYouUse unittests do not
        # have language problems.

        # Second, look for missing includes.
        CheckForIncludeWhatYouUse(state, file_name, lines, include_state, error_collector, io)
        return error_collector.Results()

    # Perform lint and compare the error message with "expected_message".
    def TestSingleLineLint(self, state, code, expected_message):
        assert expected_message == self.PerformSingleLineLint(state, code)

    def TestMultiLineLint(self, state: LintState, code, expected_message):
        assert expected_message == self.PerformMultiLineLint(state, code)

    def TestFile(
        self,
        state: LintState,
        code: list[str],
        expected_message: list[str],
        filename: Optional[str] = None,
    ):
        error_collector = ErrorCollector()
        ProcessFileData(state, filename, pathlib.Path(filename).suffix, code, error_collector)
        assert expected_message == error_collector.Results()

    def TestFileWithMessageCounts(
        self,
        state: LintState,
        code: list[str],
        filename,
        expected_messages: dict[str, int],
    ):
        error_collector = ErrorCollector()
        ProcessFileData(state, filename, pathlib.Path(filename).suffix, code, error_collector)
        for error, count in expected_messages.items():
            assert error_collector.ResultList().count(error) == count

    def TestLint(self, state: LintState, code: Union[str, list[str]], expected_message: list[str]):
        if "\n" in expected_message:
            self.TestMultiLineLint(state, code, expected_message)
        else:
            self.TestSingleLineLint(state, code, expected_message)

    def TestMultiLineLintRE(self, state: LintState, code, expected_message_re):
        message = self.PerformMultiLineLint(state, code)
        if not re.search(expected_message_re, message):
            self.fail("Message was:\n" + message + 'Expected match to "' + expected_message_re + '"')

    def TestLanguageRulesCheck(self, state, file_name, code, expected_message):
        assert expected_message == self.PerformLanguageRulesCheck(state, file_name, code)

    def TestIncludeWhatYouUse(self, state, code, expected_message):
        assert expected_message == self.PerformIncludeWhatYouUse(state, code)

    def TestBlankLinesCheck(self, state, lines, start_errors, end_errors):
        for extension in ["c", "cc", "cpp", "cxx", "c++", "cu"]:
            self.doTestBlankLinesCheck(state, lines, start_errors, end_errors, extension)

    def doTestBlankLinesCheck(self, state, lines, start_errors, end_errors, extension):
        error_collector = ErrorCollector()
        ProcessFileData(state, "foo." + extension, extension, lines, error_collector)
        assert start_errors == error_collector.Results().count(
            "Redundant blank line at the start of a code block " "should be deleted.  [whitespace/blank_line] [2]"
        )
        assert end_errors == error_collector.Results().count(
            "Redundant blank line at the end of a code block " "should be deleted.  [whitespace/blank_line] [3]"
        )

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
        min_indent = min([CountLeadingWhitespace(line) for line in text_block.split("\n") if line])
        return "\n".join([line[min_indent:] for line in text_block.split("\n")])
