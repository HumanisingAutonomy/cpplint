from .regex import Match


class _IncludeState(object):
    """Tracks line numbers for includes, and the order in which includes appear.

    include_list contains list of lists of (header, line number) pairs.
    It's a lists of lists rather than just one flat list to make it
    easier to update across preprocessor boundaries.

    Call CheckNextIncludeOrder() once for each header in the file, passing
    in the type constants defined above. Calls in an illegal order will
    raise an _IncludeError with an appropriate error message.

    """

    # self._section will move monotonically through this set. If it ever
    # needs to move backwards, CheckNextIncludeOrder will raise an error.
    _INITIAL_SECTION = 0
    _MY_H_SECTION = 1
    _C_SECTION = 2
    _CPP_SECTION = 3
    _OTHER_SYS_SECTION = 4
    _OTHER_H_SECTION = 5

    # These constants define types of headers for use with
    # _IncludeState.CheckNextIncludeOrder().
    _C_SYS_HEADER = 1
    _CPP_SYS_HEADER = 2
    _OTHER_SYS_HEADER = 3
    _LIKELY_MY_HEADER = 4
    _POSSIBLE_MY_HEADER = 5
    _OTHER_HEADER = 6

    _TYPE_NAMES = {
        _C_SYS_HEADER: "C system header",
        _CPP_SYS_HEADER: "C++ system header",
        _OTHER_SYS_HEADER: "other system header",
        _LIKELY_MY_HEADER: "header this file implements",
        _POSSIBLE_MY_HEADER: "header this file may implement",
        _OTHER_HEADER: "other header",
    }

    _SECTION_NAMES = {
        _INITIAL_SECTION: "... nothing. (This can't be an error.)",
        _MY_H_SECTION: "a header this file implements",
        _C_SECTION: "C system header",
        _CPP_SECTION: "C++ system header",
        _OTHER_SYS_SECTION: "other system header",
        _OTHER_H_SECTION: "other header",
    }

    def __init__(self):
        self.include_list = [[]]
        self._section = None
        self._last_header = None
        self.ResetSection("")

    def FindHeader(self, header):
        """Check if a header has already been included.

        Args:
          header: header to check.
        Returns:
          Line number of previous occurrence, or -1 if the header has not
          been seen before.
        """
        for section_list in self.include_list:
            for f in section_list:
                if f[0] == header:
                    return f[1]
        return -1

    def ResetSection(self, directive):
        """Reset section checking for preprocessor directive.

        Args:
          directive: preprocessor directive (e.g. "if", "else").
        """
        # The name of the current section.
        self._section = self._INITIAL_SECTION
        # The path of last found header.
        self._last_header = ""

        # Update list of includes.  Note that we never pop from the
        # include list.
        if directive in ("if", "ifdef", "ifndef"):
            self.include_list.append([])
        elif directive in ("else", "elif"):
            self.include_list[-1] = []

    def SetLastHeader(self, header_path):
        self._last_header = header_path

    def CanonicalizeAlphabeticalOrder(self, header_path):
        """Returns a path canonicalized for alphabetical comparison.

        - replaces "-" with "_" so they both cmp the same.
        - removes '-inl' since we don't require them to be after the main header.
        - lowercase everything, just in case.

        Args:
          header_path: Path to be canonicalized.

        Returns:
          Canonicalized path.
        """
        return header_path.replace("-inl.h", ".h").replace("-", "_").lower()

    def IsInAlphabeticalOrder(self, clean_lines, linenum, header_path):
        """Check if a header is in alphabetical order with the previous header.

        Args:
          clean_lines: A CleansedLines instance containing the file.
          linenum: The number of the line to check.
          header_path: Canonicalized header to be checked.

        Returns:
          Returns true if the header is in alphabetical order.
        """
        # If previous section is different from current section, _last_header will
        # be reset to empty string, so it's always less than current header.
        #
        # If previous line was a blank line, assume that the headers are
        # intentionally sorted the way they are.
        if self._last_header > header_path and Match(r"^\s*#\s*include\b", clean_lines.elided[linenum - 1]):
            return False
        return True

    def CheckNextIncludeOrder(self, header_type):
        """Returns a non-empty error message if the next header is out of order.

        This function also updates the internal state to be ready to check
        the next include.

        Args:
          header_type: One of the _XXX_HEADER constants defined above.

        Returns:
          The empty string if the header is in the right order, or an
          error message describing what's wrong.

        """
        error_message = "Found %s after %s" % (
            self._TYPE_NAMES[header_type],
            self._SECTION_NAMES[self._section],
        )

        last_section = self._section

        if header_type == self._C_SYS_HEADER:
            if self._section <= self._C_SECTION:
                self._section = self._C_SECTION
            else:
                self._last_header = ""
                return error_message
        elif header_type == self._CPP_SYS_HEADER:
            if self._section <= self._CPP_SECTION:
                self._section = self._CPP_SECTION
            else:
                self._last_header = ""
                return error_message
        elif header_type == self._OTHER_SYS_HEADER:
            if self._section <= self._OTHER_SYS_SECTION:
                self._section = self._OTHER_SYS_SECTION
            else:
                self._last_header = ""
                return error_message
        elif header_type == self._LIKELY_MY_HEADER:
            if self._section <= self._MY_H_SECTION:
                self._section = self._MY_H_SECTION
            else:
                self._section = self._OTHER_H_SECTION
        elif header_type == self._POSSIBLE_MY_HEADER:
            if self._section <= self._MY_H_SECTION:
                self._section = self._MY_H_SECTION
            else:
                # This will always be the fallback because we're not sure
                # enough that the header is associated with this file.
                self._section = self._OTHER_H_SECTION
        else:
            assert header_type == self._OTHER_HEADER
            self._section = self._OTHER_H_SECTION

        if last_section != self._section:
            self._last_header = ""

        return ""
