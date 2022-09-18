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
from halint.check_lines import CheckForNamespaceIndentation

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
        assert 0 == cpplint.GetLineWidth('')
        assert 10 == cpplint.GetLineWidth(str('x') * 10)
        assert 16 == cpplint.GetLineWidth('\u90fd|\u9053|\u5e9c|\u770c|\u652f\u5e81')
        assert 16 == cpplint.GetLineWidth(u'都|道|府|県|支庁')
        assert 5 + 13 + 9 == cpplint.GetLineWidth(u'd𝐱/dt' + u'f : t ⨯ 𝐱 → ℝ' + u't ⨯ 𝐱 → ℝ')

    def testGetTextInside(self):
        assert '' == cpplint._GetTextInside('fun()', r'fun\(')
        assert 'x, y' == cpplint._GetTextInside('f(x, y)', r'f\(')
        assert 'a(), b(c())' == cpplint._GetTextInside('printf(a(), b(c()))', r'printf\(')
        assert 'x, y{}' == cpplint._GetTextInside('f[x, y{}]', r'f\[')
        assert None == cpplint._GetTextInside('f[a, b(}]', r'f\[')
        assert None == cpplint._GetTextInside('f[x, y]', r'f\(')
        assert 'y, h(z, (a + b))' == cpplint._GetTextInside('f(x, g(y, h(z, (a + b))))', r'g\(')
        assert 'f(f(x))' == cpplint._GetTextInside('f(f(f(x)))', r'f\(')
        # Supports multiple lines.
        assert '\n  return loop(x);\n' == cpplint._GetTextInside('int loop(int x) {\n  return loop(x);\n}\n', r'\{')
        # '^' matches the beginning of each line.
        assert 'x, y' == cpplint._GetTextInside(
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
        self.TestLint(
            '// Hello there ',
            'Line ends in whitespace.  Consider deleting these extra spaces.'
            '  [whitespace/end_of_line] [4]')

    # Test line length check.
    def testLineLengthCheck(self):
        self.TestLint(
            '// Hello',
            '')
        self.TestLint(
            '// x' + ' x' * 40,
            'Lines should be <= 80 characters long'
            '  [whitespace/line_length] [2]')
        self.TestLint(
            '// x' + ' x' * 50,
            'Lines should be <= 80 characters long'
            '  [whitespace/line_length] [2]')
        self.TestLint(
            '// //some/path/to/f' + ('i' * 100) + 'le',
            '')
        self.TestLint(
            '//   //some/path/to/f' + ('i' * 100) + 'le',
            '')
        self.TestLint(
            '//   //some/path/to/f' + ('i' * 50) + 'le and some comments',
            'Lines should be <= 80 characters long'
            '  [whitespace/line_length] [2]')
        self.TestLint(
            '// http://g' + ('o' * 100) + 'gle.com/',
            '')
        self.TestLint(
            '//   https://g' + ('o' * 100) + 'gle.com/',
            '')
        self.TestLint(
            '//   https://g' + ('o' * 60) + 'gle.com/ and some comments',
            'Lines should be <= 80 characters long'
            '  [whitespace/line_length] [2]')
        self.TestLint(
            '// Read https://g' + ('o' * 60) + 'gle.com/',
            '')
        self.TestLint(
            '// $Id: g' + ('o' * 80) + 'gle.cc#1 $',
            '')
        self.TestLint(
            '// $Id: g' + ('o' * 80) + 'gle.cc#1',
            'Lines should be <= 80 characters long'
            '  [whitespace/line_length] [2]')
        self.TestMultiLineLint(
            'static const char kCStr[] = "g' + ('o' * 50) + 'gle";\n',
            'Lines should be <= 80 characters long'
            '  [whitespace/line_length] [2]')
        self.TestMultiLineLint(
            'static const char kRawStr[] = R"(g' + ('o' * 50) + 'gle)";\n',
            '')  # no warning because raw string content is elided
        self.TestMultiLineLint(
            'static const char kMultiLineRawStr[] = R"(\n'
            'g' + ('o' * 80) + 'gle\n'
            ')";',
            '')
        self.TestMultiLineLint(
            'static const char kL' + ('o' * 50) + 'ngIdentifier[] = R"()";\n',
            'Lines should be <= 80 characters long'
            '  [whitespace/line_length] [2]')
        self.TestLint(
            '  /// @copydoc ' + ('o' * (cpplint._cpplint_state._line_length * 2)),
            '')
        self.TestLint(
            '  /// @copydetails ' + ('o' * (cpplint._cpplint_state._line_length * 2)),
            '')
        self.TestLint(
            '  /// @copybrief ' + ('o' * (cpplint._cpplint_state._line_length * 2)),
            '')

    # Test error suppression annotations.
    def testErrorSuppression(self):
        # Two errors on same line:
        self.TestLint(
            'long a = (int64) 65;',
            ['Using C-style cast.  Use static_cast<int64>(...) instead'
             '  [readability/casting] [4]',
             'Use int16/int64/etc, rather than the C type long'
             '  [runtime/int] [4]',
            ])
        # One category of error suppressed:
        self.TestLint(
            'long a = (int64) 65;  // NOLINT(runtime/int)',
            'Using C-style cast.  Use static_cast<int64>(...) instead'
            '  [readability/casting] [4]')
        # All categories suppressed: (two aliases)
        self.TestLint('long a = (int64) 65;  // NOLINT', '')
        self.TestLint('long a = (int64) 65;  // NOLINT(*)', '')
        # Malformed NOLINT directive:
        self.TestLint(
            'long a = 65;  // NOLINT(foo)',
            ['Unknown NOLINT error category: foo'
             '  [readability/nolint] [5]',
             'Use int16/int64/etc, rather than the C type long  [runtime/int] [4]',
            ])
        # Irrelevant NOLINT directive has no effect:
        self.TestLint(
            'long a = 65;  // NOLINT(readability/casting)',
            'Use int16/int64/etc, rather than the C type long'
            '  [runtime/int] [4]')
        # NOLINTNEXTLINE silences warning for the next line instead of current line
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('test.cc', 'cc',
                                ['// Copyright 2014 Your Company.',
                                 '// NOLINTNEXTLINE(whitespace/line_length)',
                                 '//  ./command' + (' -verbose' * 80),
                                 ''],
                                error_collector)
        assert '' == error_collector.Results()
        # LINT_C_FILE silences cast warnings for entire file.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('test.h', 'h',
                                ['// Copyright 2014 Your Company.',
                                 '// NOLINT(build/header_guard)',
                                 'int64 a = (uint64) 65;',
                                 '//  LINT_C_FILE',
                                 ''],
                                error_collector)
        assert '' == error_collector.Results()
        # Vim modes silence cast warnings for entire file.
        for modeline in ['vi:filetype=c',
                         'vi:sw=8 filetype=c',
                         'vi:sw=8 filetype=c ts=8',
                         'vi: filetype=c',
                         'vi: sw=8 filetype=c',
                         'vi: sw=8 filetype=c ts=8',
                         'vim:filetype=c',
                         'vim:sw=8 filetype=c',
                         'vim:sw=8 filetype=c ts=8',
                         'vim: filetype=c',
                         'vim: sw=8 filetype=c',
                         'vim: sw=8 filetype=c ts=8',
                         'vim: set filetype=c:',
                         'vim: set sw=8 filetype=c:',
                         'vim: set sw=8 filetype=c ts=8:',
                         'vim: set filetype=c :',
                         'vim: set sw=8 filetype=c :',
                         'vim: set sw=8 filetype=c ts=8 :',
                         'vim: se filetype=c:',
                         'vim: se sw=8 filetype=c:',
                         'vim: se sw=8 filetype=c ts=8:',
                         'vim: se filetype=c :',
                         'vim: se sw=8 filetype=c :',
                         'vim: se sw=8 filetype=c ts=8 :']:
            error_collector = ErrorCollector()
            cpplint.ProcessFileData('test.h', 'h',
                                    ['// Copyright 2014 Your Company.',
                                     '// NOLINT(build/header_guard)',
                                     'int64 a = (uint64) 65;',
                                     '/* Prevent warnings about the modeline',
                                     modeline,
                                     '*/',
                                     ''],
                                    error_collector)
            assert '' == error_collector.Results()
        # LINT_KERNEL_FILE silences whitespace/tab warnings for entire file.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('test.h', 'h',
                                ['// Copyright 2014 Your Company.',
                                 '// NOLINT(build/header_guard)',
                                 'struct test {',
                                 '\tint member;',
                                 '};',
                                 '//  LINT_KERNEL_FILE',
                                 ''],
                                error_collector)
        assert '' == error_collector.Results()
        # NOLINT, NOLINTNEXTLINE silences the readability/braces warning for "};".
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('test.cc', 'cc',
                                ['// Copyright 2014 Your Company.',
                                 'for (int i = 0; i != 100; ++i) {',
                                 '  std::cout << i << std::endl;',
                                 '};  // NOLINT',
                                 'for (int i = 0; i != 100; ++i) {',
                                 '  std::cout << i << std::endl;',
                                 '// NOLINTNEXTLINE',
                                 '};',
                                 '//  LINT_KERNEL_FILE',
                                 ''],
                                error_collector)
        assert '' == error_collector.Results()

    # Test Variable Declarations.
    def testVariableDeclarations(self):
        self.TestLint(
            'long a = 65;',
            'Use int16/int64/etc, rather than the C type long'
            '  [runtime/int] [4]')
        self.TestLint(
            'long double b = 65.0;',
            '')
        self.TestLint(
            'long long aa = 6565;',
            'Use int16/int64/etc, rather than the C type long'
            '  [runtime/int] [4]')

    # Test C-style cast cases.
    def testCStyleCast(self):
        self.TestLint(
            'int a = (int)1.0;',
            'Using C-style cast.  Use static_cast<int>(...) instead'
            '  [readability/casting] [4]')
        self.TestLint(
            'int a = (int)-1.0;',
            'Using C-style cast.  Use static_cast<int>(...) instead'
            '  [readability/casting] [4]')
        self.TestLint(
            'int *a = (int *)NULL;',
            'Using C-style cast.  Use reinterpret_cast<int *>(...) instead'
            '  [readability/casting] [4]')

        self.TestLint(
            'uint16 a = (uint16)1.0;',
            'Using C-style cast.  Use static_cast<uint16>(...) instead'
            '  [readability/casting] [4]')
        self.TestLint(
            'int32 a = (int32)1.0;',
            'Using C-style cast.  Use static_cast<int32>(...) instead'
            '  [readability/casting] [4]')
        self.TestLint(
            'uint64 a = (uint64)1.0;',
            'Using C-style cast.  Use static_cast<uint64>(...) instead'
            '  [readability/casting] [4]')
        self.TestLint(
            'size_t a = (size_t)1.0;',
            'Using C-style cast.  Use static_cast<size_t>(...) instead'
            '  [readability/casting] [4]')

        # These shouldn't be recognized casts.
        self.TestLint('u a = (u)NULL;', '')
        self.TestLint('uint a = (uint)NULL;', '')
        self.TestLint('typedef MockCallback<int(int)> CallbackType;', '')
        self.TestLint('scoped_ptr< MockCallback<int(int)> > callback_value;', '')
        self.TestLint('std::function<int(bool)>', '')
        self.TestLint('x = sizeof(int)', '')
        self.TestLint('x = alignof(int)', '')
        self.TestLint('alignas(int) char x[42]', '')
        self.TestLint('alignas(alignof(x)) char y[42]', '')
        self.TestLint('void F(int (func)(int));', '')
        self.TestLint('void F(int (func)(int*));', '')
        self.TestLint('void F(int (Class::member)(int));', '')
        self.TestLint('void F(int (Class::member)(int*));', '')
        self.TestLint('void F(int (Class::member)(int), int param);', '')
        self.TestLint('void F(int (Class::member)(int*), int param);', '')
        self.TestLint('X Class::operator++(int)', '')
        self.TestLint('X Class::operator--(int)', '')

        # These should not be recognized (lambda functions without arg names).
        self.TestLint('[](int/*unused*/) -> bool {', '')
        self.TestLint('[](int /*unused*/) -> bool {', '')
        self.TestLint('auto f = [](MyStruct* /*unused*/)->int {', '')
        self.TestLint('[](int) -> bool {', '')
        self.TestLint('auto f = [](MyStruct*)->int {', '')

        # Cast with brace initializers
        self.TestLint('int64_t{4096} * 1000 * 1000', '')
        self.TestLint('size_t{4096} * 1000 * 1000', '')
        self.TestLint('uint_fast16_t{4096} * 1000 * 1000', '')

        # Brace initializer with templated type
        self.TestMultiLineLint(
            """
        template <typename Type1,
                  typename Type2>
        void Function(int arg1,
                      int arg2) {
          variable &= ~Type1{0} - 1;
        }""",
            '')
        self.TestMultiLineLint(
            """
        template <typename Type>
        class Class {
          void Function() {
            variable &= ~Type{0} - 1;
          }
        };""",
            '')
        self.TestMultiLineLint(
            """
        template <typename Type>
        class Class {
          void Function() {
            variable &= ~Type{0} - 1;
          }
        };""",
            '')
        self.TestMultiLineLint(
            """
        namespace {
        template <typename Type>
        class Class {
          void Function() {
            if (block) {
              variable &= ~Type{0} - 1;
            }
          }
        };
        }""",
            '')

    # Test taking address of casts (runtime/casting)
    def testRuntimeCasting(self):
        error_msg = ('Are you taking an address of a cast?  '
                     'This is dangerous: could be a temp var.  '
                     'Take the address before doing the cast, rather than after'
                     '  [runtime/casting] [4]')
        self.TestLint('int* x = &static_cast<int*>(foo);', error_msg)
        self.TestLint('int* x = &reinterpret_cast<int *>(foo);', error_msg)
        self.TestLint('int* x = &(int*)foo;',
                      ['Using C-style cast.  Use reinterpret_cast<int*>(...) '
                       'instead  [readability/casting] [4]',
                       error_msg])
        self.TestLint('BudgetBuckets&(BudgetWinHistory::*BucketFn)(void) const;',
                      '')
        self.TestLint('&(*func_ptr)(arg)', '')
        self.TestLint('Compute(arg, &(*func_ptr)(i, j));', '')

        # Alternative error message
        alt_error_msg = ('Are you taking an address of something dereferenced '
                         'from a cast?  Wrapping the dereferenced expression in '
                         'parentheses will make the binding more obvious'
                         '  [readability/casting] [4]')
        self.TestLint('int* x = &down_cast<Obj*>(obj)->member_;', alt_error_msg)
        self.TestLint('int* x = &down_cast<Obj*>(obj)[index];', alt_error_msg)
        self.TestLint('int* x = &(down_cast<Obj*>(obj)->member_);', '')
        self.TestLint('int* x = &(down_cast<Obj*>(obj)[index]);', '')
        self.TestLint('int* x = &down_cast<Obj*>(obj)\n->member_;', alt_error_msg)
        self.TestLint('int* x = &(down_cast<Obj*>(obj)\n->member_);', '')

        # It's OK to cast an address.
        self.TestLint('int* x = reinterpret_cast<int *>(&foo);', '')

        # Function pointers returning references should not be confused
        # with taking address of old-style casts.
        self.TestLint('auto x = implicit_cast<string &(*)(int)>(&foo);', '')

    def testRuntimeSelfinit(self):
        self.TestLint(
            'Foo::Foo(Bar r, Bel l) : r_(r_), l_(l_) { }',
            'You seem to be initializing a member variable with itself.'
            '  [runtime/init] [4]')
        self.TestLint(
            'Foo::Foo(Bar r, Bel l) : r_(CHECK_NOTNULL(r_)) { }',
            'You seem to be initializing a member variable with itself.'
            '  [runtime/init] [4]')
        self.TestLint(
            'Foo::Foo(Bar r, Bel l) : r_(r), l_(l) { }',
            '')
        self.TestLint(
            'Foo::Foo(Bar r) : r_(r), l_(r_), ll_(l_) { }',
            '')

    # Test for unnamed arguments in a method.
    def testCheckForUnnamedParams(self):
        self.TestLint('virtual void Func(int*) const;', '')
        self.TestLint('virtual void Func(int*);', '')
        self.TestLint('void Method(char*) {', '')
        self.TestLint('void Method(char*);', '')
        self.TestLint('static void operator delete[](void*) throw();', '')
        self.TestLint('int Method(int);', '')

        self.TestLint('virtual void Func(int* p);', '')
        self.TestLint('void operator delete(void* x) throw();', '')
        self.TestLint('void Method(char* x) {', '')
        self.TestLint('void Method(char* /*x*/) {', '')
        self.TestLint('void Method(char* x);', '')
        self.TestLint('typedef void (*Method)(int32 x);', '')
        self.TestLint('static void operator delete[](void* x) throw();', '')
        self.TestLint('static void operator delete[](void* /*x*/) throw();', '')

        self.TestLint('X operator++(int);', '')
        self.TestLint('X operator++(int) {', '')
        self.TestLint('X operator--(int);', '')
        self.TestLint('X operator--(int /*unused*/) {', '')
        self.TestLint('MACRO(int);', '')
        self.TestLint('MACRO(func(int));', '')
        self.TestLint('MACRO(arg, func(int));', '')

        self.TestLint('void (*func)(void*);', '')
        self.TestLint('void Func((*func)(void*)) {}', '')
        self.TestLint('template <void Func(void*)> void func();', '')
        self.TestLint('virtual void f(int /*unused*/) {', '')
        self.TestLint('void f(int /*unused*/) override {', '')
        self.TestLint('void f(int /*unused*/) final {', '')

    # Test deprecated casts such as int(d)
    def testDeprecatedCast(self):
        self.TestLint(
            'int a = int(2.2);',
            'Using deprecated casting style.  '
            'Use static_cast<int>(...) instead'
            '  [readability/casting] [4]')

        self.TestLint(
            '(char *) "foo"',
            'Using C-style cast.  '
            'Use const_cast<char *>(...) instead'
            '  [readability/casting] [4]')

        self.TestLint(
            '(int*)foo',
            'Using C-style cast.  '
            'Use reinterpret_cast<int*>(...) instead'
            '  [readability/casting] [4]')

        # Checks for false positives...
        self.TestLint('int a = int();', '')  # constructor
        self.TestLint('X::X() : a(int()) {}', '')  # default constructor
        self.TestLint('operator bool();', '')  # Conversion operator
        self.TestLint('new int64(123);', '')  # "new" operator on basic type
        self.TestLint('new   int64(123);', '')  # "new" operator on basic type
        self.TestLint('new const int(42);', '')  # "new" on const-qualified type
        self.TestLint('using a = bool(int arg);', '')  # C++11 alias-declaration
        self.TestLint('x = bit_cast<double(*)[3]>(y);', '')  # array of array
        self.TestLint('void F(const char(&src)[N]);', '')  # array of references

        # Placement new
        self.TestLint(
            'new(field_ptr) int(field->default_value_enum()->number());',
            '')

        # C++11 function wrappers
        self.TestLint('std::function<int(bool)>', '')
        self.TestLint('std::function<const int(bool)>', '')
        self.TestLint('std::function< int(bool) >', '')
        self.TestLint('mfunction<int(bool)>', '')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            'test.cc', 'cc',
            ['// Copyright 2014 Your Company. All Rights Reserved.',
             'typedef std::function<',
             '    bool(int)> F;',
             ''],
            error_collector)
        assert '' == error_collector.Results()

        # Return types for function pointers
        self.TestLint('typedef bool(FunctionPointer)();', '')
        self.TestLint('typedef bool(FunctionPointer)(int param);', '')
        self.TestLint('typedef bool(MyClass::*MemberFunctionPointer)();', '')
        self.TestLint('typedef bool(MyClass::* MemberFunctionPointer)();', '')
        self.TestLint('typedef bool(MyClass::*MemberFunctionPointer)() const;', '')
        self.TestLint('void Function(bool(FunctionPointerArg)());', '')
        self.TestLint('void Function(bool(FunctionPointerArg)()) {}', '')
        self.TestLint('typedef set<int64, bool(*)(int64, int64)> SortedIdSet', '')
        self.TestLint(
            'bool TraverseNode(T *Node, bool(VisitorBase:: *traverse) (T *t)) {}',
            '')

    # The second parameter to a gMock method definition is a function signature
    # that often looks like a bad cast but should not picked up by lint.
    def testMockMethod(self):
        self.TestLint(
            'MOCK_METHOD0(method, int());',
            '')
        self.TestLint(
            'MOCK_CONST_METHOD1(method, float(string));',
            '')
        self.TestLint(
            'MOCK_CONST_METHOD2_T(method, double(float, float));',
            '')
        self.TestLint(
            'MOCK_CONST_METHOD1(method, SomeType(int));',
            '')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData('mock.cc', 'cc',
                                ['MOCK_METHOD1(method1,',
                                 '             bool(int));',
                                 'MOCK_METHOD1(',
                                 '    method2,',
                                 '    bool(int));',
                                 'MOCK_CONST_METHOD2(',
                                 '    method3, bool(int,',
                                 '                  int));',
                                 'MOCK_METHOD1(method4, int(bool));',
                                 'const int kConstant = int(42);'],  # true positive
                                error_collector)
        assert 0 == error_collector.Results().count(
            ('Using deprecated casting style.  '
                'Use static_cast<bool>(...) instead  '
                '[readability/casting] [4]'))
        assert 1 == error_collector.Results().count(
                ('Using deprecated casting style.  '
                 'Use static_cast<int>(...) instead  '
                 '[readability/casting] [4]'))

    # Like gMock method definitions, MockCallback instantiations look very similar
    # to bad casts.
    def testMockCallback(self):
        self.TestLint(
            'MockCallback<bool(int)>',
            '')
        self.TestLint(
            'MockCallback<int(float, char)>',
            '')

    # Test false errors that happened with some include file names
    def testIncludeFilenameFalseError(self):
        self.TestLint(
            '#include "foo/long-foo.h"',
            '')
        self.TestLint(
            '#include "foo/sprintf.h"',
            '')

    # Test typedef cases.  There was a bug that cpplint misidentified
    # typedef for pointer to function as C-style cast and produced
    # false-positive error messages.
    def testTypedefForPointerToFunction(self):
        self.TestLint(
            'typedef void (*Func)(int x);',
            '')
        self.TestLint(
            'typedef void (*Func)(int *x);',
            '')
        self.TestLint(
            'typedef void Func(int x);',
            '')
        self.TestLint(
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
        assert (True, ''), f('a.cc' == 'a.h')
        assert (True, ''), f('base/google.cc' == 'base/google.h')
        assert (True, ''), f('base/google_test.c' == 'base/google.h')
        assert (True, ''), f('base/google_test.cc' == 'base/google.h')
        assert (True, ''), f('base/google_test.cc' == 'base/google.hpp')
        assert (True, ''), f('base/google_test.cxx' == 'base/google.hxx')
        assert (True, ''), f('base/google_test.cpp' == 'base/google.hpp')
        assert (True, ''), f('base/google_test.c++' == 'base/google.h++')
        assert (True, ''), f('base/google_test.cu' == 'base/google.cuh')
        assert (True, ''), f('base/google_unittest.cc' == 'base/google.h')
        assert (True, ''), f('base/internal/google_unittest.cc' == 'base/public/google.h')
        assert (True, 'xxx/yyy/'), f('xxx/yyy/base/internal/google_unittest.cc' == 'base/public/google.h')
        assert (True, 'xxx/yyy/'), f('xxx/yyy/base/google_unittest.cc' == 'base/public/google.h')
        assert (True, ''), f('base/google_unittest.cc' == 'base/google-inl.h')
        assert (True, '/home/build/google3/'), f('/home/build/google3/base/google.cc' == 'base/google.h')
        assert (False, ''), f('/home/build/google3/base/google.cc' == 'basu/google.h')
        assert (False, ''), f('a.cc' == 'b.h')

    def testCleanseLine(self):
        assert 'int foo = 0;' == cpplint.CleanseComments('int foo = 0;  // danger!')
        assert 'int o = 0;' == cpplint.CleanseComments('int /* foo */ o = 0;')
        assert 'foo(int a, int b);', cpplint.CleanseComments('foo(int a /* abc */ == int b);')
        assert 'f(a, b);', cpplint.CleanseComments('f(a == /* name */ b);')
        assert 'f(a, b);', cpplint.CleanseComments('f(a /* name */ == b);')
        assert 'f(a, b);', cpplint.CleanseComments('f(a == /* name */b);')
        assert 'f(a, b, c);', cpplint.CleanseComments('f(a, /**/b == /**/c);')
        assert 'f(a, b, c);', cpplint.CleanseComments('f(a, /**/b/**/ == c);')

    def testRawStrings(self):
        self.TestMultiLineLint(
            """
        int main() {
          struct A {
             A(std::string s, A&& a);
          };
        }""",
            '')
        self.TestMultiLineLint(
            """
        template <class T, class D = default_delete<T>> class unique_ptr {
         public:
            unique_ptr(unique_ptr&& u) noexcept;
        };""",
            '')
        self.TestMultiLineLint(
            """
        void Func() {
          static const char kString[] = R"(
            #endif  <- invalid preprocessor should be ignored
            */      <- invalid comment should be ignored too
          )";
        }""",
            '')
        self.TestMultiLineLint(
            """
        void Func() {
          string s = R"TrueDelimiter(
              )"
              )FalseDelimiter"
              )TrueDelimiter";
        }""",
            '')
        self.TestMultiLineLint(
            """
        void Func() {
          char char kString[] = R"(  ";" )";
        }""",
            '')
        self.TestMultiLineLint(
            """
        static const char kRawString[] = R"(
          \tstatic const int kLineWithTab = 1;
          static const int kLineWithTrailingWhiteSpace = 1;\x20

           void WeirdNumberOfSpacesAtLineStart() {
            string x;
            x += StrCat("Use StrAppend instead");
          }

          void BlankLineAtEndOfBlock() {
            // TODO incorrectly formatted
            //Badly formatted comment

          }

        )";""",
            '')
        self.TestMultiLineLint(
            """
        void Func() {
          string s = StrCat(R"TrueDelimiter(
              )"
              )FalseDelimiter"
              )TrueDelimiter", R"TrueDelimiter2(
              )"
              )FalseDelimiter2"
              )TrueDelimiter2");
        }""",
            '')
        self.TestMultiLineLint(
            """
        static SomeStruct kData = {
            {0, R"(line1
                   line2
                   )"}
            };""",
            '')

    def testMultiLineComments(self):
        # missing explicit is bad
        self.TestMultiLineLint(
            r"""int a = 0;
            /* multi-liner
            class Foo {
            Foo(int f);  // should cause a lint warning in code
            }
            */ """,
            '')
        self.TestMultiLineLint(
            r"""/* int a = 0; multi-liner
              static const int b = 0;""",
            'Could not find end of multi-line comment'
            '  [readability/multiline_comment] [5]')
        self.TestMultiLineLint(r"""  /* multi-line comment""",
                               'Could not find end of multi-line comment'
                               '  [readability/multiline_comment] [5]')
        self.TestMultiLineLint(r"""  // /* comment, but not multi-line""", '')
        self.TestMultiLineLint(r"""/**********
                                 */""", '')
        self.TestMultiLineLint(r"""/**
                                 * Doxygen comment
                                 */""",
                               '')
        self.TestMultiLineLint(r"""/*!
                                 * Doxygen comment
                                 */""",
                               '')

    def testMultilineStrings(self):
        multiline_string_error_message = (
            'Multi-line string ("...") found.  This lint script doesn\'t '
            'do well with such strings, and may give bogus warnings.  '
            'Use C++11 raw strings or concatenation instead.'
            '  [readability/multiline_string] [5]')

        for extension in ['c', 'cc', 'cpp', 'cxx', 'c++', 'cu']:
            file_path = 'mydir/foo.' + extension

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(file_path, extension,
                                    ['const char* str = "This is a\\',
                                     ' multiline string.";'],
                                    error_collector)
            assert  2 == error_collector.ResultList().count(multiline_string_error_message)

    # Test non-explicit single-argument constructors
    def testExplicitSingleArgumentConstructors(self):
        old_verbose_level = cpplint._cpplint_state.verbose_level
        cpplint._cpplint_state.verbose_level = 0

        try:
            # missing explicit is bad
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # missing explicit is bad, even with whitespace
            self.TestMultiLineLint(
                """
          class Foo {
            Foo (int f);
          };""",
                ['Extra space before ( in function call  [whitespace/parens] [4]',
                 'Single-parameter constructors should be marked explicit.'
                 '  [runtime/explicit] [5]'])
            # missing explicit, with distracting comment, is still bad
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(int f);  // simpler than Foo(blargh, blarg)
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # missing explicit, with qualified classname
            self.TestMultiLineLint(
                """
          class Qualifier::AnotherOne::Foo {
            Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # missing explicit for inline constructors is bad as well
            self.TestMultiLineLint(
                """
          class Foo {
            inline Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # missing explicit for constexpr constructors is bad as well
            self.TestMultiLineLint(
                """
          class Foo {
            constexpr Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # missing explicit for constexpr+inline constructors is bad as well
            self.TestMultiLineLint(
                """
          class Foo {
            constexpr inline Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            self.TestMultiLineLint(
                """
          class Foo {
            inline constexpr Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # explicit with inline is accepted
            self.TestMultiLineLint(
                """
          class Foo {
            inline explicit Foo(int f);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            explicit inline Foo(int f);
          };""",
                '')
            # explicit with constexpr is accepted
            self.TestMultiLineLint(
                """
          class Foo {
            constexpr explicit Foo(int f);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            explicit constexpr Foo(int f);
          };""",
                '')
            # explicit with constexpr+inline is accepted
            self.TestMultiLineLint(
                """
          class Foo {
            inline constexpr explicit Foo(int f);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            explicit inline constexpr Foo(int f);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            constexpr inline explicit Foo(int f);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            explicit constexpr inline Foo(int f);
          };""",
                '')
            # structs are caught as well.
            self.TestMultiLineLint(
                """
          struct Foo {
            Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # Templatized classes are caught as well.
            self.TestMultiLineLint(
                """
          template<typename T> class Foo {
            Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # inline case for templatized classes.
            self.TestMultiLineLint(
                """
          template<typename T> class Foo {
            inline Foo(int f);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # constructors with a default argument should still be marked explicit
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(int f = 0);
          };""",
                'Constructors callable with one argument should be marked explicit.'
                '  [runtime/explicit] [5]')
            # multi-argument constructors with all but one default argument should be
            # marked explicit
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(int f, int g = 0);
          };""",
                'Constructors callable with one argument should be marked explicit.'
                '  [runtime/explicit] [5]')
            # multi-argument constructors with all default arguments should be marked
            # explicit
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(int f = 0, int g = 0);
          };""",
                'Constructors callable with one argument should be marked explicit.'
                '  [runtime/explicit] [5]')
            # explicit no-argument constructors are bad
            self.TestMultiLineLint(
                """
          class Foo {
            explicit Foo();
          };""",
                'Zero-parameter constructors should not be marked explicit.'
                '  [runtime/explicit] [5]')
            # void constructors are considered no-argument
            self.TestMultiLineLint(
                """
          class Foo {
            explicit Foo(void);
          };""",
                'Zero-parameter constructors should not be marked explicit.'
                '  [runtime/explicit] [5]')
            # No warning for multi-parameter constructors
            self.TestMultiLineLint(
                """
          class Foo {
            explicit Foo(int f, int g);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            explicit Foo(int f, int g = 0);
          };""",
                '')
            # single-argument constructors that take a function that takes multiple
            # arguments should be explicit
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(void (*f)(int f, int g));
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # single-argument constructors that take a single template argument with
            # multiple parameters should be explicit
            self.TestMultiLineLint(
                """
          template <typename T, typename S>
          class Foo {
            Foo(Bar<T, S> b);
          };""",
                'Single-parameter constructors should be marked explicit.'
                '  [runtime/explicit] [5]')
            # but copy constructors that take multiple template parameters are OK
            self.TestMultiLineLint(
                """
          template <typename T, S>
          class Foo {
            Foo(Foo<T, S>& f);
          };""",
                '')
            # proper style is okay
            self.TestMultiLineLint(
                """
          class Foo {
            explicit Foo(int f);
          };""",
                '')
            # two argument constructor is okay
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(int f, int b);
          };""",
                '')
            # two argument constructor, across two lines, is okay
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(int f,
                int b);
          };""",
                '')
            # non-constructor (but similar name), is okay
            self.TestMultiLineLint(
                """
          class Foo {
            aFoo(int f);
          };""",
                '')
            # constructor with void argument is okay
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(void);
          };""",
                '')
            # single argument method is okay
            self.TestMultiLineLint(
                """
          class Foo {
            Bar(int b);
          };""",
                '')
            # comments should be ignored
            self.TestMultiLineLint(
                """
          class Foo {
          // Foo(int f);
          };""",
                '')
            # single argument function following class definition is okay
            # (okay, it's not actually valid, but we don't want a false positive)
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(int f, int b);
          };
          Foo(int f);""",
                '')
            # single argument function is okay
            self.TestMultiLineLint(
                """static Foo(int f);""",
                '')
            # single argument copy constructor is okay.
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(const Foo&);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(volatile Foo&);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(volatile const Foo&);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(const volatile Foo&);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(Foo const&);
          };""",
                '')
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(Foo&);
          };""",
                '')
            # templatized copy constructor is okay.
            self.TestMultiLineLint(
                """
          template<typename T> class Foo {
            Foo(const Foo<T>&);
          };""",
                '')
            # Special case for std::initializer_list
            self.TestMultiLineLint(
                """
          class Foo {
            Foo(std::initializer_list<T> &arg) {}
          };""",
                '')
            # Special case for variadic arguments
            error_collector = ErrorCollector()
            cpplint.ProcessFileData('foo.cc', 'cc',
                ['class Foo {',
                '  template<typename... Args>',
                '  explicit Foo(const int arg, Args&&... args) {}',
                '};'],
                error_collector)
            assert 0 == error_collector.ResultList().count( 'Constructors that require multiple arguments should not be marked ' 'explicit.  [runtime/explicit] [0]')
            error_collector = ErrorCollector()
            cpplint.ProcessFileData('foo.cc', 'cc',
                ['class Foo {',
                '  template<typename... Args>',
                '  explicit Foo(Args&&... args) {}',
                '};'],
                error_collector)
            assert 0 == error_collector.ResultList().count( 'Constructors that require multiple arguments should not be marked ' 'explicit.  [runtime/explicit] [0]')
            error_collector = ErrorCollector()
            cpplint.ProcessFileData('foo.cc', 'cc',
                ['class Foo {',
                '  template<typename... Args>',
                '  Foo(const int arg, Args&&... args) {}',
                '};'],
                error_collector)
            assert 1 == error_collector.ResultList().count( 'Constructors callable with one argument should be marked explicit.' '  [runtime/explicit] [5]')
            error_collector = ErrorCollector()
            cpplint.ProcessFileData('foo.cc', 'cc',
                ['class Foo {',
                '  template<typename... Args>',
                '  Foo(Args&&... args) {}',
                '};'],
                error_collector)
            assert 1 == error_collector.ResultList().count( 'Constructors callable with one argument should be marked explicit.' '  [runtime/explicit] [5]')
            # Anything goes inside an assembly block
            error_collector = ErrorCollector()
            cpplint.ProcessFileData('foo.cc', 'cc',
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

    def testSlashStarCommentOnSingleLine(self):
        self.TestMultiLineLint(
            """/* static */ Foo(int f);""",
            '')
        self.TestMultiLineLint(
            """/*/ static */  Foo(int f);""",
            '')
        self.TestMultiLineLint(
            """/*/ static Foo(int f);""",
            'Could not find end of multi-line comment'
            '  [readability/multiline_comment] [5]')
        self.TestMultiLineLint(
            """  /*/ static Foo(int f);""",
            'Could not find end of multi-line comment'
            '  [readability/multiline_comment] [5]')
        self.TestMultiLineLint(
            """  /**/ static Foo(int f);""",
            '')

    # Test suspicious usage of "if" like this:
    # if (a == b) {
    #   DoSomething();
    # } if (a == c) {   // Should be "else if".
    #   DoSomething();  // This gets called twice if a == b && a == c.
    # }
    def testSuspiciousUsageOfIf(self):
        self.TestLint(
            '  if (a == b) {',
            '')
        self.TestLint(
            '  } if (a == b) {',
            'Did you mean "else if"? If not, start a new line for "if".'
            '  [readability/braces] [4]')

    # Test suspicious usage of memset. Specifically, a 0
    # as the final argument is almost certainly an error.
    def testSuspiciousUsageOfMemset(self):
        # Normal use is okay.
        self.TestLint(
            '  memset(buf, 0, sizeof(buf))',
            '')

        # A 0 as the final argument is almost certainly an error.
        self.TestLint(
            '  memset(buf, sizeof(buf), 0)',
            'Did you mean "memset(buf, 0, sizeof(buf))"?'
            '  [runtime/memset] [4]')
        self.TestLint(
            '  memset(buf, xsize * ysize, 0)',
            'Did you mean "memset(buf, 0, xsize * ysize)"?'
            '  [runtime/memset] [4]')

        # There is legitimate test code that uses this form.
        # This is okay since the second argument is a literal.
        self.TestLint(
            "  memset(buf, 'y', 0)",
            '')
        self.TestLint(
            '  memset(buf, 4, 0)',
            '')
        self.TestLint(
            '  memset(buf, -1, 0)',
            '')
        self.TestLint(
            '  memset(buf, 0xF1, 0)',
            '')
        self.TestLint(
            '  memset(buf, 0xcd, 0)',
            '')

    def testRedundantVirtual(self):
        self.TestLint('virtual void F()', '')
        self.TestLint('virtual void F();', '')
        self.TestLint('virtual void F() {}', '')

        message_template = ('"%s" is redundant since function is already '
                            'declared as "%s"  [readability/inheritance] [4]')
        for virt_specifier in ['override', 'final']:
            error_message = message_template % ('virtual', virt_specifier)
            self.TestLint('virtual int F() %s' % virt_specifier, error_message)
            self.TestLint('virtual int F() %s;' % virt_specifier, error_message)
            self.TestLint('virtual int F() %s {' % virt_specifier, error_message)

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(
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
        self.TestLint('int F() override final', error_message)
        self.TestLint('int F() override final;', error_message)
        self.TestLint('int F() override final {}', error_message)
        self.TestLint('int F() final override', error_message)
        self.TestLint('int F() final override;', error_message)
        self.TestLint('int F() final override {}', error_message)

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
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

        self.TestLint('void Finalize(AnnotationProto *final) override;', '')

    def testCheckDeprecated(self):
        self.TestLanguageRulesCheck('foo_test.cc', '#include <iostream>', '')
        self.TestLanguageRulesCheck('foo_unittest.cc', '#include <iostream>', '')

    def testCheckPosixThreading(self):
        self.TestLint('var = sctime_r()', '')
        self.TestLint('var = strtok_r()', '')
        self.TestLint('var = strtok_r(foo, ba, r)', '')
        self.TestLint('var = brand()', '')
        self.TestLint('_rand()', '')
        self.TestLint('.rand()', '')
        self.TestLint('->rand()', '')
        self.TestLint('ACMRandom rand(seed)', '')
        self.TestLint('ISAACRandom rand()', '')
        self.TestLint('var = rand()',
                      'Consider using rand_r(...) instead of rand(...)'
                      ' for improved thread safety.'
                      '  [runtime/threadsafe_fn] [2]')
        self.TestLint('var = strtok(str, delim)',
                      'Consider using strtok_r(...) '
                      'instead of strtok(...)'
                      ' for improved thread safety.'
                      '  [runtime/threadsafe_fn] [2]')

    def testVlogMisuse(self):
        self.TestLint('VLOG(1)', '')
        self.TestLint('VLOG(99)', '')
        self.TestLint('LOG(ERROR)', '')
        self.TestLint('LOG(INFO)', '')
        self.TestLint('LOG(WARNING)', '')
        self.TestLint('LOG(FATAL)', '')
        self.TestLint('LOG(DFATAL)', '')
        self.TestLint('VLOG(SOMETHINGWEIRD)', '')
        self.TestLint('MYOWNVLOG(ERROR)', '')
        errmsg = ('VLOG() should be used with numeric verbosity level.  '
                  'Use LOG() if you want symbolic severity levels.'
                  '  [runtime/vlog] [5]')
        self.TestLint('VLOG(ERROR)', errmsg)
        self.TestLint('VLOG(INFO)', errmsg)
        self.TestLint('VLOG(WARNING)', errmsg)
        self.TestLint('VLOG(FATAL)', errmsg)
        self.TestLint('VLOG(DFATAL)', errmsg)
        self.TestLint('  VLOG(ERROR)', errmsg)
        self.TestLint('  VLOG(INFO)', errmsg)
        self.TestLint('  VLOG(WARNING)', errmsg)
        self.TestLint('  VLOG(FATAL)', errmsg)
        self.TestLint('  VLOG(DFATAL)', errmsg)

    # Test potential format string bugs like printf(foo).
    def testFormatStrings(self):
        self.TestLint('printf("foo")', '')
        self.TestLint('printf("foo: %s", foo)', '')
        self.TestLint('DocidForPrintf(docid)', '')  # Should not trigger.
        self.TestLint('printf(format, value)', '')  # Should not trigger.
        self.TestLint('printf(__VA_ARGS__)', '')  # Should not trigger.
        self.TestLint('printf(format.c_str(), value)', '')  # Should not trigger.
        self.TestLint('printf(format(index).c_str(), value)', '')
        self.TestLint(
            'printf(foo)',
            'Potential format string bug. Do printf("%s", foo) instead.'
            '  [runtime/printf] [4]')
        self.TestLint(
            'printf(foo.c_str())',
            'Potential format string bug. '
            'Do printf("%s", foo.c_str()) instead.'
            '  [runtime/printf] [4]')
        self.TestLint(
            'printf(foo->c_str())',
            'Potential format string bug. '
            'Do printf("%s", foo->c_str()) instead.'
            '  [runtime/printf] [4]')
        self.TestLint(
            'StringPrintf(foo)',
            'Potential format string bug. Do StringPrintf("%s", foo) instead.'
            ''
            '  [runtime/printf] [4]')

    # Test disallowed use of operator& and other operators.
    def testIllegalOperatorOverloading(self):
        errmsg = ('Unary operator& is dangerous.  Do not use it.'
                  '  [runtime/operator] [4]')
        self.TestLint('void operator=(const Myclass&)', '')
        self.TestLint('void operator&(int a, int b)', '')   # binary operator& ok
        self.TestLint('void operator&() { }', errmsg)
        self.TestLint('void operator & (  ) { }',
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

        self.TestLint('void f(const string&)', '')
        self.TestLint('const string& f(const string& a, const string& b)', '')
        self.TestLint('typedef const string& A;', '')

        for decl in members_declarations:
            self.TestLint(decl + ' = b;', '')
            self.TestLint(decl + '      =', '')

        # The Bad.

        for decl in members_declarations:
            self.TestLint(decl + ';', errmsg)

    # Variable-length arrays are not permitted.
    def testVariableLengthArrayDetection(self):
        errmsg = ('Do not use variable-length arrays.  Use an appropriately named '
                  "('k' followed by CamelCase) compile-time constant for the size."
                  '  [runtime/arrays] [1]')

        self.TestLint('int a[any_old_variable];', errmsg)
        self.TestLint('int doublesize[some_var * 2];', errmsg)
        self.TestLint('int a[afunction()];', errmsg)
        self.TestLint('int a[function(kMaxFooBars)];', errmsg)
        self.TestLint('bool a_list[items_->size()];', errmsg)
        self.TestLint('namespace::Type buffer[len+1];', errmsg)

        self.TestLint('int a[64];', '')
        self.TestLint('int a[0xFF];', '')
        self.TestLint('int first[256], second[256];', '')
        self.TestLint('int array_name[kCompileTimeConstant];', '')
        self.TestLint('char buf[somenamespace::kBufSize];', '')
        self.TestLint('int array_name[ALL_CAPS];', '')
        self.TestLint('AClass array1[foo::bar::ALL_CAPS];', '')
        self.TestLint('int a[kMaxStrLen + 1];', '')
        self.TestLint('int a[sizeof(foo)];', '')
        self.TestLint('int a[sizeof(*foo)];', '')
        self.TestLint('int a[sizeof foo];', '')
        self.TestLint('int a[sizeof(struct Foo)];', '')
        self.TestLint('int a[128 - sizeof(const bar)];', '')
        self.TestLint('int a[(sizeof(foo) * 4)];', '')
        self.TestLint('int a[(arraysize(fixed_size_array)/2) << 1];', '')
        self.TestLint('delete a[some_var];', '')
        self.TestLint('return a[some_var];', '')

    # DISALLOW_COPY_AND_ASSIGN and DISALLOW_IMPLICIT_CONSTRUCTORS should be at
    # end of class if present.
    def testDisallowMacrosAtEnd(self):
        for macro_name in (
            'DISALLOW_COPY_AND_ASSIGN',
            'DISALLOW_IMPLICIT_CONSTRUCTORS'):
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(
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
            cpplint.ProcessFileData(
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
            cpplint.ProcessFileData(
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
    def testBraces(self):
        # Braces shouldn't be followed by a ; unless they're defining a struct
        # or initializing an array
        self.TestLint('int a[3] = { 1, 2, 3 };', '')
        self.TestLint(
            """const int foo[] =
               {1, 2, 3 };""",
            '')
        # For single line, unmatched '}' with a ';' is ignored (not enough context)
        self.TestMultiLineLint(
            """int a[3] = { 1,
                        2,
                        3 };""",
            '')
        self.TestMultiLineLint(
            """int a[2][3] = { { 1, 2 },
                         { 3, 4 } };""",
            '')
        self.TestMultiLineLint(
            """int a[2][3] =
               { { 1, 2 },
                 { 3, 4 } };""",
            '')

    # CHECK/EXPECT_TRUE/EXPECT_FALSE replacements
    def testCheckCheck(self):
        self.TestLint('CHECK(x == 42);',
                      'Consider using CHECK_EQ instead of CHECK(a == b)'
                      '  [readability/check] [2]')
        self.TestLint('CHECK(x != 42);',
                      'Consider using CHECK_NE instead of CHECK(a != b)'
                      '  [readability/check] [2]')
        self.TestLint('CHECK(x >= 42);',
                      'Consider using CHECK_GE instead of CHECK(a >= b)'
                      '  [readability/check] [2]')
        self.TestLint('CHECK(x > 42);',
                      'Consider using CHECK_GT instead of CHECK(a > b)'
                      '  [readability/check] [2]')
        self.TestLint('CHECK(x <= 42);',
                      'Consider using CHECK_LE instead of CHECK(a <= b)'
                      '  [readability/check] [2]')
        self.TestLint('CHECK(x < 42);',
                      'Consider using CHECK_LT instead of CHECK(a < b)'
                      '  [readability/check] [2]')

        self.TestLint('DCHECK(x == 42);',
                      'Consider using DCHECK_EQ instead of DCHECK(a == b)'
                      '  [readability/check] [2]')
        self.TestLint('DCHECK(x != 42);',
                      'Consider using DCHECK_NE instead of DCHECK(a != b)'
                      '  [readability/check] [2]')
        self.TestLint('DCHECK(x >= 42);',
                      'Consider using DCHECK_GE instead of DCHECK(a >= b)'
                      '  [readability/check] [2]')
        self.TestLint('DCHECK(x > 42);',
                      'Consider using DCHECK_GT instead of DCHECK(a > b)'
                      '  [readability/check] [2]')
        self.TestLint('DCHECK(x <= 42);',
                      'Consider using DCHECK_LE instead of DCHECK(a <= b)'
                      '  [readability/check] [2]')
        self.TestLint('DCHECK(x < 42);',
                      'Consider using DCHECK_LT instead of DCHECK(a < b)'
                      '  [readability/check] [2]')

        self.TestLint(
            'EXPECT_TRUE("42" == x);',
            'Consider using EXPECT_EQ instead of EXPECT_TRUE(a == b)'
            '  [readability/check] [2]')
        self.TestLint(
            'EXPECT_TRUE("42" != x);',
            'Consider using EXPECT_NE instead of EXPECT_TRUE(a != b)'
            '  [readability/check] [2]')
        self.TestLint(
            'EXPECT_TRUE(+42 >= x);',
            'Consider using EXPECT_GE instead of EXPECT_TRUE(a >= b)'
            '  [readability/check] [2]')

        self.TestLint(
            'EXPECT_FALSE(x == 42);',
            'Consider using EXPECT_NE instead of EXPECT_FALSE(a == b)'
            '  [readability/check] [2]')
        self.TestLint(
            'EXPECT_FALSE(x != 42);',
            'Consider using EXPECT_EQ instead of EXPECT_FALSE(a != b)'
            '  [readability/check] [2]')
        self.TestLint(
            'EXPECT_FALSE(x >= 42);',
            'Consider using EXPECT_LT instead of EXPECT_FALSE(a >= b)'
            '  [readability/check] [2]')
        self.TestLint(
            'ASSERT_FALSE(x > 42);',
            'Consider using ASSERT_LE instead of ASSERT_FALSE(a > b)'
            '  [readability/check] [2]')
        self.TestLint(
            'ASSERT_FALSE(x <= 42);',
            'Consider using ASSERT_GT instead of ASSERT_FALSE(a <= b)'
            '  [readability/check] [2]')

        self.TestLint('CHECK(x<42);',
                      ['Missing spaces around <'
                       '  [whitespace/operators] [3]',
                       'Consider using CHECK_LT instead of CHECK(a < b)'
                       '  [readability/check] [2]'])
        self.TestLint('CHECK(x>42);',
                      ['Missing spaces around >'
                       '  [whitespace/operators] [3]',
                       'Consider using CHECK_GT instead of CHECK(a > b)'
                       '  [readability/check] [2]'])

        self.TestLint('using some::namespace::operator<<;', '')
        self.TestLint('using some::namespace::operator>>;', '')

        self.TestLint('CHECK(x->y == 42);',
                      'Consider using CHECK_EQ instead of CHECK(a == b)'
                      '  [readability/check] [2]')

        self.TestLint(
            '  EXPECT_TRUE(42 < x);  // Random comment.',
            'Consider using EXPECT_LT instead of EXPECT_TRUE(a < b)'
            '  [readability/check] [2]')
        self.TestLint(
            'EXPECT_TRUE( 42 < x );',
            ['Extra space after ( in function call'
             '  [whitespace/parens] [4]',
             'Extra space before )  [whitespace/parens] [2]',
             'Consider using EXPECT_LT instead of EXPECT_TRUE(a < b)'
             '  [readability/check] [2]'])

        self.TestLint('CHECK(4\'2 == x);',
                      'Consider using CHECK_EQ instead of CHECK(a == b)'
                      '  [readability/check] [2]')

    def testCheckCheckFalsePositives(self):
        self.TestLint('CHECK(some_iterator == obj.end());', '')
        self.TestLint('EXPECT_TRUE(some_iterator == obj.end());', '')
        self.TestLint('EXPECT_FALSE(some_iterator == obj.end());', '')
        self.TestLint('CHECK(some_pointer != NULL);', '')
        self.TestLint('EXPECT_TRUE(some_pointer != NULL);', '')
        self.TestLint('EXPECT_FALSE(some_pointer != NULL);', '')

        self.TestLint('CHECK(CreateTestFile(dir, (1 << 20)));', '')
        self.TestLint('CHECK(CreateTestFile(dir, (1 >> 20)));', '')

        self.TestLint('CHECK(x ^ (y < 42));', '')
        self.TestLint('CHECK((x > 42) ^ (x < 54));', '')
        self.TestLint('CHECK(a && b < 42);', '')
        self.TestLint('CHECK(42 < a && a < b);', '')
        self.TestLint('SOFT_CHECK(x > 42);', '')

        self.TestMultiLineLint(
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

        self.TestLint('CHECK(x < 42) << "Custom error message";', '')

    # Alternative token to punctuation operator replacements
    def testCheckAltTokens(self):
        self.TestLint('true or true',
                      'Use operator || instead of or'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('true and true',
                      'Use operator && instead of and'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('if (not true)',
                      'Use operator ! instead of not'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('1 bitor 1',
                      'Use operator | instead of bitor'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('1 xor 1',
                      'Use operator ^ instead of xor'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('1 bitand 1',
                      'Use operator & instead of bitand'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('x = compl 1',
                      'Use operator ~ instead of compl'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('x and_eq y',
                      'Use operator &= instead of and_eq'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('x or_eq y',
                      'Use operator |= instead of or_eq'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('x xor_eq y',
                      'Use operator ^= instead of xor_eq'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('x not_eq y',
                      'Use operator != instead of not_eq'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('line_continuation or',
                      'Use operator || instead of or'
                      '  [readability/alt_tokens] [2]')
        self.TestLint('if(true and(parentheses',
                      'Use operator && instead of and'
                      '  [readability/alt_tokens] [2]')

        self.TestLint('#include "base/false-and-false.h"', '')
        self.TestLint('#error false or false', '')
        self.TestLint('false nor false', '')
        self.TestLint('false nand false', '')

    # Passing and returning non-const references
    def testNonConstReference(self):
        # Passing a non-const reference as function parameter is forbidden.
        operand_error_message = ('Is this a non-const reference? '
                                 'If so, make const or use a pointer: %s'
                                 '  [runtime/references] [2]')
        # Warn of use of a non-const reference in operators and functions
        self.TestLint('bool operator>(Foo& s, Foo& f);',
                      [operand_error_message % 'Foo& s',
                       operand_error_message % 'Foo& f'])
        self.TestLint('bool operator+(Foo& s, Foo& f);',
                      [operand_error_message % 'Foo& s',
                       operand_error_message % 'Foo& f'])
        self.TestLint('int len(Foo& s);', operand_error_message % 'Foo& s')
        # Allow use of non-const references in a few specific cases
        self.TestLint('stream& operator>>(stream& s, Foo& f);', '')
        self.TestLint('stream& operator<<(stream& s, Foo& f);', '')
        self.TestLint('void swap(Bar& a, Bar& b);', '')
        self.TestLint('ostream& LogFunc(ostream& s);', '')
        self.TestLint('ostringstream& LogFunc(ostringstream& s);', '')
        self.TestLint('istream& LogFunc(istream& s);', '')
        self.TestLint('istringstream& LogFunc(istringstream& s);', '')
        # Returning a non-const reference from a function is OK.
        self.TestLint('int& g();', '')
        # Passing a const reference to a struct (using the struct keyword) is OK.
        self.TestLint('void foo(const struct tm& tm);', '')
        # Passing a const reference to a typename is OK.
        self.TestLint('void foo(const typename tm& tm);', '')
        # Const reference to a pointer type is OK.
        self.TestLint('void foo(const Bar* const& p) {', '')
        self.TestLint('void foo(Bar const* const& p) {', '')
        self.TestLint('void foo(Bar* const& p) {', '')
        # Const reference to a templated type is OK.
        self.TestLint('void foo(const std::vector<std::string>& v);', '')
        # Non-const reference to a pointer type is not OK.
        self.TestLint('void foo(Bar*& p);',
                      operand_error_message % 'Bar*& p')
        self.TestLint('void foo(const Bar*& p);',
                      operand_error_message % 'const Bar*& p')
        self.TestLint('void foo(Bar const*& p);',
                      operand_error_message % 'Bar const*& p')
        self.TestLint('void foo(struct Bar*& p);',
                      operand_error_message % 'struct Bar*& p')
        self.TestLint('void foo(const struct Bar*& p);',
                      operand_error_message % 'const struct Bar*& p')
        self.TestLint('void foo(struct Bar const*& p);',
                      operand_error_message % 'struct Bar const*& p')
        # Non-const reference to a templated type is not OK.
        self.TestLint('void foo(std::vector<int>& p);',
                      operand_error_message % 'std::vector<int>& p')
        # Returning an address of something is not prohibited.
        self.TestLint('return &something;', '')
        self.TestLint('if (condition) {return &something; }', '')
        self.TestLint('if (condition) return &something;', '')
        self.TestLint('if (condition) address = &something;', '')
        self.TestLint('if (condition) result = lhs&rhs;', '')
        self.TestLint('if (condition) result = lhs & rhs;', '')
        self.TestLint('a = (b+c) * sizeof &f;', '')
        self.TestLint('a = MySize(b) * sizeof &f;', '')
        # We don't get confused by C++11 range-based for loops.
        self.TestLint('for (const string& s : c)', '')
        self.TestLint('for (auto& r : c)', '')
        self.TestLint('for (typename Type& a : b)', '')
        # We don't get confused by some other uses of '&'.
        self.TestLint('T& operator=(const T& t);', '')
        self.TestLint('int g() { return (a & b); }', '')
        self.TestLint('T& r = (T&)*(vp());', '')
        self.TestLint('T& r = v', '')
        self.TestLint('static_assert((kBits & kMask) == 0, "text");', '')
        self.TestLint('COMPILE_ASSERT((kBits & kMask) == 0, text);', '')
        # Spaces before template arguments.  This is poor style, but
        # happens 0.15% of the time.
        self.TestLint('void Func(const vector <int> &const_x, '
                      'vector <int> &nonconst_x) {',
                      operand_error_message % 'vector<int> &nonconst_x')

        # Derived member functions are spared from override check
        self.TestLint('void Func(X& x);', operand_error_message % 'X& x')
        self.TestLint('void Func(X& x) {}', operand_error_message % 'X& x')
        self.TestLint('void Func(X& x) override;', '')
        self.TestLint('void Func(X& x) override {', '')
        self.TestLint('void Func(X& x) const override;', '')
        self.TestLint('void Func(X& x) const override {', '')

        # Don't warn on out-of-line method definitions.
        self.TestLint('void NS::Func(X& x) {', '')
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            'foo.cc', 'cc',
            ['// Copyright 2014 Your Company. All Rights Reserved.',
             'void a::b() {}',
             'void f(int& q) {}',
             ''],
            error_collector)
        assert operand_error_message % 'int& q' == error_collector.Results()

        # Other potential false positives.  These need full parser
        # state to reproduce as opposed to just TestLint.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
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

    def testBraceAtBeginOfLine(self):
        self.TestLint('{',
                      '{ should almost always be at the end of the previous line'
                      '  [whitespace/braces] [4]')

        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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

        self.TestMultiLineLint(
            """
        foo(
          {
            loooooooooooooooong_value,
          });""",
            '')

    def testMismatchingSpacesInParens(self):
        self.TestLint('if (foo ) {', 'Mismatching spaces inside () in if'
                      '  [whitespace/parens] [5]')
        self.TestLint('switch ( foo) {', 'Mismatching spaces inside () in switch'
                      '  [whitespace/parens] [5]')
        self.TestLint('for (foo; ba; bar ) {', 'Mismatching spaces inside () in for'
                      '  [whitespace/parens] [5]')
        self.TestLint('for (; foo; bar) {', '')
        self.TestLint('for ( ; foo; bar) {', '')
        self.TestLint('for ( ; foo; bar ) {', '')
        self.TestLint('for (foo; bar; ) {', '')
        self.TestLint('while (  foo  ) {', 'Should have zero or one spaces inside'
                      ' ( and ) in while  [whitespace/parens] [5]')

    def testSpacingForFncall(self):
        self.TestLint('if (foo) {', '')
        self.TestLint('for (foo; bar; baz) {', '')
        self.TestLint('for (;;) {', '')
        # Space should be allowed in placement new operators.
        self.TestLint('Something* p = new (place) Something();', '')
        # Test that there is no warning when increment statement is empty.
        self.TestLint('for (foo; baz;) {', '')
        self.TestLint('for (foo;bar;baz) {', 'Missing space after ;'
                      '  [whitespace/semicolon] [3]')
        # we don't warn about this semicolon, at least for now
        self.TestLint('if (condition) {return &something; }',
                      '')
        # seen in some macros
        self.TestLint('DoSth();\\', '')
        # Test that there is no warning about semicolon here.
        self.TestLint('abc;// this is abc',
                      'At least two spaces is best between code'
                      ' and comments  [whitespace/comments] [2]')
        self.TestLint('while (foo) {', '')
        self.TestLint('switch (foo) {', '')
        self.TestLint('foo( bar)', 'Extra space after ( in function call'
                      '  [whitespace/parens] [4]')
        self.TestLint('foo(  // comment', '')
        self.TestLint('foo( // comment',
                      'At least two spaces is best between code'
                      ' and comments  [whitespace/comments] [2]')
        self.TestLint('foobar( \\', '')
        self.TestLint('foobar(     \\', '')
        self.TestLint('( a + b)', 'Extra space after ('
                      '  [whitespace/parens] [2]')
        self.TestLint('((a+b))', '')
        self.TestLint('foo (foo)', 'Extra space before ( in function call'
                      '  [whitespace/parens] [4]')
        # asm volatile () may have a space, as it isn't a function call.
        self.TestLint('asm volatile ("")', '')
        self.TestLint('__asm__ __volatile__ ("")', '')
        self.TestLint('} catch (const Foo& ex) {', '')
        self.TestLint('case (42):', '')
        self.TestLint('typedef foo (*foo)(foo)', '')
        self.TestLint('typedef foo (*foo12bar_)(foo)', '')
        self.TestLint('typedef foo (Foo::*bar)(foo)', '')
        self.TestLint('using foo = type (Foo::*bar)(foo)', '')
        self.TestLint('using foo = type (Foo::*bar)(', '')
        self.TestLint('using foo = type (Foo::*)(', '')
        self.TestLint('foo (Foo::*bar)(', '')
        self.TestLint('foo (x::y::*z)(', '')
        self.TestLint('foo (Foo::bar)(',
                      'Extra space before ( in function call'
                      '  [whitespace/parens] [4]')
        self.TestLint('foo (*bar)(', '')
        self.TestLint('typedef foo (Foo::*bar)(', '')
        self.TestLint('(foo)(bar)', '')
        self.TestLint('Foo (*foo)(bar)', '')
        self.TestLint('Foo (*foo)(Bar bar,', '')
        self.TestLint('char (*p)[sizeof(foo)] = &foo', '')
        self.TestLint('char (&ref)[sizeof(foo)] = &foo', '')
        self.TestLint('const char32 (*table[])[6];', '')
        # The sizeof operator is often written as if it were a function call, with
        # an opening parenthesis directly following the operator name, but it can
        # also be written like any other operator, with a space following the
        # operator name, and the argument optionally in parentheses.
        self.TestLint('sizeof(foo)', '')
        self.TestLint('sizeof foo', '')
        self.TestLint('sizeof (foo)', '')

    def testSpacingBeforeBraces(self):
        self.TestLint('if (foo){', 'Missing space before {'
                      '  [whitespace/braces] [5]')
        self.TestLint('for{', 'Missing space before {'
                      '  [whitespace/braces] [5]')
        self.TestLint('for {', '')
        self.TestLint('EXPECT_DEBUG_DEATH({', '')
        self.TestLint('std::is_convertible<A, B>{}', '')
        self.TestLint('blah{32}', 'Missing space before {'
                      '  [whitespace/braces] [5]')
        self.TestLint('int8_t{3}', '')
        self.TestLint('int16_t{3}', '')
        self.TestLint('int32_t{3}', '')
        self.TestLint('uint64_t{12345}', '')
        self.TestLint('constexpr int64_t kBatchGapMicros ='
                      ' int64_t{7} * 24 * 3600 * 1000000;  // 1 wk.', '')
        self.TestLint('MoveOnly(int i1, int i2) : ip1{new int{i1}}, '
                      'ip2{new int{i2}} {}',
                      '')

    def testSemiColonAfterBraces(self):
        self.TestLint('if (cond) { func(); };',
                      'You don\'t need a ; after a }  [readability/braces] [4]')
        self.TestLint('void Func() {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')
        self.TestLint('void Func() const {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')
        self.TestLint('class X {};', '')
        for keyword in ['struct', 'union']:
            for align in ['', ' alignas(16)']:
                for typename in ['', ' X']:
                    for identifier in ['', ' x']:
                        self.TestLint(keyword + align + typename + ' {}' + identifier + ';',
                                      '')

        self.TestLint('class X : public Y {};', '')
        self.TestLint('class X : public MACRO() {};', '')
        self.TestLint('class X : public decltype(expr) {};', '')
        self.TestLint('DEFINE_FACADE(PCQueue::Watcher, PCQueue) {};', '')
        self.TestLint('VCLASS(XfaTest, XfaContextTest) {};', '')
        self.TestLint('class STUBBY_CLASS(H, E) {};', '')
        self.TestLint('class STUBBY2_CLASS(H, E) {};', '')
        self.TestLint('TEST(TestCase, TestName) {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')
        self.TestLint('TEST_F(TestCase, TestName) {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')

        self.TestLint('file_tocs_[i] = (FileToc) {a, b, c};', '')
        self.TestMultiLineLint('class X : public Y,\npublic Z {};', '')

    def testSpacingBeforeBrackets(self):
        self.TestLint('int numbers [] = { 1, 2, 3 };',
                      'Extra space before [  [whitespace/braces] [5]')
        # space allowed in some cases
        self.TestLint('auto [abc, def] = func();', '')
        self.TestLint('#define NODISCARD [[nodiscard]]', '')
        self.TestLint('void foo(int param [[maybe_unused]]);', '')

    def testLambda(self):
        self.TestLint('auto x = []() {};', '')
        self.TestLint('return []() {};', '')
        self.TestMultiLineLint('auto x = []() {\n};\n', '')
        self.TestLint('int operator[](int x) {};',
                      'You don\'t need a ; after a }  [readability/braces] [4]')

        self.TestMultiLineLint('auto x = [&a,\nb]() {};', '')
        self.TestMultiLineLint('auto x = [&a,\nb]\n() {};', '')
        self.TestMultiLineLint('auto x = [&a,\n'
                               '          b](\n'
                               '    int a,\n'
                               '    int b) {\n'
                               '  return a +\n'
                               '         b;\n'
                               '};\n',
                               '')

        # Avoid false positives with operator[]
        self.TestLint('table_to_children[&*table].push_back(dependent);', '')

    def testBraceInitializerList(self):
        self.TestLint('MyStruct p = {1, 2};', '')
        self.TestLint('MyStruct p{1, 2};', '')
        self.TestLint('vector<int> p = {1, 2};', '')
        self.TestLint('vector<int> p{1, 2};', '')
        self.TestLint('x = vector<int>{1, 2};', '')
        self.TestLint('x = (struct in_addr){ 0 };', '')
        self.TestLint('Func(vector<int>{1, 2})', '')
        self.TestLint('Func((struct in_addr){ 0 })', '')
        self.TestLint('Func(vector<int>{1, 2}, 3)', '')
        self.TestLint('Func((struct in_addr){ 0 }, 3)', '')
        self.TestLint('LOG(INFO) << char{7};', '')
        self.TestLint('LOG(INFO) << char{7} << "!";', '')
        self.TestLint('int p[2] = {1, 2};', '')
        self.TestLint('return {1, 2};', '')
        self.TestLint('std::unique_ptr<Foo> foo{new Foo{}};', '')
        self.TestLint('auto foo = std::unique_ptr<Foo>{new Foo{}};', '')
        self.TestLint('static_assert(Max7String{}.IsValid(), "");', '')
        self.TestLint('map_of_pairs[{1, 2}] = 3;', '')
        self.TestLint('ItemView{has_offer() ? new Offer{offer()} : nullptr', '')
        self.TestLint('template <class T, EnableIf<::std::is_const<T>{}> = 0>', '')

        self.TestMultiLineLint('std::unique_ptr<Foo> foo{\n'
                               '  new Foo{}\n'
                               '};\n', '')
        self.TestMultiLineLint('std::unique_ptr<Foo> foo{\n'
                               '  new Foo{\n'
                               '    new Bar{}\n'
                               '  }\n'
                               '};\n', '')
        self.TestMultiLineLint('if (true) {\n'
                               '  if (false){ func(); }\n'
                               '}\n',
                               'Missing space before {  [whitespace/braces] [5]')
        self.TestMultiLineLint('MyClass::MyClass()\n'
                               '    : initializer_{\n'
                               '          Func()} {\n'
                               '}\n', '')
        self.TestLint('const pair<string, string> kCL' +
                      ('o' * 41) + 'gStr[] = {\n',
                      'Lines should be <= 80 characters long'
                      '  [whitespace/line_length] [2]')
        self.TestMultiLineLint('const pair<string, string> kCL' +
                               ('o' * 40) + 'ngStr[] =\n'
                               '    {\n'
                               '        {"gooooo", "oooogle"},\n'
                               '};\n', '')
        self.TestMultiLineLint('const pair<string, string> kCL' +
                               ('o' * 39) + 'ngStr[] =\n'
                               '    {\n'
                               '        {"gooooo", "oooogle"},\n'
                               '};\n', '{ should almost always be at the end of '
                               'the previous line  [whitespace/braces] [4]')

    def testSpacingAroundElse(self):
        self.TestLint('}else {', 'Missing space before else'
                      '  [whitespace/braces] [5]')
        self.TestLint('} else{', 'Missing space before {'
                      '  [whitespace/braces] [5]')
        self.TestLint('} else {', '')
        self.TestLint('} else if (foo) {', '')

    def testSpacingWithInitializerLists(self):
        self.TestLint('int v[1][3] = {{1, 2, 3}};', '')
        self.TestLint('int v[1][1] = {{0}};', '')

    def testSpacingForBinaryOps(self):
        self.TestLint('if (foo||bar) {', 'Missing spaces around ||'
                      '  [whitespace/operators] [3]')
        self.TestLint('if (foo<=bar) {', 'Missing spaces around <='
                      '  [whitespace/operators] [3]')
        self.TestLint('if (foo<bar) {', 'Missing spaces around <'
                      '  [whitespace/operators] [3]')
        self.TestLint('if (foo>bar) {', 'Missing spaces around >'
                      '  [whitespace/operators] [3]')
        self.TestLint('if (foo<bar->baz) {', 'Missing spaces around <'
                      '  [whitespace/operators] [3]')
        self.TestLint('if (foo<bar->bar) {', 'Missing spaces around <'
                      '  [whitespace/operators] [3]')
        self.TestLint('template<typename T = double>', '')
        self.TestLint('std::unique_ptr<No<Spaces>>', '')
        self.TestLint('typedef hash_map<Foo, Bar>', '')
        self.TestLint('10<<20', '')
        self.TestLint('10<<a',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestLint('a<<20',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestLint('a<<b',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestLint('10LL<<20', '')
        self.TestLint('10ULL<<20', '')
        self.TestLint('a>>b',
                      'Missing spaces around >>  [whitespace/operators] [3]')
        self.TestLint('10>>b',
                      'Missing spaces around >>  [whitespace/operators] [3]')
        self.TestLint('LOG(ERROR)<<*foo',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestLint('LOG(ERROR)<<&foo',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestLint('StringCoder<vector<string>>::ToString()', '')
        self.TestLint('map<pair<int16, int16>, map<int16, int16>>::iterator', '')
        self.TestLint('func<int16, pair<int16, pair<int16, int16>>>()', '')
        self.TestLint('MACRO1(list<list<int16>>)', '')
        self.TestLint('MACRO2(list<list<int16>>, 42)', '')
        self.TestLint('void DoFoo(const set<vector<string>>& arg1);', '')
        self.TestLint('void SetFoo(set<vector<string>>* arg1);', '')
        self.TestLint('foo = new set<vector<string>>;', '')
        self.TestLint('reinterpret_cast<set<vector<string>>*>(a);', '')
        self.TestLint('MACRO(<<)', '')
        self.TestLint('MACRO(<<, arg)', '')
        self.TestLint('MACRO(<<=)', '')
        self.TestLint('MACRO(<<=, arg)', '')

        self.TestLint('using Vector3<T>::operator==;', '')
        self.TestLint('using Vector3<T>::operator!=;', '')

    def testSpacingBeforeLastSemicolon(self):
        self.TestLint('call_function() ;',
                      'Extra space before last semicolon. If this should be an '
                      'empty statement, use {} instead.'
                      '  [whitespace/semicolon] [5]')
        self.TestLint('while (true) ;',
                      'Extra space before last semicolon. If this should be an '
                      'empty statement, use {} instead.'
                      '  [whitespace/semicolon] [5]')
        self.TestLint('default:;',
                      'Semicolon defining empty statement. Use {} instead.'
                      '  [whitespace/semicolon] [5]')
        self.TestLint('      ;',
                      'Line contains only semicolon. If this should be an empty '
                      'statement, use {} instead.'
                      '  [whitespace/semicolon] [5]')
        self.TestLint('for (int i = 0; ;', '')

    def testEmptyBlockBody(self):
        self.TestLint('while (true);',
                      'Empty loop bodies should use {} or continue'
                      '  [whitespace/empty_loop_body] [5]')
        self.TestLint('if (true);',
                      'Empty conditional bodies should use {}'
                      '  [whitespace/empty_conditional_body] [5]')
        self.TestLint('while (true)', '')
        self.TestLint('while (true) continue;', '')
        self.TestLint('for (;;);',
                      'Empty loop bodies should use {} or continue'
                      '  [whitespace/empty_loop_body] [5]')
        self.TestLint('for (;;)', '')
        self.TestLint('for (;;) continue;', '')
        self.TestLint('for (;;) func();', '')
        self.TestLint('if (test) {}',
                      'If statement had no body and no else clause'
                      '  [whitespace/empty_if_body] [4]')
        self.TestLint('if (test) func();', '')
        self.TestLint('if (test) {} else {}', '')
        self.TestMultiLineLint("""while (true &&
                                     false);""",
                               'Empty loop bodies should use {} or continue'
                               '  [whitespace/empty_loop_body] [5]')
        self.TestMultiLineLint("""do {
                           } while (false);""",
                               '')
        self.TestMultiLineLint("""#define MACRO \\
                           do { \\
                           } while (false);""",
                               '')
        self.TestMultiLineLint("""do {
                           } while (false);  // next line gets a warning
                           while (false);""",
                               'Empty loop bodies should use {} or continue'
                               '  [whitespace/empty_loop_body] [5]')
        self.TestMultiLineLint("""if (test) {
                           }""",
                               'If statement had no body and no else clause'
                               '  [whitespace/empty_if_body] [4]')
        self.TestMultiLineLint("""if (test,
                               func({})) {
                           }""",
                               'If statement had no body and no else clause'
                               '  [whitespace/empty_if_body] [4]')
        self.TestMultiLineLint("""if (test)
                             func();""", '')
        self.TestLint('if (test) { hello; }', '')
        self.TestLint('if (test({})) { hello; }', '')
        self.TestMultiLineLint("""if (test) {
                             func();
                           }""", '')
        self.TestMultiLineLint("""if (test) {
                             // multiline
                             // comment
                           }""", '')
        self.TestMultiLineLint("""if (test) {  // comment
                           }""", '')
        self.TestMultiLineLint("""if (test) {
                           } else {
                           }""", '')
        self.TestMultiLineLint("""if (func(p1,
                               p2,
                               p3)) {
                             func();
                           }""", '')
        self.TestMultiLineLint("""if (func({}, p1)) {
                             func();
                           }""", '')

    def testSpacingForRangeBasedFor(self):
        # Basic correctly formatted case:
        self.TestLint('for (int i : numbers) {', '')

        # Missing space before colon:
        self.TestLint('for (int i: numbers) {',
                      'Missing space around colon in range-based for loop'
                      '  [whitespace/forcolon] [2]')
        # Missing space after colon:
        self.TestLint('for (int i :numbers) {',
                      'Missing space around colon in range-based for loop'
                      '  [whitespace/forcolon] [2]')
        # Missing spaces both before and after the colon.
        self.TestLint('for (int i:numbers) {',
                      'Missing space around colon in range-based for loop'
                      '  [whitespace/forcolon] [2]')

        # The scope operator '::' shouldn't cause warnings...
        self.TestLint('for (std::size_t i : sizes) {}', '')
        # ...but it shouldn't suppress them either.
        self.TestLint('for (std::size_t i: sizes) {}',
                      'Missing space around colon in range-based for loop'
                      '  [whitespace/forcolon] [2]')

    # Static or global STL strings.
    def testStaticOrGlobalSTLStrings(self):
        # A template for the error message for a const global/static string.
        error_msg = ('For a static/global string constant, use a C style '
                     'string instead: "%s[]".  [runtime/string] [4]')
        # The error message for a non-const global/static string variable.
        nonconst_error_msg = ('Static/global string variables are not permitted.'
                              '  [runtime/string] [4]')

        self.TestLint('string foo;',
                      nonconst_error_msg)
        self.TestLint('string kFoo = "hello";  // English',
                      nonconst_error_msg)
        self.TestLint('static string foo;',
                      nonconst_error_msg)
        self.TestLint('static const string foo;',
                      error_msg % 'static const char foo')
        self.TestLint('static const std::string foo;',
                      error_msg % 'static const char foo')
        self.TestLint('string Foo::bar;',
                      nonconst_error_msg)

        self.TestLint('std::string foo;',
                      nonconst_error_msg)
        self.TestLint('std::string kFoo = "hello";  // English',
                      nonconst_error_msg)
        self.TestLint('static std::string foo;',
                      nonconst_error_msg)
        self.TestLint('static const std::string foo;',
                      error_msg % 'static const char foo')
        self.TestLint('std::string Foo::bar;',
                      nonconst_error_msg)

        self.TestLint('::std::string foo;',
                      nonconst_error_msg)
        self.TestLint('::std::string kFoo = "hello";  // English',
                      nonconst_error_msg)
        self.TestLint('static ::std::string foo;',
                      nonconst_error_msg)
        self.TestLint('static const ::std::string foo;',
                      error_msg % 'static const char foo')
        self.TestLint('::std::string Foo::bar;',
                      nonconst_error_msg)

        self.TestLint('string* pointer', '')
        self.TestLint('string *pointer', '')
        self.TestLint('string* pointer = Func();', '')
        self.TestLint('string *pointer = Func();', '')
        self.TestLint('const string* pointer', '')
        self.TestLint('const string *pointer', '')
        self.TestLint('const string* pointer = Func();', '')
        self.TestLint('const string *pointer = Func();', '')
        self.TestLint('string const* pointer', '')
        self.TestLint('string const *pointer', '')
        self.TestLint('string const* pointer = Func();', '')
        self.TestLint('string const *pointer = Func();', '')
        self.TestLint('string* const pointer', '')
        self.TestLint('string *const pointer', '')
        self.TestLint('string* const pointer = Func();', '')
        self.TestLint('string *const pointer = Func();', '')
        self.TestLint('string Foo::bar() {}', '')
        self.TestLint('string Foo::operator*() {}', '')
        # Rare case.
        self.TestLint('string foo("foobar");', nonconst_error_msg)
        # Should not catch local or member variables.
        self.TestLint('  string foo', '')
        # Should not catch functions.
        self.TestLint('string EmptyString() { return ""; }', '')
        self.TestLint('string EmptyString () { return ""; }', '')
        self.TestLint('string const& FileInfo::Pathname() const;', '')
        self.TestLint('string const &FileInfo::Pathname() const;', '')
        self.TestLint('string VeryLongNameFunctionSometimesEndsWith(\n'
                      '    VeryLongNameType very_long_name_variable) {}', '')
        self.TestLint('template<>\n'
                      'string FunctionTemplateSpecialization<SomeType>(\n'
                      '      int x) { return ""; }', '')
        self.TestLint('template<>\n'
                      'string FunctionTemplateSpecialization<vector<A::B>* >(\n'
                      '      int x) { return ""; }', '')

        # should not catch methods of template classes.
        self.TestLint('string Class<Type>::Method() const {\n'
                      '  return "";\n'
                      '}\n', '')
        self.TestLint('string Class<Type>::Method(\n'
                      '   int arg) const {\n'
                      '  return "";\n'
                      '}\n', '')

        # Check multiline cases.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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

    def testNoSpacesInFunctionCalls(self):
        self.TestLint('TellStory(1, 3);',
                      '')
        self.TestLint('TellStory(1, 3 );',
                      'Extra space before )'
                      '  [whitespace/parens] [2]')
        self.TestLint('TellStory(1 /* wolf */, 3 /* pigs */);',
                      '')
        self.TestMultiLineLint("""TellStory(1, 3
                                        );""",
                               'Closing ) should be moved to the previous line'
                               '  [whitespace/parens] [2]')
        self.TestMultiLineLint("""TellStory(Wolves(1),
                                        Pigs(3
                                        ));""",
                               'Closing ) should be moved to the previous line'
                               '  [whitespace/parens] [2]')
        self.TestMultiLineLint("""TellStory(1,
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

        self.TestLint('//   TODOfix this',
                      [start_space, missing_username, end_space])
        self.TestLint('//   TODO(ljenkins)fix this',
                      [start_space, end_space])
        self.TestLint('//   TODO fix this',
                      [start_space, missing_username])
        self.TestLint('// TODO fix this', missing_username)
        self.TestLint('// TODO: fix this', missing_username)
        self.TestLint('//TODO(ljenkins): Fix this',
                      'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestLint('// TODO(ljenkins):Fix this', end_space)
        self.TestLint('// TODO(ljenkins):', '')
        self.TestLint('// TODO(ljenkins): fix this', '')
        self.TestLint('// TODO(ljenkins): Fix this', '')
        self.TestLint('#if 1  // TEST_URLTODOCID_WHICH_HAS_THAT_WORD_IN_IT_H_', '')
        self.TestLint('// See also similar TODO above', '')
        self.TestLint(r'EXPECT_EQ("\\", '
                      r'NormalizePath("/./../foo///bar/..//x/../..", ""));',
                      '')

    def testTwoSpacesBetweenCodeAndComments(self):
        self.TestLint('} // namespace foo',
                      'At least two spaces is best between code and comments'
                      '  [whitespace/comments] [2]')
        self.TestLint('}// namespace foo',
                      'At least two spaces is best between code and comments'
                      '  [whitespace/comments] [2]')
        self.TestLint('printf("foo"); // Outside quotes.',
                      'At least two spaces is best between code and comments'
                      '  [whitespace/comments] [2]')
        self.TestLint('int i = 0;  // Having two spaces is fine.', '')
        self.TestLint('int i = 0;   // Having three spaces is OK.', '')
        self.TestLint('// Top level comment', '')
        self.TestLint('  // Line starts with two spaces.', '')
        self.TestMultiLineLint('void foo() {\n'
                               '  { // A scope is opening.\n'
                               '    int a;', '')
        self.TestMultiLineLint('void foo() {\n'
                               '  { // A scope is opening.\n'
                               '#define A a',
                               'At least two spaces is best between code and '
                               'comments  [whitespace/comments] [2]')
        self.TestMultiLineLint('  foo();\n'
                               '  { // An indented scope is opening.\n'
                               '    int a;', '')
        self.TestMultiLineLint('vector<int> my_elements = {// first\n'
                               '                           1,', '')
        self.TestMultiLineLint('vector<int> my_elements = {// my_elements is ..\n'
                               '    1,',
                               'At least two spaces is best between code and '
                               'comments  [whitespace/comments] [2]')
        self.TestLint('if (foo) { // not a pure scope; comment is too close!',
                      'At least two spaces is best between code and comments'
                      '  [whitespace/comments] [2]')
        self.TestLint('printf("// In quotes.")', '')
        self.TestLint('printf("\\"%s // In quotes.")', '')
        self.TestLint('printf("%s", "// In quotes.")', '')

    def testSpaceAfterCommentMarker(self):
        self.TestLint('//', '')
        self.TestLint('//x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestLint('// x', '')
        self.TestLint('///', '')
        self.TestLint('/// x', '')
        self.TestLint('//!', '')
        self.TestLint('//----', '')
        self.TestLint('//====', '')
        self.TestLint('//////', '')
        self.TestLint('////// x', '')
        self.TestLint('///< x', '')  # After-member Doxygen comment
        self.TestLint('//!< x', '')  # After-member Doxygen comment
        self.TestLint('////x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestLint('//}', '')
        self.TestLint('//}x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestLint('//!<x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')
        self.TestLint('///<x', 'Should have a space between // and comment'
                      '  [whitespace/comments] [4]')

    # Test a line preceded by empty or comment lines.  There was a bug
    # that caused it to print the same warning N times if the erroneous
    # line was preceded by N lines of empty or comment lines.  To be
    # precise, the '// marker so line numbers and indices both start at
    # 1' line was also causing the issue.
    def testLinePrecededByEmptyOrCommentLines(self):
        def DoTest(self, lines):
            error_collector = ErrorCollector()
            cpplint.ProcessFileData('foo.cc', 'cc', lines, error_collector)
            # The warning appears only once.
            assert 1 == error_collector.Results().count(
                    'Do not use namespace using-directives.  '
                    'Use using-declarations instead.'
                    '  [build/namespaces] [5]')
        DoTest(self, ['using namespace foo;'])
        DoTest(self, ['', '', '', 'using namespace foo;'])
        DoTest(self, ['// hello', 'using namespace foo;'])

    def testUsingLiteralsNamespaces(self):
        self.TestLint('using namespace std::literals;', 'Do not use namespace'
            ' using-directives.  Use using-declarations instead.'
            '  [build/namespaces_literals] [5]')
        self.TestLint('using namespace std::literals::chrono_literals;', 'Do'
            ' not use namespace using-directives.  Use using-declarations instead.'
            '  [build/namespaces_literals] [5]')

    def testNewlineAtEOF(self):
        def DoTest(self, data, is_missing_eof):
            error_collector = ErrorCollector()
            cpplint.ProcessFileData('foo.cc', 'cc', data.split('\n'),
                                    error_collector)
            # The warning appears only once.
            assert  int(is_missing_eof) == error_collector.Results().count( 'Could not find a newline character at the end of the file.  [whitespace/ending_newline] [5]')

        DoTest(self, '// Newline\n// at EOF\n', False)
        DoTest(self, '// No newline\n// at EOF', True)

    def testInvalidUtf8(self):
        def DoTest(self, raw_bytes, has_invalid_utf8):
            error_collector = ErrorCollector()
            if sys.version_info < (3,):
                unidata = unicode(raw_bytes, 'utf8', 'replace').split('\n')
            else:
                unidata = str(raw_bytes, 'utf8', 'replace').split('\n')
            cpplint.ProcessFileData(
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

    def testBadCharacters(self):
        # Test for NUL bytes only
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('nul.cc', 'cc',
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
        assert cpplint.IsBlankLine('')
        assert cpplint.IsBlankLine(' ')
        assert cpplint.IsBlankLine(' \t\r\n')
        assert not cpplint.IsBlankLine('int a;')
        assert not cpplint.IsBlankLine('{')

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

    def testAllowBlankLineBeforeClosingNamespace(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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

    def testAllowBlankLineBeforeIfElseChain(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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

    def testAllowBlankLineAfterExtern(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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

    def testBlankLineBeforeSectionKeyword(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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

    def testNoBlankLineAfterSectionKeyword(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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

    def testAllowBlankLinesInRawStrings(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
                                ['// Copyright 2014 Your Company.',
                                 'static const char *kData[] = {R"(',
                                 '',
                                 ')", R"(',
                                 '',
                                 ')"};',
                                 ''],
                                error_collector)
        assert '' == error_collector.Results()

    def testElseOnSameLineAsClosingBraces(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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
        cpplint.ProcessFileData('foo.cc', 'cc',
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
        cpplint.ProcessFileData('foo.cc', 'cc',
                                ['if (hoge) {',
                                 '',
                                 '}',
                                 'else_function();'],
                                error_collector)
        assert 0 == error_collector.Results().count('An else should appear on the same line as the preceding }  [whitespace/newline] [4]')

    def testMultipleStatementsOnSameLine(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
                                ['for (int i = 0; i < 1; i++) {}',
                                 'switch (x) {',
                                 '  case 0: func(); break; ',
                                 '}',
                                 'sum += MathUtil::SafeIntRound(x); x += 0.1;'],
                                error_collector)
        assert 0 == error_collector.Results().count('More than one command on the same line  [whitespace/newline] [0]')

        old_verbose_level = cpplint._cpplint_state.verbose_level
        cpplint._cpplint_state.verbose_level = 0
        cpplint.ProcessFileData('foo.cc', 'cc',
                                ['sum += MathUtil::SafeIntRound(x); x += 0.1;'],
                                error_collector)
        cpplint._cpplint_state.verbose_level = old_verbose_level

    def testLambdasOnSameLine(self):
        error_collector = ErrorCollector()
        old_verbose_level = cpplint._cpplint_state.verbose_level
        cpplint._cpplint_state.verbose_level = 0
        cpplint.ProcessFileData('foo.cc', 'cc',
                                ['const auto lambda = '
                                  '[](const int i) { return i; };'],
                                error_collector)
        cpplint._cpplint_state.verbose_level = old_verbose_level
        assert 0 == error_collector.Results().count( 'More than one command on the same line  [whitespace/newline] [0]')

        error_collector = ErrorCollector()
        old_verbose_level = cpplint._cpplint_state.verbose_level
        cpplint._cpplint_state.verbose_level = 0
        cpplint.ProcessFileData('foo.cc', 'cc',
                                ['const auto result = std::any_of(vector.begin(), '
                                  'vector.end(), '
                                  '[](const int i) { return i > 0; });'],
                                error_collector)
        cpplint._cpplint_state.verbose_level = old_verbose_level
        assert 0 == error_collector.Results().count( 'More than one command on the same line  [whitespace/newline] [0]')

        error_collector = ErrorCollector()
        old_verbose_level = cpplint._cpplint_state.verbose_level
        cpplint._cpplint_state.verbose_level = 0
        cpplint.ProcessFileData('foo.cc', 'cc',
                                ['return mutex::Lock<void>([this]() { '
                                  'this->ReadLock(); }, [this]() { '
                                  'this->ReadUnlock(); });'],
                                error_collector)
        cpplint._cpplint_state.verbose_level = old_verbose_level
        assert 0 == error_collector.Results().count( 'More than one command on the same line  [whitespace/newline] [0]')

        error_collector = ErrorCollector()
        old_verbose_level = cpplint._cpplint_state.verbose_level
        cpplint._cpplint_state.verbose_level = 0
        cpplint.ProcessFileData('foo.cc', 'cc',
                                ['return mutex::Lock<void>([this]() { '
                                  'this->ReadLock(); }, [this]() { '
                                  'this->ReadUnlock(); }, object);'],
                                error_collector)
        cpplint._cpplint_state.verbose_level = old_verbose_level
        assert 0 == error_collector.Results().count( 'More than one command on the same line  [whitespace/newline] [0]')

    def testEndOfNamespaceComments(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('foo.cc', 'cc',
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
        self.TestLint('  else DoSomethingElse();',
                      'Else clause should never be on same line as else '
                      '(use 2 lines)  [whitespace/newline] [4]')
        self.TestLint('  else ifDoSomethingElse();',
                      'Else clause should never be on same line as else '
                      '(use 2 lines)  [whitespace/newline] [4]')
        self.TestLint('  } else if (blah) {', '')
        self.TestLint('  variable_ends_in_else = true;', '')

    def testComma(self):
        self.TestLint('a = f(1,2);',
                      'Missing space after ,  [whitespace/comma] [3]')
        self.TestLint('int tmp=a,a=b,b=tmp;',
                      ['Missing spaces around =  [whitespace/operators] [4]',
                       'Missing space after ,  [whitespace/comma] [3]'])
        self.TestLint('f(a, /* name */ b);', '')
        self.TestLint('f(a, /* name */b);', '')
        self.TestLint('f(a, /* name */-1);', '')
        self.TestLint('f(a, /* name */"1");', '')
        self.TestLint('f(1, /* empty macro arg */, 2)', '')
        self.TestLint('f(1,, 2)', '')
        self.TestLint('operator,()', '')
        self.TestLint('operator,(a,b)',
                      'Missing space after ,  [whitespace/comma] [3]')

    def testEqualsOperatorSpacing(self):
        self.TestLint('int tmp= a;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestLint('int tmp =a;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestLint('int tmp=a;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestLint('int tmp= 7;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestLint('int tmp =7;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestLint('int tmp=7;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestLint('int* tmp=*p;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestLint('int* tmp= *p;',
                      'Missing spaces around =  [whitespace/operators] [4]')
        self.TestMultiLineLint(
            self.TrimExtraIndent('''
            lookahead_services_=
              ::strings::Split(FLAGS_ls, ",", ::strings::SkipEmpty());'''),
            'Missing spaces around =  [whitespace/operators] [4]')
        self.TestLint('bool result = a>=42;',
                      'Missing spaces around >=  [whitespace/operators] [3]')
        self.TestLint('bool result = a<=42;',
                      'Missing spaces around <=  [whitespace/operators] [3]')
        self.TestLint('bool result = a==42;',
                      'Missing spaces around ==  [whitespace/operators] [3]')
        self.TestLint('auto result = a!=42;',
                      'Missing spaces around !=  [whitespace/operators] [3]')
        self.TestLint('int a = b!=c;',
                      'Missing spaces around !=  [whitespace/operators] [3]')
        self.TestLint('a&=42;', '')
        self.TestLint('a|=42;', '')
        self.TestLint('a^=42;', '')
        self.TestLint('a+=42;', '')
        self.TestLint('a*=42;', '')
        self.TestLint('a/=42;', '')
        self.TestLint('a%=42;', '')
        self.TestLint('a>>=5;', '')
        self.TestLint('a<<=5;', '')

    def testShiftOperatorSpacing(self):
        self.TestLint('a<<b',
                      'Missing spaces around <<  [whitespace/operators] [3]')
        self.TestLint('a>>b',
                      'Missing spaces around >>  [whitespace/operators] [3]')
        self.TestLint('1<<20', '')
        self.TestLint('1024>>10', '')
        self.TestLint('Kernel<<<1, 2>>>()', '')

    def testIndent(self):
        self.TestLint('static int noindent;', '')
        self.TestLint('  int two_space_indent;', '')
        self.TestLint('    int four_space_indent;', '')
        self.TestLint(' int one_space_indent;',
                      'Weird number of spaces at line-start.  '
                      'Are you using a 2-space indent?  [whitespace/indent] [3]')
        self.TestLint('   int three_space_indent;',
                      'Weird number of spaces at line-start.  '
                      'Are you using a 2-space indent?  [whitespace/indent] [3]')
        self.TestLint(' char* one_space_indent = "public:";',
                      'Weird number of spaces at line-start.  '
                      'Are you using a 2-space indent?  [whitespace/indent] [3]')
        self.TestLint(' public:', '')
        self.TestLint('  protected:', '')
        self.TestLint('   private:', '')
        self.TestLint(' protected: \\', '')
        self.TestLint('  public:      \\', '')
        self.TestLint('   private:   \\', '')
        # examples using QT signals/slots macro
        self.TestMultiLineLint(
            self.TrimExtraIndent("""
            class foo {
             public slots:
              void bar();
             signals:
            };"""),
            '')
        self.TestMultiLineLint(
            self.TrimExtraIndent("""
            class foo {
              public slots:
              void bar();
            };"""),
            'public slots: should be indented +1 space inside class foo'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(
            self.TrimExtraIndent("""
            class foo {
              signals:
              void bar();
            };"""),
            'signals: should be indented +1 space inside class foo'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(
            self.TrimExtraIndent('''
            static const char kRawString[] = R"("
             ")";'''),
            '')
        self.TestMultiLineLint(
            self.TrimExtraIndent('''
            KV<Query,
               Tuple<TaxonomyId, PetacatCategoryId, double>>'''),
            '')
        self.TestMultiLineLint(
            ' static const char kSingleLineRawString[] = R"(...)";',
            'Weird number of spaces at line-start.  '
            'Are you using a 2-space indent?  [whitespace/indent] [3]')

    def testSectionIndent(self):
        self.TestMultiLineLint(
            """
        class A {
         public:  // no warning
          private:  // warning here
        };""",
            'private: should be indented +1 space inside class A'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(
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
        self.TestMultiLineLint(
            """
        struct D {
         };""",
            'Closing brace should be aligned with beginning of struct D'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(
            """
         template<typename E> class F {
        };""",
            'Closing brace should be aligned with beginning of class F'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(
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
        self.TestMultiLineLint(
            """
        class H {
          /* comments */ class I {
           public:  // no warning
            private:  // warning here
          };
        };""",
            'private: should be indented +1 space inside class I'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(
            """
        class J
            : public ::K {
         public:  // no warning
          protected:  // warning here
        };""",
            'protected: should be indented +1 space inside class J'
            '  [whitespace/indent] [3]')
        self.TestMultiLineLint(
            """
        class L
            : public M,
              public ::N {
        };""",
            '')
        self.TestMultiLineLint(
            """
        template <class O,
                  class P,
                  class Q,
                  typename R>
        static void Func() {
        }""",
            '')

    def testConditionals(self):
        self.TestMultiLineLint(
            """
        if (foo)
          goto fail;
          goto fail;""",
            'If/else bodies with multiple statements require braces'
            '  [readability/braces] [4]')
        self.TestMultiLineLint(
            """
        if (foo)
          goto fail; goto fail;""",
            'If/else bodies with multiple statements require braces'
            '  [readability/braces] [4]')
        self.TestMultiLineLint(
            """
        if (foo)
          foo;
        else
          goto fail;
          goto fail;""",
            'If/else bodies with multiple statements require braces'
            '  [readability/braces] [4]')
        self.TestMultiLineLint(
            """
        if (foo) goto fail;
          goto fail;""",
            'If/else bodies with multiple statements require braces'
            '  [readability/braces] [4]')
        self.TestMultiLineLint(
            """
        if constexpr (foo) {
          goto fail;
          goto fail;
        } else if constexpr (bar) {
          hello();
        }""",
            '')
        self.TestMultiLineLint(
            """
        if (foo)
          if (bar)
            baz;
          else
            qux;""",
            'Else clause should be indented at the same level as if. Ambiguous'
            ' nested if/else chains require braces.  [readability/braces] [4]')
        self.TestMultiLineLint(
            """
        if (foo)
          if (bar)
            baz;
        else
          qux;""",
            'Else clause should be indented at the same level as if. Ambiguous'
            ' nested if/else chains require braces.  [readability/braces] [4]')
        self.TestMultiLineLint(
            """
        if (foo) {
          bar;
          baz;
        } else
          qux;""",
            'If an else has a brace on one side, it should have it on both'
            '  [readability/braces] [5]')
        self.TestMultiLineLint(
            """
        if (foo)
          bar;
        else {
          baz;
        }""",
            'If an else has a brace on one side, it should have it on both'
            '  [readability/braces] [5]')
        self.TestMultiLineLint(
            """
        if (foo)
          bar;
        else if (baz) {
          qux;
        }""",
            'If an else has a brace on one side, it should have it on both'
            '  [readability/braces] [5]')
        self.TestMultiLineLint(
            """
        if (foo) {
          bar;
        } else if (baz)
          qux;""",
            'If an else has a brace on one side, it should have it on both'
            '  [readability/braces] [5]')
        self.TestMultiLineLint(
            """
        if (foo)
          goto fail;
        bar;""",
            '')
        self.TestMultiLineLint(
            """
        if (foo
            && bar) {
          baz;
          qux;
        }""",
            '')
        self.TestMultiLineLint(
            """
        if (foo)
          goto
            fail;""",
            '')
        self.TestMultiLineLint(
            """
        if (foo)
          bar;
        else
          baz;
        qux;""",
            '')
        self.TestMultiLineLint(
            """
        for (;;) {
          if (foo)
            bar;
          else
            baz;
        }""",
            '')
        self.TestMultiLineLint(
            """
        if (foo)
          bar;
        else if (baz)
          baz;""",
            '')
        self.TestMultiLineLint(
            """
        if (foo)
          bar;
        else
          baz;""",
            '')
        self.TestMultiLineLint(
            """
        if (foo) {
          bar;
        } else {
          baz;
        }""",
            '')
        self.TestMultiLineLint(
            """
        if (foo) {
          bar;
        } else if (baz) {
          qux;
        }""",
            '')
        # Note: this is an error for a different reason, but should not trigger the
        # single-line if error.
        self.TestMultiLineLint(
            """
        if (foo)
        {
          bar;
          baz;
        }""",
            '{ should almost always be at the end of the previous line'
            '  [whitespace/braces] [4]')
        self.TestMultiLineLint(
            """
        if (foo) { \\
          bar; \\
          baz; \\
        }""",
            '')
        self.TestMultiLineLint(
            """
        void foo() { if (bar) baz; }""",
            '')
        self.TestMultiLineLint(
            """
        #if foo
          bar;
        #else
          baz;
          qux;
        #endif""",
            '')
        self.TestMultiLineLint(
            """void F() {
          variable = [] { if (true); };
          variable =
              [] { if (true); };
          Call(
              [] { if (true); },
              [] { if (true); });
        }""",
            '')
        self.TestMultiLineLint(
            """
        #if(A == 0)
          foo();
        #elif(A == 1)
          bar();
        #endif""",
            '')
        self.TestMultiLineLint(
            """
        #if (A == 0)
          foo();
        #elif (A == 1)
          bar();
        #endif""",
            '')

    def testTab(self):
        self.TestLint('\tint16 a;',
                      'Tab found; better to use spaces  [whitespace/tab] [1]')
        self.TestLint('int16 a = 5;\t\t// set a to 5',
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
            self.TestLint(
                '// H %s' % ('H' * 75),
                '')
            self.TestLint(
                '// H %s' % ('H' * 76),
                'Lines should be <= 80 characters long'
                '  [whitespace/line_length] [2]')
            cpplint._cpplint_state._line_length = 120
            self.TestLint(
                '// H %s' % ('H' * 115),
                '')
            self.TestLint(
                '// H %s' % ('H' * 116),
                'Lines should be <= 120 characters long'
                '  [whitespace/line_length] [2]')
        finally:
            cpplint._cpplint_state._line_length = old_line_length

    def testFilter(self):
        old_filters = cpplint._cpplint_state.filters
        try:
            cpplint._cpplint_state.filters = ["-","+whitespace","-whitespace/indent"]
            self.TestLint(
                '// Hello there ',
                'Line ends in whitespace.  Consider deleting these extra spaces.'
                '  [whitespace/end_of_line] [4]')
            self.TestLint('int a = (int)1.0;', '')
            self.TestLint(' weird opening space', '')
        finally:
            cpplint._cpplint_state.filters = ','.join(old_filters)

    def testDefaultFilter(self):
        state = cpplint._CppLintState()
        state.filters = ''
        assert "-build/include_alpha" in state.filters

    def testDuplicateHeader(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('path/self.cc', 'cc',
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

    def testBuildClass(self):
        # Test that the linter can parse to the end of class definitions,
        # and that it will report when it can't.
        # Use multi-line linter because it performs the ClassState check.
        self.TestMultiLineLint(
            'class Foo {',
            'Failed to find complete declaration of class Foo'
            '  [build/class] [5]')
        # Do the same for namespaces
        self.TestMultiLineLint(
            'namespace Foo {',
            'Failed to find complete declaration of namespace Foo'
            '  [build/namespaces] [5]')
        # Don't warn on forward declarations of various types.
        self.TestMultiLineLint(
            'class Foo;',
            '')
        self.TestMultiLineLint(
            """struct Foo*
             foo = NewFoo();""",
            '')
        # Test preprocessor.
        self.TestMultiLineLint(
            """#ifdef DERIVE_FROM_GOO
          struct Foo : public Goo {
        #else
          struct Foo : public Hoo {
        #endif
          };""",
            '')
        self.TestMultiLineLint(
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
        self.TestMultiLineLint(
            'class Foo {',
            'Failed to find complete declaration of class Foo'
            '  [build/class] [5]')

    def testBuildEndComment(self):
        # The crosstool compiler we currently use will fail to compile the
        # code in this test, so we might consider removing the lint check.
        self.TestMultiLineLint(
            """#if 0
        #endif Not a comment""",
            'Uncommented text after #endif is non-standard.  Use a comment.'
            '  [build/endif_comment] [5]')

    def testBuildForwardDecl(self):
        # The crosstool compiler we currently use will fail to compile the
        # code in this test, so we might consider removing the lint check.
        self.TestLint('class Foo::Goo;',
                      'Inner-style forward declarations are invalid.'
                      '  Remove this line.'
                      '  [build/forward_decl] [5]')

    def GetBuildHeaderGuardPreprocessorSymbol(self, file_path):
        # Figure out the expected header guard by processing an empty file.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h', [], error_collector)
        for error in error_collector.ResultList():
            matched = re.search(
                'No #ifndef header guard found, suggested CPP variable is: '
                '([A-Z0-9_]+)',
                error)
            if matched is not None:
                return matched.group(1)

    def testBuildHeaderGuard(self):
        file_path = 'mydir/foo.h'
        expected_guard = self.GetBuildHeaderGuardPreprocessorSymbol(file_path)
        assert re.search('MYDIR_FOO_H_$', expected_guard)

        # No guard at all: expect one error.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h', [], error_collector)
        assert 1 == error_collector.ResultList().count(
                'No #ifndef header guard found, suggested CPP variable is: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # No header guard, but the error is suppressed.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['// Copyright 2014 Your Company.',
                                 '// NOLINT(build/header_guard)', ''],
                                error_collector)
        assert [] == error_collector.ResultList()

        # Wrong guard
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['#ifndef FOO_H', '#define FOO_H'], error_collector)
        assert 1 == error_collector.ResultList().count(
                '#ifndef header guard has wrong style, please use: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # No define
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['#ifndef %s' % expected_guard], error_collector)
        assert 1 == error_collector.ResultList().count(
                'No #ifndef header guard found, suggested CPP variable is: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Mismatched define
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['#ifndef %s' % expected_guard,
                                 '#define FOO_H'],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                'No #ifndef header guard found, suggested CPP variable is: %s'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # No endif
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['#ifndef %s' % expected_guard,
                                 '#define %s' % expected_guard,
                                 ''],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Commentless endif
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['#ifndef %s' % expected_guard,
                                 '#define %s' % expected_guard,
                                 '#endif'],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Commentless endif for old-style guard
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['#ifndef %s_' % expected_guard,
                                 '#define %s_' % expected_guard,
                                 '#endif'],
                                error_collector)
        assert 1 == error_collector.ResultList().count(
                '#endif line should be "#endif  // %s"'
                '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # No header guard errors
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['#ifndef %s' % expected_guard,
                                 '#define %s' % expected_guard,
                                 '#endif  // %s' % expected_guard],
                                error_collector)
        for line in error_collector.ResultList():
            if line.find('build/header_guard') != -1:
                self.fail('Unexpected error: %s' % line)

        # No header guard errors for old-style guard
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
                                ['#ifndef %s_' % expected_guard,
                                 '#define %s_' % expected_guard,
                                 '#endif  // %s_' % expected_guard],
                                error_collector)
        for line in error_collector.ResultList():
            if line.find('build/header_guard') != -1:
                self.fail('Unexpected error: %s' % line)

        old_verbose_level = cpplint._cpplint_state.verbose_level
        try:
            cpplint._cpplint_state.verbose_level = 0
            # Warn on old-style guard if verbosity is 0.
            error_collector = ErrorCollector()
            cpplint.ProcessFileData(file_path, 'h',
                                    ['#ifndef %s_' % expected_guard,
                                     '#define %s_' % expected_guard,
                                     '#endif  // %s_' % expected_guard],
                                    error_collector)
            assert 1 == error_collector.ResultList().count(
                    '#ifndef header guard has wrong style, please use: %s'
                    '  [build/header_guard] [0]' % expected_guard), error_collector.ResultList()
        finally:
            cpplint._cpplint_state.verbose_level = old_verbose_level

        # Completely incorrect header guard
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'h',
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
        cpplint.ProcessFileData(file_path, 'h',
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
            cpplint.ProcessFileData(test_file, 'h',
                                    ['// Copyright 2014 Your Company.', ''],
                                    error_collector)
            assert 1 == error_collector.ResultList().count(
                    'No #ifndef header guard found, suggested CPP variable is: %s'
                    '  [build/header_guard] [5]' % expected_guard), error_collector.ResultList()

        # Cuda guard
        file_path = 'mydir/foo.cuh'
        expected_guard = self.GetBuildHeaderGuardPreprocessorSymbol(file_path)
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'cuh',
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

    def testPragmaOnce(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData('mydir/foo.h', 'h',
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

        assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)
        #
        # test --root flags:
        #   this changes the cpp header guard prefix
        #

        # left-strip the header guard by using a root dir inside of the repo dir.
        # relative directory
        cpplint._cpplint_state._root = 'cpplint'
        assert 'CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

        nested_header_directory = os.path.join(header_directory, "nested")
        nested_file_path = os.path.join(nested_header_directory, 'cpplint_test_header.h')
        os.makedirs(nested_header_directory)
        open(nested_file_path, 'a').close()

        cpplint._cpplint_state._root = os.path.join('cpplint', 'nested')
        actual = cpplint.GetHeaderGuardCPPVariable(nested_file_path)
        assert 'CPPLINT_TEST_HEADER_H_' == actual

        # absolute directory
        # (note that CPPLINT.cfg root=setting is always made absolute)
        cpplint._cpplint_state._root = header_directory
        assert 'CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

        cpplint._cpplint_state._root = nested_header_directory
        assert 'CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(nested_file_path)

        # --root flag is ignored if an non-existent directory is specified.
        cpplint._cpplint_state._root = 'NON_EXISTENT_DIR'
        assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

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
        assert '%sCPPLINT_CPPLINT_TEST_HEADER_H_' % (expected_prefix) == cpplint.GetHeaderGuardCPPVariable(file_path)

        # To run the 'relative path' tests, we must be in the directory of this test file.
        cur_dir = os.getcwd()
        os.chdir(this_files_path)

        # (using relative paths)
        styleguide_rel_path = os.path.relpath(styleguide_path, this_files_path)
        # '..'
        cpplint._cpplint_state._root = styleguide_rel_path
        assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

        styleguide_rel_path = os.path.relpath(styleguide_parent_path,
                                              this_files_path)  # '../..'
        cpplint._cpplint_state._root = styleguide_rel_path
        assert '%sCPPLINT_CPPLINT_TEST_HEADER_H_' % (expected_prefix) == cpplint.GetHeaderGuardCPPVariable(file_path)

        cpplint._cpplint_state._root = None

        # Restore previous CWD.
        os.chdir(cur_dir)

    def testIncludeItsHeader(self):
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
              'test/foo.cc', 'cc',
              [''],
              error_collector)
            expected = "{dir}/{fn}.cc should include its header file {dir}/{fn}.h  [build/include] [5]".format(
                fn="foo",
                dir=test_directory)
            assert 1 == error_collector.Results().count(expected)

            error_collector = ErrorCollector()
            cpplint.ProcessFileData(
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
        assert [''] == cpplint.PathSplitToList(os.path.join(''))
        assert ['.'] == cpplint.PathSplitToList(os.path.join('.'))
        assert ['..'] == cpplint.PathSplitToList(os.path.join('..'))
        assert ['..', 'a', 'b'], cpplint.PathSplitToList(os.path.join('..', 'a' == 'b'))
        assert ['a', 'b', 'c', 'd'], cpplint.PathSplitToList(os.path.join('a', 'b', 'c' == 'd'))

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
            assert 'TRUNK_CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

            # use the provided repository root for header guards
            cpplint._cpplint_state._repository = os.path.relpath(trunk_dir)
            assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)
            cpplint._cpplint_state._repository = os.path.abspath(trunk_dir)
            assert 'CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

            # ignore _repository if it doesnt exist
            cpplint._cpplint_state._repository = os.path.join(temp_directory, 'NON_EXISTANT')
            assert 'TRUNK_CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

            # ignore _repository if it exists but file isn't in it
            cpplint._cpplint_state._repository = os.path.relpath(temp_directory2)
            assert 'TRUNK_CPPLINT_CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

            # _root should be relative to _repository
            cpplint._cpplint_state._repository = os.path.relpath(trunk_dir)
            cpplint._cpplint_state._root = 'cpplint'
            assert 'CPPLINT_TEST_HEADER_H_' == cpplint.GetHeaderGuardCPPVariable(file_path)

        finally:
            shutil.rmtree(temp_directory)
            shutil.rmtree(temp_directory2)
            cpplint._cpplint_state._repository = None
            cpplint._cpplint_state._root = None

    def testBuildInclude(self):
        # Test that include statements have slashes in them.
        self.TestLint('#include "foo.h"',
                      'Include the directory when naming header files'
                      '  [build/include_subdir] [4]')
        self.TestLint('#include "bar.hh"',
                      'Include the directory when naming header files'
                      '  [build/include_subdir] [4]')
        self.TestLint('#include "baz.aa"', '')
        self.TestLint('#include "dir/foo.h"', '')
        self.TestLint('#include "Python.h"', '')
        self.TestLint('#include "lua.h"', '')

    def testHppInclude(self):
        code = '\n'.join([
          '#include <vector>',
          '#include <boost/any.hpp>'
        ])
        self.TestLanguageRulesCheck('foo.h', code, '')

    def testBuildPrintfFormat(self):
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
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
        cpplint.ProcessFileData(
            'foo.cc', 'cc',
            ['// Copyright 2014 Your Company.',
             r'printf("\\%%%d", value);',
             r'printf(R"(\[)");',
             r'printf(R"(\[%s)", R"(\])");',
             ''],
            error_collector)
        assert '' == error_collector.Results()

    def testRuntimePrintfFormat(self):
        self.TestLint(
            r'fprintf(file, "%q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestLint(
            r'aprintf(file, "The number is %12q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestLint(
            r'printf(file, "The number is" "%-12q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestLint(
            r'printf(file, "The number is" "%+12q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestLint(
            r'printf(file, "The number is" "% 12q", value);',
            '%q in format strings is deprecated.  Use %ll instead.'
            '  [runtime/printf_format] [3]')

        self.TestLint(
            r'snprintf(file, "Never mix %d and %1$d parameters!", value);',
            '%N$ formats are unconventional.  Try rewriting to avoid them.'
            '  [runtime/printf_format] [2]')

    def TestLintLogCodeOnError(self, code, expected_message):
        # Special TestLint which logs the input code on error.
        result = self.PerformSingleLineLint(code)
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
        self.TestLint('const int static foo = 5;',
                      build_storage_class_error_message)

        self.TestLint('char static foo;',
                      build_storage_class_error_message)

        self.TestLint('double const static foo = 2.0;',
                      build_storage_class_error_message)

        self.TestLint('uint64 typedef unsigned_long_long;',
                      build_storage_class_error_message)

        self.TestLint('int register foo = 0;',
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

            self.TestLintLogCodeOnError(
                ' '.join(decl_specs) + ';',
                build_storage_class_error_message)

            # but no error if storage class is first
            self.TestLintLogCodeOnError(
                storage_class + ' ' + ' '.join(other_decl_specs),
                '')

    def testLegalCopyright(self):
        legal_copyright_message = (
            'No copyright message found.  '
            'You should have a line: "Copyright [year] <Copyright Owner>"'
            '  [legal/copyright] [5]')

        copyright_line = '// Copyright 2014 Google Inc. All Rights Reserved.'

        file_path = 'mydir/googleclient/foo.cc'

        # There should be a copyright message in the first 10 lines
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'cc', [], error_collector)
        assert 1 == error_collector.ResultList().count(legal_copyright_message)

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            file_path, 'cc',
            ['' for unused_i in range(10)] + [copyright_line],
            error_collector)
        assert 1 == error_collector.ResultList().count(legal_copyright_message)

        # Test that warning isn't issued if Copyright line appears early enough.
        error_collector = ErrorCollector()
        cpplint.ProcessFileData(file_path, 'cc', [copyright_line], error_collector)
        for message in error_collector.ResultList():
            if message.find('legal/copyright') != -1:
                self.fail('Unexpected error: %s' % message)

        error_collector = ErrorCollector()
        cpplint.ProcessFileData(
            file_path, 'cc',
            ['' for unused_i in range(9)] + [copyright_line],
            error_collector)
        for message in error_collector.ResultList():
            if message.find('legal/copyright') != -1:
                self.fail('Unexpected error: %s' % message)

    def testInvalidIncrement(self):
        self.TestLint('*count++;',
                      'Changing pointer instead of value (or unused value of '
                      'operator*).  [runtime/invalid_increment] [5]')

    def testSnprintfSize(self):
        self.TestLint('vsnprintf(NULL, 0, format)', '')
        self.TestLint('snprintf(fisk, 1, format)',
                      'If you can, use sizeof(fisk) instead of 1 as the 2nd arg '
                      'to snprintf.  [runtime/printf] [3]')
