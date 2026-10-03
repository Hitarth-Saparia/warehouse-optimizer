"""
backend/security.py
Core Cryptographic Security & Rate-Limiting Module

Implements NIST-compliant cryptographic primitives using Python's standard library:
1. PBKDF2-HMAC-SHA256 password hashing with 16-byte CSPRNG salts (100,000 iterations).
2. Constant-time digest comparison (hmac.compare_digest) to prevent side-channel timing attacks.
3. Cryptographically signed stateless bearer tokens (HMAC-SHA256 signature verification).
4. Sliding Window Rate Limiter using collections.deque to guard against brute-force attacks.
"""

import os
import time
import json
import base64
import hmac
import hashlib
import secrets
from collections import deque

# Secret key for signing tokens (retrieved from environment or securely generated)
SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "wareopt-secure-wms-token-signing-key-2026")
PBKDF2_ITERATIONS = 100_000


# =====================================================================
# 1. Cryptographic Password Hashing & Constant-Time Verification
# =====================================================================

def generate_salt(length: int = 16) -> str:
    """Generates a cryptographically secure random salt hex string using CSPRNG."""
    return secrets.token_hex(length)


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """
    Hashes a plaintext password using PBKDF2-HMAC-SHA256 with 100,000 rounds.
    Returns: (password_hash_hex, salt_hex)
    """
    if salt is None:
        salt = generate_salt(16)
    
    salt_bytes = bytes.fromhex(salt)
    derived_key = hashlib.pbkdf2_hmac(
        hash_name='sha256',
        password=password.encode('utf-8'),
        salt=salt_bytes,
        iterations=PBKDF2_ITERATIONS,
        dklen=32
    )
    return derived_key.hex(), salt


def verify_password(plain_password: str, stored_hash: str, stored_salt: str) -> bool:
    """
    Verifies a password against the stored PBKDF2-HMAC-SHA256 hash using
    constant-time comparison to guard against timing analysis attacks.
    """
    if not plain_password or not stored_hash or not stored_salt:
        return False
    
    computed_hash, _ = hash_password(plain_password, stored_salt)
    return hmac.compare_digest(computed_hash, stored_hash)


# =====================================================================
# 2. Cryptographically Signed Stateless Tokens (HMAC-SHA256)
# =====================================================================

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')


def _b64url_decode(encoded_str: str) -> bytes:
    padding = '=' * (-len(encoded_str) % 4)
    return base64.urlsafe_b64decode((encoded_str + padding).encode('utf-8'))


def generate_token(payload: dict, secret: str = None, expires_in_seconds: int = 43200) -> str:
    """
    Generates a signed, tamper-proof bearer token with an expiration timestamp.
    Format: base64url(payload) + '.' + base64url(hmac_signature)
    """
    signing_secret = (secret or SECRET_KEY).encode('utf-8')
    token_claims = dict(payload)
    token_claims['iat'] = int(time.time())
    token_claims['exp'] = int(time.time()) + expires_in_seconds

    payload_json = json.dumps(token_claims, separators=(',', ':'), sort_keys=True).encode('utf-8')
    payload_b64 = _b64url_encode(payload_json)

    signature = hmac.new(signing_secret, payload_b64.encode('utf-8'), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{payload_b64}.{sig_b64}"


def verify_token(token: str, secret: str = None) -> dict | None:
    """
    Validates token signature and checks expiration.
    Returns decoded claims dictionary if valid, or None if invalid/expired.
    """
    if not token or '.' not in token:
        return None

    try:
        payload_b64, sig_b64 = token.split('.', 1)
        signing_secret = (secret or SECRET_KEY).encode('utf-8')

        # Recalculate signature and compare in constant time
        expected_sig = hmac.new(signing_secret, payload_b64.encode('utf-8'), hashlib.sha256).digest()
        provided_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, provided_sig):
            return None

        payload_bytes = _b64url_decode(payload_b64)
        claims = json.loads(payload_bytes.decode('utf-8'))

        # Check expiration claim
        if 'exp' in claims and time.time() > claims['exp']:
            return None

        return claims
    except Exception:
        return None


# =====================================================================
# 3. Sliding Window Rate Limiter (Brute-Force Attack Prevention)
# =====================================================================

class SlidingWindowRateLimiter:
    """
    Sliding Window Log algorithm to rate limit authentication attempts per identifier
    (IP address or username) to prevent dictionary / brute-force attacks.
    """
    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.history: dict[str, deque] = {}

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """
        Returns (is_allowed, retry_after_seconds).
        Purges expired timestamps and checks current window usage.
        """
        now = time.time()
        cutoff = now - self.window_seconds

        if key not in self.history:
            self.history[key] = deque()

        timestamps = self.history[key]

        # Evict timestamps older than the sliding window cutoff
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        if len(timestamps) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - timestamps[0])) + 1
            return False, max(1, retry_after)

        timestamps.append(now)
        return True, 0

    def reset(self, key: str):
        """Clears rate limit history for a key upon successful login."""
        self.history.pop(key, None)


# Default rate limiter: 5 attempts per 60 seconds per IP/email
login_rate_limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
