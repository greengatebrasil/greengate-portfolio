"""
GreenGate - Middleware de Limite de Upload

Protege contra payloads muito grandes verificando Content-Length header.
Para requests JSON normais, o header é sempre enviado pelo cliente.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import get_logger

log = get_logger(__name__)


class LimitUploadSizeMiddleware(BaseHTTPMiddleware):
    """
    Middleware para limitar tamanho de upload via Content-Length header.
    
    Nota: Não lê o body (evita problemas de stream exhaustion).
    Requests JSON normais sempre enviam Content-Length.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Paths que não precisam de limite
        if request.url.path in {"/health", "/health/detailed", "/docs", "/redoc", "/openapi.json", "/"}:
            return await call_next(request)
        
        # Métodos sem body
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        
        # Verificar Content-Length header
        content_length = request.headers.get("content-length")
        
        if content_length:
            try:
                length = int(content_length)
                max_size = settings.MAX_UPLOAD_SIZE
                
                if length > max_size:
                    log.warning(
                        "payload_too_large",
                        content_length=length,
                        max_size=max_size,
                        path=request.url.path,
                        client_ip=request.client.host if request.client else "unknown",
                    )
                    max_mb = max_size / (1024 * 1024)
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Payload too large. Maximum size: {max_mb:.1f} MB"}
                    )
            except ValueError:
                # Header inválido, deixa passar para o framework tratar
                pass
        
        # Continua normalmente
        return await call_next(request)
