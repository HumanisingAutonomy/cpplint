import pytest

from halint.lintstate import LintState

pytest.register_assert_rewrite("tests.base_case")


@pytest.fixture
def state():
    # Reset state, in case a previous test didn't clear up properly
    state = LintState()

    # Enable all filters, so we don't miss anything that is off by default.
    state._DEFAULT_FILTERS = []
    state.filters = ""
    return state


@pytest.fixture
def state_with_defaults():
    # Reset state, in case a previous test didn't clear up properly
    state = LintState()

    return state
