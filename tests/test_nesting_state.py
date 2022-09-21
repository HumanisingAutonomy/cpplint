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

from halint import NestingState

from .utils.error_collector import ErrorCollector


class TestNestingState:
    @pytest.fixture
    def nesting_state(self):
        self.error_collector = ErrorCollector() # TODO: move this into LintState
        return NestingState()

    def update_with_lines(self, state, lines, nesting_state):
        clean_lines = cpplint.CleansedLines(lines, "foo.h")
        for line in range(clean_lines.num_lines()):
            nesting_state.update(state, clean_lines, line, self.error_collector)

    def test_empty(self, state, nesting_state):
        self.update_with_lines(state, [], nesting_state)
        assert nesting_state.stack == []

    def test_namespace(self, state, nesting_state):
        self.update_with_lines(state, ["namespace {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _NamespaceInfo)
        assert nesting_state.stack[0].seen_open_brace
        assert nesting_state.stack[0].name == ""

        self.update_with_lines(state, ["namespace outer { namespace inner"], nesting_state)
        assert len(nesting_state.stack) == 3
        assert nesting_state.stack[0].seen_open_brace
        assert nesting_state.stack[1].seen_open_brace
        assert not nesting_state.stack[2].seen_open_brace
        assert nesting_state.stack[0].name == ""
        assert nesting_state.stack[1].name == "outer"
        assert nesting_state.stack[2].name == "inner"

        self.update_with_lines(state, ["{"], nesting_state)
        assert nesting_state.stack[2].seen_open_brace

        self.update_with_lines(state, ["}", "}}"], nesting_state)
        assert len(nesting_state.stack) == 0

    def test_decorated_class(self, state, nesting_state):
        self.update_with_lines(state, ["class Decorated_123 API A {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "A"
        assert not nesting_state.stack[0].is_derived
        assert nesting_state.stack[0].class_indent == 0
        self.update_with_lines(state, ["}"], nesting_state)
        assert len(nesting_state.stack) == 0

    def test_inner_class(self, state, nesting_state):
        self.update_with_lines(state, ["class A::B::C {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "A::B::C"
        assert not nesting_state.stack[0].is_derived
        assert nesting_state.stack[0].class_indent == 0
        self.update_with_lines(state, ["}"], nesting_state)
        assert len(nesting_state.stack) == 0

    def test_class(self, state, nesting_state):
        self.update_with_lines(state, ["class A {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "A"
        assert not nesting_state.stack[0].is_derived
        assert nesting_state.stack[0].class_indent == 0

        self.update_with_lines(state, ["};", "struct B : public A {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "B"
        assert nesting_state.stack[0].is_derived

        self.update_with_lines(state, ["};", "class C", ": public A {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "C"
        assert nesting_state.stack[0].is_derived

        self.update_with_lines(state, ["};", "template<T>"], nesting_state)
        assert len(nesting_state.stack) == 0

        self.update_with_lines(state, ["class D {", "  class E {"], nesting_state)
        assert len(nesting_state.stack) == 2
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "D"
        assert not nesting_state.stack[0].is_derived
        assert isinstance(nesting_state.stack[1], _ClassInfo)
        assert nesting_state.stack[1].name == "E"
        assert not nesting_state.stack[1].is_derived
        assert nesting_state.stack[1].class_indent == 2
        assert nesting_state.innermost_class().name == "E"

        self.update_with_lines(state, ["}", "}"], nesting_state)
        assert len(nesting_state.stack) == 0

    def test_class_access(self, state, nesting_state):
        self.update_with_lines(state, ["class A {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].access == "private"

        self.update_with_lines(state, [" public:"], nesting_state)
        assert nesting_state.stack[0].access == "public"
        self.update_with_lines(state, [" protracted:"], nesting_state)
        assert nesting_state.stack[0].access == "public"
        self.update_with_lines(state, [" protected:"], nesting_state)
        assert nesting_state.stack[0].access == "protected"
        self.update_with_lines(state, [" private:"], nesting_state)
        assert nesting_state.stack[0].access == "private"

        self.update_with_lines(state, ["  struct B {"], nesting_state)
        assert len(nesting_state.stack) == 2
        assert isinstance(nesting_state.stack[1], _ClassInfo)
        assert nesting_state.stack[1].access == "public"
        assert nesting_state.stack[0].access == "private"

        self.update_with_lines(state, ["   protected  :"], nesting_state)
        assert nesting_state.stack[1].access == "protected"
        assert nesting_state.stack[0].access == "private"

        self.update_with_lines(state, ["  }", "}"], nesting_state)
        assert len(nesting_state.stack) == 0

    def test_struct(self, state, nesting_state):
        self.update_with_lines(state, ["struct A {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "A"
        assert not nesting_state.stack[0].is_derived

        self.update_with_lines(state, ["}", "void Func(struct B arg) {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert not isinstance(nesting_state.stack[0], _ClassInfo)

        self.update_with_lines(state, ["}"], nesting_state)
        assert len(nesting_state.stack) == 0

    def test_preprocessor(self, state, nesting_state):
        assert len(nesting_state.pp_stack) == 0
        self.update_with_lines(state, ["#if MACRO1"], nesting_state)
        assert len(nesting_state.pp_stack) == 1
        self.update_with_lines(state, ["#endif"], nesting_state)
        assert len(nesting_state.pp_stack) == 0

        self.update_with_lines(state, ["#ifdef MACRO2"], nesting_state)
        assert len(nesting_state.pp_stack) == 1
        self.update_with_lines(state, ["#else"], nesting_state)
        assert len(nesting_state.pp_stack) == 1
        self.update_with_lines(state, ["#ifdef MACRO3"], nesting_state)
        assert len(nesting_state.pp_stack) == 2
        self.update_with_lines(state, ["#elif MACRO4"], nesting_state)
        assert len(nesting_state.pp_stack) == 2
        self.update_with_lines(state, ["#endif"], nesting_state)
        assert len(nesting_state.pp_stack) == 1
        self.update_with_lines(state, ["#endif"], nesting_state)
        assert len(nesting_state.pp_stack) == 0

        self.update_with_lines(
            state,
            [
                "#ifdef MACRO5",
                "class A {",
                "#elif MACRO6",
                "class B {",
                "#else",
                "class C {",
                "#endif",
            ], nesting_state
        )
        assert len(nesting_state.pp_stack) == 0
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "A"
        self.update_with_lines(state, ["};"], nesting_state)
        assert len(nesting_state.stack) == 0

        self.update_with_lines(state, ["class D", "#ifdef MACRO7"], nesting_state)
        assert len(nesting_state.pp_stack) == 1
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "D"
        assert not nesting_state.stack[0].is_derived

        self.update_with_lines(state, ["#elif MACRO8", ": public E"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[0].name == "D"
        assert nesting_state.stack[0].is_derived
        assert not nesting_state.stack[0].seen_open_brace

        self.update_with_lines(state, ["#else", "{"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[0].name == "D"
        assert not nesting_state.stack[0].is_derived
        assert nesting_state.stack[0].seen_open_brace

        self.update_with_lines(state, ["#endif"], nesting_state)
        assert len(nesting_state.pp_stack) == 0
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[0].name == "D"
        assert not nesting_state.stack[0].is_derived
        assert not nesting_state.stack[0].seen_open_brace

        self.update_with_lines(state, [";"], nesting_state)
        assert len(nesting_state.stack) == 0

    def test_template(self, state, nesting_state):
        self.update_with_lines(state, ["template <T,", "          class Arg1 = tmpl<T> >"], nesting_state)
        assert len(nesting_state.stack) == 0
        self.update_with_lines(state, ["class A {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "A"

        self.update_with_lines(
            state,
            [
                "};",
                "template <T,",
                "  template <typename, typename> class B>",
                "class C",
            ], nesting_state
        )
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "C"
        self.update_with_lines(state, [";"], nesting_state)
        assert len(nesting_state.stack) == 0

        self.update_with_lines(state, ["class D : public Tmpl<E>"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "D"

        self.update_with_lines(state, ["{", "};"], nesting_state)
        assert len(nesting_state.stack) == 0

        self.update_with_lines(
            state,
            [
                "template <class F,",
                "          class G,",
                "          class H,",
                "          typename I>",
                "static void Func() {",
            ], nesting_state
        )
        assert len(nesting_state.stack) == 1
        assert not isinstance(nesting_state.stack[0], _ClassInfo)
        self.update_with_lines(state, ["}", "template <class J> class K {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "K"

    def test_template_default_arg(self, state, nesting_state):
        self.update_with_lines(
            state,
            ["template <class T, class D = default_delete<T>> class unique_ptr {"],
            nesting_state
        )
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[0], isinstance(self.nesting_state.stack[0], _ClassInfo)

    def test_template_inner_class(self, state, nesting_state):
        self.update_with_lines(state, ["class A {", " public:"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)

        self.update_with_lines(
            state,
            ["  template <class B>", "  class C<alloc<B> >", "      : public A {"],
            nesting_state
        )
        assert len(nesting_state.stack) == 2
        assert isinstance(nesting_state.stack[1], _ClassInfo)

    def test_arguments(self, state, nesting_state):
        self.update_with_lines(state, ["class A {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "A"
        assert nesting_state.stack[-1].open_parentheses == 0

        self.update_with_lines(state, ["  void Func(", "    struct X arg1,"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 1
        self.update_with_lines(state, ["    struct X *arg2);"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 0

        self.update_with_lines(state, ["};"], nesting_state)
        assert len(nesting_state.stack) == 0

        self.update_with_lines(state, ["struct B {"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert isinstance(nesting_state.stack[0], _ClassInfo)
        assert nesting_state.stack[0].name == "B"

        self.update_with_lines(state, ["#ifdef MACRO", "  void Func(", "    struct X arg1"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 1
        self.update_with_lines(state, ["#else"], nesting_state)

        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 0
        self.update_with_lines(state, ["  void Func(", "    struct X arg1"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 1

        self.update_with_lines(state, ["#endif"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 1
        self.update_with_lines(state, ["    struct X *arg2);"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 0

        self.update_with_lines(state, ["};"], nesting_state)
        assert len(nesting_state.stack) == 0

    def test_inline_assembly(self, state, nesting_state):
        self.update_with_lines(
            state,
            [
                "void CopyRow_SSE2(const uint8* src, uint8* dst,",
                "                  int count) {",
            ],
            nesting_state
        )
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 0
        assert nesting_state.stack[-1].inline_asm == _NO_ASM

        self.update_with_lines(state, ["  asm volatile ("], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 1
        assert nesting_state.stack[-1].inline_asm == _INSIDE_ASM

        self.update_with_lines(
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
            nesting_state
        )
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 1
        assert nesting_state.stack[-1].inline_asm == _INSIDE_ASM

        self.update_with_lines(state, ["#if defined(__SSE2__)", '    , "xmm0", "xmm1"'], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 1
        assert nesting_state.stack[-1].inline_asm == _INSIDE_ASM

        self.update_with_lines(state, ["#endif"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 1
        assert nesting_state.stack[-1].inline_asm == _INSIDE_ASM

        self.update_with_lines(state, ["  );"], nesting_state)
        assert len(nesting_state.stack) == 1
        assert nesting_state.stack[-1].open_parentheses == 0
        assert nesting_state.stack[-1].inline_asm == _END_ASM

        self.update_with_lines(state, ["__asm {"], nesting_state)
        assert len(nesting_state.stack) == 2
        assert nesting_state.stack[-1].open_parentheses == 0
        assert nesting_state.stack[-1].inline_asm == _BLOCK_ASM

        self.update_with_lines(state, ["}"], nesting_state)
        assert len(nesting_state.stack) == 1

        self.update_with_lines(state, ["}"], nesting_state)
        assert len(nesting_state.stack) == 0
