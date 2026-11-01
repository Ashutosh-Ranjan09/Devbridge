"""Your solution. Keep the names: the tests call exactly these. Standard library only."""


class InvalidToken(Exception):
    """Raised for any token that must not be trusted."""


def verify(token: str, secret: bytes, now: int, leeway: int) -> dict:
    """The token's claims if it is a valid HS256 JWT at time `now` (seconds), allowing
    `leeway` seconds of clock skew on exp and nbf. Otherwise raise InvalidToken."""
    raise NotImplementedError
