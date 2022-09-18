from re import I
import pytest

import halint.cpplint as cpplint
from halint._cpplintstate import _CppLintState


pytest.register_assert_rewrite("tests.base_case")

@pytest.fixture
def state():
    # Reset state, in case a previous test didn't clear up properly
    state = _CppLintState()

    # Enable all filters, so we don't miss anything that is off by default.
    state._DEFAULT_FILTERS = []
    state.filters = ""
    return state


@pytest.fixture(autouse=True)
def global_setUp():
    """Runs before all tests are executed.
    """
    # Reset state, in case a previous test didn't clear up properly
    cpplint._cpplint_state = _CppLintState()

    # Enable all filters, so we don't miss anything that is off by default.
    cpplint._cpplint_state._DEFAULT_FILTERS = []
    cpplint._cpplint_state.filters = ""

    yield

    """A global check to make sure all error-categories have been tested.

    The main tearDown() routine is the only code we can guarantee will be
    run after all other tests have been executed.
    """

    #TODO: find a way to validate that all categories are touched
