import codecs
import sys

from halint import ParseArguments, ProcessFile
from halint.cpplint import _cpplint_state



def main():
  filenames = ParseArguments(_cpplint_state, sys.argv[1:])
  backup_err = sys.stderr
  try:
    # Change stderr to write with replacement characters so we don't die
    # if we try to print something containing non-ASCII characters.
    sys.stderr = codecs.StreamReader(sys.stderr, 'replace')

    _cpplint_state.ResetErrorCounts()
    for filename in filenames:
      ProcessFile(_cpplint_state, filename, _cpplint_state.verbose_level)
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
