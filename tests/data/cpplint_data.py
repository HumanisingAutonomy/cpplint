line_length_data = [
    ["// Hello", ""],
    [
        "// x" + " x" * 40,
        "Lines should be <= 80 characters long  [whitespace/line_length] [2]",
    ],
    [
        "// x" + " x" * 50,
        "Lines should be <= 80 characters long" "  [whitespace/line_length] [2]",
    ],
    ["// //some/path/to/f" + ("i" * 100) + "le", ""],
    ["//   //some/path/to/f" + ("i" * 100) + "le", ""],
    [
        "//   //some/path/to/f" + ("i" * 50) + "le and some comments",
        "Lines should be <= 80 characters long  [whitespace/line_length] [2]",
    ],
    ["// http://g" + ("o" * 100) + "gle.com/", ""],
    ["//   https://g" + ("o" * 100) + "gle.com/", ""],
    [
        "//   https://g" + ("o" * 60) + "gle.com/ and some comments",
        "Lines should be <= 80 characters long  [whitespace/line_length] [2]",
    ],
    ["// Read https://g" + ("o" * 60) + "gle.com/", ""],
    ["// $Id: g" + ("o" * 80) + "gle.cc#1 $", ""],
    [
        "// $Id: g" + ("o" * 80) + "gle.cc#1",
        "Lines should be <= 80 characters long  [whitespace/line_length] [2]",
    ],
    [
        'static const char kCStr[] = "g' + ("o" * 50) + 'gle";\n',
        "Lines should be <= 80 characters long  [whitespace/line_length] [2]",
    ],
    [
        'static const char kRawStr[] = R"(g' + ("o" * 50) + 'gle)";\n',
        "",
    ],  # no warning because raw string content is elided
    [
        'static const char kMultiLineRawStr[] = R"(\n' "g" + ("o" * 80) + "gle\n" ')";',
        "",
    ],
    [
        "static const char kL" + ("o" * 50) + 'ngIdentifier[] = R"()";\n',
        "Lines should be <= 80 characters long  [whitespace/line_length] [2]",
    ],
    ["  /// @copydoc " + ("o" * 120), ""],
    ["  /// @copydetails " + ("o" * 120), ""],
    ["  /// @copybrief " + ("o" * 120), ""],
]

error_suppression_data = [
    [
        "long a = (int64) 65;",
        [
            "Using C-style cast.  Use static_cast<int64>(...) instead  [readability/casting] [4]",
            "Use int16/int64/etc, rather than the C type long  [runtime/int] [4]",
        ],
    ],
    # One category of error suppressed:
    [
        "long a = (int64) 65;  // NOLINT(runtime/int)",
        "Using C-style cast.  Use static_cast<int64>(...) instead  [readability/casting] [4]",
    ],
    # All categories suppressed: (two aliases)
    ["long a = (int64) 65;  // NOLINT", ""],
    ["long a = (int64) 65;  // NOLINT(*)", ""],
    # Malformed NOLINT directive:
    [
        "long a = 65;  // NOLINT(foo)",
        [
            "Unknown NOLINT error category: foo  [readability/nolint] [5]",
            "Use int16/int64/etc, rather than the C type long  [runtime/int] [4]",
        ],
    ],
    # Irrelevant NOLINT directive has no effect:
    [
        "long a = 65;  // NOLINT(readability/casting)",
        "Use int16/int64/etc, rather than the C type long  [runtime/int] [4]",
    ],
]

error_suppression_file_data = [
    [
        [
            "/r Copyright 2014 Your Company.",
            "// NOLINTNEXTLINE(whitespace/line_length)",
            "//  ./command" + (" -verbose" * 80),
            "",
        ],
        "",
        "test.cc",
    ],
    # LINT_C_FILE silences cast warnings for entire file.
    [
        [
            "// Copyright 2014 Your Company.",
            "// NOLINT(build/header_guard)",
            "int64 a = (uint64) 65;",
            "//  LINT_C_FILE",
            "",
        ],
        "",
        "test.h",
    ],
    # LINT_KERNEL_FILE silences whitespace/tab warnings for entire file.
    [
        [
            "// Copyright 2014 Your Company.",
            "// NOLINT(build/header_guard)",
            "struct test {",
            "\tint member;",
            "};",
            "//  LINT_KERNEL_FILE",
            "",
        ],
        "",
        "test.h",
    ],
    # NOLINT, NOLINTNEXTLINE silences the readability/braces warning for "};".
    [
        [
            "// Copyright 2014 Your Company.",
            "for (int i = 0; i != 100; ++i) {",
            "  std::cout << i << std::endl;",
            "};  // NOLINT",
            "for (int i = 0; i != 100; ++i) {",
            "  std::cout << i << std::endl;",
            "// NOLINTNEXTLINE",
            "};",
            "//  LINT_KERNEL_FILE",
            "",
        ],
        "",
        "test.cc",
    ],
]

