import math

from .error import ErrorLogger
from .lintstate import LintState
from .regex import Match


class FunctionState(object):
    """Tracks current function name and the number of lines in its body."""

    _NORMAL_TRIGGER = 250  # for --v=0, 500 for --v=1, etc.
    _TEST_TRIGGER = 400  # about 50% more than _NORMAL_TRIGGER.

    def __init__(self) -> None:
        self.in_a_function = False
        self.lines_in_function = 0
        self.current_function = ""

    def begin(self, function_name: str) -> None:
        """Start analyzing function body.

        Args:
            function_name: The name of the function being tracked.
        """
        self.in_a_function = True
        self.lines_in_function = 0
        self.current_function = function_name

    def count(self) -> None:
        """Count line in current function body."""
        if self.in_a_function:
            self.lines_in_function += 1

    def check(self, state: LintState, error: ErrorLogger, filename: str, line_num: int) -> None:
        """Report if too many lines in function body.

        Args:
            state: The current state of the linting process.
            error: The function to call with any errors found.
            filename: The name of the current file.
            line_num: The number of the line to check.
        """
        if not self.in_a_function:
            return

        if Match(r"T(EST|est)", self.current_function):
            base_trigger = self._TEST_TRIGGER
        else:
            base_trigger = self._NORMAL_TRIGGER
        trigger = base_trigger * 2**state.verbose_level

        if self.lines_in_function > trigger:
            error_level = int(math.log(self.lines_in_function / base_trigger, 2))
            # 50 => 0, 100 => 1, 200 => 2, 400 => 3, 800 => 4, 1600 => 5, ...
            if error_level > 5:
                error_level = 5
            error(
                state,
                filename,
                line_num,
                "readability/fn_size",
                error_level,
                "Small and focused functions are preferred:"
                f" {self.current_function } has {self.lines_in_function} non-comment lines"
                f" (error triggered by exceeding {trigger} lines).",
            )

    def end(self) -> None:
        """Stop analyzing function body."""
        self.in_a_function = False
