from .base_case import CpplintTestBase
from .utils.error_collector import ErrorCollector

import halint.cpplint as cpplint

class TestCxx14(CpplintTestBase):

    def TestCxx14Feature(self, code, expected_error):
        lines = code.split('\n')
        collector = ErrorCollector()
        cpplint.RemoveMultiLineComments('foo.h', lines, collector)
        clean_lines = cpplint.CleansedLines(lines)
        cpplint.FlagCxx14Features('foo.cc', clean_lines, 0, collector)
        expected_error == collector.Results()

    def testBlockedHeaders(self):
        self.TestCxx14Feature('#include <scoped_allocator>',
                              '<scoped_allocator> is an unapproved C++14 header.'
                               '  [build/c++14] [5]')
        self.TestCxx14Feature('#include <shared_mutex>',
                              '<shared_mutex> is an unapproved C++14 header.'
                              '  [build/c++14] [5]')
