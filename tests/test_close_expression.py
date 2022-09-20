import pytest

from halint.block_info import CloseExpression, ReverseCloseExpression
from halint.cleansed_lines import CleansedLines


class TestCloseExpression:
    @pytest.fixture(autouse=True)
    def setUp(self):
        self.lines = CleansedLines(
            #           1         2         3         4         5
            # 0123456789012345678901234567890123456789012345678901234567890
            [
                "// Line 0",
                "inline RCULocked<X>::ReadPtr::ReadPtr(const RCULocked* rcu) {",
                '  DCHECK(!(data & kFlagMask)) << "Error";',
                "}",
                "// Line 4",
                "RCULocked<X>::WritePtr::WritePtr(RCULocked* rcu)",
                "    : lock_(&rcu_->mutex_) {",
                "}",
                "// Line 8",
                "template <typename T, typename... A>",
                "typename std::enable_if<",
                "    std::is_array<T>::value && (std::extent<T>::value > 0)>::type",
                "MakeUnique(A&&... a) = delete;",
                "// Line 13",
                "auto x = []() {};",
                "// Line 15",
                "template <typename U>",
                "friend bool operator==(const reffed_ptr& a,",
                "                       const reffed_ptr<U>& b) {",
                "  return a.get() == b.get();",
                "}",
                "// Line 21",
            ]
        )

    def testCloseExpression(self):
        # List of positions to test:
        # (start line, start position, end line, end position + 1)
        positions = [
            (1, 16, 1, 19),
            (1, 37, 1, 59),
            (1, 60, 3, 1),
            (2, 8, 2, 29),
            (2, 30, 22, -1),  # Left shift operator
            (9, 9, 9, 36),
            (10, 23, 11, 59),
            (11, 54, 22, -1),  # Greater than operator
            (14, 9, 14, 11),
            (14, 11, 14, 13),
            (14, 14, 14, 16),
            (17, 22, 18, 46),
            (18, 47, 20, 1),
        ]
        for p in positions:
            (_, line, column) = CloseExpression(self.lines, p[0], p[1])
            assert (p[2], p[3]) == (line, column)

    def testReverseCloseExpression(self):
        # List of positions to test:
        # (end line, end position, start line, start position)
        positions = [
            (1, 18, 1, 16),
            (1, 58, 1, 37),
            (2, 27, 2, 10),
            (2, 28, 2, 8),
            (6, 18, 0, -1),  # -> operator
            (9, 35, 9, 9),
            (11, 54, 0, -1),  # Greater than operator
            (11, 57, 11, 31),
            (14, 10, 14, 9),
            (14, 12, 14, 11),
            (14, 15, 14, 14),
            (18, 45, 17, 22),
            (20, 0, 18, 47),
        ]
        for p in positions:
            (_, line, column) = ReverseCloseExpression(self.lines, p[0], p[1])
            assert (p[2], p[3]) == (line, column)