# NOLINTNEXTLINE silences warning for the next line instead of current line
# Vim modes silence cast warnings for entire file.
error_suppression_file_data += [
    [
        [
            "// Copyright 2014 Your Company.",
            "// NOLINT(build/header_guard)",
            "int64 a = (uint64) 65;",
            "/* Prevent warnings about the modeline",
            modeline,
            "*/",
            "",
        ],
        "",
        "test.cc",
    ]
    for modeline in [
        "vi:filetype=c",
        "vi:sw=8 filetype=c",
        "vi:sw=8 filetype=c ts=8",
        "vi: filetype=c",
        "vi: sw=8 filetype=c",
        "vi: sw=8 filetype=c ts=8",
        "vim:filetype=c",
        "vim:sw=8 filetype=c",
        "vim:sw=8 filetype=c ts=8",
        "vim: filetype=c",
        "vim: sw=8 filetype=c",
        "vim: sw=8 filetype=c ts=8",
        "vim: set filetype=c:",
        "vim: set sw=8 filetype=c:",
        "vim: set sw=8 filetype=c ts=8:",
        "vim: set filetype=c :",
        "vim: set sw=8 filetype=c :",
        "vim: set sw=8 filetype=c ts=8 :",
        "vim: se filetype=c:",
        "vim: se sw=8 filetype=c:",
        "vim: se sw=8 filetype=c ts=8:",
        "vim: se filetype=c :",
        "vim: se sw=8 filetype=c :",
        "vim: se sw=8 filetype=c ts=8 :",
    ]
]

variable_declaration_data = [
    [
        "long a = 65;",
        "Use int16/int64/etc, rather than the C type long  [runtime/int] [4]",
    ],
    ["long double b = 65.0;", ""],
    [
        "long long aa = 6565;",
        "Use int16/int64/etc, rather than the C type long  [runtime/int] [4]",
    ],
]

c_style_cast_data = [
    [
        "int a = (int)1.0;",
        "Using C-style cast.  Use static_cast<int>(...) instead  [readability/casting] [4]",
    ],
    [
        "int a = (int)-1.0;",
        "Using C-style cast.  Use static_cast<int>(...) instead  [readability/casting] [4]",
    ],
    [
        "int *a = (int *)NULL;",
        "Using C-style cast.  Use reinterpret_cast<int *>(...) instead  [readability/casting] [4]",
    ],
    [
        "uint16 a = (uint16)1.0;",
        "Using C-style cast.  Use static_cast<uint16>(...) instead  [readability/casting] [4]",
    ],
    [
        "int32 a = (int32)1.0;",
        "Using C-style cast.  Use static_cast<int32>(...) instead  [readability/casting] [4]",
    ],
    [
        "uint64 a = (uint64)1.0;",
        "Using C-style cast.  Use static_cast<uint64>(...) instead  [readability/casting] [4]",
    ],
    [
        "size_t a = (size_t)1.0;",
        "Using C-style cast.  Use static_cast<size_t>(...) instead  [readability/casting] [4]",
    ],
    # These shouldn't be recognized casts.
    ["u a = (u)NULL;", ""],
    ["uint a = (uint)NULL;", ""],
    ["typedef MockCallback<int(int)> CallbackType;", ""],
    ["scoped_ptr< MockCallback<int(int)> > callback_value;", ""],
    ["std::function<int(bool)>", ""],
    ["x = sizeof(int)", ""],
    ["x = alignof(int)", ""],
    ["alignas(int) char x[42]", ""],
    ["alignas(alignof(x)) char y[42]", ""],
    ["void F(int (func)(int));", ""],
    ["void F(int (func)(int*));", ""],
    ["void F(int (Class::member)(int));", ""],
    ["void F(int (Class::member)(int*));", ""],
    ["void F(int (Class::member)(int), int param);", ""],
    ["void F(int (Class::member)(int*), int param);", ""],
    ["X Class::operator++(int)", ""],
    ["X Class::operator--(int)", ""],
    # These should not be recognized (lambda functions without arg names).
    ["[](int/*unused*/) -> bool {", ""],
    ["[](int /*unused*/) -> bool {", ""],
    ["auto f = [](MyStruct* /*unused*/)->int {", ""],
    ["[](int) -> bool {", ""],
    ["auto f = [](MyStruct*)->int {", ""],
    # Cast with brace initializers
    ["int64_t{4096} * 1000 * 1000", ""],
    ["size_t{4096} * 1000 * 1000", ""],
    ["uint_fast16_t{4096} * 1000 * 1000", ""],
    # Brace initializer with templated type
    [
        """
    template <typename Type1,
                typename Type2>
    void Function(int arg1,
                    int arg2) {
        variable &= ~Type1{0} - 1;
    }""",
        "",
    ],
    [
        """
    template <typename Type>
    class Class {
        void Function() {
        variable &= ~Type{0} - 1;
        }
    };""",
        "",
    ],
    [
        """
    template <typename Type>
    class Class {
        void Function() {
        variable &= ~Type{0} - 1;
        }
    };""",
        "",
    ],
    [
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
        "",
    ],
]

