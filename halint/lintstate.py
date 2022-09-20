import sys
import xml


class LintState(object):
    """Maintains module-wide state.."""

    # The default state of the category filter. This is overridden by the --filter=
    # flag. By default all errors are on, so only add here categories that should be
    # off by default (i.e., categories that must be enabled by the --filter= flags).
    # All entries here should start with a '-' or '+', as in the --filter= flag.
    _DEFAULT_FILTERS = ["-build/include_alpha"]

    # keywords to use with --outputs which generate stdout for machine processing
    _MACHINE_OUTPUTS = ["junit", "sed", "gsed"]

    def __init__(self):
        self._verbose_level = 1  # global setting.
        self._error_count = 0  # global count of reported errors
        # filters to apply when emitting error messages
        self._filters = self._DEFAULT_FILTERS[:]
        # backup of filter list. Used to restore the state after each file.
        self._filters_backup = self._filters[:]
        self._counting_style = "total"  # In what way are we counting errors?
        self._errors_by_category = {}  # string to int dict storing error counts
        self._quiet = False  # Suppress non-error messagess?

        self._output_format = "emacs"

        # For JUnit output, save errors and failures until the end so that they
        # can be written into the XML
        self._junit_errors = []
        self._junit_failures = []

        # {str, set(int)}: a map from error categories to sets of linenumbers
        # on which those errors are expected and should be suppressed.
        self._error_suppressions = {}

        # The root directory used for deriving header guard CPP variable.
        # This is set by --root flag.
        self._root = None
        self._root_debug = False

        # The top level repository directory. If set, _root is calculated relative to
        # this directory instead of the directory containing version control artifacts.
        # This is set by the --repository flag.
        self._repository = None

        # The allowed line length of files.
        # This is set by --linelength flag.
        self._line_length = 80

        # This allows to use different include order rule than default
        self._include_order = "default"

        # {str, bool}: a map from error categories to booleans which indicate if the
        # category should be suppressed for every line.
        self._global_error_suppressions = {}

        # Files to exclude from linting. This is set by the --exclude flag.
        self._excludes = set()

        # if empty, use defaults
        self._valid_extensions = set([])

        # Treat all headers starting with 'h' equally: .h, .hpp, .hxx etc.
        # This is set by --headers flag.
        self._hpp_headers = set([])

    @property
    def output_format(self):
        """The output format for errors.

        output format:
        "emacs" - format that emacs can parse (default)
        "eclipse" - format that eclipse can parse
        "vs7" - format that Microsoft Visual Studio 7 can parse
        "junit" - format that Jenkins, Bamboo, etc can parse
        "sed" - returns a gnu sed command to fix the problem
        "gsed" - like sed, but names the command gsed, e.g. for macOS homebrew users
        """
        return self._output_format

    @output_format.setter
    def output_format(self, output_format):
        self._output_format = output_format

    @property
    def quiet(self):
        return self._quiet

    @quiet.setter
    def quiet(self, quiet):
        self._quiet = quiet

    @property
    def verbose_level(self):
        return self._verbose_level

    @verbose_level.setter
    def verbose_level(self, level):
        self._verbose_level = level

    @property
    def counting_style(self):
        """The module's counting options."""
        return self._counting_style

    @counting_style.setter
    def counting_style(self, counting_style):
        self._counting_style = counting_style

    @property
    def filters(self):
        return self._filters

    @filters.setter
    def filters(self, filters: list[str]):
        """Sets the error-message filters.

        These filters are applied when deciding whether to emit a given
        error message.

        Args:
          filters: A string of comma-separated filters (eg "+whitespace/indent").
                   Each filter should start with + or -; else we die.

        Raises:
          ValueError: The comma-separated filters did not all start with '+' or '-'.
                      E.g. "-,+whitespace,-whitespace/indent,whitespace/badfilter"
        """
        # Default filters always have less priority than the flag ones.
        self._filters = self._DEFAULT_FILTERS[:]
        self.add_filters(filters)

    @property
    def error_count(self):
        return self._error_count

    @error_count.setter
    def error_count(self, count):
        self._error_count = count

    def add_filters(self, filters: list[str]):
        """Adds more filters to the existing list of error-message filters."""
        self._filters.extend(filters)

    def backup_filters(self):
        """Saves the current filter list to backup storage."""
        self._filters_backup = self._filters[:]

    def restore_filters(self):
        """Restores filters previously backed up."""
        self._filters = self._filters_backup[:]

    def ResetErrorCounts(self):
        """Sets the module's error statistic back to zero."""
        self.error_count = 0
        self.errors_by_category = {}

    def IncrementErrorCount(self, category):
        """Bumps the module's error statistic."""
        self.error_count += 1
        if self.counting_style in ("toplevel", "detailed"):
            if self.counting_style != "detailed":
                category = category.split("/")[0]
            if category not in self.errors_by_category:
                self.errors_by_category[category] = 0
            self.errors_by_category[category] += 1

    def PrintErrorCounts(self):
        """Print a summary of errors by category, and the total."""
        for category, count in sorted(self.errors_by_category.items()):
            self.PrintInfo("Category '%s' errors found: %d\n" % (category, count))
        if self.error_count > 0:
            self.PrintInfo("Total errors found: %d\n" % self.error_count)

    def PrintInfo(self, message):
        # _quiet does not represent --quiet flag.
        # Hide infos from stdout to keep stdout pure for machine consumption
        if not self.quiet and self.output_format not in self._MACHINE_OUTPUTS:
            sys.stdout.write(message)

    def PrintError(self, message):
        if self.output_format == "junit":
            self._junit_errors.append(message)
        else:
            sys.stderr.write(message)

    def AddJUnitFailure(self, filename, linenum, message, category, confidence):
        self._junit_failures.append((filename, linenum, message, category, confidence))

    def FormatJUnitXML(self):
        num_errors = len(self._junit_errors)
        num_failures = len(self._junit_failures)

        testsuite = xml.etree.ElementTree.Element("testsuite")
        testsuite.attrib["errors"] = str(num_errors)
        testsuite.attrib["failures"] = str(num_failures)
        testsuite.attrib["name"] = "cpplint"

        if num_errors == 0 and num_failures == 0:
            testsuite.attrib["tests"] = str(1)
            xml.etree.ElementTree.SubElement(testsuite, "testcase", name="passed")

        else:
            testsuite.attrib["tests"] = str(num_errors + num_failures)
            if num_errors > 0:
                testcase = xml.etree.ElementTree.SubElement(testsuite, "testcase")
                testcase.attrib["name"] = "errors"
                error = xml.etree.ElementTree.SubElement(testcase, "error")
                error.text = "\n".join(self._junit_errors)
            if num_failures > 0:
                # Group failures by file
                failed_file_order = []
                failures_by_file = {}
                for failure in self._junit_failures:
                    failed_file = failure[0]
                    if failed_file not in failed_file_order:
                        failed_file_order.append(failed_file)
                        failures_by_file[failed_file] = []
                    failures_by_file[failed_file].append(failure)
                # Create a testcase for each file
                for failed_file in failed_file_order:
                    failures = failures_by_file[failed_file]
                    testcase = xml.etree.ElementTree.SubElement(testsuite, "testcase")
                    testcase.attrib["name"] = failed_file
                    failure = xml.etree.ElementTree.SubElement(testcase, "failure")
                    template = "{0}: {1} [{2}] [{3}]"
                    texts = [template.format(f[1], f[2], f[3], f[4]) for f in failures]
                    failure.text = "\n".join(texts)

        xml_decl = '<?xml version="1.0" encoding="UTF-8" ?>\n'
        return xml_decl + xml.etree.ElementTree.tostring(testsuite, "utf-8").decode("utf-8")

    def IsHeaderExtension(self, file_extension):
        return file_extension in self.GetHeaderExtensions()

    def GetHeaderExtensions(self):
        if self._hpp_headers:
            return self._hpp_headers
        if self._valid_extensions:
            return {h for h in self._valid_extensions if "h" in h}
        return set(["h", "hh", "hpp", "hxx", "h++", "cuh"])

    # The allowed extensions for file names
    # This is set by --extensions flag
    def GetAllExtensions(self):
        return self.GetHeaderExtensions().union(self._valid_extensions or set(["c", "cc", "cpp", "cxx", "c++", "cu"]))

    def GetNonHeaderExtensions(self):
        return self.GetAllExtensions().difference(self.GetHeaderExtensions())
