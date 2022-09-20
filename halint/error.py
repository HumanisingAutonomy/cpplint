from typing import Callable

from halint.lintstate import LintState

ErrorLogger = Callable[[LintState, str, int, str, int, str], None]
