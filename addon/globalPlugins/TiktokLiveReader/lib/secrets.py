import base64
import binascii
import os
import random
import hmac


__all__ = ['choice', 'randbelow', 'randbits', 'token_bytes',
           'token_hex', 'token_urlsafe', 'compare_digest']


def choice(sequence):
    """Choose a random element from a non-empty sequence."""
    if not sequence:
        raise IndexError("Cannot choose from an empty sequence")
    return sequence[randbelow(len(sequence))]


def randbelow(exclusive_upper_bound):
    """Return a random int in the range [0, n)."""
    if exclusive_upper_bound <= 0:
        raise ValueError("Upper bound must be positive")
    return int.from_bytes(token_bytes(exclusive_upper_bound.bit_length() // 8 + 1), 'big') % exclusive_upper_bound


def randbits(k):
    """Return a random int with k random bits."""
    if k <= 0:
        raise ValueError("Number of bits must be greater than zero")
    num_bytes = (k + 7) // 8
    random_bytes = token_bytes(num_bytes)
    value = int.from_bytes(random_bytes, 'big')
    return value >> (num_bytes * 8 - k)


def token_bytes(nbytes=None):
    """Return a random byte string containing *nbytes* bytes.

    If *nbytes* is None or not supplied, a reasonable default is used.
    """
    if nbytes is None:
        nbytes = 32
    return os.urandom(nbytes)


def token_hex(nbytes=None):
    """Return a random text string, in hexadecimal."""
    return binascii.hexlify(token_bytes(nbytes)).decode('ascii')


def token_urlsafe(nbytes=None):
    """Return a random URL-safe text string, in Base64."""
    tok = token_bytes(nbytes)
    return base64.urlsafe_b64encode(tok).rstrip(b'=').decode('ascii')


compare_digest = hmac.compare_digest