_runtime_casting_error_msg = (
    "Are you taking an address of a cast?  "
    "This is dangerous: could be a temp var.  "
    "Take the address before doing the cast, rather than after"
    "  [runtime/casting] [4]"
)
_runtime_casting_alt_error_msg = (
    "Are you taking an address of something dereferenced "
    "from a cast?  Wrapping the dereferenced expression in "
    "parentheses will make the binding more obvious"
    "  [readability/casting] [4]"
)

runtime_casting_data = [
    ["int* x = &static_cast<int*>(foo);", _runtime_casting_error_msg],
    ["int* x = &reinterpret_cast<int *>(foo);", _runtime_casting_error_msg],
    [
        "int* x = &(int*)foo;",
        [
            "Using C-style cast.  Use reinterpret_cast<int*>(...) instead  [readability/casting] [4]",
            _runtime_casting_error_msg,
        ],
    ],
    ["BudgetBuckets&(BudgetWinHistory::*BucketFn)(void) const;", ""],
    ["&(*func_ptr)(arg)", ""],
    ["Compute(arg, &(*func_ptr)(i, j));", ""],
    # Alternative error message
    ["int* x = &down_cast<Obj*>(obj)->member_;", _runtime_casting_alt_error_msg],
    ["int* x = &down_cast<Obj*>(obj)[index];", _runtime_casting_alt_error_msg],
    ["int* x = &(down_cast<Obj*>(obj)->member_);", ""],
    ["int* x = &(down_cast<Obj*>(obj)[index]);", ""],
    ["int* x = &down_cast<Obj*>(obj)\n->member_;", _runtime_casting_alt_error_msg],
    ["int* x = &(down_cast<Obj*>(obj)\n->member_);", ""],
    # It's OK to cast an address.
    ["int* x = reinterpret_cast<int *>(&foo);", ""],
    # Function pointers returning references should not be confused
    # with taking address of old-style casts.
    ["auto x = implicit_cast<string &(*)(int)>(&foo);", ""],
]

runtime_self_init_data = [
    [
        "Foo::Foo(Bar r, Bel l) : r_(r_), l_(l_) { }",
        "You seem to be initializing a member variable with itself.  [runtime/init] [4]",
    ],
    [
        "Foo::Foo(Bar r, Bel l) : r_(CHECK_NOTNULL(r_)) { }",
        "You seem to be initializing a member variable with itself.  [runtime/init] [4]",
    ],
    ["Foo::Foo(Bar r, Bel l) : r_(r), l_(l) { }", ""],
    ["Foo::Foo(Bar r) : r_(r), l_(r_), ll_(l_) { }", ""],
]

