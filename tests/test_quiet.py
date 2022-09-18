import os
import shutil
import subprocess
import sys
import tempfile

import pytest

class TestQuiet:

    @pytest.fixture(autouse=True)
    def setUp(self):
        self.temp_dir = os.path.realpath(tempfile.mkdtemp())
        self.this_dir_path = os.path.abspath(self.temp_dir)
        self.python_executable = sys.executable or 'python'
        self.cpplint_test_h = os.path.join(self.this_dir_path,
                                           'cpplint_test_header.h')
        open(self.cpplint_test_h, 'w').close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _runCppLint(self, *args):
        cpplint_abspath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../main.py')

        cmd_line = [self.python_executable, cpplint_abspath] +                     \
            list(args) +                                                           \
            [self.cpplint_test_h]

        return_code = 0
        try:
            output = subprocess.check_output(cmd_line,
                                             stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            return_code = err.returncode
            output = err.output
        if isinstance(output, bytes):
            output = output.decode('utf-8')
        return (return_code, output)

    def testNonQuietWithErrors(self):
        # This will fail: the test header is missing a copyright and header guard.
        (return_code, output) = self._runCppLint()
        assert 1 == return_code
        # Always-on behavior: Print error messages as they come up.
        assert "[legal/copyright]" in output
        assert "[build/header_guard]" in output
        # If --quiet was unspecified: Print 'Done processing' and 'Total errors..'
        assert "Done processing" in output
        assert "Total errors found:" in output

    @pytest.mark.skip("Need to work out how output formatting works")
    def testQuietWithErrors(self):
        # When there are errors, behavior is identical to not passing --quiet.
        (return_code, output) = self._runCppLint('--quiet')
        assert 1 == return_code
        assert "[legal/copyright]" in output
        assert "[build/header_guard]" in output
        # Even though --quiet was used, print these since there were errors.
        assert "Done processing" in output
        assert "Total errors found:" in output

    def testNonQuietWithoutErrors(self):
        # This will succeed. We filtered out all the known errors for that file.
        (return_code, output) = self._runCppLint('--filter=' +
                                                    '-legal/copyright,' +
                                                    '-build/header_guard')
        assert 0 == return_code, output
        # No cpplint errors are printed since there were no errors.
        assert "[legal/copyright]" not in output
        assert "[build/header_guard]" not in output
        # Print 'Done processing' since
        # --quiet was not specified.
        assert "Done processing" in output

    def testQuietWithoutErrors(self):
        # This will succeed. We filtered out all the known errors for that file.
        (return_code, output) = self._runCppLint('--quiet',
                                                 '--filter=' +
                                                     '-legal/copyright,' +
                                                     '-build/header_guard')
        assert 0 == return_code, output
        # No cpplint errors are printed since there were no errors.
        assert "[legal/copyright]" not in output
        assert "[build/header_guard]" not in output
        # --quiet was specified and there were no errors:
        # skip the printing of 'Done processing' and 'Total errors..'
        assert "Done processing" not in  output
        assert "Total errors found:" not in  output
        # Output with no errors must be completely blank!
        assert "" == output
