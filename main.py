import codecs
import sys

from hacpplint import ParseArguments, ProcessFile, _CppLintState


_cpplint_state = _CppLintState()

def main():
  filenames = ParseArguments(sys.argv[1:])
  backup_err = sys.stderr
  try:
    # Change stderr to write with replacement characters so we don't die
    # if we try to print something containing non-ASCII characters.
    sys.stderr = codecs.StreamReader(sys.stderr, 'replace')

    _cpplint_state.ResetErrorCounts()
    for filename in filenames:
      ProcessFile(filename, _cpplint_state.verbose_level)
    # If --quiet is passed, suppress printing error count unless there are errors.
    if not _cpplint_state.quiet or _cpplint_state.error_count > 0:
      _cpplint_state.PrintErrorCounts()

    if _cpplint_state.output_format == 'junit':
      sys.stderr.write(_cpplint_state.FormatJUnitXML())

  finally:
    sys.stderr = backup_err

  sys.exit(_cpplint_state.error_count > 0)


if __name__ == '__main__':
  main()