check_for_unnamed_params_data = [
    ["virtual void Func(int*) const;", ""],
    ["virtual void Func(int*);", ""],
    ["void Method(char*) {", ""],
    ["void Method(char*);", ""],
    ["static void operator delete[](void*) throw();", ""],
    ["int Method(int);", ""],
    ["virtual void Func(int* p);", ""],
    ["void operator delete(void* x) throw();", ""],
    ["void Method(char* x) {", ""],
    ["void Method(char* /*x*/) {", ""],
    ["void Method(char* x);", ""],
    ["typedef void (*Method)(int32 x);", ""],
    ["static void operator delete[](void* x) throw();", ""],
    ["static void operator delete[](void* /*x*/) throw();", ""],
    ["X operator++(int);", ""],
    ["X operator++(int) {", ""],
    ["X operator--(int);", ""],
    ["X operator--(int /*unused*/) {", ""],
    ["MACRO(int);", ""],
    ["MACRO(func(int));", ""],
    ["MACRO(arg, func(int));", ""],
    ["void (*func)(void*);", ""],
    ["void Func((*func)(void*)) {}", ""],
    ["template <void Func(void*)> void func();", ""],
    ["virtual void f(int /*unused*/) {", ""],
    ["void f(int /*unused*/) override {", ""],
    ["void f(int /*unused*/) final {", ""],
]

# Test deprecated casts such as int(d)
deprecated_cast_data = [
    [
        "int a = int(2.2);",
        "Using deprecated casting style.  Use static_cast<int>(...) instead  [readability/casting] [4]",
    ],
    [
        '(char *) "foo"',
        "Using C-style cast.  Use const_cast<char *>(...) instead  [readability/casting] [4]",
    ],
    [
        "(int*)foo",
        "Using C-style cast.  Use reinterpret_cast<int*>(...) instead  [readability/casting] [4]",
    ],
    # Checks for false positives...
    ["int a = int();", ""],  # constructor
    ["X::X() : a(int()) {}", ""],  # default constructor
    ["operator bool();", ""],  # Conversion operator
    ["new int64(123);", ""],  # "new" operator on basic type
    ["new   int64(123);", ""],  # "new" operator on basic type
    ["new const int(42);", ""],  # "new" on const-qualified type
    ["using a = bool(int arg);", ""],  # C++11 alias-declaration
    ["x = bit_cast<double(*)[3]>(y);", ""],  # array of array
    ["void F(const char(&src)[N]);", ""],  # array of references
    # Placement new
    ["new(field_ptr) int(field->default_value_enum()->number());", ""],
    # C++11 function wrappers
    ["std::function<int(bool)>", ""],
    ["std::function<const int(bool)>", ""],
    ["std::function< int(bool) >", ""],
    ["mfunction<int(bool)>", ""],
    # Return types for function pointers
    ["typedef bool(FunctionPointer)();", ""],
    ["typedef bool(FunctionPointer)(int param);", ""],
    ["typedef bool(MyClass::*MemberFunctionPointer)();", ""],
    ["typedef bool(MyClass::* MemberFunctionPointer)();", ""],
    ["typedef bool(MyClass::*MemberFunctionPointer)() const;", ""],
    ["void Function(bool(FunctionPointerArg)());", ""],
    ["void Function(bool(FunctionPointerArg)()) {}", ""],
    ["typedef set<int64, bool(*)(int64, int64)> SortedIdSet", ""],
    ["bool TraverseNode(T *Node, bool(VisitorBase:: *traverse) (T *t)) {}", ""],
]

deprecated_cast_file_data = [
    [
        [
            "// Copyright 2014 Your Company. All Rights Reserved.",
            "typedef std::function<",
            "    bool(int)> F;",
            "",
        ],
        "",
        "test.cc",
    ]
]

mock_method_data = [
    ["MOCK_METHOD0(method, int());", ""],
    ["MOCK_CONST_METHOD1(method, float(string));", ""],
    ["MOCK_CONST_METHOD2_T(method, double(float, float));", ""],
    ["MOCK_CONST_METHOD1(method, SomeType(int));", ""],
]

