class FakeRandom:
    """Deterministic ids and tokens: every call draws the next counter value."""

    def __init__(self):
        self._count = 0

    def token_bytes(self, nbytes):
        self._count += 1
        return self._count.to_bytes(8, "big").rjust(nbytes, b"\0")[-nbytes:]

    def token_hex(self, nbytes):
        return self.token_bytes(nbytes).hex()

    def token_urlsafe(self, nbytes):
        return self.token_hex(nbytes)

    def hex_id(self):
        return self.token_hex(16)
