"""
Endpoints de autenticação para painel admin e auto-registro público
"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.auth import verify_admin_credentials, create_access_token
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import rate_limiter
from app.services.api_key_service import APIKeyService
from app.models.api_key import APIKey


router = APIRouter(
    prefix="/auth",
    tags=["Autenticação"],
)


class LoginRequest(BaseModel):
    """Request de login."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Response de login bem-sucedido."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos


@router.post("/login", response_model=LoginResponse)
async def login(credentials: LoginRequest, request: Request):
    """
    Autentica admin e retorna JWT token.

    O token deve ser incluído nas requisições subsequentes:
    ```
    Authorization: Bearer <token>
    ```

    **Credenciais padrão (TROCAR EM PRODUÇÃO)**:
    - Username: admin
    - Password: (configurar ADMIN_PASSWORD_HASH)

    **Rate limit:** Máximo 5 tentativas por IP a cada 5 minutos.
    """
    # Rate limit: máx 5 tentativas por IP por 5 minutos (proteção brute force)
    client_ip = _get_client_ip(request)
    rate_info = rate_limiter.check(
        client_id=f"login:{client_ip}",
        limit=5,
        window_seconds=300  # 5 minutos
    )

    if not rate_info.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Muitas tentativas de login",
                "message": "Máximo de 5 tentativas a cada 5 minutos. Aguarde e tente novamente.",
                "retry_after": rate_info.reset_at,
            }
        )

    # Verificar credenciais
    if not verify_admin_credentials(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Criar token JWT
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": credentials.username, "role": "admin"},
        expires_delta=access_token_expires
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # converter para segundos
    )


@router.post("/logout")
async def logout():
    """
    Logout (lado do cliente deve descartar o token).

    JWT é stateless, então não há invalidação no servidor.
    O cliente deve simplesmente remover o token do localStorage.
    """
    return {"message": "Logout realizado com sucesso"}


# =============================================================================
# AUTO-REGISTRO PÚBLICO
# =============================================================================

class RegisterRequest(BaseModel):
    """Request de auto-registro."""
    email: EmailStr


class RegisterResponse(BaseModel):
    """Response de registro bem-sucedido."""
    success: bool
    api_key: str
    message: str
    quota: int
    warning: str = "Guarde esta API key! Ela não será mostrada novamente."


def _get_client_ip(request: Request) -> str:
    """Extrai IP do cliente (considerando proxies)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


@router.post("/register", response_model=RegisterResponse)
async def register(
    request: RegisterRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    🆓 Auto-registro público - Obtenha sua API key instantaneamente.

    **Como funciona:**
    1. Informe seu email
    2. Receba uma API key com 3 validações gratuitas
    3. Use a API key no header `x-api-key` das requisições

    **Importante:**
    - Um email só pode ter uma API key ativa
    - A API key é mostrada apenas UMA VEZ - guarde-a!
    - Para mais validações, entre em contato: greengatebrasil@gmail.com

    **Rate limit:** Máximo 3 registros por IP a cada 24 horas.
    """
    # Rate limit: máx 3 registros por IP por dia (86400 segundos)
    client_ip = _get_client_ip(http_request)
    rate_info = rate_limiter.check(
        client_id=f"register:{client_ip}",
        limit=3,
        window_seconds=86400  # 24 horas
    )

    if not rate_info.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Limite de registros excedido",
                "message": "Máximo de 3 registros por dia. Tente novamente amanhã.",
                "retry_after": rate_info.reset_at,
            }
        )

    email = request.email.lower().strip()

    # Validar domínio do email (bloquear temporários/descartáveis)
    domain = email.split('@')[1] if '@' in email else ''
    blocked_domains = {
        'tempmail.com', 'guerrillamail.com', 'mailinator.com', '10minutemail.com',
        'throwaway.email', 'fakeinbox.com', 'trashmail.com', 'temp-mail.org',
        'yopmail.com', 'sharklasers.com', 'guerrillamail.info', 'grr.la',
        'dispostable.com', 'mailnesia.com', 'maildrop.cc', 'getairmail.com',
        'mohmal.com', 'tempail.com', 'tempr.email', 'discard.email',
        'discardmail.com', 'spamgourmet.com', 'mytemp.email', 'mt2009.com',
        'tempinbox.com', 'fakemailgenerator.com', 'emailondeck.com', 'getnada.com',
        'mintemail.com', 'mailcatch.com', 'dropmail.me', 'harakirimail.com'
    }

    if domain in blocked_domains:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Email temporário não permitido",
                "message": "Por favor, use um email real. Emails temporários/descartáveis não são aceitos.",
            }
        )

    # Verificar se email já tem API key ativa
    query = select(APIKey).where(
        APIKey.client_email == email,
        APIKey.is_active == True,
        APIKey.is_revoked == False,
    )
    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Email já cadastrado",
                "message": f"Este email já possui uma API key (prefixo: {existing.key_prefix}). Se perdeu a chave, entre em contato: greengatebrasil@gmail.com",
            }
        )

    # Criar nova API key
    service = APIKeyService(db)

    try:
        result = await service.create_api_key(
            client_name=email.split("@")[0],  # Usar parte antes do @ como nome
            plan="free",
            client_email=email,
            notes="Auto-registro via /auth/register",
            created_by="self-registration",
        )

        return RegisterResponse(
            success=True,
            api_key=result["api_key"],
            message=f"API key criada com sucesso! Você tem {result['monthly_quota']} validações gratuitas.",
            quota=result["monthly_quota"],
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar API key: {str(e)}"
        )
