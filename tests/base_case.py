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
from halint.file_info import FileInfo
from halint.function_state import FunctionState
from halint.include_state import IncludeState
from halint.lintstate import LintState
from halint import NestingState


class CpplintTestBase(ABC):
    """Provides some useful helper functions for cpplint tests."""

    def setUp(self):
        # Allow subclasses to cheat os.path.abspath called in FileInfo class.
        self.os_path_abspath_orig = os.path.abspath

    def tearDown(self):
        os.path.abspath = self.os_path_abspath_orig

    # Perform lint on single line of input and return the error message.
    def PerformSingleLineLint(self, state, code):
        lines = code.split("\n")
        RemoveMultiLineComments(state, "foo.h", lines)
        clean_lines = CleansedLines(lines, "foo.h")
        include_state = IncludeState()
        function_state = FunctionState()
        nesting_state = NestingState()
        ProcessLine(
            state,
            "cc",
            clean_lines,
            0,
            include_state,
            function_state,
            nesting_state,
        )
        # Single-line lint tests are allowed to fail the 'unlintable function'
        # check.
        state.RemoveIfPresent("Lint failed to find start of function body.")
        return state.Results()

    # Perform lint over multiple lines and return the error message.
    def PerformMultiLineLint(self, state: LintState, code: str):
        file_name = "foo.h"
        lines = code.split("\n")
        RemoveMultiLineComments(state, file_name, lines)
        lines = CleansedLines(lines, file_name)
        nesting_state = NestingState()
        for i in range(lines.num_lines()):
            nesting_state.update(state, lines, i)
            CheckStyle(state, lines, i, nesting_state)
            CheckForNonStandardConstructs(state, lines, i, nesting_state)
        nesting_state.check_completed_blocks(state, file_name)
        return state.Results()

    # Similar to PerformMultiLineLint, but calls CheckLanguage instead of
    # CheckForNonStandardConstructs
    def PerformLanguageRulesCheck(self, state: LintState, file_name, code):
        include_state = IncludeState()
        nesting_state = NestingState()
        lines = code.split("\n")
        RemoveMultiLineComments(state, file_name, lines)
        lines = CleansedLines(lines, file_name)
        ext = file_name[file_name.rfind(".") + 1 :]
        for i in range(lines.num_lines()):
            CheckLanguage(
                state,
                lines,
                i,
                ext,
                include_state,
                nesting_state,
            )
        return state.Results()

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
        function_state = FunctionState()
        lines = code.split("\n")
        RemoveMultiLineComments(state, file_name, lines)
        lines = CleansedLines(lines, file_name)
        for i in range(lines.num_lines()):
            CheckForFunctionLengths(state, lines, i, function_state)
        return state.Results()

    def PerformIncludeWhatYouUse(self, state: LintState, code: str, file_name: str = "foo.h", io=codecs):
        # First, build up the include state.
        include_state = IncludeState()
        nesting_state = NestingState()
        lines = code.split("\n")
        RemoveMultiLineComments(state, file_name, lines)
        lines = CleansedLines(lines, file_name)
        file_extension = pathlib.Path(file_name).suffix
        for i in range(lines.num_lines()):
            CheckLanguage(
                state,
                lines,
                i,
                file_extension,
                include_state,
                nesting_state,
            )
        # We could clear the error_collector here, but this should
        # also be fine, since our IncludeWhatYouUse unittests do not
        # have language problems.

        # Second, look for missing includes.
        CheckForIncludeWhatYouUse(state, lines, include_state, io)
        results = state.Results()
        state.ResetErrorCounts()
        return results

    # Perform lint and compare the error message with "expected_message".
    def TestSingleLineLint(self, state, code, expected_message):
        assert self.PerformSingleLineLint(state, code) == expected_message
        # TODO: remove this when tests are independent
        state.ResetErrorCounts()

    def TestMultiLineLint(self, state: LintState, code, expected_message):
        assert self.PerformMultiLineLint(state, code) == expected_message
        # TODO: remove this when tests are independent
        state.ResetErrorCounts()

    def lint_legacy_file(
        self,
        state: LintState,
        code: list[str],
        expected_message: list[str],
        filename: Optional[str] = None,
    ):
        ProcessFileData(state, filename, pathlib.Path(filename).suffix, code)
        assert state.Results() == expected_message
        state.ResetErrorCounts()

    def lint_file(self, state: LintState, file_name: str, expected_messages: str | list[str],
                  ignore_addition_messages: bool = False):
        path = pathlib.Path("tests/data").joinpath(file_name)
        file_name = str(path)
        file_info = FileInfo(file_name)
        with open(file_name) as file:
            ProcessFileData(
                state,
                file_name,
                file_info.extension(),
                file.read().split("\n")
            )

            self._compare_messages(expected_messages, state.Results(), ignore_addition_messages)

    def _compare_messages(self,
                          expected_messages: str | list[str],
                          actual_messages: str | list[str],
                          ignore_additional_messages: bool
                          ):
        if not ignore_additional_messages:
            assert actual_messages == expected_messages
            return

        if type(actual_messages) == str:
            assert actual_messages == expected_messages
        else:
            if type(expected_messages) == str:
                assert expected_messages in actual_messages
            else:
                assert set(expected_messages).issubset(actual_messages)




    def TestFileWithMessageCounts(
        self,
        state: LintState,
        code: list[str],
        filename,
        expected_messages: dict[str, int],
    ):
        ProcessFileData(state, filename, pathlib.Path(filename).suffix, code)
        for error, count in expected_messages.items():
            assert state.ResultList().count(error) == count
        state.ResetErrorCounts()

    def lint(self, state: LintState, code: Union[str, list[str]], expected_message: str | list[str]):
        if "\n" in code:
            self.TestMultiLineLint(state, code, expected_message)
        else:
            self.TestSingleLineLint(state, code, expected_message)

    def TestMultiLineLintRE(self, state: LintState, code, expected_message_re):
        message = self.PerformMultiLineLint(state, code)
        if not re.search(expected_message_re, message):
            self.fail("Message was:\n" + message + 'Expected match to "' + expected_message_re + '"')

    def TestLanguageRulesCheck(self, state, file_name, code, expected_message):
        assert expected_message == self.PerformLanguageRulesCheck(state, file_name, code)
        state.ResetErrorCounts()

    def TestIncludeWhatYouUse(self, state, code, expected_message):
        assert expected_message == self.PerformIncludeWhatYouUse(state, code)
        state.ResetErrorCounts()

    def TestBlankLinesCheck(self, state, lines, start_errors, end_errors):
        for extension in ["c", "cc", "cpp", "cxx", "c++", "cu"]:
            self.doTestBlankLinesCheck(state, lines, start_errors, end_errors, extension)
        state.ResetErrorCounts()

    def doTestBlankLinesCheck(self, state, lines, start_errors, end_errors, extension):
        ProcessFileData(state, "foo." + extension, extension, lines)
        assert start_errors == state.Results().count(
            "Redundant blank line at the start of a code block " "should be deleted.  [whitespace/blank_line] [2]"
        )
        assert end_errors == state.Results().count(
            "Redundant blank line at the end of a code block " "should be deleted.  [whitespace/blank_line] [3]"
        )
        state.ResetErrorCounts()

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