mock_method_file_data = [
    [
        [
            "MOCK_METHOD1(method1,",
            "             bool(int));",
            "MOCK_METHOD1(",
            "    method2,",
            "    bool(int));",
            "MOCK_CONST_METHOD2(",
            "    method3, bool(int,",
            "                  int));",
            "MOCK_METHOD1(method4, int(bool));",
            "const int kConstant = int(42);",
        ],  # true positive
        "mock.cc",
        {
            "Using deprecated casting style.  Use static_cast<bool>(...) instead  [readability/casting] [4]": 0,
            "Using deprecated casting style.  Use static_cast<int>(...) instead  [readability/casting] [4]": 1,
        },
    ]
]

raw_strings_data = [
    [
        """
int main() {
    struct A {
        A(std::string s, A&& a);
    };
}""",
        "",
    ],
    [
        """
template <class T, class D = default_delete<T>> class unique_ptr {
 public:
    unique_ptr(unique_ptr&& u) noexcept;
};""",
        "",
    ],
    [
        """
void Func() {
    static const char kString[] = R"(
    #endif  <- invalid preprocessor should be ignored
    */      <- invalid comment should be ignored too
    )";
}""",
        "",
    ],
    [
        """
void Func() {
    string s = R"TrueDelimiter(
        )"
        )FalseDelimiter"
        )TrueDelimiter";
}""",
        "",
    ],
    [
        """
void Func() {
    char char kString[] = R"(  ";" )";
}""",
        "",
    ],
    [
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
        "",
    ],
    [
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
        "",
    ],
    [
        """
static SomeStruct kData = {
    {0, R"(line1
            line2
            )"}
    };""",
        "",
    ],
]

multiline_comment_data = [
    [
        r"""int a = 0;
/* multi-liner
class Foo {
Foo(int f);  // should cause a lint warning in code
}
*/ """,
        "",
    ],
    [
        r"""/* int a = 0; multi-liner
               static const int b = 0;""",
            "Could not find end of multi-line comment  [readability/multiline_comment] [5]"
    ],
    [
        r"""/* multi-line comment""",
        [
            "Could not find end of multi-line comment  [readability/multiline_comment] [5]",
            "Complex multi-line /*...*/-style comment found. Lint may give bogus warnings.  Consider replacing these with //-style comments, with #if 0...#endif, or with more clearly structured multi-line comments.  [readability/multiline_comment] [5]",
        ],
    ],
    [r"""// /* comment, but not multi-line""", ""],
    [
        r"""/**********
 */""",
        "",
    ],
    [
        """/**
  * Doxygen comment
  */""",
        "",
    ],
    [
        r"""/*!
  * Doxygen comment
  */""",
        "",
    ],
]

