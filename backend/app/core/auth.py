"""
Autenticação Admin - Sistema de login seguro para painel administrativo

Utiliza bcrypt para hashing de senhas (padrão da indústria).
bcrypt automaticamente:
- Gera salt único por hash
- Usa key stretching (custo computacional ajustável)
- É resistente a ataques de timing
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt

from app.core.config import settings


# Security scheme
security = HTTPBearer()


def hash_password(password: str) -> str:
    """
    Gera hash bcrypt da senha.

    bcrypt automaticamente:
    - Gera salt único (16 bytes)
    - Aplica key stretching (work factor padrão: 12)
    - Retorna hash no formato: $2b$12$salt+hash

    Para gerar hash via CLI:
        python -c "import bcrypt; print(bcrypt.hashpw(b'sua_senha', bcrypt.gensalt()).decode())"
    """
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """
    Verifica se senha corresponde ao hash bcrypt.

    Usa comparação timing-safe internamente.
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        # Hash inválido ou formato incorreto
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Cria JWT token para sessão admin."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=24)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )

    return encoded_jwt


def verify_token(token: str) -> dict:
    """Verifica e decodifica JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Dependency para proteger rotas admin.

    Uso:
        @router.get("/admin/endpoint")
        async def admin_endpoint(admin: dict = Depends(verify_admin)):
            # Apenas admins autenticados podem acessar
            return {"message": "OK"}
    """
    token = credentials.credentials
    payload = verify_token(token)

    # Verificar se é token admin
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado - apenas administradores"
        )

    return payload


def verify_admin_credentials(username: str, password: str) -> bool:
    """
    Verifica credenciais admin.

    Credenciais configuradas via variáveis de ambiente:
    - ADMIN_USERNAME (padrão: admin)
    - ADMIN_PASSWORD_HASH (hash bcrypt da senha)

    Para gerar hash bcrypt:
        python -c "from app.core.auth import hash_password; print(hash_password('sua_senha_segura'))"

    Exemplo de hash bcrypt válido:
        $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.G5x8TtYGnHJPHi
    """
    expected_username = settings.ADMIN_USERNAME
    expected_password_hash = settings.ADMIN_PASSWORD_HASH

    if username != expected_username:
        return False

    return verify_password(password, expected_password_hash)
