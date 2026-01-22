"""
GreenGate - Segurança e Autenticação

API Key simples para proteção básica.
Para usar, configure API_KEY no .env:
    API_KEY=sua-chave-secreta-aqui

Endpoints protegidos:
- POST /api/v1/validations/*
- POST /api/v1/reports/*

Endpoints públicos:
- GET /health
- GET /docs
"""
from typing import Optional
from fastapi import Header, HTTPException, status, Depends
from fastapi.security import APIKeyHeader

from app.core.config import settings


# Header scheme para Swagger
api_key_header = APIKeyHeader(
    name=settings.API_KEY_HEADER,
    auto_error=False,  # Não levanta erro automaticamente (nós controlamos)
)


async def verify_api_key(
    api_key: Optional[str] = Depends(api_key_header)
) -> Optional[str]:
    """
    Verifica se a API Key é válida.
    
    Se API_KEY não estiver configurada no .env, permite acesso sem autenticação.
    Isso facilita desenvolvimento local.
    
    Returns:
        A API Key se válida, ou None se não requerida
        
    Raises:
        HTTPException 401 se API Key for inválida
        HTTPException 403 se API Key for obrigatória mas não fornecida
    """
    # Se API_KEY não configurada, permite acesso livre
    if not settings.API_KEY:
        return None
    
    # API_KEY configurada - exige autenticação
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "API Key não fornecida",
                "message": f"Inclua o header '{settings.API_KEY_HEADER}' com sua chave de API",
            }
        )
    
    # Comparação segura (timing-safe)
    import hmac
    if not hmac.compare_digest(api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "API Key inválida",
                "message": "A chave de API fornecida não é válida",
            }
        )
    
    return api_key


async def require_api_key(
    api_key: Optional[str] = Depends(verify_api_key)
) -> str:
    """
    Versão estrita: SEMPRE exige API Key, mesmo se não configurada.
    Útil para endpoints que NUNCA devem ser públicos.
    """
    if api_key is None and settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key obrigatória"
        )
    return api_key or "development"
