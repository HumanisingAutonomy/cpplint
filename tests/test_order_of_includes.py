import os

import pytest

import halint.cpplint as cpplint
from halint.block_info import _ClassifyInclude, _DropCommonSuffixes
from halint.include_state import IncludeState

from .base_case import CpplintTestBase


class TestOrderOfIncludes(CpplintTestBase):
    @pytest.fixture(autouse=True)
    def setUp(self):
        super().setUp()
        self.include_state = cpplint.IncludeState()
        os.path.abspath = lambda value: value

    def testCheckNextIncludeOrder_OtherThenCpp(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._OTHER_HEADER)
        assert "Found C++ system header after other header" == self.include_state.check_next_include_order(
            IncludeState._CPP_SYS_HEADER
        )

    def testCheckNextIncludeOrder_CppThenC(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._CPP_SYS_HEADER)
        assert "Found C system header after C++ system header" == self.include_state.check_next_include_order(
            IncludeState._C_SYS_HEADER
        )

    def testCheckNextIncludeOrder_OtherSysThenC(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._OTHER_SYS_HEADER)
        assert "Found C system header after other system header" == self.include_state.check_next_include_order(
            IncludeState._C_SYS_HEADER
        )

    def testCheckNextIncludeOrder_OtherSysThenCpp(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._OTHER_SYS_HEADER)
        assert "Found C++ system header after other system header" == self.include_state.check_next_include_order(
            IncludeState._CPP_SYS_HEADER
        )

    def testCheckNextIncludeOrder_LikelyThenCpp(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._LIKELY_MY_HEADER)
        assert "" == self.include_state.check_next_include_order(IncludeState._CPP_SYS_HEADER)

    def testCheckNextIncludeOrder_PossibleThenCpp(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._POSSIBLE_MY_HEADER)
        assert "" == self.include_state.check_next_include_order(IncludeState._CPP_SYS_HEADER)

    def testCheckNextIncludeOrder_CppThenLikely(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._CPP_SYS_HEADER)
        # This will eventually fail.
        assert "" == self.include_state.check_next_include_order(IncludeState._LIKELY_MY_HEADER)

    def testCheckNextIncludeOrder_CppThenPossible(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._CPP_SYS_HEADER)
        assert "" == self.include_state.check_next_include_order(IncludeState._POSSIBLE_MY_HEADER)

    def testCheckNextIncludeOrder_CppThenOtherSys(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._CPP_SYS_HEADER)
        assert "" == self.include_state.check_next_include_order(IncludeState._OTHER_SYS_HEADER)

    def testCheckNextIncludeOrder_OtherSysThenPossible(self):
        assert "" == self.include_state.check_next_include_order(IncludeState._OTHER_SYS_HEADER)
        assert "" == self.include_state.check_next_include_order(IncludeState._POSSIBLE_MY_HEADER)

    def testClassifyInclude(self, state):
        file_info = cpplint.FileInfo
        classify_include = _ClassifyInclude
        assert IncludeState._C_SYS_HEADER == classify_include(state, file_info("foo/foo.cc"), "stdio.h", True)
        assert IncludeState._C_SYS_HEADER == classify_include(state, file_info("foo/foo.cc"), "sys/time.h", True)
        assert IncludeState._C_SYS_HEADER == classify_include(state, file_info("foo/foo.cc"), "netipx/ipx.h", True)
        assert IncludeState._C_SYS_HEADER == classify_include(state, file_info("foo/foo.cc"), "arpa/ftp.h", True)
        assert IncludeState._CPP_SYS_HEADER == classify_include(state, file_info("foo/foo.cc"), "string", True)
        assert IncludeState._CPP_SYS_HEADER == classify_include(state, file_info("foo/foo.cc"), "typeinfo", True)
        assert IncludeState._C_SYS_HEADER == classify_include(state, file_info("foo/foo.cc"), "foo/foo.h", True)
        assert IncludeState._OTHER_SYS_HEADER == classify_include(
            state, file_info("foo/foo.cc"), "foo/foo.h", True, "standardcfirst"
        )
        assert IncludeState._OTHER_HEADER == classify_include(state, file_info("foo/foo.cc"), "string", False)
        assert IncludeState._OTHER_HEADER == classify_include(state, file_info("foo/foo.cc"), "boost/any.hpp", True)
        assert IncludeState._OTHER_HEADER == classify_include(state, file_info("foo/foo.hxx"), "boost/any.hpp", True)
        assert IncludeState._OTHER_HEADER == classify_include(state, file_info("foo/foo.h++"), "boost/any.hpp", True)
        assert IncludeState._LIKELY_MY_HEADER == classify_include(
            state, file_info("foo/foo.cc"), "foo/foo-inl.h", False
        )
        assert IncludeState._LIKELY_MY_HEADER == classify_include(
            state, file_info("foo/internal/foo.cc"), "foo/public/foo.h", False
        )
        assert IncludeState._POSSIBLE_MY_HEADER == classify_include(
            state, file_info("foo/internal/foo.cc"), "foo/other/public/foo.h", False
        )
        assert IncludeState._OTHER_HEADER == classify_include(
            state, file_info("foo/internal/foo.cc"), "foo/other/public/foop.h", False
        )

    def testTryDropCommonSuffixes(self, state):
        cpplint._hpp_headers = set([])
        cpplint._valid_extensions = set([])
        assert "foo/foo" == _DropCommonSuffixes(state, "foo/foo-inl.h")
        assert "foo/foo" == _DropCommonSuffixes(state, "foo/foo-inl.hxx")
        assert "foo/foo" == _DropCommonSuffixes(state, "foo/foo-inl.h++")
        assert "foo/foo" == _DropCommonSuffixes(state, "foo/foo-inl.hpp")
        assert "foo/bar/foo" == _DropCommonSuffixes(state, "foo/bar/foo_inl.h")
        assert "foo/foo" == _DropCommonSuffixes(state, "foo/foo.cc")
        assert "foo/foo" == _DropCommonSuffixes(state, "foo/foo.cxx")
        assert "foo/foo" == _DropCommonSuffixes(state, "foo/foo.c")
        assert "foo/foo_unusualinternal" == _DropCommonSuffixes(state, "foo/foo_unusualinternal.h")
        assert "foo/foo_unusualinternal" == _DropCommonSuffixes(state, "foo/foo_unusualinternal.hpp")
        assert "" == _DropCommonSuffixes(state, "_test.cc")
        assert "" == _DropCommonSuffixes(state, "_test.c")
        assert "" == _DropCommonSuffixes(state, "_test.c++")
        assert "test" == _DropCommonSuffixes(state, "test.c")
        assert "test" == _DropCommonSuffixes(state, "test.cc")
        assert "test" == _DropCommonSuffixes(state, "test.c++")

    def testRegression(self, state):
        def Format(includes):
            include_list = []
            for item in includes:
                if item.startswith('"') or item.startswith("<"):
                    include_list.append("#include %s\n" % item)
                else:
                    include_list.append(item + "\n")
            return "".join(include_list)

        # Test singleton cases first.
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(['"foo/foo.h"']), "")
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(["<stdio.h>"]), "")
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(["<string>"]), "")
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(['"foo/foo-inl.h"']), "")
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(['"bar/bar-inl.h"']), "")
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(['"bar/bar.h"']), "")

        # Test everything in a good and new order.
        self.TestLanguageRulesCheck(
            state,
            "foo/foo.cc",
            Format(
                [
                    '"foo/foo.h"',
                    '"foo/foo-inl.h"',
                    "<stdio.h>",
                    "<string>",
                    "<unordered_map>",
                    '"bar/bar-inl.h"',
                    '"bar/bar.h"',
                ]
            ),
            "",
        )

        # Test bad orders.
        self.TestLanguageRulesCheck(
            state,
            "foo/foo.cc",
            Format(["<string>", "<stdio.h>"]),
            "Found C system header after C++ system header."
            " Should be: foo.h, c system, c++ system, other."
            "  [build/include_order] [4]",
        )
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(['"foo/bar-inl.h"', '"foo/foo-inl.h"']), "")
        self.TestLanguageRulesCheck(
            state,
            "foo/foo.cc",
            Format(
                [
                    '"foo/e.h"',
                    '"foo/b.h"',  # warning here (e>b)
                    '"foo/c.h"',
                    '"foo/d.h"',
                    '"foo/a.h"',
                ]
            ),  # warning here (d>a)
            [
                'Include "foo/b.h" not in alphabetical order' "  [build/include_alpha] [4]",
                'Include "foo/a.h" not in alphabetical order' "  [build/include_alpha] [4]",
            ],
        )
        # -inl.h headers are no longer special.
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(['"foo/foo-inl.h"', "<string>"]), "")
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(['"foo/bar.h"', '"foo/bar-inl.h"']), "")
        # Test componentized header.  OK to have my header in ../public dir.
        self.TestLanguageRulesCheck(state, "foo/internal/foo.cc", Format(['"foo/public/foo.h"', "<string>"]), "")
        # OK to have my header in other dir (not stylistically, but
        # cpplint isn't as good as a human).
        self.TestLanguageRulesCheck(
            state,
            "foo/internal/foo.cc",
            Format(['"foo/other/public/foo.h"', "<string>"]),
            "",
        )
        self.TestLanguageRulesCheck(
            state,
            "foo/foo.cc",
            Format(['"foo/foo.h"', "<string>", '"base/google.h"', '"base/flags.h"']),
            'Include "base/flags.h" not in alphabetical ' "order  [build/include_alpha] [4]",
        )
        # According to the style, -inl.h should come before .h, but we don't
        # complain about that.
        self.TestLanguageRulesCheck(
            state,
            "foo/foo.cc",
            Format(
                [
                    '"foo/foo-inl.h"',
                    '"foo/foo.h"',
                    '"base/google.h"',
                    '"base/google-inl.h"',
                ]
            ),
            "",
        )
        # Allow project includes to be separated by blank lines
        self.TestLanguageRulesCheck(
            state,
            "a/a.cc",
            Format(
                [
                    '"a/a.h"',
                    "<string>",
                    '"base/google.h"',
                    "",
                    '"b/c.h"',
                    "",
                    "MACRO",
                    '"a/b.h"',
                ]
            ),
            "",
        )
        self.TestLanguageRulesCheck(
            state,
            "a/a.cc",
            Format(['"a/a.h"', "<string>", '"base/google.h"', '"a/b.h"']),
            'Include "a/b.h" not in alphabetical ' "order  [build/include_alpha] [4]",
        )

        # Test conditional includes
        self.TestLanguageRulesCheck(
            state,
            "a/a.cc",
            "".join(
                [
                    "#include <string.h>\n",
                    '#include "base/port.h"\n',
                    "#include <initializer_list>\n",
                ]
            ),
            (
                "Found C++ system header after other header. "
                "Should be: a.h, c system, c++ system, other.  "
                "[build/include_order] [4]"
            ),
        )
        self.TestLanguageRulesCheck(
            state,
            "a/a.cc",
            "".join(
                [
                    "#include <string.h>\n",
                    '#include "base/port.h"\n',
                    "#ifdef LANG_CXX11\n",
                    "#include <initializer_list>\n",
                    "#endif  // LANG_CXX11\n",
                ]
            ),
            "",
        )
        self.TestLanguageRulesCheck(
            state,
            "a/a.cc",
            "".join(
                [
                    "#include <string.h>\n",
                    "#ifdef LANG_CXX11\n",
                    '#include "base/port.h"\n',
                    "#include <initializer_list>\n",
                    "#endif  // LANG_CXX11\n",
                ]
            ),
            (
                "Found C++ system header after other header. "
                "Should be: a.h, c system, c++ system, other.  "
                "[build/include_order] [4]"
            ),
        )

        # Third party headers are exempt from order checks
        self.TestLanguageRulesCheck(state, "foo/foo.cc", Format(["<string>", '"Python.h"', "<vector>"]), "")
