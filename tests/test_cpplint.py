import codecs
import random
import re
import os
import pytest
import shutil
import sys
import tempfile

import halint.cpplint as cpplint
import halint.cli as cli
from halint.check_line import (
    CheckForNamespaceIndentation
)

from halint import _CppLintState

from halint.block_info import (
    ReverseCloseExpression,
    GetLineWidth,
    _GetTextInside,
    IsBlankLine
)

# Pattern for matching FileInfo.BaseName() against test file name
_test_suffixes = ['_test', '_regtest', '_unittest']
_TEST_FILE_SUFFIX = '(' + '|'.join(_test_suffixes) + r')$'

from halint.file_info import PathSplitToList

from .base_case import CpplintTestBase
from .utils.error_collector import ErrorCollector
from .utils.mock_io import MockIo

class TestCpplint(CpplintTestBase):

    def GetNamespaceResults(self, lines):
        error_collector = ErrorCollector()
        cpplint.RemoveMultiLineComments('foo.h', lines, error_collector)
        lines = cpplint.CleansedLines(lines)
        nesting_state = cpplint.NestingState()
        for i in range(lines.NumLines()):
            nesting_state.Update('foo.h', lines, i, error_collector)
            CheckForNamespaceIndentation('foo.h', nesting_state,
                                                 lines, i, error_collector)

        return error_collector.Results()

    def testForwardDeclarationNameSpaceIndentation(self):
        lines = ['namespace Test {',
                 '  class ForwardDeclaration;',
                 '}  // namespace Test']

        results = self.GetNamespaceResults(lines)
        assert results == 'Do not indent within a namespace  [runtime/indentation_namespace] [4]'

    def testNameSpaceIndentationForClass(self):
        lines = ['namespace Test {',
                 'void foo() { }',
                 '  class Test {',
                 '  };',
                 '}  // namespace Test']

        results = self.GetNamespaceResults(lines)
        assert results == 'Do not indent within a namespace  [runtime/indentation_namespace] [4]'

    def testNameSpaceIndentationNoError(self):
        lines = ['namespace Test {',
                 'void foo() { }',
                 '}  // namespace Test']

        results = self.GetNamespaceResults(lines)
        assert results == ''

    def testWhitespaceBeforeNamespace(self):
        lines = ['  namespace Test {',
                 '  void foo() { }',
                 '  }  // namespace Test']

        results = self.GetNamespaceResults(lines)
        assert results == ''

    def testFalsePositivesNoError(self):
        lines = ['namespace Test {',
                 'struct OuterClass {',
                 '  struct NoFalsePositivesHere;',
                 '  struct NoFalsePositivesHere member_variable;',
                 '};',
                 '}  // namespace Test']

        results = self.GetNamespaceResults(lines)
        assert results == ''

    # Test get line width.
    def testGetLineWidth(self):
        assert 0 == GetLineWidth('')
        assert 10 == GetLineWidth(str('x') * 10)
        assert 16 == GetLineWidth('\u90fd|\u9053|\u5e9c|\u770c|\u652f\u5e81')
        assert 16 == GetLineWidth(u'都|道|府|県|支庁')
        assert 5 + 13 + 9 == GetLineWidth(u'd𝐱/dt' + u'f : t ⨯ 𝐱 → ℝ' + u't ⨯ 𝐱 → ℝ')

    def testGetTextInside(self):
        assert '' == _GetTextInside('fun()', r'fun\(')
        assert 'x, y' == _GetTextInside('f(x, y)', r'f\(')
        assert 'a(), b(c())' == _GetTextInside('printf(a(), b(c()))', r'printf\(')
        assert 'x, y{}' == _GetTextInside('f[x, y{}]', r'f\[')
        assert None == _GetTextInside('f[a, b(}]', r'f\[')
        assert None == _GetTextInside('f[x, y]', r'f\(')
        assert 'y, h(z, (a + b))' == _GetTextInside('f(x, g(y, h(z, (a + b))))', r'g\(')
        assert 'f(f(x))' == _GetTextInside('f(f(f(x)))', r'f\(')
        # Supports multiple lines.
        assert '\n  return loop(x);\n' == _GetTextInside('int loop(int x) {\n  return loop(x);\n}\n', r'\{')
        # '^' matches the beginning of each line.
        assert 'x, y' == _GetTextInside(
                              '#include "inl.h"  // skip #define\n'
                              '#define A2(x, y) a_inl_(x, y, __LINE__)\n'
                              '#define A(x) a_inl_(x, "", __LINE__)\n',
                              r'^\s*#define\s*\w+\(')

    def testFindNextMultiLineCommentStart(self):
        assert 1 == cpplint.FindNextMultiLineCommentStart([''], 0)

        lines = ['a', 'b', '/* c']
        assert 2 == cpplint.FindNextMultiLineCommentStart(lines, 0)

        lines = ['char a[] = "/*";']  # not recognized as comment.
        assert 1 == cpplint.FindNextMultiLineCommentStart(lines, 0)

    def testFindNextMultiLineCommentEnd(self):
        assert 1 == cpplint.FindNextMultiLineCommentEnd([''], 0)
        lines = ['a', 'b', ' c */']
        assert 2 == cpplint.FindNextMultiLineCommentEnd(lines, 0)

    def testRemoveMultiLineCommentsFromRange(self):
        lines = ['a', '  /* comment ', ' * still comment', ' comment */   ', 'b']
        cpplint.RemoveMultiLineCommentsFromRange(lines, 1, 4)
        assert ['a', '/**/', '/**/', '/**/', 'b'] == lines

    def testSpacesAtEndOfLine(self):
        self.TestSingleLineLint(
            '// Hello there ',
            'Line ends in whitespace.  Consider deleting these extra spaces.'
            '  [whitespace/end_of_line] [4]')

    # Test line length check.
    from .data.cpplint_data import line_length_data
    @pytest.mark.parametrize("code,expected_message", line_length_data)
    def testLineLengthCheck(self, state: _CppLintState, code: str, expected_message: str):
        self.TestLint(state, code, expected_message)

    # Test error suppression annotations.
    from .data.cpplint_data import error_suppression_data
    @pytest.mark.parametrize("code,expected_message", error_suppression_data)
    def testErrorSuppressionData(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    # Test error suppression annotations.
    from .data.cpplint_data import error_suppression_file_data
    @pytest.mark.parametrize("code,expected_message,filename", error_suppression_file_data)
    def testErrorSuppressionFileData(self, state, code, expected_message, filename):
        self.TestFile(state, code, expected_message, filename)

    # Test Variable Declarations.
    from .data.cpplint_data import variable_declaration_data
    @pytest.mark.parametrize("code,expected_message",variable_declaration_data)
    def testVariableDeclarations(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    # Test C-style cast cases.
    from .data.cpplint_data import c_style_cast_data
    @pytest.mark.parametrize("code,expected_message",c_style_cast_data)
    def testCStyleCast(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    # Test taking address of casts (runtime/casting)
    from .data.cpplint_data import runtime_casting_data
    @pytest.mark.parametrize("code,expected_message",runtime_casting_data)
    def testRuntimeCasting(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    from .data.cpplint_data import runtime_self_init_data
    @pytest.mark.parametrize("code,expected_message", runtime_self_init_data)
    def testRuntimeSelfinit(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    # Test for unnamed arguments in a method.
    from .data.cpplint_data import check_for_unnamed_params_data
    @pytest.mark.parametrize("code,expected_message", check_for_unnamed_params_data)
    def testCheckForUnnamedParams(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    from .data.cpplint_data import deprecated_cast_data
    @pytest.mark.parametrize("code,expected_message", deprecated_cast_data)
    def testDeprecatedCastData(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    from .data.cpplint_data import deprecated_cast_file_data
    @pytest.mark.parametrize("code,expected_message,filename", deprecated_cast_file_data)
    def testDeprecatedCastFileData(self, state, code, expected_message, filename):
        self.TestFile(state, code, expected_message, filename)

    # The second parameter to a gMock method definition is a function signature
    # that often looks like a bad cast but should not picked up by lint.
    from .data.cpplint_data import mock_method_data
    @pytest.mark.parametrize("code,expected_message", mock_method_data)
    def testMockMethodData(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    from .data.cpplint_data import mock_method_file_data
    @pytest.mark.parametrize("code,filename,expected_messages", mock_method_file_data)
    def testMockMethodFileData(self, state, code, filename, expected_messages):
        self.TestFileWithMessageCounts(state, code, filename, expected_messages)

    # Like gMock method definitions, MockCallback instantiations look very similar
    # to bad casts.
    def testMockCallback(self):
        self.TestSingleLineLint(
            'MockCallback<bool(int)>',
            '')
        self.TestSingleLineLint(
            'MockCallback<int(float, char)>',
            '')

    # Test false errors that happened with some include file names
    def testIncludeFilenameFalseError(self):
        self.TestSingleLineLint(
            '#include "foo/long-foo.h"',
            '')
        self.TestSingleLineLint(
            '#include "foo/sprintf.h"',
            '')

    # Test typedef cases.  There was a bug that cpplint misidentified
    # typedef for pointer to function as C-style cast and produced
    # false-positive error messages.
    def testTypedefForPointerToFunction(self):
        self.TestSingleLineLint(
            'typedef void (*Func)(int x);',
            '')
        self.TestSingleLineLint(
            'typedef void (*Func)(int *x);',
            '')
        self.TestSingleLineLint(
            'typedef void Func(int x);',
            '')
        self.TestSingleLineLint(
            'typedef void Func(int *x);',
            '')

    def testIncludeWhatYouUseNoImplementationFiles(self):
        code = 'std::vector<int> foo;'
        for extension in ['h', 'hpp', 'hxx', 'h++', 'cuh']:
            assert 'Add #include <vector> for vector<>  [build/include_what_you_use] [4]' == \
                self.PerformIncludeWhatYouUse(code, 'foo.' + extension)
        for extension in ['c', 'cc', 'cpp', 'cxx', 'c++', 'cu']:
            assert '' == self.PerformIncludeWhatYouUse(code, 'foo.' + extension)

    def testIncludeWhatYouUse(self):
        self.TestIncludeWhatYouUse(
            """#include <vector>
           std::vector<int> foo;
        """,
            '')
        self.TestIncludeWhatYouUse(
            """#include <map>
           std::pair<int,int> foo;
        """,
            'Add #include <utility> for pair<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <multimap>
           std::pair<int,int> foo;
        """,
            'Add #include <utility> for pair<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <hash_map>
           std::pair<int,int> foo;
        """,
            'Add #include <utility> for pair<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <hash_map>
           auto foo = std::make_pair(1, 2);
        """,
            'Add #include <utility> for make_pair'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <utility>
           std::pair<int,int> foo;
        """,
            '')
        self.TestIncludeWhatYouUse(
            """#include <vector>
           DECLARE_string(foobar);
        """,
            '')
        self.TestIncludeWhatYouUse(
            """#include <vector>
           DEFINE_string(foobar, "", "");
        """,
            '')
        self.TestIncludeWhatYouUse(
            """#include <vector>
           std::pair<int,int> foo;
        """,
            'Add #include <utility> for pair<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include "base/foobar.h"
           std::vector<int> foo;
        """,
            'Add #include <vector> for vector<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <vector>
           std::set<int> foo;
        """,
            'Add #include <set> for set<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include "base/foobar.h"
          hash_map<int, int> foobar;
        """,
            'Add #include <hash_map> for hash_map<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include "base/containers/hash_tables.h"
          base::hash_map<int, int> foobar;
        """,
            '')
        self.TestIncludeWhatYouUse(
            """#include "base/foobar.h"
           bool foobar = std::less<int>(0,1);
        """,
            'Add #include <functional> for less<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include "base/foobar.h"
           bool foobar = min<int>(0,1);
        """,
            'Add #include <algorithm> for min  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            'void a(const string &foobar);',
            'Add #include <string> for string  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            'void a(const std::string &foobar);',
            'Add #include <string> for string  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            'void a(const my::string &foobar);',
            '')  # Avoid false positives on strings in other namespaces.
        self.TestIncludeWhatYouUse(
            """#include "base/foobar.h"
           bool foobar = swap(0,1);
        """,
            'Add #include <utility> for swap  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include "base/foobar.h"
           bool foobar = transform(a.begin(), a.end(), b.start(), Foo);
        """,
            'Add #include <algorithm> for transform  '
            '[build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include "base/foobar.h"
           bool foobar = min_element(a.begin(), a.end());
        """,
            'Add #include <algorithm> for min_element  '
            '[build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """foo->swap(0,1);
           foo.swap(0,1);
        """,
            '')
        self.TestIncludeWhatYouUse(
            """#include <string>
           void a(const std::multimap<int,string> &foobar);
        """,
            'Add #include <map> for multimap<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <string>
           void a(const std::unordered_map<int,string> &foobar);
        """,
            'Add #include <unordered_map> for unordered_map<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <string>
           void a(const std::unordered_set<int> &foobar);
        """,
            'Add #include <unordered_set> for unordered_set<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <queue>
           void a(const std::priority_queue<int> &foobar);
        """,
            '')
        self.TestIncludeWhatYouUse(
            """#include <assert.h>
           #include <string>
           #include <vector>
           #include "base/basictypes.h"
           #include "base/port.h"
           vector<string> hajoa;""", '')
        self.TestIncludeWhatYouUse(
            """#include <string>
           int i = numeric_limits<int>::max()
        """,
            'Add #include <limits> for numeric_limits<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <limits>
           int i = numeric_limits<int>::max()
        """,
            '')
        self.TestIncludeWhatYouUse(
            """#include <string>
           std::unique_ptr<int> x;
        """,
            'Add #include <memory> for unique_ptr<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <string>
           auto x = std::make_unique<int>(0);
        """,
            'Add #include <memory> for make_unique<>'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <vector>
           vector<int> foo(vector<int> x) { return std::move(x); }
        """,
            'Add #include <utility> for move'
            '  [build/include_what_you_use] [4]')
        self.TestIncludeWhatYouUse(
            """#include <string>
           int a, b;
           std::swap(a, b);
        """,
            'Add #include <utility> for swap'
            '  [build/include_what_you_use] [4]')
        # False positive for std::set
        self.TestIncludeWhatYouUse(
            """
        #include <string>
        struct Foo {
            template <typename T>
            void set(const std::string& name, const T& value);
        };
        Foo bar;
        Foo* pbar = &bar;
        bar.set<int>("int", 5);
        pbar->set<bool>("bool", false);""",
            '')
        # False positive for std::map
        self.TestIncludeWhatYouUse(
            """
        template <typename T>
        struct Foo {
            T t;
        };
        template <typename T>
        Foo<T> map(T t) {
            return Foo<T>{ t };
        }
        struct Bar {
        };
        auto res = map<Bar>();
        """,
            '')

        # Test the UpdateIncludeState code path.
        mock_header_contents = ['#include "blah/foo.h"', '#include "blah/bar.h"']
        message = self.PerformIncludeWhatYouUse(
            '#include "blah/a.h"',
            filename='blah/a.cc',
            io=MockIo(mock_header_contents))
        assert message == ''

        mock_header_contents = ['#include <set>']
        message = self.PerformIncludeWhatYouUse(
            """#include "blah/a.h"
           std::set<int> foo;""",
            filename='blah/a.cc',
            io=MockIo(mock_header_contents))
        assert message == ''

        # Make sure we can find the correct header file if the cc file seems to be
        # a temporary file generated by Emacs's flymake.
        mock_header_contents = ['']
        message = self.PerformIncludeWhatYouUse(
            """#include "blah/a.h"
           std::set<int> foo;""",
            filename='blah/a_flymake.cc',
            io=MockIo(mock_header_contents))
        assert message == 'Add #include <set> for set<>  [build/include_what_you_use] [4]'

        # If there's just a cc and the header can't be found then it's ok.
        message = self.PerformIncludeWhatYouUse(
            """#include "blah/a.h"
           std::set<int> foo;""",
            filename='blah/a.cc')
        assert message == ''

        # Make sure we find the headers with relative paths.
        mock_header_contents = ['']
        message = self.PerformIncludeWhatYouUse(
            """#include "%s/a.h"
           std::set<int> foo;""" % os.path.basename(os.getcwd()),
            filename='a.cc',
            io=MockIo(mock_header_contents))
        assert message == 'Add #include <set> for set<>  [build/include_what_you_use] [4]'

    def testFilesBelongToSameModule(self):
        f = cpplint.FilesBelongToSameModule
        assert (True, '') == f('a.cc' , 'a.h')
        assert (True, '') == f('base/google.cc' , 'base/google.h')
        assert (True, '') == f('base/google_test.c' , 'base/google.h')
        assert (True, '') == f('base/google_test.cc' , 'base/google.h')
        assert (True, '') == f('base/google_test.cc' , 'base/google.hpp')
        assert (True, '') == f('base/google_test.cxx' , 'base/google.hxx')
        assert (True, '') == f('base/google_test.cpp' , 'base/google.hpp')
        assert (True, '') == f('base/google_test.c++' , 'base/google.h++')
        assert (True, '') == f('base/google_test.cu' , 'base/google.cuh')
        assert (True, '') == f('base/google_unittest.cc' , 'base/google.h')
        assert (True, '') == f('base/internal/google_unittest.cc' , 'base/public/google.h')
        assert (True, 'xxx/yyy/') == f('xxx/yyy/base/internal/google_unittest.cc' , 'base/public/google.h')
        assert (True, 'xxx/yyy/') == f('xxx/yyy/base/google_unittest.cc' , 'base/public/google.h')
        assert (True, '') == f('base/google_unittest.cc' , 'base/google-inl.h')
        assert (True, '/home/build/google3/') == f('/home/build/google3/base/google.cc' , 'base/google.h')
        assert (False, '') == f('/home/build/google3/base/google.cc' , 'basu/google.h')
        assert (False, '') == f('a.cc' , 'b.h')

    def testCleanseLine(self):
        assert 'int foo = 0;' == cpplint.CleanseComments('int foo = 0;  // danger!')
        assert 'int o = 0;' == cpplint.CleanseComments('int /* foo */ o = 0;')
        assert 'foo(int a, int b);' == cpplint.CleanseComments('foo(int a /* abc */, int b);')
        assert 'f(a, b);' == cpplint.CleanseComments('f(a, /* name */ b);')
        assert 'f(a, b);' == cpplint.CleanseComments('f(a /* name */, b);')
        assert 'f(a, b);' == cpplint.CleanseComments('f(a, /* name */b);')
        assert 'f(a, b, c);' == cpplint.CleanseComments('f(a, /**/b, /**/c);')
        assert 'f(a, b, c);' == cpplint.CleanseComments('f(a, /**/b/**/, c);')

    from .data.cpplint_data import raw_strings_data
    @pytest.mark.parametrize("code, expected_message", raw_strings_data)
    def testRawStrings(self, state, code, expected_message):
        self.TestLint(state, code, expected_message)

    from .data.cpplint_data import multiline_comment_data
    @pytest.mark.parametrize("code, expected_message", multiline_comment_data)
    def testMultiLineComments(self, state: _CppLintState, code, expected_message):
        self.TestLint(state, code, expected_message)

    def testMultilineStrings(self, state):
        multiline_string_error_message = (
            'Multi-line string ("...") found.  This lint script doesn\'t '
            'do well with such strings, and may give bogus warnings.  '
            'Use C++11 raw strings or concatenation instead.'
            '  [readability/multiline_string] [5]')

        for extension in ['c', 'cc', 'cpp', 'cxx', 'c++', 'cu']:
            file_path = 'mydir/foo.' + extension

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, file_path, extension,
                                    ['const char* str = "This is a\\',
                                     ' multiline string.";'],
                                    error_collector)
            assert  2 == error_collector.ResultList().count(multiline_string_error_message)

    from .data.cpplint_data import explicit_single_argument_constructors_data
    @pytest.mark.parametrize("code, expected_message", explicit_single_argument_constructors_data)
    def testExplicitSingleArgumentConstrustorsData(self, state, code, expected_message):
        old_verbose_level = state.verbose_level
        state.verbose_level = 0

        try:
            self.TestMultiLineLint(state, code, expected_message)
        finally:
            state.verbose_level = old_verbose_level

    # Test non-explicit single-argument constructors
    def testExplicitSingleArgumentConstructors(self, state):
        old_verbose_level = cpplint._cpplint_state.verbose_level
        cpplint._cpplint_state.verbose_level = 0

        try:
            # Special case for variadic arguments
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                ['class Foo {',
                '  template<typename... Args>',
                '  explicit Foo(const int arg, Args&&... args) {}',
                '};'],
                error_collector)
            assert 0 == error_collector.ResultList().count( 'Constructors that require multiple arguments should not be marked explicit.  [runtime/explicit] [0]')
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                ['class Foo {',
                '  template<typename... Args>',
                '  explicit Foo(Args&&... args) {}',
                '};'],
                error_collector)
            assert 0 == error_collector.ResultList().count( 'Constructors that require multiple arguments should not be marked explicit.  [runtime/explicit] [0]')
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                ['class Foo {',
                '  template<typename... Args>',
                '  Foo(const int arg, Args&&... args) {}',
                '};'],
                error_collector)
            assert 1 == error_collector.ResultList().count( 'Constructors callable with one argument should be marked explicit.  [runtime/explicit] [5]')
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                ['class Foo {',
                '  template<typename... Args>',
                '  Foo(Args&&... args) {}',
                '};'],
                error_collector)
            assert 1 == error_collector.ResultList().count( 'Constructors callable with one argument should be marked explicit.  [runtime/explicit] [5]')
            # Anything goes inside an assembly block
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                    ['void Func() {',
                                     '  __asm__ (',
                                     '    "hlt"',
                                     '  );',
                                     '  asm {',
                                     '    movdqa [edx + 32], xmm2',
                                     '  }',
                                     '}'],
                                    error_collector)
            assert  0 == error_collector.ResultList().count( 'Extra space before ( in function call  [whitespace/parens] [4]')
            assert  0 == error_collector.ResultList().count( 'Closing ) should be moved to the previous line  [whitespace/parens] [2]')
            assert  0 == error_collector.ResultList().count( 'Extra space before [  [whitespace/braces] [5]')
        finally:
            cpplint._cpplint_state.verbose_level = old_verbose_level

    def testSlashStarCommentOnSingleLine(self, state):
        self.TestMultiLineLint(state,
            """/* static */ Foo(int f);""",
            '')
        self.TestMultiLineLint(state,
            """/*/ static */  Foo(int f);""",
            '')
        self.TestMultiLineLint(state,
            """/*/ static Foo(int f);""",
            'Could not find end of multi-line comment'
            '  [readability/multiline_comment] [5]')
        self.TestMultiLineLint(state,
            """  /*/ static Foo(int f);""",
            'Could not find end of multi-line comment'
            '  [readability/multiline_comment] [5]')
        self.TestMultiLineLint(state,
            """  /**/ static Foo(int f);""",
            '')

    # Test suspicious usage of "if" like this:
    # if (a == b) {
    #   DoSomething();
    # } if (a == c) {   // Should be "else if".
    #   DoSomething();  // This gets called twice if a == b && a == c.
    # }
    def testSuspiciousUsageOfIf(self):
        self.TestSingleLineLint(
            '  if (a == b) {',
            '')
        self.TestSingleLineLint(
            '  } if (a == b) {',
            'Did you mean "else if"? If not, start a new line for "if".'
            '  [readability/braces] [4]')

    # Test suspicious usage of memset. Specifically, a 0
    # as the final argument is almost certainly an error.
    def testSuspiciousUsageOfMemset(self):
        # Normal use is okay.
        self.TestSingleLineLint(
            '  memset(buf, 0, sizeof(buf))',
            '')

        # A 0 as the final argument is almost certainly an error.
        self.TestSingleLineLint(
            '  memset(buf, sizeof(buf), 0)',
            'Did you mean "memset(buf, 0, sizeof(buf))"?'
            '  [runtime/memset] [4]')
        self.TestSingleLineLint(
            '  memset(buf, xsize * ysize, 0)',
            'Did you mean "memset(buf, 0, xsize * ysize)"?'
            '  [runtime/memset] [4]')

        # There is legitimate test code that uses this form.
        # This is okay since the second argument is a literal.
        self.TestSingleLineLint(
            "  memset(buf, 'y', 0)",
            '')
        self.TestSingleLineLint(
            '  memset(buf, 4, 0)',
            '')
        self.TestSingleLineLint(
            '  memset(buf, -1, 0)',
            '')
        self.TestSingleLineLint(
            '  memset(buf, 0xF1, 0)',
            '')
        self.TestSingleLineLint(
            '  memset(buf, 0xcd, 0)',
            '')

    def testRedundantVirtual(self, state):
        self.TestSingleLineLint('virtual void F()', '')
        self.TestSingleLineLint('virtual void F();', '')
        self.TestSingleLineLint('virtual void F() {}', '')

        message_template = ('"%s" is redundant since function is already '
                            'declared as "%s"  [readability/inheritance] [4]')
        for virt_specifier in ['override', 'final']:
            error_message = message_template % ('virtual', virt_specifier)
            self.TestSingleLineLint('virtual int F() %s' % virt_specifier, error_message)
            self.TestSingleLineLint('virtual int F() %s;' % virt_specifier, error_message)
            self.TestSingleLineLint('virtual int F() %s {' % virt_specifier, error_message)

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state,
                'foo.cc', 'cc',
                ['// Copyright 2014 Your Company.',
                 'virtual void F(int a,',
                 '               int b) ' + virt_specifier + ';',
                 'virtual void F(int a,',
                 '               int b) LOCKS_EXCLUDED(lock) ' + virt_specifier + ';',
                 'virtual void F(int a,',
                 '               int b)',
                 '    LOCKS_EXCLUDED(lock) ' + virt_specifier + ';',
                 ''],
                error_collector)
            assert  [error_message, error_message, error_message] == error_collector.Results()

        error_message = message_template % ('override', 'final')
        self.TestSingleLineLint('int F() override final', error_message)
        self.TestSingleLineLint('int F() override final;', error_message)
        self.TestSingleLineLint('int F() override final {}', error_message)
        self.TestSingleLineLint('int F() final override', error_message)
        self.TestSingleLineLint('int F() final override;', error_message)
        self.TestSingleLineLint('int F() final override {}', error_message)

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state,
            'foo.cc', 'cc',
            ['// Copyright 2014 Your Company.',
             'struct A : virtual B {',
             '  ~A() override;'
             '};',
             'class C',
             '    : public D,',
             '      public virtual E {',
             '  void Func() override;',
             '}',
             ''],
            error_collector)
        assert '' == error_collector.Results()

        self.TestSingleLineLint('void Finalize(AnnotationProto *final) override;', '')

    def testCheckDeprecated(self):
        self.TestLanguageRulesCheck('foo_test.cc', '#include <iostream>', '')
        self.TestLanguageRulesCheck('foo_unittest.cc', '#include <iostream>', '')

    def testCheckPosixThreading(self):
        self.TestSingleLineLint('var = sctime_r()', '')
        self.TestSingleLineLint('var = strtok_r()', '')
        self.TestSingleLineLint('var = strtok_r(foo, ba, r)', '')
        self.TestSingleLineLint('var = brand()', '')
        self.TestSingleLineLint('_rand()', '')
        self.TestSingleLineLint('.rand()', '')
        self.TestSingleLineLint('->rand()', '')
        self.TestSingleLineLint('ACMRandom rand(seed)', '')
        self.TestSingleLineLint('ISAACRandom rand()', '')
        self.TestSingleLineLint('var = rand()',
                      'Consider using rand_r(...) instead of rand(...)'
                      ' for improved thread safety.'
                      '  [runtime/threadsafe_fn] [2]')
        self.TestSingleLineLint('var = strtok(str, delim)',
                      'Consider using strtok_r(...) '
                      'instead of strtok(...)'
                      ' for improved thread safety.'
                      '  [runtime/threadsafe_fn] [2]')

    def testVlogMisuse(self):
        self.TestSingleLineLint('VLOG(1)', '')
        self.TestSingleLineLint('VLOG(99)', '')
        self.TestSingleLineLint('LOG(ERROR)', '')
        self.TestSingleLineLint('LOG(INFO)', '')
        self.TestSingleLineLint('LOG(WARNING)', '')
        self.TestSingleLineLint('LOG(FATAL)', '')
        self.TestSingleLineLint('LOG(DFATAL)', '')
        self.TestSingleLineLint('VLOG(SOMETHINGWEIRD)', '')
        self.TestSingleLineLint('MYOWNVLOG(ERROR)', '')
        errmsg = ('VLOG() should be used with numeric verbosity level.  '
                  'Use LOG() if you want symbolic severity levels.'
                  '  [runtime/vlog] [5]')
        self.TestSingleLineLint('VLOG(ERROR)', errmsg)
        self.TestSingleLineLint('VLOG(INFO)', errmsg)
        self.TestSingleLineLint('VLOG(WARNING)', errmsg)
        self.TestSingleLineLint('VLOG(FATAL)', errmsg)
        self.TestSingleLineLint('VLOG(DFATAL)', errmsg)
        self.TestSingleLineLint('  VLOG(ERROR)', errmsg)
        self.TestSingleLineLint('  VLOG(INFO)', errmsg)
        self.TestSingleLineLint('  VLOG(WARNING)', errmsg)
        self.TestSingleLineLint('  VLOG(FATAL)', errmsg)
        self.TestSingleLineLint('  VLOG(DFATAL)', errmsg)

    # Test potential format string bugs like printf(foo).
    def testFormatStrings(self):
        self.TestSingleLineLint('printf("foo")', '')
        self.TestSingleLineLint('printf("foo: %s", foo)', '')
        self.TestSingleLineLint('DocidForPrintf(docid)', '')  # Should not trigger.
        self.TestSingleLineLint('printf(format, value)', '')  # Should not trigger.
        self.TestSingleLineLint('printf(__VA_ARGS__)', '')  # Should not trigger.
        self.TestSingleLineLint('printf(format.c_str(), value)', '')  # Should not trigger.
        self.TestSingleLineLint('printf(format(index).c_str(), value)', '')
        self.TestSingleLineLint(
            'printf(foo)',
            'Potential format string bug. Do printf("%s", foo) instead.'
            '  [runtime/printf] [4]')
        self.TestSingleLineLint(
            'printf(foo.c_str())',
            'Potential format string bug. '
            'Do printf("%s", foo.c_str()) instead.'
            '  [runtime/printf] [4]')
        self.TestSingleLineLint(
            'printf(foo->c_str())',
            'Potential format string bug. '
            'Do printf("%s", foo->c_str()) instead.'
            '  [runtime/printf] [4]')
        self.TestSingleLineLint(
            'StringPrintf(foo)',
            'Potential format string bug. Do StringPrintf("%s", foo) instead.'
            ''
            '  [runtime/printf] [4]')

    # Test disallowed use of operator& and other operators.
    def testIllegalOperatorOverloading(self):
        errmsg = ('Unary operator& is dangerous.  Do not use it.'
                  '  [runtime/operator] [4]')
        self.TestSingleLineLint('void operator=(const Myclass&)', '')
        self.TestSingleLineLint('void operator&(int a, int b)', '')   # binary operator& ok
        self.TestSingleLineLint('void operator&() { }', errmsg)
        self.TestSingleLineLint('void operator & (  ) { }',
                      ['Extra space after (  [whitespace/parens] [2]', errmsg])

    # const string reference members are dangerous..
    def testConstStringReferenceMembers(self):
        errmsg = ('const string& members are dangerous. It is much better to use '
                  'alternatives, such as pointers or simple constants.'
                  '  [runtime/member_string_references] [2]')

        members_declarations = ['const string& church',
                                'const string &turing',
                                'const string & godel']
        # TODO(unknown): Enable also these tests if and when we ever
        # decide to check for arbitrary member references.
        #                         "const Turing & a",
        #                         "const Church& a",
        #                         "const vector<int>& a",
        #                         "const     Kurt::Godel    &    godel",
        #                         "const Kazimierz::Kuratowski& kk" ]

        # The Good.

        self.TestSingleLineLint('void f(const string&)', '')
        self.TestSingleLineLint('const string& f(const string& a, const string& b)', '')
        self.TestSingleLineLint('typedef const string& A;', '')

        for decl in members_declarations:
            self.TestSingleLineLint(decl + ' = b;', '')
            self.TestSingleLineLint(decl + '      =', '')

        # The Bad.

        for decl in members_declarations:
            self.TestSingleLineLint(decl + ';', errmsg)

    # Variable-length arrays are not permitted.
    def testVariableLengthArrayDetection(self):
        errmsg = ('Do not use variable-length arrays.  Use an appropriately named '
                  "('k' followed by CamelCase) compile-time constant for the size."
                  '  [runtime/arrays] [1]')

        self.TestSingleLineLint('int a[any_old_variable];', errmsg)
        self.TestSingleLineLint('int doublesize[some_var * 2];', errmsg)
        self.TestSingleLineLint('int a[afunction()];', errmsg)
        self.TestSingleLineLint('int a[function(kMaxFooBars)];', errmsg)
        self.TestSingleLineLint('bool a_list[items_->size()];', errmsg)
        self.TestSingleLineLint('namespace::Type buffer[len+1];', errmsg)

        self.TestSingleLineLint('int a[64];', '')
        self.TestSingleLineLint('int a[0xFF];', '')
        self.TestSingleLineLint('int first[256], second[256];', '')
        self.TestSingleLineLint('int array_name[kCompileTimeConstant];', '')
        self.TestSingleLineLint('char buf[somenamespace::kBufSize];', '')
        self.TestSingleLineLint('int array_name[ALL_CAPS];', '')
        self.TestSingleLineLint('AClass array1[foo::bar::ALL_CAPS];', '')
        self.TestSingleLineLint('int a[kMaxStrLen + 1];', '')
        self.TestSingleLineLint('int a[sizeof(foo)];', '')
        self.TestSingleLineLint('int a[sizeof(*foo)];', '')
        self.TestSingleLineLint('int a[sizeof foo];', '')
        self.TestSingleLineLint('int a[sizeof(struct Foo)];', '')
        self.TestSingleLineLint('int a[128 - sizeof(const bar)];', '')
        self.TestSingleLineLint('int a[(sizeof(foo) * 4)];', '')
        self.TestSingleLineLint('int a[(arraysize(fixed_size_array)/2) << 1];', '')
        self.TestSingleLineLint('delete a[some_var];', '')
        self.TestSingleLineLint('return a[some_var];', '')

    # DISALLOW_COPY_AND_ASSIGN and DISALLOW_IMPLICIT_CONSTRUCTORS should be at
    # end of class if present.
    def testDisallowMacrosAtEnd(self, state):
        for macro_name in (
            'DISALLOW_COPY_AND_ASSIGN',
            'DISALLOW_IMPLICIT_CONSTRUCTORS'):
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state,
                'foo.cc', 'cc',
                ['// Copyright 2014 Your Company.',
                 'class SomeClass {',
                 ' private:',
                 '  %s(SomeClass);' % macro_name,
                 '  int member_;',
                 '};',
                 ''],
                error_collector)
            assert  ('%s should be the last thing in the class' % macro_name) + '  [readability/constructors] [3]' == error_collector.Results()

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state,
                'foo.cc', 'cc',
                ['// Copyright 2014 Your Company.',
                 'class OuterClass {',
                 ' private:',
                 '  struct InnerClass {',
                 '   private:',
                 '    %s(InnerClass);' % macro_name,
                 '    int member;',
                 '  };',
                 '};',
                 ''],
                error_collector)
            assert  ('%s should be the last thing in the class' % macro_name) + '  [readability/constructors] [3]' == error_collector.Results()

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state,
                'foo.cc', 'cc',
                ['// Copyright 2014 Your Company.',
                 'class OuterClass1 {',
                 ' private:',
                 '  struct InnerClass1 {',
                 '   private:',
                 '    %s(InnerClass1);' % macro_name,
                 '  };',
                 '  %s(OuterClass1);' % macro_name,
                 '};',
                 'struct OuterClass2 {',
                 ' private:',
                 '  class InnerClass2 {',
                 '   private:',
                 '    %s(InnerClass2);' % macro_name,
                 '    // comment',
                 '  };',
                 '',
                 '  %s(OuterClass2);' % macro_name,
                 '',
                 '  // comment',
                 '};',
                 'void Func() {',
                 '  struct LocalClass {',
                 '   private:',
                 '    %s(LocalClass);' % macro_name,
                 '  } variable;',
                 '}',
                 ''],
                error_collector)
            assert '' == error_collector.Results()

    # Brace usage
    def testBraces(self, state):
        # Braces shouldn't be followed by a ; unless they're defining a struct
        # or initializing an array
        self.TestSingleLineLint('int a[3] = { 1, 2, 3 };', '')
        self.TestSingleLineLint(
            """const int foo[] =
               {1, 2, 3 };""",
            '')
        # For single line, unmatched '}' with a ';' is ignored (not enough context)
        self.TestMultiLineLint(state,
            """int a[3] = { 1,
                        2,
                        3 };""",
            '')
        self.TestMultiLineLint(state,
            """int a[2][3] = { { 1, 2 },
                         { 3, 4 } };""",
            '')
        self.TestMultiLineLint(state,
            """int a[2][3] =
               { { 1, 2 },
                 { 3, 4 } };""",
            '')

    # CHECK/EXPECT_TRUE/EXPECT_FALSE replacements
    def testCheckCheck(self):
        self.TestSingleLineLint('CHECK(x == 42);',
                      'Consider using CHECK_EQ instead of CHECK(a == b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('CHECK(x != 42);',
                      'Consider using CHECK_NE instead of CHECK(a != b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('CHECK(x >= 42);',
                      'Consider using CHECK_GE instead of CHECK(a >= b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('CHECK(x > 42);',
                      'Consider using CHECK_GT instead of CHECK(a > b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('CHECK(x <= 42);',
                      'Consider using CHECK_LE instead of CHECK(a <= b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('CHECK(x < 42);',
                      'Consider using CHECK_LT instead of CHECK(a < b)'
                      '  [readability/check] [2]')

        self.TestSingleLineLint('DCHECK(x == 42);',
                      'Consider using DCHECK_EQ instead of DCHECK(a == b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('DCHECK(x != 42);',
                      'Consider using DCHECK_NE instead of DCHECK(a != b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('DCHECK(x >= 42);',
                      'Consider using DCHECK_GE instead of DCHECK(a >= b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('DCHECK(x > 42);',
                      'Consider using DCHECK_GT instead of DCHECK(a > b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('DCHECK(x <= 42);',
                      'Consider using DCHECK_LE instead of DCHECK(a <= b)'
                      '  [readability/check] [2]')
        self.TestSingleLineLint('DCHECK(x < 42);',
                      'Consider using DCHECK_LT instead of DCHECK(a < b)'
                      '  [readability/check] [2]')

        self.TestSingleLineLint(
            'EXPECT_TRUE("42" == x);',
            'Consider using EXPECT_EQ instead of EXPECT_TRUE(a == b)'
            '  [readability/check] [2]')
        self.TestSingleLineLint(
            'EXPECT_TRUE("42" != x);',
            'Consider using EXPECT_NE instead of EXPECT_TRUE(a != b)'
            '  [readability/check] [2]')
        self.TestSingleLineLint(
            'EXPECT_TRUE(+42 >= x);',
            'Consider using EXPECT_GE instead of EXPECT_TRUE(a >= b)'
            '  [readability/check] [2]')

        self.TestSingleLineLint(
            'EXPECT_FALSE(x == 42);',
            'Consider using EXPECT_NE instead of EXPECT_FALSE(a == b)'
            '  [readability/check] [2]')
        self.TestSingleLineLint(
            'EXPECT_FALSE(x != 42);',
            'Consider using EXPECT_EQ instead of EXPECT_FALSE(a != b)'
            '  [readability/check] [2]')
        self.TestSingleLineLint(
            'EXPECT_FALSE(x >= 42);',
            'Consider using EXPECT_LT instead of EXPECT_FALSE(a >= b)'
            '  [readability/check] [2]')
        self.TestSingleLineLint(
            'ASSERT_FALSE(x > 42);',
            'Consider using ASSERT_LE instead of ASSERT_FALSE(a > b)'
            '  [readability/check] [2]')
        self.TestSingleLineLint(
            'ASSERT_FALSE(x <= 42);',
            'Consider using ASSERT_GT instead of ASSERT_FALSE(a <= b)'
            '  [readability/check] [2]')

        self.TestSingleLineLint('CHECK(x<42);',
                      ['Missing spaces around <'
                       '  [whitespace/operators] [3]',
                       'Consider using CHECK_LT instead of CHECK(a < b)'
                       '  [readability/check] [2]'])
        self.TestSingleLineLint('CHECK(x>42);',
                      ['Missing spaces around >'
                       '  [whitespace/operators] [3]',
                       'Consider using CHECK_GT instead of CHECK(a > b)'
                       '  [readability/check] [2]'])

        self.TestSingleLineLint('using some::namespace::operator<<;', '')
        self.TestSingleLineLint('using some::namespace::operator>>;', '')

        self.TestSingleLineLint('CHECK(x->y == 42);',
                      'Consider using CHECK_EQ instead of CHECK(a == b)'
                      '  [readability/check] [2]')

        self.TestSingleLineLint(
            '  EXPECT_TRUE(42 < x);  // Random comment.',
            'Consider using EXPECT_LT instead of EXPECT_TRUE(a < b)'
            '  [readability/check] [2]')
        self.TestSingleLineLint(
            'EXPECT_TRUE( 42 < x );',
            ['Extra space after ( in function call'
             '  [whitespace/parens] [4]',
             'Extra space before )  [whitespace/parens] [2]',
             'Consider using EXPECT_LT instead of EXPECT_TRUE(a < b)'
             '  [readability/check] [2]'])

        self.TestSingleLineLint('CHECK(4\'2 == x);',
                      'Consider using CHECK_EQ instead of CHECK(a == b)'
                      '  [readability/check] [2]')

    def testCheckCheckFalsePositives(self, state):
        self.TestSingleLineLint('CHECK(some_iterator == obj.end());', '')
        self.TestSingleLineLint('EXPECT_TRUE(some_iterator == obj.end());', '')
        self.TestSingleLineLint('EXPECT_FALSE(some_iterator == obj.end());', '')
        self.TestSingleLineLint('CHECK(some_pointer != NULL);', '')
        self.TestSingleLineLint('EXPECT_TRUE(some_pointer != NULL);', '')
        self.TestSingleLineLint('EXPECT_FALSE(some_pointer != NULL);', '')

        self.TestSingleLineLint('CHECK(CreateTestFile(dir, (1 << 20)));', '')
        self.TestSingleLineLint('CHECK(CreateTestFile(dir, (1 >> 20)));', '')

        self.TestSingleLineLint('CHECK(x ^ (y < 42));', '')
        self.TestSingleLineLint('CHECK((x > 42) ^ (x < 54));', '')
        self.TestSingleLineLint('CHECK(a && b < 42);', '')
        self.TestSingleLineLint('CHECK(42 < a && a < b);', '')
        self.TestSingleLineLint('SOFT_CHECK(x > 42);', '')

        self.TestMultiLineLint(state,
            """_STLP_DEFINE_BINARY_OP_CHECK(==, _OP_EQUAL);
        _STLP_DEFINE_BINARY_OP_CHECK(!=, _OP_NOT_EQUAL);
        _STLP_DEFINE_BINARY_OP_CHECK(<, _OP_LESS_THAN);
        _STLP_DEFINE_BINARY_OP_CHECK(<=, _OP_LESS_EQUAL);
        _STLP_DEFINE_BINARY_OP_CHECK(>, _OP_GREATER_THAN);
        _STLP_DEFINE_BINARY_OP_CHECK(>=, _OP_GREATER_EQUAL);
        _STLP_DEFINE_BINARY_OP_CHECK(+, _OP_PLUS);
        _STLP_DEFINE_BINARY_OP_CHECK(*, _OP_TIMES);
        _STLP_DEFINE_BINARY_OP_CHECK(/, _OP_DIVIDE);
        _STLP_DEFINE_BINARY_OP_CHECK(-, _OP_SUBTRACT);
        _STLP_DEFINE_BINARY_OP_CHECK(%, _OP_MOD);""",
            '')

        self.TestSingleLineLint('CHECK(x < 42) << "Custom error message";', '')

    # Alternative token to punctuation operator replacements
    def testCheckAltTokens(self):
        self.TestSingleLineLint('true or true',
                      'Use operator || instead of or'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('true and true',
                      'Use operator && instead of and'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('if (not true)',
                      'Use operator ! instead of not'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('1 bitor 1',
                      'Use operator | instead of bitor'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('1 xor 1',
                      'Use operator ^ instead of xor'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('1 bitand 1',
                      'Use operator & instead of bitand'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('x = compl 1',
                      'Use operator ~ instead of compl'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('x and_eq y',
                      'Use operator &= instead of and_eq'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('x or_eq y',
                      'Use operator |= instead of or_eq'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('x xor_eq y',
                      'Use operator ^= instead of xor_eq'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('x not_eq y',
                      'Use operator != instead of not_eq'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('line_continuation or',
                      'Use operator || instead of or'
                      '  [readability/alt_tokens] [2]')
        self.TestSingleLineLint('if(true and(parentheses',
                      'Use operator && instead of and'
                      '  [readability/alt_tokens] [2]')

        self.TestSingleLineLint('#include "base/false-and-false.h"', '')
        self.TestSingleLineLint('#error false or false', '')
        self.TestSingleLineLint('false nor false', '')
        self.TestSingleLineLint('false nand false', '')

    # Passing and returning non-const references
    def testNonConstReference(self, state):
        # Passing a non-const reference as function parameter is forbidden.
        operand_error_message = ('Is this a non-const reference? '
                                 'If so, make const or use a pointer: %s'
                                 '  [runtime/references] [2]')
        # Warn of use of a non-const reference in operators and functions
        self.TestSingleLineLint('bool operator>(Foo& s, Foo& f);',
                      [operand_error_message % 'Foo& s',
                       operand_error_message % 'Foo& f'])
        self.TestSingleLineLint('bool operator+(Foo& s, Foo& f);',
                      [operand_error_message % 'Foo& s',
                       operand_error_message % 'Foo& f'])
        self.TestSingleLineLint('int len(Foo& s);', operand_error_message % 'Foo& s')
        # Allow use of non-const references in a few specific cases
        self.TestSingleLineLint('stream& operator>>(stream& s, Foo& f);', '')
        self.TestSingleLineLint('stream& operator<<(stream& s, Foo& f);', '')
        self.TestSingleLineLint('void swap(Bar& a, Bar& b);', '')
        self.TestSingleLineLint('ostream& LogFunc(ostream& s);', '')
        self.TestSingleLineLint('ostringstream& LogFunc(ostringstream& s);', '')
        self.TestSingleLineLint('istream& LogFunc(istream& s);', '')
        self.TestSingleLineLint('istringstream& LogFunc(istringstream& s);', '')
        # Returning a non-const reference from a function is OK.
        self.TestSingleLineLint('int& g();', '')
        # Passing a const reference to a struct (using the struct keyword) is OK.
        self.TestSingleLineLint('void foo(const struct tm& tm);', '')
        # Passing a const reference to a typename is OK.
        self.TestSingleLineLint('void foo(const typename tm& tm);', '')
        # Const reference to a pointer type is OK.
        self.TestSingleLineLint('void foo(const Bar* const& p) {', '')
        self.TestSingleLineLint('void foo(Bar const* const& p) {', '')
        self.TestSingleLineLint('void foo(Bar* const& p) {', '')
        # Const reference to a templated type is OK.
        self.TestSingleLineLint('void foo(const std::vector<std::string>& v);', '')
        # Non-const reference to a pointer type is not OK.
        self.TestSingleLineLint('void foo(Bar*& p);',
                      operand_error_message % 'Bar*& p')
        self.TestSingleLineLint('void foo(const Bar*& p);',
                      operand_error_message % 'const Bar*& p')
        self.TestSingleLineLint('void foo(Bar const*& p);',
                      operand_error_message % 'Bar const*& p')
        self.TestSingleLineLint('void foo(struct Bar*& p);',
                      operand_error_message % 'struct Bar*& p')
        self.TestSingleLineLint('void foo(const struct Bar*& p);',
                      operand_error_message % 'const struct Bar*& p')
        self.TestSingleLineLint('void foo(struct Bar const*& p);',
                      operand_error_message % 'struct Bar const*& p')
        # Non-const reference to a templated type is not OK.
        self.TestSingleLineLint('void foo(std::vector<int>& p);',
                      operand_error_message % 'std::vector<int>& p')
        # Returning an address of something is not prohibited.
        self.TestSingleLineLint('return &something;', '')
        self.TestSingleLineLint('if (condition) {return &something; }', '')
        self.TestSingleLineLint('if (condition) return &something;', '')
        self.TestSingleLineLint('if (condition) address = &something;', '')
        self.TestSingleLineLint('if (condition) result = lhs&rhs;', '')
        self.TestSingleLineLint('if (condition) result = lhs & rhs;', '')
        self.TestSingleLineLint('a = (b+c) * sizeof &f;', '')
        self.TestSingleLineLint('a = MySize(b) * sizeof &f;', '')
        # We don't get confused by C++11 range-based for loops.
        self.TestSingleLineLint('for (const string& s : c)', '')
        self.TestSingleLineLint('for (auto& r : c)', '')
        self.TestSingleLineLint('for (typename Type& a : b)', '')
        # We don't get confused by some other uses of '&'.
        self.TestSingleLineLint('T& operator=(const T& t);', '')
        self.TestSingleLineLint('int g() { return (a & b); }', '')
        self.TestSingleLineLint('T& r = (T&)*(vp());', '')
        self.TestSingleLineLint('T& r = v', '')
        self.TestSingleLineLint('static_assert((kBits & kMask) == 0, "text");', '')
        self.TestSingleLineLint('COMPILE_ASSERT((kBits & kMask) == 0, text);', '')
        # Spaces before template arguments.  This is poor style, but
        # happens 0.15% of the time.
        self.TestSingleLineLint('void Func(const vector <int> &const_x, '
                      'vector <int> &nonconst_x) {',
                      operand_error_message % 'vector<int> &nonconst_x')

        # Derived member functions are spared from override check
        self.TestSingleLineLint('void Func(X& x);', operand_error_message % 'X& x')
        self.TestSingleLineLint('void Func(X& x) {}', operand_error_message % 'X& x')
        self.TestSingleLineLint('void Func(X& x) override;', '')
        self.TestSingleLineLint('void Func(X& x) override {', '')
        self.TestSingleLineLint('void Func(X& x) const override;', '')
        self.TestSingleLineLint('void Func(X& x) const override {', '')

        # Don't warn on out-of-line method definitions.
        self.TestSingleLineLint('void NS::Func(X& x) {', '')
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            state,
            'foo.cc', 'cc',
            ['// Copyright 2014 Your Company. All Rights Reserved.',
             'void a::b() {}',
             'void f(int& q) {}',
             ''],
            error_collector)
        assert operand_error_message % 'int& q' == error_collector.Results()

        # Other potential false positives.  These need full parser
        # state to reproduce as opposed to just TestSingleLineLint.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            state,
            'foo.cc', 'cc',
            ['// Copyright 2014 Your Company. All Rights Reserved.',
             'void swap(int &x,',
             '          int &y) {',
             '}',
             'void swap(',
             '    sparsegroup<T, GROUP_SIZE, Alloc> &x,',
             '    sparsegroup<T, GROUP_SIZE, Alloc> &y) {',
             '}',
             'ostream& operator<<(',
             '    ostream& out',
             '    const dense_hash_set<Value, Hash, Equals, Alloc>& seq) {',
             '}',
             'class A {',
             '  void Function(',
             '      string &x) override {',
             '  }',
             '};',
             'void Derived::Function(',
             '    string &x) {',
             '}',
             '#define UNSUPPORTED_MASK(_mask) \\',
             '  if (flags & _mask) { \\',
             '    LOG(FATAL) << "Unsupported flag: " << #_mask; \\',
             '  }',
             'Constructor::Constructor()',
             '    : initializer1_(a1 & b1),',
             '      initializer2_(a2 & b2) {',
             '}',
             'Constructor::Constructor()',
             '    : initializer1_{a3 & b3},',
             '      initializer2_(a4 & b4) {',
             '}',
             'Constructor::Constructor()',
             '    : initializer1_{a5 & b5},',
             '      initializer2_(a6 & b6) {}',
             ''],
            error_collector)
        assert '' == error_collector.Results()

        # Multi-line references
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            state,
            'foo.cc', 'cc',
            ['// Copyright 2014 Your Company. All Rights Reserved.',
             'void Func(const Outer::',
             '              Inner& const_x,',
             '          const Outer',
             '              ::Inner& const_y,',
             '          const Outer<',
             '              int>::Inner& const_z,',
             '          Outer::',
             '              Inner& nonconst_x,',
             '          Outer',
             '              ::Inner& nonconst_y,',
             '          Outer<',
             '              int>::Inner& nonconst_z) {',
             '}',
             ''],
            error_collector)
        assert [operand_error_message % 'Outer::Inner& nonconst_x',
             operand_error_message % 'Outer::Inner& nonconst_y',
             operand_error_message % 'Outer<int>::Inner& nonconst_z'] == \
            error_collector.Results()

        # A peculiar false positive due to bad template argument parsing
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            state,
            'foo.cc', 'cc',
            ['// Copyright 2014 Your Company. All Rights Reserved.',
             'inline RCULocked<X>::ReadPtr::ReadPtr(const RCULocked* rcu) {',
             '  DCHECK(!(data & kFlagMask)) << "Error";',
             '}',
             '',
             'RCULocked<X>::WritePtr::WritePtr(RCULocked* rcu)',
             '    : lock_(&rcu_->mutex_) {',
             '}',
             ''],
            error_collector.Results())
        assert '' == error_collector.Results()

    def testBraceAtBeginOfLine(self, state):
        self.TestSingleLineLint('{',
                      '{ should almost always be at the end of the previous line'
                      '  [whitespace/braces] [4]')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['int function()',
                                 '{',  # warning here
                                 '  MutexLock l(&mu);',
                                 '}',
                                 'int variable;'
                                 '{',  # no warning
                                 '  MutexLock l(&mu);',
                                 '}',
                                 'MyType m = {',
                                 '  {value1, value2},',
                                 '  {',  # no warning
                                 '    loooong_value1, looooong_value2',
                                 '  }',
                                 '};',
                                 '#if PREPROCESSOR',
                                 '{',  # no warning
                                 '  MutexLock l(&mu);',
                                 '}',
                                 '#endif'],
                                error_collector)
        assert 1 == error_collector.Results().count(
            '{ should almost always be at the end of the previous line'
            '  [whitespace/braces] [4]')

        self.TestMultiLineLint(state,
            """
        foo(
          {
            loooooooooooooooong_value,
          });""",
            '')

    def testMismatchingSpacesInParens(self):
        self.TestSingleLineLint('if (foo ) {', 'Mismatching spaces inside () in if'
                      '  [whitespace/parens] [5]')
        self.TestSingleLineLint('switch ( foo) {', 'Mismatching spaces inside () in switch'
                      '  [whitespace/parens] [5]')
        self.TestSingleLineLint('for (foo; ba; bar ) {', 'Mismatching spaces inside () in for'
                      '  [whitespace/parens] [5]')
        self.TestSingleLineLint('for (; foo; bar) {', '')
        self.TestSingleLineLint('for ( ; foo; bar) {', '')
        self.TestSingleLineLint('for ( ; foo; bar ) {', '')
        self.TestSingleLineLint('for (foo; bar; ) {', '')
        self.TestSingleLineLint('while (  foo  ) {', 'Should have zero or one spaces inside'
                      ' ( and ) in while  [whitespace/parens] [5]')

    def testSpacingForFncall(self):
        self.TestSingleLineLint('if (foo) {', '')
        self.TestSingleLineLint('for (foo; bar; baz) {', '')
        self.TestSingleLineLint('for (;;) {', '')
        # Space should be allowed in placement new operators.
        self.TestSingleLineLint('Something* p = new (place) Something();', '')
        # Test that there is no warning when increment statement is empty.
        self.TestSingleLineLint('for (foo; baz;) {', '')
        self.TestSingleLineLint('for (foo;bar;baz) {', 'Missing space after ;'
                      '  [whitespace/semicolon] [3]')
        # we don't warn about this semicolon, at least for now
        self.TestSingleLineLint('if (condition) {return &something; }',
                      '')
        # seen in some macros
        self.TestSingleLineLint('DoSth();\\', '')
        # Test that there is no warning about semicolon here.
        self.TestSingleLineLint('abc;// this is abc',
                      'At least two spaces is best between code'
                      ' and comments  [whitespace/comments] [2]')
        self.TestSingleLineLint('while (foo) {', '')
        self.TestSingleLineLint('switch (foo) {', '')
        self.TestSingleLineLint('foo( bar)', 'Extra space after ( in function call'
                      '  [whitespace/parens] [4]')
        self.TestSingleLineLint('foo(  // comment', '')
        self.TestSingleLineLint('foo( // comment',
                      'At least two spaces is best between code'
                      ' and comments  [whitespace/comments] [2]')
        self.TestSingleLineLint('foobar( \\', '')
        self.TestSingleLineLint('foobar(     \\', '')
        self.TestSingleLineLint('( a + b)', 'Extra space after ('
                      '  [whitespace/parens] [2]')
        self.TestSingleLineLint('((a+b))', '')
        self.TestSingleLineLint('foo (foo)', 'Extra space before ( in function call'
                      '  [whitespace/parens] [4]')
        # asm volatile () may have a space, as it isn't a function call.
        self.TestSingleLineLint('asm volatile ("")', '')
        self.TestSingleLineLint('__asm__ __volatile__ ("")', '')
        self.TestSingleLineLint('} catch (const Foo& ex) {', '')
        self.TestSingleLineLint('case (42):', '')
        self.TestSingleLineLint('typedef foo (*foo)(foo)', '')
        self.TestSingleLineLint('typedef foo (*foo12bar_)(foo)', '')
        self.TestSingleLineLint('typedef foo (Foo::*bar)(foo)', '')
        self.TestSingleLineLint('using foo = type (Foo::*bar)(foo)', '')
        self.TestSingleLineLint('using foo = type (Foo::*bar)(', '')
        self.TestSingleLineLint('using foo = type (Foo::*)(', '')
        self.TestSingleLineLint('foo (Foo::*bar)(', '')
        self.TestSingleLineLint('foo (x::y::*z)(', '')
        self.TestSingleLineLint('foo (Foo::bar)(',
                      'Extra space before ( in function call'
                      '  [whitespace/parens] [4]')
        self.TestSingleLineLint('foo (*bar)(', '')
        self.TestSingleLineLint('typedef foo (Foo::*bar)(', '')
        self.TestSingleLineLint('(foo)(bar)', '')
        self.TestSingleLineLint('Foo (*foo)(bar)', '')
        self.TestSingleLineLint('Foo (*foo)(Bar bar,', '')
        self.TestSingleLineLint('char (*p)[sizeof(foo)] = &foo', '')
        self.TestSingleLineLint('char (&ref)[sizeof(foo)] = &foo', '')
        self.TestSingleLineLint('const char32 (*table[])[6];', '')
        # The sizeof operator is often written as if it were a function call, with
        # an opening parenthesis directly following the operator name, but it can
        # also be written like any other operator, with a space following the
        # operator name, and the argument optionally in parentheses.
        self.TestSingleLineLint('sizeof(foo)', '')
        self.TestSingleLineLint('sizeof foo', '')
        self.TestSingleLineLint('sizeof (foo)', '')

    def testSpacingBeforeBraces(self):
        self.TestSingleLineLint('if (foo){', 'Missing space before {'
                      '  [whitespace/braces] [5]')
        self.TestSingleLineLint('for{', 'Missing space before {'
                      '  [whitespace/braces] [5]')
        self.TestSingleLineLint('for {', '')
        self.TestSingleLineLint('EXPECT_DEBUG_DEATH({', '')
        self.TestSingleLineLint('std::is_convertible<A, B>{}', '')
        self.TestSingleLineLint('blah{32}', 'Missing space before {'
                      '  [whitespace/braces] [5]')
        self.TestSingleLineLint('int8_t{3}', '')
        self.TestSingleLineLint('int16_t{3}', '')
        self.TestSingleLineLint('int32_t{3}', '')
        self.TestSingleLineLint('uint64_t{12345}', '')
        self.TestSingleLineLint('constexpr int64_t kBatchGapMicros ='
                      ' int64_t{7} * 24 * 3600 * 1000000;  // 1 wk.', '')
        self.TestSingleLineLint('MoveOnly(int i1, int i2) : ip1{new int{i1}}, '
                      'ip2{new int{i2}} {}',
                      '')

    def testSemiColonAfterBraces(self, state):
        self.TestSingleLineLint('if (cond) { func(); };',
                      'You don\'t need a ; after a }  [readability/braces] [4]')
        self.TestSingleLineLint('void Func() {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')
        self.TestSingleLineLint('void Func() const {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')
        self.TestSingleLineLint('class X {};', '')
        for keyword in ['struct', 'union']:
            for align in ['', ' alignas(16)']:
                for typename in ['', ' X']:
                    for identifier in ['', ' x']:
                        self.TestSingleLineLint(keyword + align + typename + ' {}' + identifier + ';',
                                      '')

        self.TestSingleLineLint('class X : public Y {};', '')
        self.TestSingleLineLint('class X : public MACRO() {};', '')
        self.TestSingleLineLint('class X : public decltype(expr) {};', '')
        self.TestSingleLineLint('DEFINE_FACADE(PCQueue::Watcher, PCQueue) {};', '')
        self.TestSingleLineLint('VCLASS(XfaTest, XfaContextTest) {};', '')
        self.TestSingleLineLint('class STUBBY_CLASS(H, E) {};', '')
        self.TestSingleLineLint('class STUBBY2_CLASS(H, E) {};', '')
        self.TestSingleLineLint('TEST(TestCase, TestName) {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')
        self.TestSingleLineLint('TEST_F(TestCase, TestName) {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')

        self.TestSingleLineLint('file_tocs_[i] = (FileToc) {a, b, c};', '')
        self.TestMultiLineLint(state, 'class X : public Y,\npublic Z {};', '')

    def testSpacingBeforeBrackets(self):
        self.TestSingleLineLint('int numbers [] = { 1, 2, 3 };',
                      'Extra space before [  [whitespace/braces] [5]')
        # space allowed in some cases
        self.TestSingleLineLint('auto [abc, def] = func();', '')
        self.TestSingleLineLint('#define NODISCARD [[nodiscard]]', '')
        self.TestSingleLineLint('void foo(int param [[maybe_unused]]);', '')

    def testLambda(self, state):
        self.TestSingleLineLint('auto x = []() {};', '')
        self.TestSingleLineLint('return []() {};', '')
        self.TestMultiLineLint(state, 'auto x = []() {\n};\n', '')
        self.TestSingleLineLint('int operator[](int x) {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')

        self.TestMultiLineLint(state, 'auto x = [&a,\nb]() {};', '')
        self.TestMultiLineLint(state, 'auto x = [&a,\nb]\n() {};', '')
        self.TestMultiLineLint(state, 'auto x = [&a,\n'
                               '          b](\n'
                               '    int a,\n'
                               '    int b) {\n'
                               '  return a +\n'
                               '         b;\n'
                               '};\n',
                               '')

        # Avoid false positives with operator[]
        self.TestSingleLineLint('table_to_children[&*table].push_back(dependent);', '')

    def testBraceInitializerList(self, state):
        self.TestSingleLineLint('MyStruct p = {1, 2};', '')
        self.TestSingleLineLint('MyStruct p{1, 2};', '')
        self.TestSingleLineLint('vector<int> p = {1, 2};', '')
        self.TestSingleLineLint('vector<int> p{1, 2};', '')
        self.TestSingleLineLint('x = vector<int>{1, 2};', '')
        self.TestSingleLineLint('x = (struct in_addr){ 0 };', '')
        self.TestSingleLineLint('Func(vector<int>{1, 2})', '')
        self.TestSingleLineLint('Func((struct in_addr){ 0 })', '')
        self.TestSingleLineLint('Func(vector<int>{1, 2}, 3)', '')
        self.TestSingleLineLint('Func((struct in_addr){ 0 }, 3)', '')
        self.TestSingleLineLint('LOG(INFO) << char{7};', '')
        self.TestSingleLineLint('LOG(INFO) << char{7} << "!";', '')
        self.TestSingleLineLint('int p[2] = {1, 2};', '')
        self.TestSingleLineLint('return {1, 2};', '')
        self.TestSingleLineLint('std::unique_ptr<Foo> foo{new Foo{}};', '')
        self.TestSingleLineLint('auto foo = std::unique_ptr<Foo>{new Foo{}};', '')
        self.TestSingleLineLint('static_assert(Max7String{}.IsValid(), "");', '')
        self.TestSingleLineLint('map_of_pairs[{1, 2}] = 3;', '')
        self.TestSingleLineLint('ItemView{has_offer() ? new Offer{offer()} : nullptr', '')
        self.TestSingleLineLint('template <class T, EnableIf<::std::is_const<T>{}> = 0>', '')

        self.TestMultiLineLint(state, 'std::unique_ptr<Foo> foo{\n'
                               '  new Foo{}\n'
                               '};\n', '')
        self.TestMultiLineLint(state, 'std::unique_ptr<Foo> foo{\n'
                               '  new Foo{\n'
                               '    new Bar{}\n'
                               '  }\n'
                               '};\n', '')
        self.TestMultiLineLint(state, 'if (true) {\n'
                               '  if (false){ func(); }\n'
                               '}\n',
                               'Missing space before {  [whitespace/braces] [5]')
        self.TestMultiLineLint(state, 'MyClass::MyClass()\n'
                               '    : initializer_{\n'
                               '          Func()} {\n'
                               '}\n', '')
        self.TestSingleLineLint('const pair<string, string> kCL' +
                      ('o' * 41) + 'gStr[] = {\n',
                      'Lines should be <= 80 characters long'
                      '  [whitespace/line_length] [2]')
        self.TestMultiLineLint(state, 'const pair<string, string> kCL' +
                               ('o' * 40) + 'ngStr[] =\n'
                               '    {\n'
                               '        {"gooooo", "oooogle"},\n'
                               '};\n', '')
        self.TestMultiLineLint(state, 'const pair<string, string> kCL' +
                               ('o' * 39) + 'ngStr[] =\n'
                               '    {\n'
                               '        {"gooooo", "oooogle"},\n'
                               '};\n', '{ should almost always be at the end of '
                               'the previous line  [whitespace/braces] [4]')

    def testSpacingAroundElse(self):
        self.TestSingleLineLint('}else {', 'Missing space before else'
                      '  [whitespace/braces] [5]')
        self.TestSingleLineLint('} else{', 'Missing space before {'
                      '  [whitespace/braces] [5]')
        self.TestSingleLineLint('} else {', '')
        self.TestSingleLineLint('} else if (foo) {', '')

    def testSpacingWithInitializerLists(self):
        self.TestSingleLineLint('int v[1][3] = {{1, 2, 3}};', '')
        self.TestSingleLineLint('int v[1][1] = {{0}};', '')

    def testSpacingForBinaryOps(self):
        self.TestSingleLineLint('if (foo||bar) {', 'Missing spaces around ||'
                      '  [whitespace/operators] [3]')
        self.TestSingleLineLint('if (foo<=bar) {', 'Missing spaces around <='
                      '  [whitespace/operators] [3]')
        self.TestSingleLineLint('if (foo<bar) {', 'Missing spaces around <'
                      '  [whitespace/operators] [3]')
        self.TestSingleLineLint('if (foo>bar) {', 'Missing spaces around >'
                      '  [whitespace/operators] [3]')
        self.TestSingleLineLint('if (foo<bar->baz) {', 'Missing spaces around <'
                      '  [whitespace/operators] [3]')
        self.TestSingleLineLint('if (foo<bar->bar) {', 'Missing spaces around <'
                      '  [whitespace/operators] [3]')
        self.TestSingleLineLint('template<typename T = double>', '')
        self.TestSingleLineLint('std::unique_ptr<No<Spaces>>', '')
        self.TestSingleLineLint('typedef hash_map<Foo, Bar>', '')
        self.TestSingleLineLint('10<<20', '')
        self.TestSingleLineLint('10<<a',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestSingleLineLint('a<<20',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestSingleLineLint('a<<b',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestSingleLineLint('10LL<<20', '')
        self.TestSingleLineLint('10ULL<<20', '')
        self.TestSingleLineLint('a>>b',
                      'Missing spaces around >>  [whitespace/operators] [3]')
        self.TestSingleLineLint('10>>b',
                      'Missing spaces around >>  [whitespace/operators] [3]')
        self.TestSingleLineLint('LOG(ERROR)<<*foo',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestSingleLineLint('LOG(ERROR)<<&foo',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestSingleLineLint('StringCoder<vector<string>>::ToString()', '')
        self.TestSingleLineLint('map<pair<int16, int16>, map<int16, int16>>::iterator', '')
        self.TestSingleLineLint('func<int16, pair<int16, pair<int16, int16>>>()', '')
        self.TestSingleLineLint('MACRO1(list<list<int16>>)', '')
        self.TestSingleLineLint('MACRO2(list<list<int16>>, 42)', '')
        self.TestSingleLineLint('void DoFoo(const set<vector<string>>& arg1);', '')
        self.TestSingleLineLint('void SetFoo(set<vector<string>>* arg1);', '')
        self.TestSingleLineLint('foo = new set<vector<string>>;', '')
        self.TestSingleLineLint('reinterpret_cast<set<vector<string>>*>(a);', '')
        self.TestSingleLineLint('MACRO(<<)', '')
        self.TestSingleLineLint('MACRO(<<, arg)', '')
        self.TestSingleLineLint('MACRO(<<=)', '')
        self.TestSingleLineLint('MACRO(<<=, arg)', '')

        self.TestSingleLineLint('using Vector3<T>::operator==;', '')
        self.TestSingleLineLint('using Vector3<T>::operator!=;', '')

    def testSpacingBeforeLastSemicolon(self):
        self.TestSingleLineLint('call_function() ;',
                      'Extra space before last semicolon. If this should be an '
                      'empty statement, use {} instead.'
                      '  [whitespace/semicolon] [5]')
        self.TestSingleLineLint('while (true) ;',
                      'Extra space before last semicolon. If this should be an '
                      'empty statement, use {} instead.'
                      '  [whitespace/semicolon] [5]')
        self.TestSingleLineLint('default:;',
                      'Semicolon defining empty statement. Use {} instead.'
                      '  [whitespace/semicolon] [5]')
        self.TestSingleLineLint('      ;',
                      'Line contains only semicolon. If this should be an empty '
                      'statement, use {} instead.'
                      '  [whitespace/semicolon] [5]')
        self.TestSingleLineLint('for (int i = 0; ;', '')

    def testEmptyBlockBody(self, state):
        self.TestSingleLineLint('while (true);',
                      'Empty loop bodies should use {} or continue'
                      '  [whitespace/empty_loop_body] [5]')
        self.TestSingleLineLint('if (true);',
                      'Empty conditional bodies should use {}'
                      '  [whitespace/empty_conditional_body] [5]')
        self.TestSingleLineLint('while (true)', '')
        self.TestSingleLineLint('while (true) continue;', '')
        self.TestSingleLineLint('for (;;);',
                      'Empty loop bodies should use {} or continue'
                      '  [whitespace/empty_loop_body] [5]')
        self.TestSingleLineLint('for (;;)', '')
        self.TestSingleLineLint('for (;;) continue;', '')
        self.TestSingleLineLint('for (;;) func();', '')
        self.TestSingleLineLint('if (test) {}',
                      'If statement had no body and no else clause'
                      '  [whitespace/empty_if_body] [4]')
        self.TestSingleLineLint('if (test) func();', '')
        self.TestSingleLineLint('if (test) {} else {}', '')
        self.TestMultiLineLint(state, """while (true &&
                                     false);""",
                               'Empty loop bodies should use {} or continue'
                               '  [whitespace/empty_loop_body] [5]')
        self.TestMultiLineLint(state, """do {
                           } while (false);""",
                               '')
        self.TestMultiLineLint(state, """#define MACRO \\
                           do { \\
                           } while (false);""",
                               '')
        self.TestMultiLineLint(state, """do {
                           } while (false);  // next line gets a warning
                           while (false);""",
                               'Empty loop bodies should use {} or continue'
                               '  [whitespace/empty_loop_body] [5]')
        self.TestMultiLineLint(state, """if (test) {
                           }""",
                               'If statement had no body and no else clause'
                               '  [whitespace/empty_if_body] [4]')
        self.TestMultiLineLint(state, """if (test,
                               func({})) {
                           }""",
                               'If statement had no body and no else clause'
                               '  [whitespace/empty_if_body] [4]')
        self.TestMultiLineLint(state, """if (test)
                             func();""", '')
        self.TestSingleLineLint('if (test) { hello; }', '')
        self.TestSingleLineLint('if (test({})) { hello; }', '')
        self.TestMultiLineLint(state, """if (test) {
                             func();
                           }""", '')
        self.TestMultiLineLint(state, """if (test) {
                             // multiline
                             // comment
                           }""", '')
        self.TestMultiLineLint(state, """if (test) {  // comment
                           }""", '')
        self.TestMultiLineLint(state, """if (test) {
                           } else {
                           }""", '')
        self.TestMultiLineLint(state, """if (func(p1,
                               p2,
                               p3)) {
                             func();
                           }""", '')
        self.TestMultiLineLint(state, """if (func({}, p1)) {
                             func();
                           }""", '')

    def testSpacingForRangeBasedFor(self):
        # Basic correctly formatted case:
        self.TestSingleLineLint('for (int i : numbers) {', '')

        # Missing space before colon:
        self.TestSingleLineLint('for (int i: numbers) {',
                      'Missing space around colon in range-based for loop'
                      '  [whitespace/forcolon] [2]')
        # Missing space after colon:
        self.TestSingleLineLint('for (int i :numbers) {',
                      'Missing space around colon in range-based for loop'
                      '  [whitespace/forcolon] [2]')
        # Missing spaces both before and after the colon.
        self.TestSingleLineLint('for (int i:numbers) {',
                      'Missing space around colon in range-based for loop'
                      '  [whitespace/forcolon] [2]')

        # The scope operator '::' shouldn't cause warnings...
        self.TestSingleLineLint('for (std::size_t i : sizes) {}', '')
        # ...but it shouldn't suppress them either.
        self.TestSingleLineLint('for (std::size_t i: sizes) {}',
                      'Missing space around colon in range-based for loop'
                      '  [whitespace/forcolon] [2]')

    # Static or global STL strings.
    def testStaticOrGlobalSTLStrings(self, state):
        # A template for the error message for a const global/static string.
        error_msg = ('For a static/global string constant, use a C style '
                     'string instead: "%s[]".  [runtime/string] [4]')
        # The error message for a non-const global/static string variable.
        nonconst_error_msg = ('Static/global string variables are not permitted.'
                              '  [runtime/string] [4]')

        self.TestSingleLineLint('string foo;',
                      nonconst_error_msg)
        self.TestSingleLineLint('string kFoo = "hello";  // English',
                      nonconst_error_msg)
        self.TestSingleLineLint('static string foo;',
                      nonconst_error_msg)
        self.TestSingleLineLint('static const string foo;',
                      error_msg % 'static const char foo')
        self.TestSingleLineLint('static const std::string foo;',
                      error_msg % 'static const char foo')
        self.TestSingleLineLint('string Foo::bar;',
                      nonconst_error_msg)

        self.TestSingleLineLint('std::string foo;',
                      nonconst_error_msg)
        self.TestSingleLineLint('std::string kFoo = "hello";  // English',
                      nonconst_error_msg)
        self.TestSingleLineLint('static std::string foo;',
                      nonconst_error_msg)
        self.TestSingleLineLint('static const std::string foo;',
                      error_msg % 'static const char foo')
        self.TestSingleLineLint('std::string Foo::bar;',
                      nonconst_error_msg)

        self.TestSingleLineLint('::std::string foo;',
                      nonconst_error_msg)
        self.TestSingleLineLint('::std::string kFoo = "hello";  // English',
                      nonconst_error_msg)
        self.TestSingleLineLint('static ::std::string foo;',
                      nonconst_error_msg)
        self.TestSingleLineLint('static const ::std::string foo;',
                      error_msg % 'static const char foo')
        self.TestSingleLineLint('::std::string Foo::bar;',
                      nonconst_error_msg)

        self.TestSingleLineLint('string* pointer', '')
        self.TestSingleLineLint('string *pointer', '')
        self.TestSingleLineLint('string* pointer = Func();', '')
        self.TestSingleLineLint('string *pointer = Func();', '')
        self.TestSingleLineLint('const string* pointer', '')
        self.TestSingleLineLint('const string *pointer', '')
        self.TestSingleLineLint('const string* pointer = Func();', '')
        self.TestSingleLineLint('const string *pointer = Func();', '')
        self.TestSingleLineLint('string const* pointer', '')
        self.TestSingleLineLint('string const *pointer', '')
        self.TestSingleLineLint('string const* pointer = Func();', '')
        self.TestSingleLineLint('string const *pointer = Func();', '')
        self.TestSingleLineLint('string* const pointer', '')
        self.TestSingleLineLint('string *const pointer', '')
        self.TestSingleLineLint('string* const pointer = Func();', '')
        self.TestSingleLineLint('string *const pointer = Func();', '')
        self.TestSingleLineLint('string Foo::bar() {}', '')
        self.TestSingleLineLint('string Foo::operator*() {}', '')
        # Rare case.
        self.TestSingleLineLint('string foo("foobar");', nonconst_error_msg)
        # Should not catch local or member variables.
        self.TestSingleLineLint('  string foo', '')
        # Should not catch functions.
        self.TestSingleLineLint('string EmptyString() { return ""; }', '')
        self.TestSingleLineLint('string EmptyString () { return ""; }', '')
        self.TestSingleLineLint('string const& FileInfo::Pathname() const;', '')
        self.TestSingleLineLint('string const &FileInfo::Pathname() const;', '')
        self.TestSingleLineLint('string VeryLongNameFunctionSometimesEndsWith(\n'
                      '    VeryLongNameType very_long_name_variable) {}', '')
        self.TestSingleLineLint('template<>\n'
                      'string FunctionTemplateSpecialization<SomeType>(\n'
                      '      int x) { return ""; }', '')
        self.TestSingleLineLint('template<>\n'
                      'string FunctionTemplateSpecialization<vector<A::B>* >(\n'
                      '      int x) { return ""; }', '')

        # should not catch methods of template classes.
        self.TestSingleLineLint('string Class<Type>::Method() const {\n'
                      '  return "";\n'
                      '}\n', '')
        self.TestSingleLineLint('string Class<Type>::Method(\n'
                      '   int arg) const {\n'
                      '  return "";\n'
                      '}\n', '')

        # Check multiline cases.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['// Copyright 2014 Your Company.',
                                 'string Class',
                                 '::MemberFunction1();',
                                 'string Class::',
                                 'MemberFunction2();',
                                 'string Class::',
                                 'NestedClass::MemberFunction3();',
                                 'string TemplateClass<T>::',
                                 'NestedClass::MemberFunction4();',
                                 'const string Class',
                                 '::static_member_variable1;',
                                 'const string Class::',
                                 'static_member_variable2;',
                                 'const string Class',
                                 '::static_member_variable3 = "initial value";',
                                 'const string Class::',
                                 'static_member_variable4 = "initial value";',
                                 'string Class::',
                                 'static_member_variable5;',
                                 ''],
                                error_collector)
        assert error_collector.Results() == \
                          [error_msg % 'const char Class::static_member_variable1',
                           error_msg % 'const char Class::static_member_variable2',
                           error_msg % 'const char Class::static_member_variable3',
                           error_msg % 'const char Class::static_member_variable4',
                           nonconst_error_msg]

    def testNoSpacesInFunctionCalls(self, state):
        self.TestSingleLineLint('TellStory(1, 3);',
                      '')
        self.TestSingleLineLint('TellStory(1, 3 );',
                      'Extra space before )'
                      '  [whitespace/parens] [2]')
        self.TestSingleLineLint('TellStory(1 /* wolf */, 3 /* pigs */);',
                      '')
        self.TestMultiLineLint(state, """TellStory(1, 3
                                        );""",
                               'Closing ) should be moved to the previous line'
                               '  [whitespace/parens] [2]')
        self.TestMultiLineLint(state, """TellStory(Wolves(1),
                                        Pigs(3
                                        ));""",
                               'Closing ) should be moved to the previous line'
                               '  [whitespace/parens] [2]')
        self.TestMultiLineLint(state, """TellStory(1,
                                        3 );""",
                               'Extra space before )'
                               '  [whitespace/parens] [2]')

    def testToDoComments(self):
        start_space = ('Too many spaces before TODO'
                       '  [whitespace/todo] [2]')
        missing_username = ('Missing username in TODO; it should look like '
                            '"// TODO(my_username): Stuff."'
                            '  [readability/todo] [2]')
        end_space = ('TODO(my_username) should be followed by a space'
                     '  [whitespace/todo] [2]')

        self.TestSingleLineLint('//   TODOfix this',
                      [start_space, missing_username, end_space])
        self.TestSingleLineLint('//   TODO(ljenkins)fix this',
                      [start_space, end_space])
        self.TestSingleLineLint('//   TODO fix this',
                      [start_space, missing_username])
        self.TestSingleLineLint('// TODO fix this', missing_username)
        self.TestSingleLineLint('// TODO: fix this', missing_username)
        self.TestSingleLineLint('//TODO(ljenkins): Fix this',
                      'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestSingleLineLint('// TODO(ljenkins):Fix this', end_space)
        self.TestSingleLineLint('// TODO(ljenkins):', '')
        self.TestSingleLineLint('// TODO(ljenkins): fix this', '')
        self.TestSingleLineLint('// TODO(ljenkins): Fix this', '')
        self.TestSingleLineLint('#if 1  // TEST_URLTODOCID_WHICH_HAS_THAT_WORD_IN_IT_H_', '')
        self.TestSingleLineLint('// See also similar TODO above', '')
        self.TestSingleLineLint(r'EXPECT_EQ("\\", '
                      r'NormalizePath("/./../foo///bar/..//x/../..", ""));',
                      '')

    def testTwoSpacesBetweenCodeAndComments(self, state):
        self.TestSingleLineLint('} // namespace foo',
                      'At least two spaces is best between code and comments'
                      '  [whitespace/comments] [2]')
        self.TestSingleLineLint('}// namespace foo',
                      'At least two spaces is best between code and comments'
                      '  [whitespace/comments] [2]')
        self.TestSingleLineLint('printf("foo"); // Outside quotes.',
                      'At least two spaces is best between code and comments'
                      '  [whitespace/comments] [2]')
        self.TestSingleLineLint('int i = 0;  // Having two spaces is fine.', '')
        self.TestSingleLineLint('int i = 0;   // Having three spaces is OK.', '')
        self.TestSingleLineLint('// Top level comment', '')
        self.TestSingleLineLint('  // Line starts with two spaces.', '')
        self.TestMultiLineLint(state, 'void foo() {\n'
                               '  { // A scope is opening.\n'
                               '    int a;', '')
        self.TestMultiLineLint(state, 'void foo() {\n'
                               '  { // A scope is opening.\n'
                               '#define A a',
                               'At least two spaces is best between code and '
                               'comments  [whitespace/comments] [2]')
        self.TestMultiLineLint(state, '  foo();\n'
                               '  { // An indented scope is opening.\n'
                               '    int a;', '')
        self.TestMultiLineLint(state, 'vector<int> my_elements = {// first\n'
                               '                           1,', '')
        self.TestMultiLineLint(state, 'vector<int> my_elements = {// my_elements is ..\n'
                               '    1,',
                               'At least two spaces is best between code and '
                               'comments  [whitespace/comments] [2]')
        self.TestSingleLineLint('if (foo) { // not a pure scope; comment is too close!',
                      'At least two spaces is best between code and comments'
                      '  [whitespace/comments] [2]')
        self.TestSingleLineLint('printf("// In quotes.")', '')
        self.TestSingleLineLint('printf("\\"%s // In quotes.")', '')
        self.TestSingleLineLint('printf("%s", "// In quotes.")', '')

    def testSpaceAfterCommentMarker(self):
        self.TestSingleLineLint('//', '')
        self.TestSingleLineLint('//x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestSingleLineLint('// x', '')
        self.TestSingleLineLint('///', '')
        self.TestSingleLineLint('/// x', '')
        self.TestSingleLineLint('//!', '')
        self.TestSingleLineLint('//----', '')
        self.TestSingleLineLint('//====', '')
        self.TestSingleLineLint('//////', '')
        self.TestSingleLineLint('////// x', '')
        self.TestSingleLineLint('///< x', '')  # After-member Doxygen comment
        self.TestSingleLineLint('//!< x', '')  # After-member Doxygen comment
        self.TestSingleLineLint('////x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestSingleLineLint('//}', '')
        self.TestSingleLineLint('//}x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestSingleLineLint('//!<x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestSingleLineLint('///<x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')

    # Test a line preceded by empty or comment lines.  There was a bug
    # that caused it to print the same warning N times if the erroneous
    # line was preceded by N lines of empty or comment lines.  To be
    # precise, the '// marker so line numbers and indices both start at
    # 1' line was also causing the issue.
    def testLinePrecededByEmptyOrCommentLines(self, state):
        def DoTest(self, lines):
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, 'foo.cc', 'cc', lines, error_collector)
            # The warning appears only once.
            assert 1 == error_collector.Results().count(
                    'Do not use namespace using-directives.  '
                    'Use using-declarations instead.'
                    '  [build/namespaces] [5]')
        DoTest(self, ['using namespace foo;'])
        DoTest(self, ['', '', '', 'using namespace foo;'])
        DoTest(self, ['// hello', 'using namespace foo;'])

    def testUsingLiteralsNamespaces(self):
        self.TestSingleLineLint('using namespace std::literals;', 'Do not use namespace'
            ' using-directives.  Use using-declarations instead.'
            '  [build/namespaces_literals] [5]')
        self.TestSingleLineLint('using namespace std::literals::chrono_literals;', 'Do'
            ' not use namespace using-directives.  Use using-declarations instead.'
            '  [build/namespaces_literals] [5]')

    def testNewlineAtEOF(self, state):
        def DoTest(self, data, is_missing_eof):
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, 'foo.cc', 'cc', data.split('\n'),
                                    error_collector)
            # The warning appears only once.
            assert  int(is_missing_eof) == error_collector.Results().count( 'Could not find a newline character at the end of the file.  [whitespace/ending_newline] [5]')

        DoTest(self, '// Newline\n// at EOF\n', False)
        DoTest(self, '// No newline\n// at EOF', True)

    def testInvalidUtf8(self, state):
        def DoTest(self, raw_bytes, has_invalid_utf8):
            error_collector = ErrorCollector()
            if sys.version_info < (3,):
                unidata = unicode(raw_bytes, 'utf8', 'replace').split('\n')
            else:
                unidata = str(raw_bytes, 'utf8', 'replace').split('\n')
            cpplint.ProcessFileData(
                state,
                'foo.cc', 'cc',
                unidata,
                error_collector)
            # The warning appears only once.
            assert  int(has_invalid_utf8) == error_collector.Results().count( 'Line contains invalid UTF-8 (or Unicode replacement character).  [readability/utf8] [5]')

        DoTest(self, codecs.latin_1_encode('Hello world\n')[0], False)
        DoTest(self, codecs.latin_1_encode('\xe9\x8e\xbd\n')[0], False)
        DoTest(self, codecs.latin_1_encode('\xe9x\x8e\xbd\n')[0], True)
        # This is the encoding of the replacement character itself (which
        # you can see by evaluating codecs.getencoder('utf8')(u'\ufffd')).
        DoTest(self, codecs.latin_1_encode('\xef\xbf\xbd\n')[0], True)

    def testBadCharacters(self, state):
        # Test for NUL bytes only
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'nul.cc', 'cc',
                                ['// Copyright 2014 Your Company.',
                                 '\0', ''], error_collector)
        assert  error_collector.Results() == 'Line contains NUL byte.  [readability/nul] [5]'

        # Make sure both NUL bytes and UTF-8 are caught if they appear on
        # the same line.
        error_collector = ErrorCollector()
        raw_bytes = codecs.latin_1_encode('\xe9x\0')[0]
        if sys.version_info < (3,):
            unidata = unicode(raw_bytes, 'utf8', 'replace')
        else:
            unidata = str(raw_bytes, 'utf8', 'replace')
        cpplint.ProcessFileData(
            state,
            'nul_utf8.cc', 'cc',
            ['// Copyright 2014 Your Company.',
             unidata,
             ''],
            error_collector)
        assert  error_collector.Results() == \
            ['Line contains invalid UTF-8 (or Unicode replacement character).'
             '  [readability/utf8] [5]',
             'Line contains NUL byte.  [readability/nul] [5]']

    def testIsBlankLine(self):
        assert IsBlankLine('')
        assert IsBlankLine(' ')
        assert IsBlankLine(' \t\r\n')
        assert not IsBlankLine('int a;')
        assert not IsBlankLine('{')

    def testBlankLinesCheck(self):
        self.TestBlankLinesCheck(['{\n', '\n', '\n', '}\n'], 1, 1)
        self.TestBlankLinesCheck(['  if (foo) {\n', '\n', '  }\n'], 1, 1)
        self.TestBlankLinesCheck(
            ['\n', '// {\n', '\n', '\n', '// Comment\n', '{\n', '}\n'], 0, 0)
        self.TestBlankLinesCheck(['\n', 'run("{");\n', '\n'], 0, 0)
        self.TestBlankLinesCheck(['\n', '  if (foo) { return 0; }\n', '\n'], 0, 0)
        self.TestBlankLinesCheck(
            ['int x(\n', '    int a) {\n', '\n', 'return 0;\n', '}'], 0, 0)
        self.TestBlankLinesCheck(
            ['int x(\n', '    int a) const {\n', '\n', 'return 0;\n', '}'], 0, 0)
        self.TestBlankLinesCheck(
            ['int x(\n', '     int a) {\n', '\n', 'return 0;\n', '}'], 1, 0)
        self.TestBlankLinesCheck(
            ['int x(\n', '   int a) {\n', '\n', 'return 0;\n', '}'], 1, 0)

    def testAllowBlankLineBeforeClosingNamespace(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['namespace {',
                                 '',
                                 '}  // namespace',
                                 'namespace another_namespace {',
                                 '',
                                 '}',
                                 'namespace {',
                                 '',
                                 'template<class T, ',
                                 '         class A = hoge<T>, ',
                                 '         class B = piyo<T>, ',
                                 '         class C = fuga<T> >',
                                 'class D {',
                                 ' public:',
                                 '};',
                                 '', '', '', '',
                                 '}'],
                                error_collector)
        assert 0 == error_collector.Results().count( 'Redundant blank line at the end of a code block should be deleted.  [whitespace/blank_line] [3]')

    def testAllowBlankLineBeforeIfElseChain(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['if (hoge) {',
                                 '',  # No warning
                                 '} else if (piyo) {',
                                 '',  # No warning
                                 '} else if (piyopiyo) {',
                                 '  hoge = true;',  # No warning
                                 '} else {',
                                 '',  # Warning on this line
                                 '}'],
                                error_collector)
        assert 1 == error_collector.Results().count( 'Redundant blank line at the end of a code block should be deleted.  [whitespace/blank_line] [3]')

    def testAllowBlankLineAfterExtern(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['extern "C" {',
                                 '',
                                 'EXPORTAPI void APICALL Some_function() {}',
                                 '',
                                 '}'],
                                error_collector)
        assert 0 == error_collector.Results().count(
            'Redundant blank line at the start of a code block should be deleted.'
            '  [whitespace/blank_line] [2]')
        assert 0 == error_collector.Results().count(
            'Redundant blank line at the end of a code block should be deleted.'
            '  [whitespace/blank_line] [3]')

    def testBlankLineBeforeSectionKeyword(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['class A {',
                                 ' public:',
                                 ' protected:',   # warning 1
                                 ' private:',     # warning 2
                                 '  struct B {',
                                 '   public:',
                                 '   private:'] +  # warning 3
                                ([''] * 100) +  # Make A and B longer than 100 lines
                                ['  };',
                                 '  struct C {',
                                 '   protected:',
                                 '   private:',  # C is too short for warnings
                                 '  };',
                                 '};',
                                 'class D',
                                 '    : public {',
                                 ' public:',  # no warning
                                 '};',
                                 'class E {\\',
                                 ' public:\\'] +
                                (['\\'] * 100) +  # Makes E > 100 lines
                                ['  int non_empty_line;\\',
                                 ' private:\\',   # no warning
                                 '  int a;\\',
                                 '};'],
                                error_collector)
        assert 2 == error_collector.Results().count( '"private:" should be preceded by a blank line  [whitespace/blank_line] [3]')
        assert 1 == error_collector.Results().count( '"protected:" should be preceded by a blank line  [whitespace/blank_line] [3]')

    def testNoBlankLineAfterSectionKeyword(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['class A {',
                                 ' public:',
                                 '',  # warning 1
                                 ' private:',
                                 '',  # warning 2
                                 '  struct B {',
                                 '   protected:',
                                 '',  # warning 3
                                 '  };',
                                 '};'],
                                error_collector)
        assert 1 == error_collector.Results().count( 'Do not leave a blank line after "public:"  [whitespace/blank_line] [3]')
        assert 1 == error_collector.Results().count( 'Do not leave a blank line after "protected:"  [whitespace/blank_line] [3]')
        assert 1 == error_collector.Results().count( 'Do not leave a blank line after "private:"  [whitespace/blank_line] [3]')

    def testAllowBlankLinesInRawStrings(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['// Copyright 2014 Your Company.',
                                 'static const char *kData[] = {R"(',
                                 '',
                                 ')", R"(',
                                 '',
                                 ')"};',
                                 ''],
                                error_collector)
        assert '' == error_collector.Results()

    def testElseOnSameLineAsClosingBraces(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['if (hoge) {',
                                 '}',
                                 'else if (piyo) {',  # Warning on this line
                                 '}',
                                 ' else {'  # Warning on this line
                                 '',
                                 '}'],
                                error_collector)
        assert 2 == error_collector.Results().count('An else should appear on the same line as the preceding }  [whitespace/newline] [4]')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['if (hoge) {',
                                 '',
                                 '}',
                                 'else',  # Warning on this line
                                 '{',
                                 '',
                                 '}'],
                                error_collector)
        assert 1 == error_collector.Results().count('An else should appear on the same line as the preceding }  [whitespace/newline] [4]')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['if (hoge) {',
                                 '',
                                 '}',
                                 'else_function();'],
                                error_collector)
        assert 0 == error_collector.Results().count('An else should appear on the same line as the preceding }  [whitespace/newline] [4]')

    def testMultipleStatementsOnSameLine(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['for (int i = 0; i < 1; i++) {}',
                                 'switch (x) {',
                                 '  case 0: func(); break; ',
                                 '}',
                                 'sum += MathUtil::SafeIntRound(x); x += 0.1;'],
                                error_collector)
        assert 0 == error_collector.Results().count('More than one command on the same line  [whitespace/newline] [0]')

        state.verbose_level = 0
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['sum += MathUtil::SafeIntRound(x); x += 0.1;'],
                                error_collector)

    def testLambdasOnSameLine(self, state):
        error_collector = ErrorCollector()
        state.verbose_level = 0
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['const auto lambda = '
                                  '[](const int i) { return i; };'],
                                error_collector)
        assert 0 == error_collector.Results().count( 'More than one command on the same line  [whitespace/newline] [0]')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['const auto result = std::any_of(vector.begin(), '
                                  'vector.end(), '
                                  '[](const int i) { return i > 0; });'],
                                error_collector)
        assert 0 == error_collector.Results().count( 'More than one command on the same line  [whitespace/newline] [0]')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['return mutex::Lock<void>([this]() { '
                                  'this->ReadLock(); }, [this]() { '
                                  'this->ReadUnlock(); });'],
                                error_collector)
        assert 0 == error_collector.Results().count( 'More than one command on the same line  [whitespace/newline] [0]')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['return mutex::Lock<void>([this]() { '
                                  'this->ReadLock(); }, [this]() { '
                                  'this->ReadUnlock(); }, object);'],
                                error_collector)
        assert 0 == error_collector.Results().count( 'More than one command on the same line  [whitespace/newline] [0]')

    def testEndOfNamespaceComments(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'foo.cc', 'cc',
                                ['namespace {',
                                 '',
                                 '}',  # No warning (too short)
                                 'namespace expected {',
                                 '}  // namespace mismatched',  # Warning here
                                 'namespace {',
                                 '}  // namespace mismatched',  # Warning here
                                 'namespace outer { namespace nested {'] +
                                ([''] * 10) +
                                ['}',  # Warning here
                                 '}',  # Warning here
                                 'namespace {'] +
                                ([''] * 10) +
                                ['}',  # Warning here
                                 'namespace {'] +
                                ([''] * 10) +
                                ['}  // namespace some description',  # Anon warning
                                 'namespace {'] +
                                ([''] * 10) +
                                ['}  // namespace anonymous',  # Variant warning
                                 'namespace {'] +
                                ([''] * 10) +
                                ['}  // anonymous namespace (utils)',  # Variant
                                 'namespace {'] +
                                ([''] * 10) +
                                ['}  // anonymous namespace',  # No warning
                                 'namespace missing_comment {'] +
                                ([''] * 10) +
                                ['}',  # Warning here
                                 'namespace no_warning {'] +
                                ([''] * 10) +
                                ['}  // namespace no_warning',
                                 'namespace no_warning {'] +
                                ([''] * 10) +
                                ['};  // end namespace no_warning',
                                 '#define MACRO \\',
                                 'namespace c_style { \\'] +
                                (['\\'] * 10) +
                                ['}  /* namespace c_style. */ \\',
                                 ';'],
                                error_collector)
        assert 1 == error_collector.Results().count(
            'Namespace should be terminated with "// namespace expected"'
            '  [readability/namespace] [5]')
        assert 1 == error_collector.Results().count(
            'Namespace should be terminated with "// namespace outer"'
            '  [readability/namespace] [5]')
        assert 1 == error_collector.Results().count(
            'Namespace should be terminated with "// namespace nested"'
            '  [readability/namespace] [5]')
        assert 3 == error_collector.Results().count(
            'Anonymous namespace should be terminated with "// namespace"'
            '  [readability/namespace] [5]')
        assert 2 == error_collector.Results().count(
            'Anonymous namespace should be terminated with "// namespace" or'
            ' "// anonymous namespace"'
            '  [readability/namespace] [5]')
        assert 1 == error_collector.Results().count(
            'Namespace should be terminated with "// namespace missing_comment"'
            '  [readability/namespace] [5]')
        assert 0 == error_collector.Results().count(
            'Namespace should be terminated with "// namespace no_warning"'
            '  [readability/namespace] [5]')

    def testElseClauseNotOnSameLineAsElse(self):
        self.TestSingleLineLint('  else DoSomethingElse();',
                      'Else clause should never be on same line as else '
                      '(use 2 lines)  [whitespace/newline] [4]')
        self.TestSingleLineLint('  else ifDoSomethingElse();',
                      'Else clause should never be on same line as else '
                      '(use 2 lines)  [whitespace/newline] [4]')
        self.TestSingleLineLint('  } else if (blah) {', '')
        self.TestSingleLineLint('  variable_ends_in_else = true;', '')

    def testComma(self):
        self.TestSingleLineLint('a = f(1,2);',
                      'Missing space after ,  [whitespace/comma] [3]')
        self.TestSingleLineLint('int tmp=a,a=b,b=tmp;',
                      ['Missing spaces around =  [whitespace/operators] [4]',
                       'Missing space after ,  [whitespace/comma] [3]'])
        self.TestSingleLineLint('f(a, /* name */ b);', '')
        self.TestSingleLineLint('f(a, /* name */b);', '')
        self.TestSingleLineLint('f(a, /* name */-1);', '')
        self.TestSingleLineLint('f(a, /* name */"1");', '')
        self.TestSingleLineLint('f(1, /* empty macro arg */, 2)', '')
        self.TestSingleLineLint('f(1,, 2)', '')
        self.TestSingleLineLint('operator,()', '')
        self.TestSingleLineLint('operator,(a,b)',
                      'Missing space after ,  [whitespace/comma] [3]')

    def testEqualsOperatorSpacing(self, state):
        self.TestSingleLineLint('int tmp= a;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestSingleLineLint('int tmp =a;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestSingleLineLint('int tmp=a;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestSingleLineLint('int tmp= 7;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestSingleLineLint('int tmp =7;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestSingleLineLint('int tmp=7;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestSingleLineLint('int* tmp=*p;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestSingleLineLint('int* tmp= *p;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestMultiLineLint(state,
            self.TrimExtraIndent('''
            lookahead_services_=
              ::strings::Split(FLAGS_ls, ",", ::strings::SkipEmpty());'''),
            'Missing spaces around =  [whitespace/operators] [4]')
        self.TestSingleLineLint('bool result = a>=42;',
                      'Missing spaces around >=  [whitespace/operators] [3]')
        self.TestSingleLineLint('bool result = a<=42;',
                      'Missing spaces around <=  [whitespace/operators] [3]')
        self.TestSingleLineLint('bool result = a==42;',
                      'Missing spaces around ==  [whitespace/operators] [3]')
        self.TestSingleLineLint('auto result = a!=42;',
                      'Missing spaces around !=  [whitespace/operators] [3]')
        self.TestSingleLineLint('int a = b!=c;',
                      'Missing spaces around !=  [whitespace/operators] [3]')
        self.TestSingleLineLint('a&=42;', '')
        self.TestSingleLineLint('a|=42;', '')
        self.TestSingleLineLint('a^=42;', '')
        self.TestSingleLineLint('a+=42;', '')
        self.TestSingleLineLint('a*=42;', '')
        self.TestSingleLineLint('a/=42;', '')
        self.TestSingleLineLint('a%=42;', '')
        self.TestSingleLineLint('a>>=5;', '')
        self.TestSingleLineLint('a<<=5;', '')

    def testShiftOperatorSpacing(self):
        self.TestSingleLineLint('a<<b',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestSingleLineLint('a>>b',
                      'Missing spaces around >>  [whitespace/operators] [3]')
        self.TestSingleLineLint('1<<20', '')
        self.TestSingleLineLint('1024>>10', '')
        self.TestSingleLineLint('Kernel<<<1, 2>>>()', '')

    def testIndent(self, state):
        self.TestSingleLineLint('static int noindent;', '')
        self.TestSingleLineLint('  int two_space_indent;', '')
        self.TestSingleLineLint('    int four_space_indent;', '')
        self.TestSingleLineLint(' int one_space_indent;',
                      'Weird number of spaces at line-start.  '
                      'Are you using a 2-space indent?  [whitespace/indent] [3]')
        self.TestSingleLineLint('   int three_space_indent;',
                      'Weird number of spaces at line-start.  '
                      'Are you using a 2-space indent?  [whitespace/indent] [3]')
        self.TestSingleLineLint(' char* one_space_indent = "public:";',
                      'Weird number of spaces at line-start.  '
                      'Are you using a 2-space indent?  [whitespace/indent] [3]')
        self.TestSingleLineLint(' public:', '')
        self.TestSingleLineLint('  protected:', '')
        self.TestSingleLineLint('   private:', '')
        self.TestSingleLineLint(' protected: \\', '')
        self.TestSingleLineLint('  public:      \\', '')
        self.TestSingleLineLint('   private:   \\', '')
        # examples using QT signals/slots macro
        self.TestMultiLineLint(state,
            self.TrimExtraIndent("""
            class foo {
             public slots:
              void bar();
             signals:
            };"""),
            '')
        self.TestMultiLineLint(state,
            self.TrimExtraIndent("""
            class foo {
              public slots:
              void bar();
            };"""),
            'public slots: should be indented +1 space inside class foo'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(state,
            self.TrimExtraIndent("""
            class foo {
              signals:
              void bar();
            };"""),
            'signals: should be indented +1 space inside class foo'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(state,
            self.TrimExtraIndent('''
            static const char kRawString[] = R"("
             ")";'''),
            '')
        self.TestMultiLineLint(state,
            self.TrimExtraIndent('''
            KV<Query,
               Tuple<TaxonomyId, PetacatCategoryId, double>>'''),
            '')
        self.TestMultiLineLint(state,
            ' static const char kSingleLineRawString[] = R"(...)";',
            'Weird number of spaces at line-start.  '
            'Are you using a 2-space indent?  [whitespace/indent] [3]')

    def testSectionIndent(self, state):
        self.TestMultiLineLint(state,
            """
        class A {
         public:  // no warning
          private:  // warning here
        };""",
            'private: should be indented +1 space inside class A'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(state,
            """
        class B {
         public:  // no warning
          template<> struct C {
            public:    // warning here
           protected:  // no warning
          };
        };""",
            'public: should be indented +1 space inside struct C'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(state,
            """
        struct D {
         };""",
            'Closing brace should be aligned with beginning of struct D'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(state,
            """
         template<typename E> class F {
        };""",
            'Closing brace should be aligned with beginning of class F'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(state,
            """
        class G {
          Q_OBJECT
        public slots:
        signals:
        };""",
            ['public slots: should be indented +1 space inside class G'
             '  [whitespace/indent] [3]',
             'signals: should be indented +1 space inside class G'
             '  [whitespace/indent] [3]'])
        self.TestMultiLineLint(state,
            """
        class H {
          /* comments */ class I {
           public:  // no warning
            private:  // warning here
          };
        };""",
            'private: should be indented +1 space inside class I'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(state,
            """
        class J
            : public ::K {
         public:  // no warning
          protected:  // warning here
        };""",
            'protected: should be indented +1 space inside class J'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(state,
            """
        class L
            : public M,
              public ::N {
        };""",
            '')
        self.TestMultiLineLint(state,
            """
        template <class O,
                  class P,
                  class Q,
                  typename R>
        static void Func() {
        }""",
            '')

    def testConditionals(self, state):
        self.TestMultiLineLint(state,
            """
        if (foo)
          goto fail;
          goto fail;""",
            'If/else bodies with multiple statements require braces'
            '  [readability/braces] [4]')
        self.TestMultiLineLint(state,
            """
        if (foo)
          goto fail; goto fail;""",
            'If/else bodies with multiple statements require braces'
            '  [readability/braces] [4]')
        self.TestMultiLineLint(state,
            """
        if (foo)
          foo;
        else
          goto fail;
          goto fail;""",
            'If/else bodies with multiple statements require braces'
            '  [readability/braces] [4]')
        self.TestMultiLineLint(state,
            """
        if (foo) goto fail;
          goto fail;""",
            'If/else bodies with multiple statements require braces'
            '  [readability/braces] [4]')
        self.TestMultiLineLint(state,
            """
        if constexpr (foo) {
          goto fail;
          goto fail;
        } else if constexpr (bar) {
          hello();
        }""",
            '')
        self.TestMultiLineLint(state,
            """
        if (foo)
          if (bar)
            baz;
          else
            qux;""",
            'Else clause should be indented at the same level as if. Ambiguous'
            ' nested if/else chains require braces.  [readability/braces] [4]')
        self.TestMultiLineLint(state,
            """
        if (foo)
          if (bar)
            baz;
        else
          qux;""",
            'Else clause should be indented at the same level as if. Ambiguous'
            ' nested if/else chains require braces.  [readability/braces] [4]')
        self.TestMultiLineLint(state,
            """
        if (foo) {
          bar;
          baz;
        } else
          qux;""",
            'If an else has a brace on one side, it should have it on both'
            '  [readability/braces] [5]')
        self.TestMultiLineLint(state,
            """
        if (foo)
          bar;
        else {
          baz;
        }""",
            'If an else has a brace on one side, it should have it on both'
            '  [readability/braces] [5]')
        self.TestMultiLineLint(state,
            """
        if (foo)
          bar;
        else if (baz) {
          qux;
        }""",
            'If an else has a brace on one side, it should have it on both'
            '  [readability/braces] [5]')
        self.TestMultiLineLint(state,
            """
        if (foo) {
          bar;
        } else if (baz)
          qux;""",
            'If an else has a brace on one side, it should have it on both'
            '  [readability/braces] [5]')
        self.TestMultiLineLint(state,
            """
        if (foo)
          goto fail;
        bar;""",
            '')
        self.TestMultiLineLint(state,
            """
        if (foo
            && bar) {
          baz;
          qux;
        }""",
            '')
        self.TestMultiLineLint(state,
            """
        if (foo)
          goto
            fail;""",
            '')
        self.TestMultiLineLint(state,
            """
        if (foo)
          bar;
        else
          baz;
        qux;""",
            '')
        self.TestMultiLineLint(state,
            """
        for (;;) {
          if (foo)
            bar;
          else
            baz;
        }""",
            '')
        self.TestMultiLineLint(state,
            """
        if (foo)
          bar;
        else if (baz)
          baz;""",
            '')
        self.TestMultiLineLint(state,
            """
        if (foo)
          bar;
        else
          baz;""",
            '')
        self.TestMultiLineLint(state,
            """
        if (foo) {
          bar;
        } else {
          baz;
        }""",
            '')
        self.TestMultiLineLint(state,
            """
        if (foo) {
          bar;
        } else if (baz) {
          qux;
        }""",
            '')
        # Note: this is an error for a different reason, but should not trigger the
        # single-line if error.
        self.TestMultiLineLint(state,
            """
        if (foo)
        {
          bar;
          baz;
        }""",
            '{ should almost always be at the end of the previous line'
            '  [whitespace/braces] [4]')
        self.TestMultiLineLint(state,
            """
        if (foo) { \\
          bar; \\
          baz; \\
        }""",
            '')
        self.TestMultiLineLint(state,
            """
        void foo() { if (bar) baz; }""",
            '')
        self.TestMultiLineLint(state,
            """
        #if foo
          bar;
        #else
          baz;
          qux;
        #endif""",
            '')
        self.TestMultiLineLint(state,
            """void F() {
          variable = [] { if (true); };
          variable =
              [] { if (true); };
          Call(
              [] { if (true); },
              [] { if (true); });
        }""",
            '')
        self.TestMultiLineLint(state,
            """
        #if(A == 0)
          foo();
        #elif(A == 1)
          bar();
        #endif""",
            '')
        self.TestMultiLineLint(state,
            """
        #if (A == 0)
          foo();
        #elif (A == 1)
          bar();
        #endif""",
            '')

    def testTab(self):
        self.TestSingleLineLint('\tint16 a;',
                      'Tab found; better to use spaces  [whitespace/tab] [1]')
        self.TestSingleLineLint('int16 a = 5;\t\t// set a to 5',
                      'Tab found; better to use spaces  [whitespace/tab] [1]')

    def testParseArguments(self):
        old_output_format = cpplint._cpplint_state.output_format
        old_verbose_level = cpplint._cpplint_state.verbose_level
        old_headers = cpplint._cpplint_state._hpp_headers
        old_filters = cpplint._cpplint_state.filters
        old_line_length = cpplint._cpplint_state._line_length
        old_valid_extensions = cpplint._cpplint_state._valid_extensions
        try:
            # Don't print usage during the tests, or filter categories
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')

            with pytest.raises(SystemExit):
                cli.ParseArguments(cpplint._cpplint_state, [])
            with pytest.raises(SystemExit):
                cli.ParseArguments( cpplint._cpplint_state, ['--badopt'])
            with pytest.raises(SystemExit):
                cli.ParseArguments( cpplint._cpplint_state, ['--help'])
            with pytest.raises(SystemExit):
                cli.ParseArguments( cpplint._cpplint_state, ['--version'])
            with pytest.raises(SystemExit):
                cli.ParseArguments( cpplint._cpplint_state, ['--v=0'])
            with pytest.raises(SystemExit):
                cli.ParseArguments( cpplint._cpplint_state, ['--filter='])
            # This is illegal because all filters must start with + or -
            with pytest.raises(SystemExit):
                cli.ParseArguments(cpplint._cpplint_state, ['--filter=foo'])
            with pytest.raises(SystemExit):
                cli.ParseArguments(cpplint._cpplint_state, ['--filter=+a,b,-c'])
            with pytest.raises(SystemExit):
                cli.ParseArguments(cpplint._cpplint_state, ['--headers'])

            assert ['foo.cc'] == cli.ParseArguments(cpplint._cpplint_state, ['foo.cc'])
            assert old_output_format == cpplint._cpplint_state.output_format
            assert old_verbose_level == cpplint._cpplint_state.verbose_level

            assert ['foo.cc'] == cli.ParseArguments(cpplint._cpplint_state, ['--v=1', 'foo.cc'])
            assert 1 == cpplint._cpplint_state.verbose_level
            assert ['foo.h'] == cli.ParseArguments(cpplint._cpplint_state, ['--v=3', 'foo.h'])
            assert 3 == cpplint._cpplint_state.verbose_level
            assert ['foo.cpp'] == cli.ParseArguments(cpplint._cpplint_state, ['--verbose=5', 'foo.cpp'])
            assert 5 == cpplint._cpplint_state.verbose_level
            with pytest.raises(ValueError):
                cli.ParseArguments(cpplint._cpplint_state, ['--v=f', 'foo.cc'])

            assert ['foo.cc'] == cli.ParseArguments(cpplint._cpplint_state, ['--output=emacs', 'foo.cc'])
            assert 'emacs' == cpplint._cpplint_state.output_format
            assert ['foo.h'] == cli.ParseArguments(cpplint._cpplint_state, ['--output=vs7', 'foo.h'])
            assert 'vs7' == cpplint._cpplint_state.output_format
            with pytest.raises(SystemExit):
                cli.ParseArguments( cpplint._cpplint_state, ['--output=blah', 'foo.cc'])

            filt = '-,+whitespace,-whitespace/indent'
            assert ['foo.h'] == cli.ParseArguments(cpplint._cpplint_state, ['--filter='+filt, 'foo.h'])
            assert ['-', '+whitespace', '-whitespace/indent'] == cpplint._cpplint_state.filters

            assert ['foo.cc', 'foo.h'] == cli.ParseArguments(cpplint._cpplint_state, ['foo.cc', 'foo.h'])

            cpplint._cpplint_state._hpp_headers = old_headers
            cpplint._cpplint_state._valid_extensions = old_valid_extensions
            assert ['foo.h'] == cli.ParseArguments(cpplint._cpplint_state, ['--linelength=120', 'foo.h'])
            assert 120 == cpplint._cpplint_state._line_length
            assert set(['h', 'hh', 'hpp', 'hxx', 'h++', 'cuh']) ==cpplint._cpplint_state.GetHeaderExtensions()

            cpplint._cpplint_state._hpp_headers = old_headers
            cpplint._cpplint_state._valid_extensions = old_valid_extensions
            assert ['foo.h'] == cli.ParseArguments(cpplint._cpplint_state, ['--headers=h', 'foo.h'])
            assert set(['h', 'c', 'cc', 'cpp', 'cxx', 'c++', 'cu']) == cpplint._cpplint_state.GetAllExtensions()

            cpplint._cpplint_state._hpp_headers = old_headers
            cpplint._cpplint_state._valid_extensions = old_valid_extensions
            assert ['foo.h'] == cli.ParseArguments(cpplint._cpplint_state, ['--extensions=hpp,cpp,cpp', 'foo.h'])
            assert set(['hpp', 'cpp']) ==cpplint._cpplint_state.GetAllExtensions()
            assert set(['hpp']) ==cpplint._cpplint_state.GetHeaderExtensions()

            cpplint._cpplint_state._hpp_headers = old_headers
            cpplint._cpplint_state._valid_extensions = old_valid_extensions
            assert ['foo.h'] == cli.ParseArguments(cpplint._cpplint_state, ['--extensions=cpp,cpp', '--headers=hpp,h', 'foo.h'])
            assert set(['hpp', 'h']) ==cpplint._cpplint_state.GetHeaderExtensions()
            assert set(['hpp', 'h', 'cpp']) ==cpplint._cpplint_state.GetAllExtensions()

        finally:
            sys.stdout == sys.__stdout__
            sys.stderr == sys.__stderr__
            cpplint._cpplint_state.output_format = old_output_format
            cpplint._cpplint_state.verbose_level = old_verbose_level
            cpplint._cpplint_state.filters = old_filters
            cpplint._cpplint_state._line_length = old_line_length
            cpplint._cpplint_state._valid_extensions = old_valid_extensions
            cpplint._cpplint_state._hpp_headers = old_headers

    def testRecursiveArgument(self):
        working_dir = os.getcwd()
        temp_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            src_dir = os.path.join(temp_dir, "src")
            nested_dir = os.path.join(temp_dir, "src", "nested")
            os.makedirs(nested_dir)
            open(os.path.join(temp_dir, "one.cpp"), 'w').close()
            open(os.path.join(src_dir, "two.cpp"), 'w').close()
            open(os.path.join(nested_dir, "three.cpp"), 'w').close()
            os.chdir(temp_dir)
            expected = ['one.cpp', os.path.join('src', 'two.cpp'),
                        os.path.join('src', 'nested', 'three.cpp')]
            cli._excludes = None
            actual = cli.ParseArguments(cpplint._cpplint_state, ['--recursive', 'one.cpp', 'src'])
            assert set(expected) == set(actual)
        finally:
            os.chdir(working_dir)
            shutil.rmtree(temp_dir)

    def testRecursiveExcludeInvalidFileExtension(self):
        working_dir = os.getcwd()
        temp_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            src_dir = os.path.join(temp_dir, "src")
            os.makedirs(src_dir)
            open(os.path.join(temp_dir, "one.cpp"), 'w').close()
            open(os.path.join(src_dir, "two.cpp"), 'w').close()
            open(os.path.join(src_dir, "three.cc"), 'w').close()
            os.chdir(temp_dir)
            expected = ['one.cpp', os.path.join('src', 'two.cpp')]
            cli._excludes = None
            actual = cli.ParseArguments(cpplint._cpplint_state, ['--recursive', '--extensions=cpp',
                'one.cpp', 'src'])
            assert set(expected) == set(actual)
        finally:
            os.chdir(working_dir)
            shutil.rmtree(temp_dir)
            cpplint._hpp_headers = set([])
            cpplint._valid_extensions = set([])

    def testRecursiveExclude(self):
        working_dir = os.getcwd()
        temp_dir = os.path.realpath(tempfile.mkdtemp())
        try:
            src_dir = os.path.join(temp_dir, 'src')
            src2_dir = os.path.join(temp_dir, 'src2')
            os.makedirs(src_dir)
            os.makedirs(src2_dir)
            open(os.path.join(src_dir, 'one.cc'), 'w').close()
            open(os.path.join(src_dir, 'two.cc'), 'w').close()
            open(os.path.join(src_dir, 'three.cc'), 'w').close()
            open(os.path.join(src2_dir, 'one.cc'), 'w').close()
            open(os.path.join(src2_dir, 'two.cc'), 'w').close()
            open(os.path.join(src2_dir, 'three.cc'), 'w').close()
            os.chdir(temp_dir)

            expected = [
              os.path.join('src', 'one.cc'),
              os.path.join('src', 'two.cc'),
              os.path.join('src', 'three.cc')
            ]
            cli._excludes = None
            actual = cli.ParseArguments(cpplint._cpplint_state, ['src'])
            assert set(['src']) == set(actual)

            cli._excludes = None
            actual = cli.ParseArguments(cpplint._cpplint_state, ['--recursive', 'src'])
            assert set(expected) == set(actual)

            expected = [os.path.join('src', 'one.cc')]
            cli._excludes = None
            actual = cli.ParseArguments(cpplint._cpplint_state, ['--recursive',
                '--exclude=src{0}t*'.format(os.sep), 'src'])
            assert set(expected) == set(actual)

            expected = [os.path.join('src', 'one.cc')]
            cli._excludes = None
            actual = cli.ParseArguments(cpplint._cpplint_state, ['--recursive',
                '--exclude=src/two.cc', '--exclude=src/three.cc', 'src'])
            assert set(expected) == set(actual)

            expected = set([
              os.path.join('src2', 'one.cc'),
              os.path.join('src2', 'two.cc'),
              os.path.join('src2', 'three.cc')
            ])
            cli._excludes = None
            actual = cli.ParseArguments(cpplint._cpplint_state, ['--recursive',
                '--exclude=src', '.'])
            assert expected == set(actual)
        finally:
            os.chdir(working_dir)
            shutil.rmtree(temp_dir)

    def testJUnitXML(self):
        try:
            cpplint._cpplint_state._junit_errors = []
            cpplint._cpplint_state._junit_failures = []
            expected = ('<?xml version="1.0" encoding="UTF-8" ?>\n'
                '<testsuite errors="0" failures="0" name="cpplint" tests="1">'
                '<testcase name="passed" />'
                '</testsuite>')
            assert expected == cpplint._cpplint_state.FormatJUnitXML()

            cpplint._cpplint_state._junit_errors = ['ErrMsg1']
            cpplint._cpplint_state._junit_failures = []
            expected = ('<?xml version="1.0" encoding="UTF-8" ?>\n'
                '<testsuite errors="1" failures="0" name="cpplint" tests="1">'
                '<testcase name="errors"><error>ErrMsg1</error></testcase>'
                '</testsuite>')
            assert expected == cpplint._cpplint_state.FormatJUnitXML()

            cpplint._cpplint_state._junit_errors = ['ErrMsg1', 'ErrMsg2']
            cpplint._cpplint_state._junit_failures = []
            expected = ('<?xml version="1.0" encoding="UTF-8" ?>\n'
                '<testsuite errors="2" failures="0" name="cpplint" tests="2">'
                '<testcase name="errors"><error>ErrMsg1\nErrMsg2</error></testcase>'
                '</testsuite>')
            assert expected == cpplint._cpplint_state.FormatJUnitXML()

            cpplint._cpplint_state._junit_errors = ['ErrMsg']
            cpplint._cpplint_state._junit_failures = [
                ('File', 5, 'FailMsg', 'category/subcategory', 3)]
            expected = ('<?xml version="1.0" encoding="UTF-8" ?>\n'
                '<testsuite errors="1" failures="1" name="cpplint" tests="2">'
                '<testcase name="errors"><error>ErrMsg</error></testcase>'
                '<testcase name="File"><failure>5: FailMsg [category/subcategory] '
                '[3]</failure></testcase></testsuite>')
            assert expected == cpplint._cpplint_state.FormatJUnitXML()

            cpplint._cpplint_state._junit_errors = []
            cpplint._cpplint_state._junit_failures = [
                ('File1', 5, 'FailMsg1', 'category/subcategory', 3),
                ('File2', 99, 'FailMsg2', 'category/subcategory', 3),
                ('File1', 19, 'FailMsg3', 'category/subcategory', 3)]
            expected = ('<?xml version="1.0" encoding="UTF-8" ?>\n'
                '<testsuite errors="0" failures="3" name="cpplint" tests="3">'
                '<testcase name="File1"><failure>5: FailMsg1 [category/subcategory]'
                ' [3]\n19: FailMsg3 [category/subcategory] [3]</failure></testcase>'
                '<testcase name="File2"><failure>99: FailMsg2 '
                '[category/subcategory] [3]</failure></testcase></testsuite>')
            assert expected == cpplint._cpplint_state.FormatJUnitXML()

            cpplint._cpplint_state._junit_errors = ['&</error>']
            cpplint._cpplint_state._junit_failures = [
                ('File1', 5, '&</failure>', 'category/subcategory', 3)]
            expected = ('<?xml version="1.0" encoding="UTF-8" ?>\n'
                '<testsuite errors="1" failures="1" name="cpplint" tests="2">'
                '<testcase name="errors"><error>&amp;&lt;/error&gt;</error>'
                '</testcase><testcase name="File1"><failure>5: '
                '&amp;&lt;/failure&gt; [category/subcategory] [3]</failure>'
                '</testcase></testsuite>')
            assert expected == cpplint._cpplint_state.FormatJUnitXML()

        finally:
            cpplint._cpplint_state._junit_errors = []
            cpplint._cpplint_state._junit_failures = []

    def testQuiet(self):
        assert cpplint._cpplint_state.quiet == False
        cli.ParseArguments(cpplint._cpplint_state, ['--quiet', 'one.cpp'])
        assert cpplint._cpplint_state.quiet == True

    def testLineLength(self):
        old_line_length = cpplint._cpplint_state._line_length
        try:
            cpplint._cpplint_state._line_length = 80
            self.TestSingleLineLint(
                '// H %s' % ('H' * 75),
                '')
            self.TestSingleLineLint(
                '// H %s' % ('H' * 76),
                'Lines should be <= 80 characters long'
                '  [whitespace/line_length] [2]')
            cpplint._cpplint_state._line_length = 120
            self.TestSingleLineLint(
                '// H %s' % ('H' * 115),
                '')
            self.TestSingleLineLint(
                '// H %s' % ('H' * 116),
                'Lines should be <= 120 characters long'
                '  [whitespace/line_length] [2]')
        finally:
            cpplint._cpplint_state._line_length = old_line_length

    def testFilter(self):
        old_filters = cpplint._cpplint_state.filters
        try:
            cpplint._cpplint_state.filters = ["-","+whitespace","-whitespace/indent"]
            self.TestSingleLineLint(
                '// Hello there ',
                'Line ends in whitespace.  Consider deleting these extra spaces.'
                '  [whitespace/end_of_line] [4]')
            self.TestSingleLineLint('int a = (int)1.0;', '')
            self.TestSingleLineLint(' weird opening space', '')
        finally:
            cpplint._cpplint_state.filters = ','.join(old_filters)

    def testDefaultFilter(self):
        state = cpplint._CppLintState()
        state.filters = ''
        assert "-build/include_alpha" in state.filters

    def testDuplicateHeader(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'path/self.cc', 'cc',
                                ['// Copyright 2014 Your Company. All Rights Reserved.',
                                 '#include "path/self.h"',
                                 '#include "path/duplicate.h"',
                                 '#include "path/duplicate.h"',
                                 '#ifdef MACRO',
                                 '#include "path/unique.h"',
                                 '#else',
                                 '#include "path/unique.h"',
                                 '#endif',
                                 ''],
                                error_collector)
        assert ['"path/duplicate.h" already included at path/self.cc:3  '
             '[build/include] [4]'] == \
            error_collector.ResultList()

    def testUnnamedNamespacesInHeaders(self):
        for extension in ['h', 'hpp', 'hxx', 'h++', 'cuh']:
            self.doTestUnnamedNamespacesInHeaders(extension)

    def doTestUnnamedNamespacesInHeaders(self, extension):
        self.TestLanguageRulesCheck(
            'foo.' + extension, 'namespace {',
            'Do not use unnamed namespaces in header files.  See'
            ' https://google-styleguide.googlecode.com/svn/trunk/cppguide.xml#Namespaces'
            ' for more information.  [build/namespaces_headers] [4]')
        # namespace registration macros are OK.
        self.TestLanguageRulesCheck('foo.' + extension, 'namespace {  \\', '')
        # named namespaces are OK.
        self.TestLanguageRulesCheck('foo.' + extension, 'namespace foo {', '')
        self.TestLanguageRulesCheck('foo.' + extension, 'namespace foonamespace {', '')

    def testUnnamedNamespacesInNonHeaders(self):
        for extension in ['c', 'cc', 'cpp', 'cxx', 'c++', 'cu']:
            self.TestLanguageRulesCheck('foo.' + extension, 'namespace {', '')
            self.TestLanguageRulesCheck('foo.' + extension, 'namespace foo {', '')

    def testBuildClass(self, state):
        # Test that the linter can parse to the end of class definitions,
        # and that it will report when it can't.
        # Use multi-line linter because it performs the ClassState check.
        self.TestMultiLineLint(state,
            'class Foo {',
            'Failed to find complete declaration of class Foo'
            '  [build/class] [5]')
        # Do the same for namespaces
        self.TestMultiLineLint(state,
            'namespace Foo {',
            'Failed to find complete declaration of namespace Foo'
            '  [build/namespaces] [5]')
        # Don't warn on forward declarations of various types.
        self.TestMultiLineLint(state,
            'class Foo;',
            '')
        self.TestMultiLineLint(state,
            """struct Foo*
             foo = NewFoo();""",
            '')
        # Test preprocessor.
        self.TestMultiLineLint(state,
            """#ifdef DERIVE_FROM_GOO
          struct Foo : public Goo {
        #else
          struct Foo : public Hoo {
        #endif
          };""",
            '')
        self.TestMultiLineLint(state,
            """
        class Foo
        #ifdef DERIVE_FROM_GOO
          : public Goo {
        #else
          : public Hoo {
        #endif
        };""",
            '')
        # Test incomplete class
        self.TestMultiLineLint(state,
            'class Foo {',
            'Failed to find complete declaration of class Foo'
            '  [build/class] [5]')

    def testBuildEndComment(self, state):
        # The crosstool compiler we currently use will fail to compile the
        # code in this test, so we might consider removing the lint check.
        self.TestMultiLineLint(state,
            """#if 0
        #endif Not a comment""",
            'Uncommented text after #endif is non-standard.  Use a comment.'
            '  [build/endif_comment] [5]')

    def testBuildForwardDecl(self):
        # The crosstool compiler we currently use will fail to compile the
        # code in this test, so we might consider removing the lint check.
        self.TestSingleLineLint('class Foo::Goo;',
                      'Inner-style forward declarations are invalid.'
                      '  Remove this line.'
                      '  [build/forward_decl] [5]')

    def GetBuildHeaderGuardPreprocessorSymbol(self, state: _CppLintState, file_path):
        # Figure out the expected header guard by processing an empty file.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h', [], error_collector)
        for error in error_collector.ResultList():
            matched = re.search(
                'No #ifndef header guard found, suggested CPP variable is: '
                '([A-Z0-9_]+)',
                error)
            if matched is not None:
                return matched.group(1)

    def testBuildHeaderGuard(self, state: _CppLintState):
        file_path = 'mydir/foo.h'
        expected_guard = self.GetBuildHeaderGuardPreprocessorSymbol(state, file_path)
        assert re.search('MYDIR_FOO_H_$', expected_guard)

        # No guard at all: expect one error.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h', [], error_collector)
        assert 1 == error_collector.ResultList().count(
                'No #ifndef header guard found, suggested CPP variable is: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # No header guard, but the error is suppressed.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['// Copyright 2014 Your Company.',
                                 '// NOLINT(build/header_guard)', ''],
                                error_collector)
        assert [] == error_collector.ResultList()

        # Wrong guard
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef FOO_H', '#define FOO_H'], error_collector)
        assert 1 == error_collector.ResultList().count(
                '#ifndef header guard has wrong style, please use: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # No define
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef %s' % expected_guard], error_collector)
        assert 1 == error_collector.ResultList().count(
                'No #ifndef header guard found, suggested CPP variable is: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Mismatched define
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef %s' % expected_guard,
                                 '#define FOO_H'],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                'No #ifndef header guard found, suggested CPP variable is: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # No endif
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef %s' % expected_guard,
                                 '#define %s' % expected_guard,
                                 ''],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Commentless endif
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef %s' % expected_guard,
                                 '#define %s' % expected_guard,
                                 '#endif'],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Commentless endif for old-style guard
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef %s_' % expected_guard,
                                 '#define %s_' % expected_guard,
                                 '#endif'],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # No header guard errors
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef %s' % expected_guard,
                                 '#define %s' % expected_guard,
                                 '#endif  // %s' % expected_guard],
                                error_collector)
        for line in error_collector.ResultList():
            if line.find('build/header_guard') != -1:
                self.fail('Unexpected error: %s' % line)

        # No header guard errors for old-style guard
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef %s_' % expected_guard,
                                 '#define %s_' % expected_guard,
                                 '#endif  // %s_' % expected_guard],
                                error_collector)
        for line in error_collector.ResultList():
            if line.find('build/header_guard') != -1:
                self.fail('Unexpected error: %s' % line)

        old_verbose_level = state.verbose_level
        try:
            state.verbose_level = 0
            # Warn on old-style guard if verbosity is 0.
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, file_path, 'h',
                                    ['#ifndef %s_' % expected_guard,
                                     '#define %s_' % expected_guard,
                                     '#endif  // %s_' % expected_guard],
                                    error_collector)
            assert 1 == error_collector.ResultList().count(
                    '#ifndef header guard has wrong style, please use: %s'
                    '  [build/header_guard] [0]' % expected_guard), error_collector.ResultList()
        finally:
            state.verbose_level = old_verbose_level

        # Completely incorrect header guard
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef FOO',
                                 '#define FOO',
                                 '#endif  // FOO'],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                '#ifndef header guard has wrong style, please use: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()
        assert 1 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # incorrect header guard with nolint
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'h',
                                ['#ifndef FOO  // NOLINT',
                                 '#define FOO',
                                 '#endif  // FOO NOLINT'],
                                error_collector)
        assert 0 == error_collector.ResultList().count(
            '#ifndef header guard has wrong style, please use: %s'
            '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        assert 0 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Special case for flymake
        for test_file in ['mydir/foo_flymake.h', 'mydir/.flymake/foo.h']:
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(state, test_file, 'h',
                                    ['// Copyright 2014 Your Company.', ''],
                                    error_collector)
            assert 1 == error_collector.ResultList().count(
                    'No #ifndef header guard found, suggested CPP variable is: %s'
                    '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Cuda guard
        file_path = 'mydir/foo.cuh'
        expected_guard = self.GetBuildHeaderGuardPreprocessorSymbol(file_path)
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'cuh',
                                ['#ifndef FOO',
                                 '#define FOO',
                                 '#endif  // FOO'],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                '#ifndef header guard has wrong style, please use: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()
        assert 1 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

    def testPragmaOnce(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, 'mydir/foo.h', 'h',
            ['// Copyright 2014 Your Company.', '#pragma once', ''],
            error_collector)
        assert [] == error_collector.ResultList()

    def testBuildHeaderGuardWithRoot(self):
        temp_directory = os.path.realpath(tempfile.mkdtemp())
        try:
            test_directory = os.path.join(temp_directory, "test")
            os.makedirs(test_directory)
            os.makedirs(os.path.join(test_directory, ".svn"))
            header_directory = os.path.join(test_directory, "cpplint")
            os.makedirs(header_directory)
            self.doTestBuildHeaderGuardWithRoot(header_directory)
        finally:
            shutil.rmtree(temp_directory)

    def doTestBuildHeaderGuardWithRoot(self, header_directory):

        # note: Tested file paths must be real, otherwise
        # the repository name lookup will fail.
        file_path = os.path.join(header_directory,
                                 'cpplint_test_header.h')
        open(file_path, 'a').close()
        file_info = cpplint.FileInfo(file_path)
        if file_info.FullName() == file_info.RepositoryName(cpplint._cpplint_state._repository):
            # When FileInfo cannot deduce the root directory of the repository,
            # FileInfo.RepositoryName returns the same value as FileInfo.FullName.
            # This can happen when this source file was obtained without .svn or
            # .git directory. (e.g. using 'svn export' or 'git archive').
            # Skip this test in such a case because --root flag makes sense only
            # when the root directory of the repository is properly deduced.
            return

        assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)
        #
        # test --root flags:
        #   this changes the cpp header guard prefix
        #

        # left-strip the header guard by using a root dir inside of the repo dir.
        # relative directory
        cpplint._cpplint_state._root = 'cpplint'
        assert 'CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

        nested_header_directory = os.path.join(header_directory, "nested")
        nested_file_path = os.path.join(nested_header_directory, 'cpplint_test_header.h')
        os.makedirs(nested_header_directory)
        open(nested_file_path, 'a').close()

        cpplint._cpplint_state._root = os.path.join('cpplint', 'nested')
        actual = cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, nested_file_path)
        assert 'CPPLINT_TEST_HEADER_H_' == actual

        # absolute directory
        # (note that CPPLINT.cfg root=setting is always made absolute)
        cpplint._cpplint_state._root = header_directory
        assert 'CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state,file_path)

        cpplint._cpplint_state._root = nested_header_directory
        assert 'CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state,nested_file_path)

        # --root flag is ignored if an non-existent directory is specified.
        cpplint._cpplint_state._root = 'NON_EXISTENT_DIR'
        assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

        # prepend to the header guard by using a root dir that is more outer
        # than the repo dir

        # (using absolute paths)
        # (note that CPPLINT.cfg root=setting is always made absolute)
        this_files_path = os.path.dirname(os.path.abspath(file_path))
        (styleguide_path, this_files_dir) = os.path.split(this_files_path)
        (styleguide_parent_path, styleguide_dir_name) = os.path.split(styleguide_path)
        # parent dir of styleguide
        cpplint._cpplint_state._root = styleguide_parent_path
        assert styleguide_parent_path is not None
        # do not hardcode the 'styleguide' repository name, it could be anything.
        expected_prefix = re.sub(r'[^a-zA-Z0-9]', '_', styleguide_dir_name).upper() + '_'
        # do not have 'styleguide' repo in '/'
        assert '%sCPPLINT_CPPLINT_TEST_HEADER_H_' % (expected_prefix) == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

        # To run the 'relative path' tests, we must be in the directory of this test file.
        cur_dir = os.getcwd()
        os.chdir(this_files_path)

        # (using relative paths)
        styleguide_rel_path = os.path.relpath(styleguide_path, this_files_path)
        # '..'
        cpplint._cpplint_state._root = styleguide_rel_path
        assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

        styleguide_rel_path = os.path.relpath(styleguide_parent_path,
                                              this_files_path)  # '../..'
        cpplint._cpplint_state._root = styleguide_rel_path
        assert '%sCPPLINT_CPPLINT_TEST_HEADER_H_' % (expected_prefix) == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

        cpplint._cpplint_state._root = None

        # Restore previous CWD.
        os.chdir(cur_dir)

    def testIncludeItsHeader(self, state):
        temp_directory = os.path.realpath(tempfile.mkdtemp())
        cur_dir = os.getcwd()
        try:
            test_directory = os.path.join(temp_directory, "test")
            os.makedirs(test_directory)
            file_path = os.path.join(test_directory, 'foo.h')
            open(file_path, 'a').close()
            file_path = os.path.join(test_directory, 'Bar.h')
            open(file_path, 'a').close()

            os.chdir(temp_directory)

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(
              state,
              'test/foo.cc', 'cc',
              [''],
              error_collector)
            expected = "{dir}/{fn}.cc should include its header file {dir}/{fn}.h  [build/include] [5]".format(
                fn="foo",
                dir=test_directory)
            assert 1 == error_collector.Results().count(expected)

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(
              state,
              'test/foo.cc', 'cc',
              [r'#include "test/foo.h"',
               ''
               ],
              error_collector)
            assert 0 == error_collector.Results().count(expected)

            # Unix directory aliases are not allowed, and should trigger the
            # "include itse header file" error
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(
              state,
              'test/foo.cc', 'cc',
              [r'#include "./test/foo.h"',
               ''
               ],
              error_collector)
            expected = "{dir}/{fn}.cc should include its header file {dir}/{fn}.h{unix_text}  [build/include] [5]".format(
                fn="foo",
                dir=test_directory,
                unix_text=". Relative paths like . and .. are not allowed.")
            assert 1 == error_collector.Results().count(expected)

            # This should continue to work
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(
              state,
              'test/Bar.cc', 'cc',
              [r'#include "test/Bar.h"',
               ''
               ],
              error_collector)
            expected = "{dir}/{fn}.cc should include its header file {dir}/{fn}.h  [build/include] [5]".format(
                fn="Bar",
                dir=test_directory)
            assert 0 == error_collector.Results().count(expected)

            # Since Bar.cc & Bar.h look 3rd party-ish, it should be ok without the include dir
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(
              state,
              'test/Bar.cc', 'cc',
              [r'#include "Bar.h"',
               ''
               ],
              error_collector)
            assert 0 == error_collector.Results().count(expected)

        finally:
            # Restore previous CWD.
            os.chdir(cur_dir)
            shutil.rmtree(temp_directory)

    def testPathSplitToList(self):
        assert [''] == PathSplitToList(os.path.join(''))
        assert ['.'] == PathSplitToList(os.path.join('.'))
        assert ['..'] == PathSplitToList(os.path.join('..'))
        assert ['..', 'a', 'b'], PathSplitToList(os.path.join('..', 'a' == 'b'))
        assert ['a', 'b', 'c', 'd'], PathSplitToList(os.path.join('a', 'b', 'c' == 'd'))

    def testBuildHeaderGuardWithRepository(self):
        temp_directory = os.path.realpath(tempfile.mkdtemp())
        temp_directory2 = os.path.realpath(tempfile.mkdtemp())
        try:
            os.makedirs(os.path.join(temp_directory, ".svn"))
            trunk_dir = os.path.join(temp_directory, "trunk")
            os.makedirs(trunk_dir)
            header_directory = os.path.join(trunk_dir, "cpplint")
            os.makedirs(header_directory)
            file_path = os.path.join(header_directory, 'cpplint_test_header.h')
            open(file_path, 'a').close()

            # search for .svn if _repository is not specified
            assert 'TRUNK_CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

            # use the provided repository root for header guards
            cpplint._cpplint_state._repository = os.path.relpath(trunk_dir)
            assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)
            cpplint._cpplint_state._repository = os.path.abspath(trunk_dir)
            assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

            # ignore _repository if it doesnt exist
            cpplint._cpplint_state._repository = os.path.join(temp_directory, 'NON_EXISTANT')
            assert 'TRUNK_CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

            # ignore _repository if it exists but file isn't in it
            cpplint._cpplint_state._repository = os.path.relpath(temp_directory2)
            assert 'TRUNK_CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

            # _root should be relative to _repository
            cpplint._cpplint_state._repository = os.path.relpath(trunk_dir)
            cpplint._cpplint_state._root = 'cpplint'
            assert 'CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(cpplint._cpplint_state, file_path)

        finally:
            shutil.rmtree(temp_directory)
            shutil.rmtree(temp_directory2)
            cpplint._cpplint_state._repository = None
            cpplint._cpplint_state._root = None

    def testBuildInclude(self):
        # Test that include statements have slashes in them.
        self.TestSingleLineLint('#include "foo.h"',
                      'Include the directory when naming header files'
                      '  [build/include_subdir] [4]')
        self.TestSingleLineLint('#include "bar.hh"',
                      'Include the directory when naming header files'
                      '  [build/include_subdir] [4]')
        self.TestSingleLineLint('#include "baz.aa"', '')
        self.TestSingleLineLint('#include "dir/foo.h"', '')
        self.TestSingleLineLint('#include "Python.h"', '')
        self.TestSingleLineLint('#include "lua.h"', '')

    def testHppInclude(self):
        code = '\n'.join([
          '#include <vector>',
          '#include <boost/any.hpp>'
        ])
        self.TestLanguageRulesCheck('foo.h', code, '')

    def testBuildPrintfFormat(self, state):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state,
            'foo.cc', 'cc',
            [r'printf("\%%d", value);',
             r'snprintf(buffer, sizeof(buffer), "\[%d", value);',
             r'fprintf(file, "\(%d", value);',
             r'vsnprintf(buffer, sizeof(buffer), "\\\{%d", ap);'],
            error_collector)
        assert 4 == error_collector.Results().count(
                '%, [, (, and { are undefined character escapes.  Unescape them.'
                '  [build/printf_format] [3]')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state,
            'foo.cc', 'cc',
            ['// Copyright 2014 Your Company.',
             r'printf("\\%%%d", value);',
             r'printf(R"(\[)");',
             r'printf(R"(\[%s)", R"(\])");',
             ''],
            error_collector)
        assert '' == error_collector.Results()

    def testRuntimePrintfFormat(self):
        self.TestSingleLineLint(
            r'fprintf(file, "%q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestSingleLineLint(
            r'aprintf(file, "The number is %12q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestSingleLineLint(
            r'printf(file, "The number is" "%-12q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestSingleLineLint(
            r'printf(file, "The number is" "%+12q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestSingleLineLint(
            r'printf(file, "The number is" "% 12q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestSingleLineLint(
            r'snprintf(file, "Never mix %d and %1$d parameters!", value);',
            '%N$ formats are unconventional.  Try rewriting to avoid them.'
            '  [runtime/printf_format] [2]')

    def TestSingleLineLintLogCodeOnError(self, state, code, expected_message):
        # Special TestSingleLineLint which logs the input code on error.
        result = self.PerformSingleLineLint(state, code)
        if result != expected_message:
            self.fail('For code: "%s"\nGot: "%s"\nExpected: "%s"'
                      % (code, result, expected_message))

    def testBuildStorageClass(self):
        qualifiers = [None, 'const', 'volatile']
        signs = [None, 'signed', 'unsigned']
        types = ['void', 'char', 'int', 'float', 'double',
                 'schar', 'int8', 'uint8', 'int16', 'uint16',
                 'int32', 'uint32', 'int64', 'uint64']
        storage_classes = ['extern', 'register', 'static', 'typedef']

        build_storage_class_error_message = (
            'Storage-class specifier (static, extern, typedef, etc) should be '
            'at the beginning of the declaration.  [build/storage_class] [5]')

        # Some explicit cases. Legal in C++, deprecated in C99.
        self.TestSingleLineLint('const int static foo = 5;',
                      build_storage_class_error_message)

        self.TestSingleLineLint('char static foo;',
                      build_storage_class_error_message)

        self.TestSingleLineLint('double const static foo = 2.0;',
                      build_storage_class_error_message)

        self.TestSingleLineLint('uint64 typedef unsigned_long_long;',
                      build_storage_class_error_message)

        self.TestSingleLineLint('int register foo = 0;',
                      build_storage_class_error_message)

        # Since there are a very large number of possibilities, randomly
        # construct declarations.
        # Make sure that the declaration is logged if there's an error.
        # Seed generator with an integer for absolute reproducibility.
        random.seed(25)
        for unused_i in range(10):
            # Build up random list of non-storage-class declaration specs.
            other_decl_specs = [random.choice(qualifiers), random.choice(signs),
                                random.choice(types)]
            # remove None
            other_decl_specs = [x for x in other_decl_specs if x is not None]

            # shuffle
            random.shuffle(other_decl_specs)

            # insert storage class after the first
            storage_class = random.choice(storage_classes)
            insertion_point = random.randint(1, len(other_decl_specs))
            decl_specs = (other_decl_specs[0:insertion_point]
                          + [storage_class]
                          + other_decl_specs[insertion_point:])

            self.TestSingleLineLintLogCodeOnError(
                ' '.join(decl_specs) + ';',
                build_storage_class_error_message)

            # but no error if storage class is first
            self.TestSingleLineLintLogCodeOnError(
                storage_class + ' ' + ' '.join(other_decl_specs),
                '')

    def testLegalCopyright(self, state):
        legal_copyright_message = (
            'No copyright message found.  '
            'You should have a line: "Copyright [year] <Copyright Owner>"'
            '  [legal/copyright] [5]')

        copyright_line = '// Copyright 2014 Google Inc. All Rights Reserved.'

        file_path = 'mydir/googleclient/foo.cc'

        # There should be a copyright message in the first 10 lines
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'cc', [], error_collector)
        assert 1 == error_collector.ResultList().count(legal_copyright_message)

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state,
            file_path, 'cc',
            ['' for unused_i in range(10)] + [copyright_line],
            error_collector)
        assert 1 == error_collector.ResultList().count(legal_copyright_message)

        # Test that warning isn't issued if Copyright line appears early enough.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(state, file_path, 'cc', [copyright_line], error_collector)
        for message in error_collector.ResultList():
            if message.find('legal/copyright') != -1:
                self.fail('Unexpected error: %s' % message)

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            state,
            file_path, 'cc',
            ['' for unused_i in range(9)] + [copyright_line],
            error_collector)
        for message in error_collector.ResultList():
            if message.find('legal/copyright') != -1:
                self.fail('Unexpected error: %s' % message)

    def testInvalidIncrement(self):
        self.TestSingleLineLint('*count++;',
                      'Changing pointer instead of value (or unused value of '
                      'operator*).  [runtime/invalid_increment] [5]')

    def testSnprintfSize(self):
        self.TestSingleLineLint('vsnprintf(NULL, 0, format)', '')
        self.TestSingleLineLint('snprintf(fisk, 1, format)',
                      'If you can, use sizeof(fisk) instead of 1 as the 2nd arg '
                      'to snprintf.  [runtime/printf] [3]')
