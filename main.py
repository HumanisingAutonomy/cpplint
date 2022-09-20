import codecs
import sys

from halint.cli import parse_arguments, process_file
from halint.lintstate import LintState


def main():
    state = LintState()
    filenames = parse_arguments(state, sys.argv[1:])
    backup_err = sys.stderr
    try:
        # Change stderr to write with replacement characters so we don't die
        # if we try to print something containing non-ASCII characters.
        sys.stderr = codecs.StreamReader(sys.stderr, "replace")

        state.ResetErrorCounts()
        for filename in filenames:
            process_file(state, filename, state.verbose_level)
        # If --quiet is passed, suppress printing error count unless there are errors.
        if not state.quiet or state.error_count > 0:
            state.PrintErrorCounts()

        if state.output_format == "junit":
            sys.stderr.write(state.FormatJUnitXML())

    finally:
        sys.stderr = backup_err

    sys.exit(state.error_count > 0)


if __name__ == "__main__":
    main()
