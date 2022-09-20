import codecs
import getopt
import glob
import re
import os
import sys

from ._cpplintstate import _CppLintState
from .categories import _ERROR_CATEGORIES
from .cpplint import ProcessFileData, Error

_USAGE = """
Syntax: cpplint.py [--verbose=#] [--output=emacs|eclipse|vs7|junit|sed|gsed]
                   [--filter=-x,+y,...]
                   [--counting=total|toplevel|detailed] [--root=subdir]
                   [--repository=path]
                   [--linelength=digits] [--headers=x,y,...]
                   [--recursive]
                   [--exclude=path]
                   [--extensions=hpp,cpp,...]
                   [--includeorder=default|standardcfirst]
                   [--quiet]
                   [--version]
        <file> [file] ...

  Style checker for C/C++ source files.
  This is a fork of the Google style checker with minor extensions.

  The style guidelines this tries to follow are those in
    https://google.github.io/styleguide/cppguide.html

  Every problem is given a confidence score from 1-5, with 5 meaning we are
  certain of the problem, and 1 meaning it could be a legitimate construct.
  This will miss some errors, and is not a substitute for a code review.

  To suppress false-positive errors of a certain category, add a
  'NOLINT(category)' comment to the line.  NOLINT or NOLINT(*)
  suppresses errors of all categories on that line.

  The files passed in will be linted; at least one file must be provided.
  Default linted extensions are %s.
  Other file types will be ignored.
  Change the extensions with the --extensions flag.

  Flags:

    output=emacs|eclipse|vs7|junit|sed|gsed
      By default, the output is formatted to ease emacs parsing.  Visual Studio
      compatible output (vs7) may also be used.  Further support exists for
      eclipse (eclipse), and JUnit (junit). XML parsers such as those used
      in Jenkins and Bamboo may also be used.
      The sed format outputs sed commands that should fix some of the errors.
      Note that this requires gnu sed. If that is installed as gsed on your
      system (common e.g. on macOS with homebrew) you can use the gsed output
      format. Sed commands are written to stdout, not stderr, so you should be
      able to pipe output straight to a shell to run the fixes.

    verbose=#
      Specify a number 0-5 to restrict errors to certain verbosity levels.
      Errors with lower verbosity levels have lower confidence and are more
      likely to be false positives.

    quiet
      Don't print anything if no errors are found.

    filter=-x,+y,...
      Specify a comma-separated list of category-filters to apply: only
      error messages whose category names pass the filters will be printed.
      (Category names are printed with the message and look like
      "[whitespace/indent]".)  Filters are evaluated left to right.
      "-FOO" means "do not print categories that start with FOO".
      "+FOO" means "do print categories that start with FOO".

      Examples: --filter=-whitespace,+whitespace/braces
                --filter=-whitespace,-runtime/printf,+runtime/printf_format
                --filter=-,+build/include_what_you_use

      To see a list of all the categories used in cpplint, pass no arg:
         --filter=

    counting=total|toplevel|detailed
      The total number of errors found is always printed. If
      'toplevel' is provided, then the count of errors in each of
      the top-level categories like 'build' and 'whitespace' will
      also be printed. If 'detailed' is provided, then a count
      is provided for each category like 'build/class'.

    repository=path
      The top level directory of the repository, used to derive the header
      guard CPP variable. By default, this is determined by searching for a
      path that contains .git, .hg, or .svn. When this flag is specified, the
      given path is used instead. This option allows the header guard CPP
      variable to remain consistent even if members of a team have different
      repository root directories (such as when checking out a subdirectory
      with SVN). In addition, users of non-mainstream version control systems
      can use this flag to ensure readable header guard CPP variables.

      Examples:
        Assuming that Alice checks out ProjectName and Bob checks out
        ProjectName/trunk and trunk contains src/chrome/ui/browser.h, then
        with no --repository flag, the header guard CPP variable will be:

        Alice => TRUNK_SRC_CHROME_BROWSER_UI_BROWSER_H_
        Bob   => SRC_CHROME_BROWSER_UI_BROWSER_H_

        If Alice uses the --repository=trunk flag and Bob omits the flag or
        uses --repository=. then the header guard CPP variable will be:

        Alice => SRC_CHROME_BROWSER_UI_BROWSER_H_
        Bob   => SRC_CHROME_BROWSER_UI_BROWSER_H_

    root=subdir
      The root directory used for deriving header guard CPP variable.
      This directory is relative to the top level directory of the repository
      which by default is determined by searching for a directory that contains
      .git, .hg, or .svn but can also be controlled with the --repository flag.
      If the specified directory does not exist, this flag is ignored.

      Examples:
        Assuming that src is the top level directory of the repository (and
        cwd=top/src), the header guard CPP variables for
        src/chrome/browser/ui/browser.h are:

        No flag => CHROME_BROWSER_UI_BROWSER_H_
        --root=chrome => BROWSER_UI_BROWSER_H_
        --root=chrome/browser => UI_BROWSER_H_
        --root=.. => SRC_CHROME_BROWSER_UI_BROWSER_H_

    linelength=digits
      This is the allowed line length for the project. The default value is
      80 characters.

      Examples:
        --linelength=120

    recursive
      Search for files to lint recursively. Each directory given in the list
      of files to be linted is replaced by all files that descend from that
      directory. Files with extensions not in the valid extensions list are
      excluded.

    exclude=path
      Exclude the given path from the list of files to be linted. Relative
      paths are evaluated relative to the current directory and shell globbing
      is performed. This flag can be provided multiple times to exclude
      multiple files.

      Examples:
        --exclude=one.cc
        --exclude=src/*.cc
        --exclude=src/*.cc --exclude=test/*.cc

    extensions=extension,extension,...
      The allowed file extensions that cpplint will check

      Examples:
        --extensions=%s

    includeorder=default|standardcfirst
      For the build/include_order rule, the default is to blindly assume angle
      bracket includes with file extension are c-system-headers (default),
      even knowing this will have false classifications.
      The default is established at google.
      standardcfirst means to instead use an allow-list of known c headers and
      treat all others as separate group of "other system headers". The C headers
      included are those of the C-standard lib and closely related ones.

    headers=x,y,...
      The header extensions that cpplint will treat as .h in checks. Values are
      automatically added to --extensions list.
     (by default, only files with extensions %s will be assumed to be headers)

      Examples:
        --headers=%s
        --headers=hpp,hxx
        --headers=hpp

    cpplint.py supports per-directory configurations specified in CPPLINT.cfg
    files. CPPLINT.cfg file can contain a number of key=value pairs.
    Currently the following options are supported:

      set noparent
      filter=+filter1,-filter2,...
      exclude_files=regex
      linelength=80
      root=subdir
      headers=x,y,...

    "set noparent" option prevents cpplint from traversing directory tree
    upwards looking for more .cfg files in parent directories. This option
    is usually placed in the top-level project directory.

    The "filter" option is similar in function to --filter flag. It specifies
    message filters in addition to the |_DEFAULT_FILTERS| and those specified
    through --filter command-line flag.

    "exclude_files" allows to specify a regular expression to be matched against
    a file name. If the expression matches, the file is skipped and not run
    through the linter.

    "linelength" allows to specify the allowed line length for the project.

    The "root" option is similar in function to the --root flag (see example
    above). Paths are relative to the directory of the CPPLINT.cfg.

    The "headers" option is similar in function to the --headers flag
    (see example above).

    CPPLINT.cfg has an effect on files in the same directory and all
    sub-directories, unless overridden by a nested configuration file.

      Example file:
        filter=-build/include_order,+build/include_alpha
        exclude_files=.*\\.cc

    The above example disables build/include_order warning and enables
    build/include_alpha as well as excludes all .cc from being
    processed by linter, in the current directory (where the .cfg
    file is located) and all sub-directories.
"""

