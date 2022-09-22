from functools import partial

import pytest

from halint import LintState, ProcessFileData

from .base_case import CpplintTestBase

test_lints = partial(pytest.mark.parametrize, "code, expected_message")


class TestSpacesAtStartAndEndOfLine(CpplintTestBase):
    spaces_at_start_and_end_of_line_data = [
        ["// Hello there ",
         "Line ends in whitespace.  Consider deleting these extra spaces.  [whitespace/end_of_line] [4]"],
        [" // Hello there",
         "Weird number of spaces at line-start.  Are you using a 2-space indent?  [whitespace/indent] [3]"]
    ]

    @test_lints(spaces_at_start_and_end_of_line_data)
    def test_spaces_at_start_and_end_of_line(self, state, code, expected_message):
        self.lint(state, code, expected_message)


class TestLineLengths(CpplintTestBase):
    line_lengths_data = [
        [80, "// H %s" % ("H" * 75), ""],
        [80, "// H %s" % ("H" * 76), "Lines should be <= 80 characters long  [whitespace/line_length] [2]"],
        [120, "// H %s" % ("H" * 115), ""],
        [120, "// H %s" % ("H" * 116), "Lines should be <= 120 characters long  [whitespace/line_length] [2]"],
    ]

    @pytest.mark.parametrize("max_line_length,code,expected_message", line_lengths_data)
    def test_line_lengths(self, state: LintState, max_line_length: int, code: str, expected_message: str):
        state._line_length = max_line_length
        self.lint(state, code, expected_message)


class TestSingleStatementOnEachLine(CpplintTestBase):
    multiple_statements_on_same_line_data = [
        ["for (int i = 0; i < 1; i++) {}", ""],
        ["""switch (x) {
                case 0: func(); break;
                }""", ""],
        ["sum += MathUtil::SafeIntRound(x); x += 0.1;",
         "More than one command on the same line  [whitespace/newline] [0]"],
    ]

    @test_lints(multiple_statements_on_same_line_data)
    def test_multiple_statements_on_same_line(self, state, code, expected_message):
        state._verbose_level = 0
        self.lint(state, code, expected_message)


class TestBraces(CpplintTestBase):
    # Braces shouldn't be followed by a ; unless they're defining a struct
    # or initializing an array
    brace_data = [["int a[3] = { 1, 2, 3 };", ""],
                  ["""const int foo[] =
        {1, 2, 3 };""", ""],
                  # For single line, unmatched '}' with a ';' is ignored (not enough context)
                  ["""int a[3] = { 1,
                2,
                3 };""",
                   "", ],
                  ["""int a[2][3] = { { 1, 2 },
                 { 3, 4 } };""",
                   "", ],
                  ["""int a[2][3] =
       { { 1, 2 },
         { 3, 4 } };""",
                   "", ]]

    @test_lints(brace_data)
    def test_braces(self, state, code, expected_message):
        self.lint(state, code, expected_message)

    brace_initializer_list_data = [
        ["MyStruct p = {1, 2};", ""],
        ["MyStruct p{1, 2};", ""],
        ["vector<int> p = {1, 2};", ""],
        ["vector<int> p{1, 2};", ""],
        ["x = vector<int>{1, 2};", ""],
        ["x = (struct in_addr){ 0 };", ""],
        ["Func(vector<int>{1, 2})", ""],
        ["Func((struct in_addr){ 0 })", ""],
        ["Func(vector<int>{1, 2}, 3)", ""],
        ["Func((struct in_addr){ 0 }, 3)", ""],
        ["LOG(INFO) << char{7};", ""],
        ['"!";', ""],
        ["int p[2] = {1, 2};", ""],
        ["return {1, 2};", ""],
        ["std::unique_ptr<Foo> foo{new Foo{}};", ""],
        ["auto foo = std::unique_ptr<Foo>{new Foo{}};", ""],
        ['"");', ""],
        ["map_of_pairs[{1, 2}] = 3;", ""],
        ["ItemView{has_offer() ? new Offer{offer()} : nullptr", ""],
        ["template <class T, EnableIf<::std::is_const<T>{}> = 0>", ""],

        ["std::unique_ptr<Foo> foo{\n" "  new Foo{}\n" "};\n", ""],
        ["std::unique_ptr<Foo> foo{\n" "  new Foo{\n" "    new Bar{}\n" "  }\n" "};\n", ""],
        ["if (true) {\n" "  if (false){ func(); }\n" "}\n", "Missing space before {  [whitespace/braces] [5]"],
        ["MyClass::MyClass()\n" "    : initializer_{\n" "          Func()} {\n" "}\n", ""],
        ["const pair<string, string> kCL" + ("o" * 41) + "gStr[] = {",
         "Lines should be <= 80 characters long  [whitespace/line_length] [2]"],
        ["const pair<string, string> kCL" + ("o" * 40) + "ngStr[] =\n"
                                                         "    {\n"
                                                         '        {"gooooo", "oooogle"},\n'
                                                         "};\n", ""],
        ["const pair<string, string> kCL" + ("o" * 39) + "ngStr[] =\n"
                                                         "    {\n"
                                                         '        {"gooooo", "oooogle"},\n'
                                                         "};\n",
         "{ should almost always be at the end of the previous line  [whitespace/braces] [4]"],
    ]

    @pytest.mark.parametrize("code, expected_message", brace_initializer_list_data)
    def test_brace_initializer_list(self, state, code, expected_message):
        self.lint(state, code, expected_message)


