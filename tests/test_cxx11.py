import halint.cpplint as cpplint

from .base_case import CpplintTestBase
from .utils.error_collector import ErrorCollector

class TestCxx11(CpplintTestBase):

    def Helper(self, package, extension, lines, count):
        filename = package + '/foo.' + extension
        lines = lines[:]

        # Header files need to have an ifdef guard wrapped around their code.
        if extension.startswith('h'):
            guard = filename.upper().replace('/', '_').replace('.', '_') + '_'
            lines.insert(0, '#ifndef ' + guard)
            lines.insert(1, '#define ' + guard)
            lines.append('#endif  // ' + guard)

        # All files need a final blank line.
        lines.append('')

        # Process the file and check resulting error count.
        collector = ErrorCollector(self.assert_)
        cpplint.ProcessFileData(filename, extension, lines, collector)
        error_list = collector.ResultList()
        self.assertEqual(count, len(error_list), error_list)

    def TestCxx11Feature(self, state, code, expected_error):
        lines = code.split('\n')
        collector = ErrorCollector()
        cpplint.RemoveMultiLineComments(state, 'foo.h', lines, collector)
        clean_lines = cpplint.CleansedLines(lines)
        cpplint.FlagCxx11Features(state, 'foo.cc', clean_lines, 0, collector)
        assert expected_error == collector.Results()

    def testBlockedHeaders(self, state):
        self.TestCxx11Feature(state, '#include <tr1/regex>',
                              'C++ TR1 headers such as <tr1/regex> are '
                              'unapproved.  [build/c++tr1] [5]')
        self.TestCxx11Feature(state, '#include <mutex>',
                              '<mutex> is an unapproved C++11 header.'
                              '  [build/c++11] [5]')

    def testBlockedClasses(self, state):
        self.TestCxx11Feature(state, 'std::alignment_of<T>',
                              'std::alignment_of is an unapproved '
                              'C++11 class or function.  Send c-style an example '
                              'of where it would make your code more readable, '
                              'and they may let you use it.'
                              '  [build/c++11] [5]')
        self.TestCxx11Feature(state, 'std::alignment_offer', '')
        self.TestCxx11Feature(state, 'mystd::alignment_of', '')
        self.TestCxx11Feature(state, 'std::binomial_distribution', '')

    def testBlockedFunctions(self, state):
        self.TestCxx11Feature(state, 'std::alignment_of<int>',
                              'std::alignment_of is an unapproved '
                              'C++11 class or function.  Send c-style an example '
                              'of where it would make your code more readable, '
                              'and they may let you use it.'
                              '  [build/c++11] [5]')
        # Missed because of the lack of "std::".  Compiles because ADL
        # looks in the namespace of my_shared_ptr, which (presumably) is
        # std::.  But there will be a lint error somewhere in this file
        # since my_shared_ptr had to be defined.
        self.TestCxx11Feature(state, 'static_pointer_cast<Base>(my_shared_ptr)', '')
        self.TestCxx11Feature(state, 'std::declval<T>()', '')

    def testExplicitMakePair(self, state):
        self.TestSingleLineLint(state, 'make_pair', '')
        self.TestSingleLineLint(state, 'make_pair(42, 42)', '')
        self.TestSingleLineLint(state, 'make_pair<',
                      'For C++11-compatibility, omit template arguments from'
                      ' make_pair OR use pair directly OR if appropriate,'
                      ' construct a pair directly'
                      '  [build/explicit_make_pair] [4]')
        self.TestSingleLineLint(state, 'make_pair <',
                      'For C++11-compatibility, omit template arguments from'
                      ' make_pair OR use pair directly OR if appropriate,'
                      ' construct a pair directly'
                      '  [build/explicit_make_pair] [4]')
        self.TestSingleLineLint(state, 'my_make_pair<int, int>', '')
