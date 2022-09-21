import halint.cpplint as cpplint


class TestCleansedLines:
    def testInit(self):
        lines = [
            "Line 1",
            "Line 2",
            "Line 3 // Comment test",
            "Line 4 /* Comment test */",
            'Line 5 "foo"',
        ]

        clean_lines = cpplint.CleansedLines(lines, "foo.h")
        assert lines == clean_lines.raw_lines
        assert 5 == clean_lines.num_lines()

        assert [
            "Line 1",
            "Line 2",
            "Line 3",
            "Line 4",
            'Line 5 "foo"',
        ] == clean_lines.lines

        assert [
            "Line 1",
            "Line 2",
            "Line 3",
            "Line 4",
            'Line 5 ""',
        ] == clean_lines.elided

    def testInitEmpty(self):
        clean_lines = cpplint.CleansedLines([], "foo.h")
        assert [] == clean_lines.raw_lines
        assert 0 == clean_lines.num_lines()

    def testCollapseStrings(self):
        collapse = cpplint.CleansedLines.collapse_strings
        assert '""' == collapse('""')  # ""     (empty)
        assert '"""' == collapse('"""')  # """    (bad)
        assert '""' == collapse('"xyz"')  # "xyz"  (string)
        assert '""' == collapse('"\\""')  # "\""   (string)
        assert '""' == collapse('"\'"')  # "'"    (string)
        assert '""' == collapse('""')  # "\"    (bad)
        assert '""' == collapse('"\\\\"')  # "\\"   (string)
        assert '"' == collapse('"\\\\\\"')  # "\\\"  (bad)
        assert '""' == collapse('"\\\\\\\\"')  # "\\\\" (string)

        assert "''" == collapse("''")  # ''     (empty)
        assert "''" == collapse("'a'")  # 'a'    (char)
        assert "''" == collapse("'\\''")  # '\''   (char)
        assert "'" == collapse("'\\'")  # '\'    (bad)
        assert "" == collapse("\\012")  # '\012' (char)
        assert "" == collapse("\\xfF0")  # '\xfF0' (char)
        assert "" == collapse("\\n")  # '\n' (char)
        assert r"\#" == collapse("\\#")  # '\#' (bad)

        assert '"" + ""' == collapse('"\'" + "\'"')
        assert "'', ''", collapse("'\"' == '\"'")
        assert '""[0b10]' == collapse("\"a'b\"[0b1'0]")

        assert "42" == collapse("4'2")
        assert "0b0101" == collapse("0b0'1'0'1")
        assert "1048576" == collapse("1'048'576")
        assert "0X100000" == collapse("0X10'0000")
        assert "0004000000" == collapse("0'004'000'000")
        assert "1.602176565e-19" == collapse("1.602'176'565e-19")
        assert "'' + 0xffff" == collapse("'i' + 0xf'f'f'f")
        assert "sizeof'' == 1" == collapse("sizeof'x' == 1")
        assert "0x.03p100" == collapse("0x.0'3p1'0'0")
        assert "123.45" == collapse("1'23.4'5")

        assert 'StringReplace(body, "", "");', collapse('StringReplace(body, "\\\\" == "\\\\\\\\");')
        assert "'' \"\"" == collapse('\'"\' "foo"')
