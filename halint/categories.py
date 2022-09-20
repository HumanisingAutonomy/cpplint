# We categorize each error message we print.  Here are the categories.
# We want an explicit list so we can list them all in cpplint --filter=.
# If you add a new error message with a new category, add it to the list
# here!  cpplint_unittest.py should tell you if you forget to do this.
_ERROR_CATEGORIES = [
    "build/class",
    "build/c++11",
    "build/c++14",
    "build/c++tr1",
    "build/deprecated",
    "build/endif_comment",
    "build/explicit_make_pair",
    "build/forward_decl",
    "build/header_guard",
    "build/include",
    "build/include_subdir",
    "build/include_alpha",
    "build/include_order",
    "build/include_what_you_use",
    "build/namespaces_headers",
    "build/namespaces_literals",
    "build/namespaces",
    "build/printf_format",
    "build/storage_class",
    "legal/copyright",
    "readability/alt_tokens",
    "readability/braces",
    "readability/casting",
    "readability/check",
    "readability/constructors",
    "readability/fn_size",
    "readability/inheritance",
    "readability/multiline_comment",
    "readability/multiline_string",
    "readability/namespace",
    "readability/nolint",
    "readability/nul",
    "readability/strings",
    "readability/todo",
    "readability/utf8",
    "runtime/arrays",
    "runtime/casting",
    "runtime/explicit",
    "runtime/int",
    "runtime/init",
    "runtime/invalid_increment",
    "runtime/member_string_references",
    "runtime/memset",
    "runtime/indentation_namespace",
    "runtime/operator",
    "runtime/printf",
    "runtime/printf_format",
    "runtime/references",
    "runtime/string",
    "runtime/threadsafe_fn",
    "runtime/vlog",
    "whitespace/blank_line",
    "whitespace/braces",
    "whitespace/comma",
    "whitespace/comments",
    "whitespace/empty_conditional_body",
    "whitespace/empty_if_body",
    "whitespace/empty_loop_body",
    "whitespace/end_of_line",
    "whitespace/ending_newline",
    "whitespace/forcolon",
    "whitespace/indent",
    "whitespace/line_length",
    "whitespace/newline",
    "whitespace/operators",
    "whitespace/parens",
    "whitespace/semicolon",
    "whitespace/tab",
    "whitespace/todo",
]
