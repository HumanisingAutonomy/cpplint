import pytest

import halint.cpplint as cpplint
from halint.block_info import (
    _BLOCK_ASM,
    _END_ASM,
    _INSIDE_ASM,
    _NO_ASM,
    _ClassInfo,
    _NamespaceInfo,
)
from halint.nesting_state import NestingState

from .utils.error_collector import ErrorCollector


class TestNestingState:
    @pytest.fixture(autouse=True)
    def setUp(self):
        self.nesting_state = NestingState()
        self.error_collector = ErrorCollector()

    def UpdateWithLines(self, state, lines):
        clean_lines = cpplint.CleansedLines(lines)
        for line in range(clean_lines.NumLines()):
            self.nesting_state.Update(state, "test.cc", clean_lines, line, self.error_collector)

    def testEmpty(self, state):
        self.UpdateWithLines(state, [])
        assert self.nesting_state.stack == []

    def testNamespace(self, state):
        self.UpdateWithLines(state, ["namespace {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _NamespaceInfo)
        assert self.nesting_state.stack[0].seen_open_brace
        assert self.nesting_state.stack[0].name == ""

        self.UpdateWithLines(state, ["namespace outer { namespace inner"])
        assert len(self.nesting_state.stack) == 3
        assert self.nesting_state.stack[0].seen_open_brace
        assert self.nesting_state.stack[1].seen_open_brace
        assert not self.nesting_state.stack[2].seen_open_brace
        assert self.nesting_state.stack[0].name == ""
        assert self.nesting_state.stack[1].name == "outer"
        assert self.nesting_state.stack[2].name == "inner"

        self.UpdateWithLines(state, ["{"])
        assert self.nesting_state.stack[2].seen_open_brace

        self.UpdateWithLines(state, ["}", "}}"])
        assert len(self.nesting_state.stack) == 0

    def testDecoratedClass(self, state):
        self.UpdateWithLines(state, ["class Decorated_123 API A {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "A"
        assert not self.nesting_state.stack[0].is_derived
        assert self.nesting_state.stack[0].class_indent == 0
        self.UpdateWithLines(state, ["}"])
        assert len(self.nesting_state.stack) == 0

    def testInnerClass(self, state):
        self.UpdateWithLines(state, ["class A::B::C {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "A::B::C"
        assert not self.nesting_state.stack[0].is_derived
        assert self.nesting_state.stack[0].class_indent == 0
        self.UpdateWithLines(state, ["}"])
        assert len(self.nesting_state.stack) == 0

    def testClass(self, state):
        self.UpdateWithLines(state, ["class A {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "A"
        assert not self.nesting_state.stack[0].is_derived
        assert self.nesting_state.stack[0].class_indent == 0

        self.UpdateWithLines(state, ["};", "struct B : public A {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "B"
        assert self.nesting_state.stack[0].is_derived

        self.UpdateWithLines(state, ["};", "class C", ": public A {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "C"
        assert self.nesting_state.stack[0].is_derived

        self.UpdateWithLines(state, ["};", "template<T>"])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(state, ["class D {", "  class E {"])
        assert len(self.nesting_state.stack) == 2
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "D"
        assert not self.nesting_state.stack[0].is_derived
        assert isinstance(self.nesting_state.stack[1], _ClassInfo)
        assert self.nesting_state.stack[1].name == "E"
        assert not self.nesting_state.stack[1].is_derived
        assert self.nesting_state.stack[1].class_indent == 2
        assert self.nesting_state.InnermostClass().name == "E"

        self.UpdateWithLines(state, ["}", "}"])
        assert len(self.nesting_state.stack) == 0

    def testClassAccess(self, state):
        self.UpdateWithLines(state, ["class A {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].access == "private"

        self.UpdateWithLines(state, [" public:"])
        assert self.nesting_state.stack[0].access == "public"
        self.UpdateWithLines(state, [" protracted:"])
        assert self.nesting_state.stack[0].access == "public"
        self.UpdateWithLines(state, [" protected:"])
        assert self.nesting_state.stack[0].access == "protected"
        self.UpdateWithLines(state, [" private:"])
        assert self.nesting_state.stack[0].access == "private"

        self.UpdateWithLines(state, ["  struct B {"])
        assert len(self.nesting_state.stack) == 2
        assert isinstance(self.nesting_state.stack[1], _ClassInfo)
        assert self.nesting_state.stack[1].access == "public"
        assert self.nesting_state.stack[0].access == "private"

        self.UpdateWithLines(state, ["   protected  :"])
        assert self.nesting_state.stack[1].access == "protected"
        assert self.nesting_state.stack[0].access == "private"

        self.UpdateWithLines(state, ["  }", "}"])
        assert len(self.nesting_state.stack) == 0

    def testStruct(self, state):
        self.UpdateWithLines(state, ["struct A {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "A"
        assert not self.nesting_state.stack[0].is_derived

        self.UpdateWithLines(state, ["}", "void Func(struct B arg) {"])
        assert len(self.nesting_state.stack) == 1
        assert not isinstance(self.nesting_state.stack[0], _ClassInfo)

        self.UpdateWithLines(state, ["}"])
        assert len(self.nesting_state.stack) == 0

    def testPreprocessor(self, state):
        assert len(self.nesting_state.pp_stack) == 0
        self.UpdateWithLines(state, ["#if MACRO1"])
        assert len(self.nesting_state.pp_stack) == 1
        self.UpdateWithLines(state, ["#endif"])
        assert len(self.nesting_state.pp_stack) == 0

        self.UpdateWithLines(state, ["#ifdef MACRO2"])
        assert len(self.nesting_state.pp_stack) == 1
        self.UpdateWithLines(state, ["#else"])
        assert len(self.nesting_state.pp_stack) == 1
        self.UpdateWithLines(state, ["#ifdef MACRO3"])
        assert len(self.nesting_state.pp_stack) == 2
        self.UpdateWithLines(state, ["#elif MACRO4"])
        assert len(self.nesting_state.pp_stack) == 2
        self.UpdateWithLines(state, ["#endif"])
        assert len(self.nesting_state.pp_stack) == 1
        self.UpdateWithLines(state, ["#endif"])
        assert len(self.nesting_state.pp_stack) == 0

        self.UpdateWithLines(
            state,
            [
                "#ifdef MACRO5",
                "class A {",
                "#elif MACRO6",
                "class B {",
                "#else",
                "class C {",
                "#endif",
            ],
        )
        assert len(self.nesting_state.pp_stack) == 0
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "A"
        self.UpdateWithLines(state, ["};"])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(state, ["class D", "#ifdef MACRO7"])
        assert len(self.nesting_state.pp_stack) == 1
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "D"
        assert not self.nesting_state.stack[0].is_derived

        self.UpdateWithLines(state, ["#elif MACRO8", ": public E"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[0].name == "D"
        assert self.nesting_state.stack[0].is_derived
        assert not self.nesting_state.stack[0].seen_open_brace

        self.UpdateWithLines(state, ["#else", "{"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[0].name == "D"
        assert not self.nesting_state.stack[0].is_derived
        assert self.nesting_state.stack[0].seen_open_brace

        self.UpdateWithLines(state, ["#endif"])
        assert len(self.nesting_state.pp_stack) == 0
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[0].name == "D"
        assert not self.nesting_state.stack[0].is_derived
        assert not self.nesting_state.stack[0].seen_open_brace

        self.UpdateWithLines(state, [";"])
        assert len(self.nesting_state.stack) == 0

    def testTemplate(self, state):
        self.UpdateWithLines(state, ["template <T,", "          class Arg1 = tmpl<T> >"])
        assert len(self.nesting_state.stack) == 0
        self.UpdateWithLines(state, ["class A {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "A"

        self.UpdateWithLines(
            state,
            [
                "};",
                "template <T,",
                "  template <typename, typename> class B>",
                "class C",
            ],
        )
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "C"
        self.UpdateWithLines(state, [";"])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(state, ["class D : public Tmpl<E>"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "D"

        self.UpdateWithLines(state, ["{", "};"])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(
            state,
            [
                "template <class F,",
                "          class G,",
                "          class H,",
                "          typename I>",
                "static void Func() {",
            ],
        )
        assert len(self.nesting_state.stack) == 1
        assert not isinstance(self.nesting_state.stack[0], _ClassInfo)
        self.UpdateWithLines(state, ["}", "template <class J> class K {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "K"

    def testTemplateDefaultArg(self, state):
        self.UpdateWithLines(
            state,
            ["template <class T, class D = default_delete<T>> class unique_ptr {"],
        )
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[0], isinstance(self.nesting_state.stack[0], _ClassInfo)

    def testTemplateInnerClass(self, state):
        self.UpdateWithLines(state, ["class A {", " public:"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)

        self.UpdateWithLines(
            state,
            ["  template <class B>", "  class C<alloc<B> >", "      : public A {"],
        )
        assert len(self.nesting_state.stack) == 2
        assert isinstance(self.nesting_state.stack[1], _ClassInfo)

    def testArguments(self, state):
        self.UpdateWithLines(state, ["class A {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "A"
        assert self.nesting_state.stack[-1].open_parentheses == 0

        self.UpdateWithLines(state, ["  void Func(", "    struct X arg1,"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        self.UpdateWithLines(state, ["    struct X *arg2);"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0

        self.UpdateWithLines(state, ["};"])
        assert len(self.nesting_state.stack) == 0

        self.UpdateWithLines(state, ["struct B {"])
        assert len(self.nesting_state.stack) == 1
        assert isinstance(self.nesting_state.stack[0], _ClassInfo)
        assert self.nesting_state.stack[0].name == "B"

        self.UpdateWithLines(state, ["#ifdef MACRO", "  void Func(", "    struct X arg1"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        self.UpdateWithLines(state, ["#else"])

        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0
        self.UpdateWithLines(state, ["  void Func(", "    struct X arg1"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1

        self.UpdateWithLines(state, ["#endif"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        self.UpdateWithLines(state, ["    struct X *arg2);"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0

        self.UpdateWithLines(state, ["};"])
        assert len(self.nesting_state.stack) == 0

    def testInlineAssembly(self, state):
        self.UpdateWithLines(
            state,
            [
                "void CopyRow_SSE2(const uint8* src, uint8* dst,",
                "                  int count) {",
            ],
        )
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0
        assert self.nesting_state.stack[-1].inline_asm == _NO_ASM

        self.UpdateWithLines(state, ["  asm volatile ("])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        assert self.nesting_state.stack[-1].inline_asm == _INSIDE_ASM

        self.UpdateWithLines(
            state,
            [
                '    "sub        %0,%1                         \\n"',
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
                "  :",
                '  : "memory", "cc"',
            ],
        )
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        assert self.nesting_state.stack[-1].inline_asm == _INSIDE_ASM

        self.UpdateWithLines(state, ["#if defined(__SSE2__)", '    , "xmm0", "xmm1"'])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        assert self.nesting_state.stack[-1].inline_asm == _INSIDE_ASM

        self.UpdateWithLines(state, ["#endif"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 1
        assert self.nesting_state.stack[-1].inline_asm == _INSIDE_ASM

        self.UpdateWithLines(state, ["  );"])
        assert len(self.nesting_state.stack) == 1
        assert self.nesting_state.stack[-1].open_parentheses == 0
        assert self.nesting_state.stack[-1].inline_asm == _END_ASM

        self.UpdateWithLines(state, ["__asm {"])
        assert len(self.nesting_state.stack) == 2
        assert self.nesting_state.stack[-1].open_parentheses == 0
        assert self.nesting_state.stack[-1].inline_asm == _BLOCK_ASM

        self.UpdateWithLines(state, ["}"])
        assert len(self.nesting_state.stack) == 1

        self.UpdateWithLines(state, ["}"])
        assert len(self.nesting_state.stack) == 0