def ProcessHppHeadersOption(state, val):
    try:
        state._hpp_headers = {ext.strip() for ext in val.split(',')}
    except ValueError:
        PrintUsage('Header extensions must be comma separated list.')

def ProcessIncludeOrderOption(state, val):
    if val is None or val == "default":
        pass
    elif val == "standardcfirst":
        state._include_order = val
    else:
        PrintUsage('Invalid includeorder value %s. Expected default|standardcfirst')

def ProcessExtensionsOption(state: _CppLintState, val):
    try:
        extensions = [ext.strip() for ext in val.split(',')]
        state._valid_extensions = set(extensions)
    except ValueError:
        PrintUsage('Extensions should be a comma-separated list of values;'
                   'for example: extensions=hpp,cpp\n'
                   'This could not be parsed: "%s"' % (val,))

def PrintUsage(state: _CppLintState, message):
    """Prints a brief usage string and exits, optionally with an error message.

    Args:
      message: The optional error message.
    """
    sys.stderr.write(_USAGE  % (sorted(list(state.GetAllExtensions())),
         ','.join(sorted(list(state.GetAllExtensions()))),
         sorted(state.GetHeaderExtensions()),
         ','.join(sorted(state.GetHeaderExtensions()))))

    if message:
        sys.exit('\nFATAL ERROR: ' + message)
    else:
        sys.exit(0)

