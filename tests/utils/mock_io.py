# This class is a lame mock of codecs. We do not verify filename, mode, or
# encoding, but for the current use case it is not needed.
class MockIo(object):

    def __init__(self, mock_file):
        # wrap list to allow "with open(mock)"
        class EnterableList(list):
            def __enter__(self):
                return self

            def __exit__(self, type, value, tb):
                return self
        self.mock_file = EnterableList(mock_file)

    def open(self,  # pylint: disable=C6409
             unused_filename, unused_mode, unused_encoding, _):
        return self.mock_file