class TestTrailingSemicolon(CpplintTestBase):
    semicolon_after_braces_data = [["if (cond) { func(); };",
                                    "You don't need a ; after a }  [readability/braces] [4]"],
                                   ["void Func() {};",
                                    "You don't need a ; after a }  [readability/braces] [4]"],
                                   ["void Func() const {};",
                                    "You don't need a ; after a }  [readability/braces] [4]"],
                                   ["class X {};", ""],
                                   ["class X : public Y {};", ""],
                                   ["class X : public MACRO() {};", ""],
                                   ["class X : public decltype(expr) {};", ""],
                                   ["DEFINE_FACADE(PCQueue::Watcher, PCQueue) {};", ""],
                                   ["VCLASS(XfaTest, XfaContextTest) {};", ""],
                                   ["class STUBBY_CLASS(H, E) {};", ""],
                                   ["class STUBBY2_CLASS(H, E) {};", ""],
                                   ["file_tocs_[i] = (FileToc) {a, b, c};", ""],
                                   ["class X : public Y,\npublic Z {};", ""],
                                   ["TEST(TestCase, TestName) {};",
                                    "You don't need a ; after a }  [readability/braces] [4]"],
                                   ["TEST_F(TestCase, TestName) {};",
                                    "You don't need a ; after a }  [readability/braces] [4]"],
                                   ]

    for keyword in ["struct", "union"]:
        for align in ["", " alignas(16)"]:
            for typename in ["", " X"]:
                for identifier in ["", " x"]:
                    semicolon_after_braces_data.append([keyword + align + typename + " {}" + identifier + ";", ""])

    @test_lints(semicolon_after_braces_data)
    def test_semicolon_after_braces(self, state, code, expected_message):
        self.lint(state, code, expected_message)


class TestEmptyBlockBody(CpplintTestBase):
    empty_block_body_data = [
        ["while (true);", "Empty loop bodies should use {} or continue  [whitespace/empty_loop_body] [5]"],
        ["if (true);", "Empty conditional bodies should use {}  [whitespace/empty_conditional_body] [5]"],
        ["for (;;);", "Empty loop bodies should use {} or continue  [whitespace/empty_loop_body] [5]"],
        ["for (;;) continue;", ""],
        ["for (;;) func();", ""],
        ["if (test) {}", "If statement had no body and no else clause  [whitespace/empty_if_body] [4]"],
        ["if (test) func();", ""],
        ["if (test) {} else {}", ""],
        ["""while (true &&
                                 false);""",
         "Empty loop bodies should use {} or continue  [whitespace/empty_loop_body] [5]"],
        ["""do {
                       } while (false);""", ""],
        ["""#define MACRO \\
                           do { \\
                           } while (false);""",
         ""],
        ["""do {
                           } while (false);  // next line gets a warning
                           while (false);""",
         "Empty loop bodies should use {} or continue  [whitespace/empty_loop_body] [5]"],
        ["""if (test) {
                           }""",
         "If statement had no body and no else clause  [whitespace/empty_if_body] [4]"],
        ["""if (test,
                               func({})) {
                           }""",
         "If statement had no body and no else clause  [whitespace/empty_if_body] [4]"],
        ["""if (test)
                          func();""",
         ""],
        ["if (test) { hello; }", ""],
        ["if (test({})) { hello; }", ""],
        ["""if (test) {
                             func();
                           }""",
         ""],
        ["""if (test) {
                             // multiline
                             // comment
                           }""",
         ""],
        ["""if (test) {  // comment
                           }""",
         ""],
        ["""if (test) {
                           } else {
                           }""",
         ""],
        ["""if (func(p1,
                               p2,
                               p3)) {
                             func();
                           }""",
         ""],
        ["""if (func({}, p1)) {
                             func();
                           }""",
         ""],
    ]

    @test_lints(empty_block_body_data)
    def test_empty_block_body(self, state, code, expected_message):
        self.lint(state, code, expected_message)


class TestSpacing(CpplintTestBase):
    spacing_around_else_data = [["}else {", "Missing space before else" "  [whitespace/braces] [5]"],
                                ["} else{", "Missing space before {" "  [whitespace/braces] [5]"],
                                ["} else {", ""],
                                ["} else if (foo) {", ""]]

    @test_lints(spacing_around_else_data)
    def test_spacing_around_else(self, state, code, expected_message):
        self.lint(state, code, expected_message)

    def test_no_blank_line_after_section_keyword(self, state):
        self.lint_file(state, "check_style/spacing/no_blank_line_after_section_keyword.cc",
                       ['Do not leave a blank line after "public:"  [whitespace/blank_line] [3]',
                        'Do not leave a blank line after "private:"  [whitespace/blank_line] [3]',
                        'Do not leave a blank line after "protected:"  [whitespace/blank_line] [3]'],
                       ignore_addition_messages=True
                       )


class TestOperatorSpacing(CpplintTestBase):
    shift_operator_spacing_data = [
        ["a<<b", "Missing spaces around <<  [whitespace/operators] [3]"],
        ["a>>b", "Missing spaces around >>  [whitespace/operators] [3]"],
        ["1<<20", ""],
        ["1024>>10", ""],
        ["Kernel<<<1, 2>>>()", ""],
    ]

    @test_lints(shift_operator_spacing_data)
    def test_shift_operator_spacing(self, state, code, expected_message):
        self.lint(state, code, expected_message)