explicit_single_argument_constructors_data = [
    # missing explicit is bad
    [
        """
class Foo {
    Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # missing explicit is bad, even with whitespace
    [
        """
class Foo {
    Foo (int f);
};""",
        [
            "Extra space before ( in function call  [whitespace/parens] [4]",
            "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
        ],
    ],
    # missing explicit, with distracting comment, is still bad
    [
        """
class Foo {
    Foo(int f);  // simpler than Foo(blargh, blarg)
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # missing explicit, with qualified classname
    [
        """
class Qualifier::AnotherOne::Foo {
    Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # missing explicit for inline constructors is bad as well
    [
        """
class Foo {
    inline Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # missing explicit for constexpr constructors is bad as well
    [
        """
class Foo {
    constexpr Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # missing explicit for constexpr+inline constructors is bad as well
    [
        """
class Foo {
    constexpr inline Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    [
        """
class Foo {
    inline constexpr Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # explicit with inline is accepted
    [
        """
class Foo {
    inline explicit Foo(int f);
};""",
        "",
    ],
    [
        """
class Foo {
    explicit inline Foo(int f);
};""",
        "",
    ],
    # explicit with constexpr is accepted
    [
        """
class Foo {
    constexpr explicit Foo(int f);
};""",
        "",
    ],
    [
        """
class Foo {
    explicit constexpr Foo(int f);
};""",
        "",
    ],
    # explicit with constexpr+inline is accepted
    [
        """
class Foo {
    inline constexpr explicit Foo(int f);
};""",
        "",
    ],
    [
        """
class Foo {
    explicit inline constexpr Foo(int f);
};""",
        "",
    ],
    [
        """
class Foo {
    constexpr inline explicit Foo(int f);
};""",
        "",
    ],
    [
        """
class Foo {
    explicit constexpr inline Foo(int f);
};""",
        "",
    ],
    # structs are caught as well.
    [
        """
struct Foo {
    Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # Templatized classes are caught as well.
    [
        """
template<typename T> class Foo {
    Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # inline case for templatized classes.
    [
        """
template<typename T> class Foo {
    inline Foo(int f);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # constructors with a default argument should still be marked explicit
    [
        """
class Foo {
    Foo(int f = 0);
};""",
        "Constructors callable with one argument should be marked explicit.  [runtime/explicit] [5]",
    ],
    # multi-argument constructors with all but one default argument should be marked explicit
    [
        """
class Foo {
    Foo(int f, int g = 0);
};""",
        "Constructors callable with one argument should be marked explicit.  [runtime/explicit] [5]",
    ],
    # multi-argument constructors with all default arguments should be marked explicit
    [
        """
class Foo {
    Foo(int f = 0, int g = 0);
};""",
        "Constructors callable with one argument should be marked explicit.  [runtime/explicit] [5]",
    ],
    # explicit no-argument constructors are bad
    [
        """
class Foo {
    explicit Foo();
};""",
        "Zero-parameter constructors should not be marked explicit.  [runtime/explicit] [5]",
    ],
    # void constructors are considered no-argument
    [
        """
class Foo {
    explicit Foo(void);
};""",
        "Zero-parameter constructors should not be marked explicit.  [runtime/explicit] [5]",
    ],
    # No warning for multi-parameter constructors
    [
        """
class Foo {
    explicit Foo(int f, int g);
};""",
        "",
    ],
    [
        """
class Foo {
    explicit Foo(int f, int g = 0);
};""",
        "",
    ],
    # single-argument constructors that take a function that takes multiple arguments should be explicit
    [
        """
class Foo {
    Foo(void (*f)(int f, int g));
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # single-argument constructors that take a single template argument with multiple parameters should be explicit
    [
        """
template <typename T, typename S>
class Foo {
    Foo(Bar<T, S> b);
};""",
        "Single-parameter constructors should be marked explicit.  [runtime/explicit] [5]",
    ],
    # but copy constructors that take multiple template parameters are OK
    [
        """
template <typename T, S>
class Foo {
    Foo(Foo<T, S>& f);
};""",
        "",
    ],
    # proper style is okay
    [
        """
class Foo {
    explicit Foo(int f);
};""",
        "",
    ],
    # two argument constructor is okay
    [
        """
class Foo {
    Foo(int f, int b);
};""",
        "",
    ],
    # two argument constructor, across two lines, is okay
    [
        """
class Foo {
    Foo(int f,
int b);
};""",
        "",
    ],
    # non-constructor (but similar name), is okay
    [
        """
class Foo {
    aFoo(int f);
};""",
        "",
    ],
    # constructor with void argument is okay
    [
        """
class Foo {
    Foo(void);
};""",
        "",
    ],
    # single argument method is okay
    [
        """
class Foo {
    Bar(int b);
};""",
        "",
    ],
    # comments should be ignored
    [
        """
class Foo {
    // Foo(int f);
};""",
        "",
    ],
    # single argument function following class definition is okay
    # (okay, it's not actually valid, but we don't want a false positive)
    [
        """
class Foo {
    Foo(int f, int b);
};
Foo(int f);""",
        "",
    ],
    # single argument function is okay
    ["""static Foo(int f);""", ""],
    # single argument copy constructor is okay.
    [
        """
class Foo {
    Foo(const Foo&);
};""",
        "",
    ],
    [
        """
class Foo {
    Foo(volatile Foo&);
};""",
        "",
    ],
    [
        """
class Foo {
    Foo(volatile const Foo&);
};""",
        "",
    ],
    [
        """
class Foo {
    Foo(const volatile Foo&);
};""",
        "",
    ],
    [
        """
class Foo {
    Foo(Foo const&);
};""",
        "",
    ],
    [
        """
class Foo {
    Foo(Foo&);
};""",
        "",
    ],
    # templatized copy constructor is okay.
    [
        """
template<typename T> class Foo {
    Foo(const Foo<T>&);
};""",
        "",
    ],
    # Special case for std::initializer_list
    [
        """
class Foo {
    Foo(std::initializer_list<T> &arg) {}
};""",
        "",
    ],
]
