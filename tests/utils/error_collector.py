import sys
from typing import Union

import halint.cpplint as cpplint
from halint.error import (
    _ERROR_CATEGORIES,
    _ShouldPrintError
)
from halint.lintstate import LintState


# This class works as an error collector and replaces cpplint.Error
# function for the unit tests.  We also verify each category we see
# is in cpplint._ERROR_CATEGORIES, to help keep that list up to date.
class ErrorCollector(object):
    # These are a global list, covering all categories seen ever.
    _SEEN_ERROR_CATEGORIES = {}
    _ERROR_CATEGORIES = _ERROR_CATEGORIES

    def __init__(self):
        self._errors = []

    def __call__(
        self,
        state: LintState,
        unused_filename: str,
        line_num: int,
        category: str,
        confidence: int,
        message: str,
    ):
        if category not in self._ERROR_CATEGORIES:
            raise ValueError(f"Message {message} has category {category}, which is not in _ERROR_CATEGORIES")
        self._SEEN_ERROR_CATEGORIES[category] = 1
        if _ShouldPrintError(state, category, confidence, line_num):
            self._errors.append("%s  [%s] [%d]" % (message, category, confidence))

    def Results(self) -> Union[str, list[str]]:
        if len(self._errors) <= 1:
            return "".join(self._errors)  # Most tests expect to have a string.
        else:
            return self._errors  # Let's give a list if there is more than one.

    def ResultList(self) -> list[str]:
        return self._errors

    def VerifyAllCategoriesAreSeen(self) -> None:
        """Fails if there's a category in _ERROR_CATEGORIES~_SEEN_ERROR_CATEGORIES.

        This should only be called after all tests are run, so
        _SEEN_ERROR_CATEGORIES has had a chance to fully populate.  Since
        this isn't called from within the normal unittest framework, we
        can't use the normal unittest assert macros.  Instead we just exit
        when we see an error.  Good thing this test is always run last!
        """
        for category in self._ERROR_CATEGORIES:
            if category not in self._SEEN_ERROR_CATEGORIES:
                sys.exit('FATAL ERROR: There are no tests for category "%s"' % category)

    def RemoveIfPresent(self, substr: str) -> None:
        for (index, error) in enumerate(self._errors):
            if error.find(substr) != -1:
                self._errors = self._errors[0:index] + self._errors[(index + 1) :]
                break