def PrintVersion():
    sys.stdout.write('Cpplint fork (https://github.com/cpplint/cpplint)\n')
    # TODO: fix printing version number
    sys.stdout.write('cpplint ' + "FIXME" + '\n')
    sys.stdout.write('Python ' + sys.version + '\n')
    sys.exit(0)

def PrintCategories():
    """Prints a list of all the error-categories used by error messages.

    These are the categories used to filter messages via --filter.
    """
    sys.stderr.write(''.join('  %s\n' % cat for cat in _ERROR_CATEGORIES))
    sys.exit(0)

def parse_filters(filter_string: str) -> list[str]:
    """Takes a comma separated list of filters and returns a list of filters"""
    filters = []

    for filter in filter_string.split(','):
        clean_filter = filter.strip()
        if clean_filter:
            filters.append(clean_filter)
    for filter in filters:
        if not (filter.startswith('+') or filter.startswith('-')):
            raise ValueError('Every filter in --filters must start with + or -'
                                ' (%s does not)' % filter)
    return filters

def _IsParentOrSame(parent, child):
    """Return true if child is subdirectory of parent.
    Assumes both paths are absolute and don't contain symlinks.
    """
    parent = os.path.normpath(parent)
    child = os.path.normpath(child)
    if parent == child:
        return True

    prefix = os.path.commonprefix([parent, child])
    if prefix != parent:
        return False
    # Note: os.path.commonprefix operates on character basis, so
    # take extra care of situations like '/foo/ba' and '/foo/bar/baz'
    child_suffix = child[len(prefix):]
    child_suffix = child_suffix.lstrip(os.sep)
    return child == os.path.join(prefix, child_suffix)

def ParseArguments(state: _CppLintState, args):
    """Parses the command line arguments.

    This may set the output format and verbosity level as side-effects.

    Args:
      args: The command line arguments:

    Returns:
      The list of filenames to lint.
    """
    try:
        (opts, filenames) = getopt.getopt(args, '', ['help', 'output=', 'verbose=',
                                                     'v=',
                                                     'version',
                                                     'counting=',
                                                     'filter=',
                                                     'root=',
                                                     'repository=',
                                                     'linelength=',
                                                     'extensions=',
                                                     'exclude=',
                                                     'recursive',
                                                     'headers=',
                                                     'includeorder=',
                                                     'quiet'])
    except getopt.GetoptError:
        PrintUsage(state, 'Invalid arguments.')

    verbosity = state.verbose_level
    output_format = state.output_format
    filters = ''
    quiet = state.quiet
    counting_style = ''
    recursive = False
    root = state._root
    repository = state._repository
    excludes = state._excludes
    line_length = 80

    for (opt, val) in opts:
        if opt == '--help':
            PrintUsage(state, None)
        if opt == '--version':
            PrintVersion()
        elif opt == '--output':
            if val not in ('emacs', 'vs7', 'eclipse', 'junit', 'sed', 'gsed'):
                PrintUsage(state, 'The only allowed output formats are emacs, vs7, eclipse '
                           'sed, gsed and junit.')
            output_format = val
        elif opt == '--quiet':
            quiet = True
        elif opt == '--verbose' or opt == '--v':
            verbosity = int(val)
        elif opt == '--filter':
            filters = val
            if not filters:
                PrintCategories()
        elif opt == '--counting':
            if val not in ('total', 'toplevel', 'detailed'):
                PrintUsage(state, 'Valid counting options are total, toplevel, and detailed')
            counting_style = val
        elif opt == '--root':
            root = val
        elif opt == '--repository':
            repository = val
        elif opt == '--linelength':
            try:
                line_length = int(val)
            except ValueError:
                PrintUsage(state, 'Line length must be digits.')
        elif opt == '--exclude':
            excludes = set()
            excludes.update(glob.glob(val))
        elif opt == '--extensions':
            ProcessExtensionsOption(state, val)
        elif opt == '--headers':
            ProcessHppHeadersOption(state, val)
        elif opt == '--recursive':
            recursive = True
        elif opt == '--includeorder':
            ProcessIncludeOrderOption(state, val)

    if excludes:
        state._excludes.update(excludes)

    if not filenames:
        PrintUsage(state, 'No files were specified.')

    if recursive:
        filenames = _ExpandDirectories(state, filenames)

    if len(state._excludes) > 0:
        filenames = _FilterExcludedFiles(state, filenames)


    state.output_format = output_format
    state.quiet = quiet
    state.verbose_level = verbosity
    state.filters = parse_filters(filters)
    state.counting_style = counting_style
    state._root = root
    state._repository = repository
    state._line_length = line_length

    filenames.sort()
    return filenames

