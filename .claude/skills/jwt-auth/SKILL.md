---
name: jwt-auth
description: JWT authentication implementation with bcrypt, refresh tokens, and rate limiting. Use for auth-related development, login, registration, or token handling.
allowed-tools: Read, Edit, Bash, Grep
---

# JWT Authentication Standards

This skill guides authentication implementation for the E-Signature Platform.

## Token Configuration (esig-design.md)

| Token Type | Format | Expiry | Storage |
|------------|--------|--------|---------|
| Access Token | JWT (HS256) | 1 hour | Client memory |
| Refresh Token | Random 64-byte | 7 days | httpOnly cookie + DB (bcrypt hashed) |
| Signing Token | Random 32-byte | 30 days | DB (bcrypt hashed), single-use |
| Password Reset | Random 32-byte | 24 hours | DB (bcrypt hashed) |
| Password | bcrypt | - | Cost factor 12 |

## Password Hashing

```python
import bcrypt

BCRYPT_COST = 12

def hash_password(password: str) -> str:
    """Hash password with bcrypt, cost factor 12."""
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt(rounds=BCRYPT_COST)
    ).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(
        password.encode('utf-8'),
        hashed.encode('utf-8')
    )
```

## JWT Access Token

```python
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 1

def create_access_token(user_id: int) -> str:
    """Create JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access"
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_access_token(token: str) -> int | None:
    """Verify JWT and return user_id, or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return int(payload.get("sub"))
    except JWTError:
        return None
```

## Refresh Token

```python
import secrets

REFRESH_TOKEN_BYTES = 64
REFRESH_TOKEN_EXPIRE_DAYS = 7

def create_refresh_token() -> tuple[str, str]:
    """Create refresh token and its hash.

    Returns:
        tuple: (plain_token, hashed_token)
        - Send plain_token to client (via httpOnly cookie)
        - Store hashed_token in database
    """
    token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    hashed = bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()
    return token, hashed

def verify_refresh_token(token: str, stored_hash: str) -> bool:
    """Verify refresh token against stored hash."""
    return bcrypt.checkpw(token.encode(), stored_hash.encode())
```

## Signing Token (for recipients)

```python
SIGNING_TOKEN_BYTES = 32
SIGNING_TOKEN_EXPIRE_DAYS = 30

def create_signing_token() -> tuple[str, str]:
    """Create signing token for recipient email link.

    Returns:
        tuple: (plain_token, hashed_token)
        - plain_token goes in email link
        - hashed_token stored in recipients table
    """
    token = secrets.token_urlsafe(SIGNING_TOKEN_BYTES)
    hashed = bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()
    return token, hashed

def verify_signing_token(token: str, stored_hash: str) -> bool:
    """Verify signing token against stored hash."""
    return bcrypt.checkpw(token.encode(), stored_hash.encode())
```

## Authentication Dependency

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Extract and verify user from JWT."""
    token = credentials.credentials
    user_id = verify_access_token(token)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "AUTH_TOKEN_INVALID",
                    "message": "Token is malformed or invalid",
                    "details": {}
                }
            }
        )

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "AUTH_TOKEN_INVALID",
                    "message": "User not found",
                    "details": {}
                }
            }
        )

    return user

async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: AsyncSession = Depends(get_db)
) -> User | None:
    """Get user if authenticated, None otherwise."""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None
```

## Rate Limiting (esig-design.md)

```python
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

# In-memory rate limiter (use Redis in production)
class RateLimiter:
    def __init__(self):
        self.requests: dict[str, list[datetime]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(
        self,
        key: str,
        limit: int,
        window_seconds: int
    ) -> bool:
        """Check if request is allowed under rate limit."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(seconds=window_seconds)

            # Clean old requests
            self.requests[key] = [
                t for t in self.requests[key] if t > cutoff
            ]

            if len(self.requests[key]) >= limit:
                return False

            self.requests[key].append(now)
            return True

