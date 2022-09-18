import pytest

import halint.cpplint as cpplint
from halint.nesting_state import NestingState
from .utils.error_collector import ErrorCollector

class TestNestingState:

    @pytest.fixture(autouse=True)
    def setUp(self):
        self.nesting_state = NestingState()
        self.error_collector = ErrorCollector()

    def UpdateWithLines(self, lines):
        clean_lines = cpplint.CleansedLines(lines)
        for line in range(clean_lines.NumLines()):
            self.nesting_state.Update('test.cc',
                                      clean_lines, line, self.error_collector)

    def testEmpty(self):
        self.UpdateWithLines([])
        assert self.nesting_state.stack == []

    def testNamespace(self):
        self.UpdateWithLines(['namespace {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._NamespaceInfo)
        assert self.nesting_state.stack[0].seen_open_brace
        assert self.nesting_state.stack[0].name == ''

        self.UpdateWithLines(['namespace outer { namespace inner'])
        assert len(self.nesting_state.stack) == 3
        assert self.nesting_state.stack[0].seen_open_brace
        assert self.nesting_state.stack[1].seen_open_brace
        assert not self.nesting_state.stack[2].seen_open_brace
        assert self.nesting_state.stack[0].name == ''
        assert self.nesting_state.stack[1].name == 'outer'
        assert self.nesting_state.stack[2].name == 'inner'

        self.UpdateWithLines(['{'])
        assert self.nesting_state.stack[2].seen_open_brace

        self.UpdateWithLines(['}', '}}'])
        assert len(self.nesting_state.stack) == 0

    def testDecoratedClass(self):
        self.UpdateWithLines(['class Decorated_123 API A {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'A'
        assert not self.nesting_state.stack[0].is_derived
        assert self.nesting_state.stack[0].class_indent == 0
        self.UpdateWithLines(['}'])
        assert len(self.nesting_state.stack) == 0

    def testInnerClass(self):
        self.UpdateWithLines(['class A::B::C {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'A::B::C'
        assert not self.nesting_state.stack[0].is_derived
        assert self.nesting_state.stack[0].class_indent == 0
        self.UpdateWithLines(['}'])
        assert len(self.nesting_state.stack) == 0

    def testClass(self):
        self.UpdateWithLines(['class A {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'A'
        assert not self.nesting_state.stack[0].is_derived
        assert self.nesting_state.stack[0].class_indent == 0

        self.UpdateWithLines(['};',
                              'struct B : public A {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'B'
        assert self.nesting_state.stack[0].is_derived

        self.UpdateWithLines(['};',
                              'class C',
                              ': public A {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'C'
        assert self.nesting_state.stack[0].is_derived

        self.UpdateWithLines(['};',
                              'template<T>'])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(['class D {', '  class E {'])
        assert len(self.nesting_state.stack) == 2
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'D'
        assert not self.nesting_state.stack[0].is_derived
        assert isinstance(self.nesting_state.stack[1], cpplint._ClassInfo)
        assert self.nesting_state.stack[1].name == 'E'
        assert not self.nesting_state.stack[1].is_derived
        assert self.nesting_state.stack[1].class_indent == 2
        assert self.nesting_state.InnermostClass().name == 'E'

        self.UpdateWithLines(['}', '}'])
        assert len(self.nesting_state.stack) == 0

    def testClassAccess(self):
        self.UpdateWithLines(['class A {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].access == 'private'

        self.UpdateWithLines([' public:'])
        assert self.nesting_state.stack[0].access == 'public'
        self.UpdateWithLines([' protracted:'])
        assert self.nesting_state.stack[0].access == 'public'
        self.UpdateWithLines([' protected:'])
        assert self.nesting_state.stack[0].access == 'protected'
        self.UpdateWithLines([' private:'])
        assert self.nesting_state.stack[0].access == 'private'

        self.UpdateWithLines(['  struct B {'])
        assert len(self.nesting_state.stack) == 2
        assert isinstance(self.nesting_state.stack[1], cpplint._ClassInfo)
        assert self.nesting_state.stack[1].access == 'public'
        assert self.nesting_state.stack[0].access == 'private'

        self.UpdateWithLines(['   protected  :'])
        assert self.nesting_state.stack[1].access == 'protected'
        assert self.nesting_state.stack[0].access == 'private'

        self.UpdateWithLines(['  }', '}'])
        assert len(self.nesting_state.stack) == 0

    def testStruct(self):
        self.UpdateWithLines(['struct A {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'A'
        assert not self.nesting_state.stack[0].is_derived

        self.UpdateWithLines(['}',
                              'void Func(struct B arg) {'])
        assert len(self.nesting_state.stack) == 1
        assert not isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)

        self.UpdateWithLines(['}'])
        assert len(self.nesting_state.stack) == 0

    def testPreprocessor(self):
        assert len(self.nesting_state.pp_stack) == 0
        self.UpdateWithLines(['#if MACRO1'])
        assert len(self.nesting_state.pp_stack) == 1
        self.UpdateWithLines(['#endif'])
        assert len(self.nesting_state.pp_stack) == 0

        self.UpdateWithLines(['#ifdef MACRO2'])
        assert len(self.nesting_state.pp_stack) == 1
        self.UpdateWithLines(['#else'])
        assert len(self.nesting_state.pp_stack) == 1
        self.UpdateWithLines(['#ifdef MACRO3'])
        assert len(self.nesting_state.pp_stack) == 2
        self.UpdateWithLines(['#elif MACRO4'])
        assert len(self.nesting_state.pp_stack) == 2
        self.UpdateWithLines(['#endif'])
        assert len(self.nesting_state.pp_stack) == 1
        self.UpdateWithLines(['#endif'])
        assert len(self.nesting_state.pp_stack) == 0

        self.UpdateWithLines(['#ifdef MACRO5',
                              'class A {',
                              '#elif MACRO6',
                              'class B {',
                              '#else',
                              'class C {',
                              '#endif'])
        assert len(self.nesting_state.pp_stack) == 0
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'A'
        self.UpdateWithLines(['};'])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(['class D',
                              '#ifdef MACRO7'])
        assert len(self.nesting_state.pp_stack) == 1
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'D'
        assert not self.nesting_state.stack[0].is_derived

        self.UpdateWithLines(['#elif MACRO8', ': public E'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[0].name == 'D'
        assert self.nesting_state.stack[0].is_derived
        assert not self.nesting_state.stack[0].seen_open_brace

        self.UpdateWithLines(['#else',
                              '{'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[0].name == 'D'
        assert not self.nesting_state.stack[0].is_derived
        assert self.nesting_state.stack[0].seen_open_brace

        self.UpdateWithLines(['#endif'])
        assert len(self.nesting_state.pp_stack) == 0
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[0].name == 'D'
        assert not self.nesting_state.stack[0].is_derived
        assert not self.nesting_state.stack[0].seen_open_brace

        self.UpdateWithLines([';'])
        assert len(self.nesting_state.stack) == 0

    def testTemplate(self):
        self.UpdateWithLines(['template <T,',
                              '          class Arg1 = tmpl<T> >'])
        assert len(self.nesting_state.stack) == 0
        self.UpdateWithLines(['class A {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'A'

        self.UpdateWithLines(['};',
                              'template <T,',
                              '  template <typename, typename> class B>',
                              'class C'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'C'
        self.UpdateWithLines([';'])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(['class D : public Tmpl<E>'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'D'

        self.UpdateWithLines(['{', '};'])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(['template <class F,',
                              '          class G,',
                              '          class H,',
                              '          typename I>',
                              'static void Func() {'])
        assert len(self.nesting_state.stack) == 1
        assert not isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        self.UpdateWithLines(['}',
                              'template <class J> class K {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'K'

    def testTemplateDefaultArg(self):
        self.UpdateWithLines([
          'template <class T, class D = default_delete<T>> class unique_ptr {'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[0], isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)

    def testTemplateInnerClass(self):
        self.UpdateWithLines(['class A {',
                              ' public:'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)

        self.UpdateWithLines(['  template <class B>',
                              '  class C<alloc<B> >',
                              '      : public A {'])
        assert len(self.nesting_state.stack) == 2
        assert isinstance(self.nesting_state.stack[1], cpplint._ClassInfo)

    def testArguments(self):
        self.UpdateWithLines(['class A {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'A'
        assert self.nesting_state.stack[-1].open_parentheses == 0

        self.UpdateWithLines(['  void Func(',
                              '    struct X arg1,'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        self.UpdateWithLines(['    struct X *arg2);'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0

        self.UpdateWithLines(['};'])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(['struct B {'])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], cpplint._ClassInfo)
        assert self.nesting_state.stack[0].name == 'B'

        self.UpdateWithLines(['#ifdef MACRO',
                              '  void Func(',
                              '    struct X arg1'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        self.UpdateWithLines(['#else'])

        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0
        self.UpdateWithLines(['  void Func(',
                              '    struct X arg1'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1

        self.UpdateWithLines(['#endif'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        self.UpdateWithLines(['    struct X *arg2);'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0

        self.UpdateWithLines(['};'])
        assert len(self.nesting_state.stack) == 0

    def testInlineAssembly(self):
        self.UpdateWithLines(['void CopyRow_SSE2(const uint8* src, uint8* dst,',
                              '                  int count) {'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0
        assert self.nesting_state.stack[-1].inline_asm == cpplint._NO_ASM

        self.UpdateWithLines(['  asm volatile ('])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        assert self.nesting_state.stack[-1].inline_asm == cpplint._INSIDE_ASM

        self.UpdateWithLines(['    "sub        %0,%1                         \\n"',
                              '  "1:                                         \\n"',
                              '    "movdqa    (%0),%%xmm0                    \\n"',
                              '    "movdqa    0x10(%0),%%xmm1                \\n"',
                              '    "movdqa    %%xmm0,(%0,%1)                 \\n"',
                              '    "movdqa    %%xmm1,0x10(%0,%1)             \\n"',
                              '    "lea       0x20(%0),%0                    \\n"',
                              '    "sub       $0x20,%2                       \\n"',
                              '    "jg        1b                             \\n"',
                              '  : "+r"(src),   // %0',
                              '    "+r"(dst),   // %1',
                              '    "+r"(count)  // %2',
                              '  :',
                              '  : "memory", "cc"'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        assert self.nesting_state.stack[-1].inline_asm == cpplint._INSIDE_ASM

        self.UpdateWithLines(['#if defined(__SSE2__)',
                              '    , "xmm0", "xmm1"'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        assert self.nesting_state.stack[-1].inline_asm == cpplint._INSIDE_ASM

        self.UpdateWithLines(['#endif'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        assert self.nesting_state.stack[-1].inline_asm == cpplint._INSIDE_ASM

        self.UpdateWithLines(['  );'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0
        assert self.nesting_state.stack[-1].inline_asm == cpplint._END_ASM

        self.UpdateWithLines(['__asm {'])
        assert len(self.nesting_state.stack) == 2
        assert self.nesting_state.stack[-1].open_parentheses == 0
        assert self.nesting_state.stack[-1].inline_asm == cpplint._BLOCK_ASM

        self.UpdateWithLines(['}'])
        assert len(self.nesting_state.stack) == 1

        self.UpdateWithLines(['}'])
        assert len(self.nesting_state.stack) == 0
