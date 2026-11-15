class FakeHost:
    def __init__(self, pid=4242, hostname="fake-host"):
        self._pid = pid
        self._hostname = hostname

    def pid(self):
        return self._pid

    def hostname(self):
        return self._hostname