rate_limiter = RateLimiter()
```

## Rate Limits Reference

| Endpoint | Limit | Window |
|----------|-------|--------|
| `POST /api/auth/*` | 5 | 1 minute |
| `POST /api/auth/login` (failed) | 5 | 15 minutes |
| `POST /api/auth/forgot-password` | 3 | 1 minute |
| `POST /api/signing/*/complete` | 3 | 1 minute |
| All other authenticated | 100 | 1 minute |
| All other public | 30 | 1 minute |

## Login Flow

```python
@router.post("/auth/login")
async def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    # Rate limit check
    client_ip = request.client.host
    if not await rate_limiter.check(f"login:{client_ip}", 5, 60):
        raise HTTPException(
            status_code=429,
            detail={"error": {"code": "AUTH_RATE_LIMITED", "message": "Too many requests", "details": {"retry_after": 60}}}
        )

    # Find user
    user = await db.scalar(
        select(User).where(User.email == credentials.email)
    )

    if user is None or not verify_password(credentials.password, user.password_hash):
        # SECURITY: Same error for wrong email or password
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "AUTH_INVALID_CREDENTIALS",
                    "message": "Email or password incorrect",
                    "details": {}
                }
            }
        )

    # Generate tokens
    access_token = create_access_token(user.id)
    refresh_token, refresh_hash = create_refresh_token()

    # Store refresh token
    db_token = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(db_token)
    await db.commit()

    # Set refresh token in httpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,  # HTTPS only
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )

    return TokenResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_HOURS * 3600
    )
```

## Token Refresh (with rotation)

```python
@router.post("/auth/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    # Get refresh token from cookie
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail={"error": {"code": "AUTH_REFRESH_TOKEN_INVALID", ...}})

    # Find valid refresh token
    tokens = await db.scalars(
        select(RefreshToken)
        .where(RefreshToken.revoked_at.is_(None))
        .where(RefreshToken.expires_at > datetime.now(timezone.utc))
    )

    valid_token = None
    for token in tokens:
        if verify_refresh_token(refresh_token, token.token_hash):
            valid_token = token
            break

    if valid_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "AUTH_REFRESH_TOKEN_INVALID", ...}}
        )

    # SECURITY: Revoke old token (rotation)
    valid_token.revoked_at = datetime.now(timezone.utc)

    # Generate new tokens
    access_token = create_access_token(valid_token.user_id)
    new_refresh, new_hash = create_refresh_token()

    # Store new refresh token
    db.add(RefreshToken(
        user_id=valid_token.user_id,
        token_hash=new_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    ))
    await db.commit()

    # Set new refresh token in cookie
    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )

    return {"access_token": access_token, "expires_in": ACCESS_TOKEN_EXPIRE_HOURS * 3600}
```

## Security Checklist

- [ ] Never store plain refresh tokens (always hash)
- [ ] Rotate refresh tokens on each use
- [ ] Same error message for wrong email or password
- [ ] Rate limit all auth endpoints
- [ ] Return 202 for forgot-password (no email enumeration)
- [ ] Hash password reset tokens
- [ ] Expire password reset tokens (24 hours)
- [ ] Hash signing tokens
- [ ] Expire signing tokens (30 days default)
- [ ] Log failed auth attempts (for monitoring)
- [ ] Use httpOnly cookies for refresh tokens

## Frontend Token Storage

```typescript
// AuthContext.tsx
// Access token: memory only (lost on refresh, but that's OK)
// Refresh token: httpOnly cookie (managed by browser)

const [accessToken, setAccessToken] = useState<string | null>(null);

// On app load, try to refresh
useEffect(() => {
  refreshAccessToken();
}, []);

// Auto-refresh before expiry
useEffect(() => {
  if (!accessToken) return;

  // Refresh 5 minutes before expiry
  const timeout = setTimeout(() => {
    refreshAccessToken();
  }, (60 - 5) * 60 * 1000); // 55 minutes

  return () => clearTimeout(timeout);
}, [accessToken]);
```