def _ExpandDirectories(state, filenames):
    """Searches a list of filenames and replaces directories in the list with
    all files descending from those directories. Files with extensions not in
    the valid extensions list are excluded.

    Args:
      filenames: A list of files or directories

    Returns:
      A list of all files that are members of filenames or descended from a
      directory in filenames
    """
    expanded = set()
    for filename in filenames:
        if not os.path.isdir(filename):
            expanded.add(filename)
            continue

        for root, _, files in os.walk(filename):
            for loopfile in files:
                fullname = os.path.join(root, loopfile)
                if fullname.startswith('.' + os.path.sep):
                    fullname = fullname[len('.' + os.path.sep):]
                expanded.add(fullname)

    filtered = []
    for filename in expanded:
        if os.path.splitext(filename)[1][1:] in state.GetAllExtensions():
            filtered.append(filename)
    return filtered

def _FilterExcludedFiles(state, fnames):
    """Filters out files listed in the --exclude command line switch. File paths
    in the switch are evaluated relative to the current working directory
    """
    exclude_paths = [os.path.abspath(f) for f in state._excludes]
    # because globbing does not work recursively, exclude all subpath of all excluded entries
    return [f for f in fnames
            if not any(e for e in exclude_paths
                    if _IsParentOrSame(e, os.path.abspath(f)))]

def ProcessFile(state: _CppLintState, filename, vlevel, extra_check_functions=None):
    """Does google-lint on a single file.

    Args:
      filename: The name of the file to parse.

      vlevel: The level of errors to report.  Every error of confidence
      >= verbose_level will be reported.  0 is a good default.

      extra_check_functions: An array of additional check functions that will be
                             run on each source line. Each function takes 4
                             arguments: filename, clean_lines, line, error
    """

    state.verbose_level = vlevel
    state.backup_filters()
    old_errors = state.error_count

    if not ProcessConfigOverrides(state, filename):
        state.backup_filters()
        return

    lf_lines = []
    crlf_lines = []
    try:
        # Support the UNIX convention of using "-" for stdin.  Note that
        # we are not opening the file with universal newline support
        # (which codecs doesn't support anyway), so the resulting lines do
        # contain trailing '\r' characters if we are reading a file that
        # has CRLF endings.
        # If after the split a trailing '\r' is present, it is removed
        # below.
        if filename == '-':
            lines = codecs.StreamReaderWriter(sys.stdin,
                                              codecs.getreader('utf8'),
                                              codecs.getwriter('utf8'),
                                              'replace').read().split('\n')
        else:
            with codecs.open(filename, 'r', 'utf8', 'replace') as target_file:
                lines = target_file.read().split('\n')

        # Remove trailing '\r'.
        # The -1 accounts for the extra trailing blank line we get from split()
        for linenum in range(len(lines) - 1):
            if lines[linenum].endswith('\r'):
                lines[linenum] = lines[linenum].rstrip('\r')
                crlf_lines.append(linenum + 1)
            else:
                lf_lines.append(linenum + 1)

    except IOError:
        state.PrintError(
            "Skipping input '%s': Can't open for reading\n" % filename)
        state.restore_filters()
        return

    # Note, if no dot is found, this will give the entire filename as the ext.
    file_extension = filename[filename.rfind('.') + 1:]

    # When reading from stdin, the extension is unknown, so no cpplint tests
    # should rely on the extension.
    if filename != '-' and file_extension not in state.GetAllExtensions():
        state.PrintError('Ignoring %s; not a valid file name '
                         '(%s)\n' % (filename, ', '.join(state.GetAllExtensions())))
    else:
        ProcessFileData(state, filename, file_extension, lines, Error,
                        extra_check_functions)

        # If end-of-line sequences are a mix of LF and CR-LF, issue
        # warnings on the lines with CR.
        #
        # Don't issue any warnings if all lines are uniformly LF or CR-LF,
        # since critique can handle these just fine, and the style guide
        # doesn't dictate a particular end of line sequence.
        #
        # We can't depend on os.linesep to determine what the desired
        # end-of-line sequence should be, since that will return the
        # server-side end-of-line sequence.
        if lf_lines and crlf_lines:
            # Warn on every line with CR.  An alternative approach might be to
            # check whether the file is mostly CRLF or just LF, and warn on the
            # minority, we bias toward LF here since most tools prefer LF.
            for linenum in crlf_lines:
                Error(state, filename, linenum, 'whitespace/newline', 1,
                      'Unexpected \\r (^M) found; better to use only \\n')

    # Suppress printing anything if --quiet was passed unless the error
    # count has increased after processing this file.
    if not state.quiet or old_errors != state.error_count:
         state.PrintInfo('Done processing %s\n' % filename)
    state.restore_filters()

