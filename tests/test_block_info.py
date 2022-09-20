import pytest

from .base_case import CpplintTestBase

from halint.block_info import FindNextMultiLineCommentStart


class TestBlockInfo(CpplintTestBase):

    find_next_multiline_comment_start_data = [
        [[""], 1],
        [["a", "b", "/* c"], 2],
        [['char a[] = "/*";'], 1]  # not recognized as comment.
    ]

    @pytest.mark.parametrize("lines, expected_index", find_next_multiline_comment_start_data)
    def test_find_next_multiline_comment_start(self, lines, expected_index):
        assert expected_index == FindNextMultiLineCommentStart(lines, 0)
