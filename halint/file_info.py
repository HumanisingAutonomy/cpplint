import os
import pathlib


def _IsExtension(extension: str, extensions: list[str]):
    """File extension (excluding dot) matches a file extension."""
    return extension in extensions


class FileInfo(object):
    """Provides utility functions for filenames.

    FileInfo provides easy access to the components of a file's path
    relative to the project root.
    """

    def __init__(self, filename: str):
        self._filename = filename
        self._path = pathlib.Path(self._filename)

    def FullName(self):
        """Make Windows paths like Unix."""
        return os.path.abspath(self._filename).replace("\\", "/")

    def RepositoryName(self, repository: str):
        r"""FullName after removing the local path to the repository.

        If we have a real absolute path name here we can try to do something smart:
        detecting the root of the checkout and truncating /path/to/checkout from
        the name so that we get header guards that don't include things like
        "C:\\Documents and Settings\\..." or "/home/username/..." in them and thus
        people on different computers who have checked the source out to different
        locations won't see bogus errors.
        """
        fullname = self.FullName()

        if os.path.exists(fullname):
            project_dir = os.path.dirname(fullname)

            # If the user specified a repository path, it exists, and the file is
            # contained in it, use the specified repository path
            if repository:
                repo = FileInfo(repository).FullName()
                root_dir = project_dir
                while os.path.exists(root_dir):
                    # allow case insensitive compare on Windows
                    if os.path.normcase(root_dir) == os.path.normcase(repo):
                        return os.path.relpath(fullname, root_dir).replace("\\", "/")
                    one_up_dir = os.path.dirname(root_dir)
                    if one_up_dir == root_dir:
                        break
                    root_dir = one_up_dir

            if os.path.exists(os.path.join(project_dir, ".svn")):
                # If there's a .svn file in the current directory, we recursively look
                # up the directory tree for the top of the SVN checkout
                root_dir = project_dir
                one_up_dir = os.path.dirname(root_dir)
                while os.path.exists(os.path.join(one_up_dir, ".svn")):
                    root_dir = os.path.dirname(root_dir)
                    one_up_dir = os.path.dirname(one_up_dir)

                prefix = os.path.commonprefix([root_dir, project_dir])
                return fullname[len(prefix) + 1 :]

            # Not SVN <= 1.6? Try to find a git, hg, or svn top level directory by
            # searching up from the current path.
            root_dir = current_dir = os.path.dirname(fullname)
            while current_dir != os.path.dirname(current_dir):
                if (
                    os.path.exists(os.path.join(current_dir, ".git"))
                    or os.path.exists(os.path.join(current_dir, ".hg"))
                    or os.path.exists(os.path.join(current_dir, ".svn"))
                ):
                    root_dir = current_dir
                current_dir = os.path.dirname(current_dir)

            if (
                os.path.exists(os.path.join(root_dir, ".git"))
                or os.path.exists(os.path.join(root_dir, ".hg"))
                or os.path.exists(os.path.join(root_dir, ".svn"))
            ):
                prefix = os.path.commonprefix([root_dir, project_dir])
                return fullname[len(prefix) + 1 :]

        # Don't know what to do; header guard warnings may be wrong...
        # warnings.warn("Cannot determine repository root, header guard checks may be wrong", RuntimeWarning)
        return fullname

    def BaseName(self):
        """File base name - text after the final slash, before the final period."""
        return self._path.stem

    def Extension(self):
        """File extension - text following the final period, includes that period."""
        return self._path.suffix

    def IsExtension(self, extensions: list[str]) -> bool:
        """File has a source file extension."""
        return _IsExtension(self.Extension()[1:], extensions)


def PathSplitToList(path):
    """Returns the path split into a list by the separator.

    Args:
      path: An absolute or relative path (e.g. '/a/b/c/' or '../a')

    Returns:
      A list of path components (e.g. ['a', 'b', 'c]).
    """
    lst = []
    while True:
        (head, tail) = os.path.split(path)
        if head == path:  # absolute paths end
            lst.append(head)
            break
        if tail == path:  # relative paths end
            lst.append(tail)
            break

        path = head
        lst.append(tail)

    lst.reverse()
    return lst
