import pytest

import halint.cpplint as cpplint

from .base_case import CpplintTestBase


class TestCxx14(CpplintTestBase):

    blocked_headers_data = [["#include <shared_mutex>",
                             "<shared_mutex> is an unapproved C++14 header.  [build/c++14] [5]"],
                            ["#include <scoped_allocator>",
                             "<scoped_allocator> is an unapproved C++14 header.  [build/c++14] [5]"]]

    @pytest.mark.parametrize("code,expected_error", blocked_headers_data)
    def test_blocked_headers(self, state, code, expected_error):
        lines = code.split("\n")
        cpplint.RemoveMultiLineComments(state, "foo.h", lines)
        clean_lines = cpplint.CleansedLines(lines, "foo.h")
        cpplint.FlagCxx14Features(state, clean_lines, 0)
        assert expected_error == state.Results()
        state.ResetErrorCounts()
