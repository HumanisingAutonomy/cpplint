from typing import Callable

from halint._cpplintstate import _CppLintState

ErrorLogger = Callable[[_CppLintState, str, int, str, int, str], None]