def ProcessConfigOverrides(state, filename):
    """ Loads the configuration files and processes the config overrides.

    Args:
      filename: The name of the file being processed by the linter.

    Returns:
      False if the current |filename| should not be processed further.
    """

    abs_filename = os.path.abspath(filename)
    cfg_filters = []
    keep_looking = True
    while keep_looking:
        abs_path, base_name = os.path.split(abs_filename)
        if not base_name:
            break  # Reached the root directory.

        cfg_file = os.path.join(abs_path, "CPPLINT.cfg")
        abs_filename = abs_path
        if not os.path.isfile(cfg_file):
            continue

        try:
            with codecs.open(cfg_file, 'r', 'utf8', 'replace') as file_handle:
                for line in file_handle:
                    line, _, _ = line.partition('#')  # Remove comments.
                    if not line.strip():
                        continue

                    name, _, val = line.partition('=')
                    name = name.strip()
                    val = val.strip()
                    if name == 'set noparent':
                        keep_looking = False
                    elif name == 'filter':
                        cfg_filters.append(val)
                    elif name == 'exclude_files':
                        # When matching exclude_files pattern, use the base_name of
                        # the current file name or the directory name we are processing.
                        # For example, if we are checking for lint errors in /foo/bar/baz.cc
                        # and we found the .cfg file at /foo/CPPLINT.cfg, then the config
                        # file's "exclude_files" filter is meant to be checked against "bar"
                        # and not "baz" nor "bar/baz.cc".
                        if base_name:
                            pattern = re.compile(val)
                            if pattern.match(base_name):
                                if state.quiet:
                                    # Suppress "Ignoring file" warning when using --quiet.
                                    return False
                                state.PrintInfo('Ignoring "%s": file excluded by "%s". '
                                                 'File path component "%s" matches '
                                                 'pattern "%s"\n' %
                                                 (filename, cfg_file, base_name, val))
                                return False
                    elif name == 'linelength':
                        global _line_length
                        try:
                            _line_length = int(val)
                        except ValueError:
                             state.PrintError('Line length must be numeric.')
                    elif name == 'extensions':
                        ProcessExtensionsOption(state, val)
                    elif name == 'root':
                        global _root
                        # root directories are specified relative to CPPLINT.cfg dir.
                        _root = os.path.join(os.path.dirname(cfg_file), val)
                    elif name == 'headers':
                        ProcessHppHeadersOption(state, val)
                    elif name == 'includeorder':
                        ProcessIncludeOrderOption(state, val)
                    else:
                         state.PrintError(
                            'Invalid configuration option (%s) in file %s\n' %
                            (name, cfg_file))

        except IOError:
            state.PrintError(
                "Skipping config file '%s': Can't open for reading\n" % cfg_file)
            keep_looking = False

    # Apply all the accumulated filters in reverse order (top-level directory
    # config options having the least priority).
    for cfg_filter in reversed(cfg_filters):
        state.add_filters(parse_filters(cfg_filter))

    return True
