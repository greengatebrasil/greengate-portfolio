"""
GreenGate - Request Logging Middleware

Implementa:
- Geração de request_id único (UUID4)
- Binding ao contexto structlog via contextvars
- Header X-Request-ID na resposta
- Log de cada request com contexto HTTP completo
"""
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import structlog

from app.core.logging_config import get_logger


# Context var para request_id (gerenciado pelo structlog.contextvars)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware que:
    1. Gera request_id único para cada request
    2. Adiciona ao contexto do structlog
    3. Loga início e fim do request com métricas
    4. Retorna header X-Request-ID
    """
    
    # Paths que não devem ser logados (health checks, métricas)
    SKIP_PATHS = {"/health", "/health/", "/metrics", "/metrics/"}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Gerar request_id único
        request_id = str(uuid.uuid4())
        
        # Extrair informações do request
        path = request.url.path
        method = request.method
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Limpar e bindar novo contexto
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=path,
            method=method,
            client_ip=client_ip,
        )
        
        # Skip logging para health checks
        should_log = path not in self.SKIP_PATHS
        
        log = get_logger("greengate.http")
        
        # Log de início (apenas para debug)
        if should_log:
            log.debug(
                "request_started",
                user_agent=user_agent[:100] if user_agent else None,  # Truncar
            )
        
        # Processar request
        start_time = time.perf_counter()
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            error = None
        except Exception as exc:
            status_code = 500
            error = str(exc)
            raise
        finally:
            # Calcular duração
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            
            # Log de conclusão
            if should_log:
                log_method = log.info if status_code < 400 else log.warning if status_code < 500 else log.error
                
                log_method(
                    "request_completed",
                    status_code=status_code,
                    duration_ms=duration_ms,
                    user_agent=user_agent[:100] if user_agent else None,
                    error=error,
                )
        
        # Adicionar header X-Request-ID na resposta
        response.headers["X-Request-ID"] = request_id
        
        # Adicionar header de tempo de processamento
        response.headers["X-Process-Time"] = f"{duration_ms}ms"
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """
        Extrai IP do cliente, considerando proxies (X-Forwarded-For).
        """
        # Verificar headers de proxy
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Pegar primeiro IP da lista (cliente original)
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback para IP direto
        if request.client:
            return request.client.host
        
        return "unknown"


class BusinessLoggerMixin:
    """
    Mixin para facilitar logging de eventos de negócio.
    
    Uso em services:
        from app.middleware.logger import BusinessLoggerMixin
        
        class MyService(BusinessLoggerMixin):
            def process(self):
                self.log_business("validation_completed", risk_score=0, status="rejected")
    """
    
    _log = None
    
    @property
    def log(self) -> structlog.BoundLogger:
        if self._log is None:
            self._log = get_logger(self.__class__.__name__)
        return self._log
    
    def log_business(self, event: str, **kwargs) -> None:
        """
        Loga evento de negócio com contexto automático.
        Todas as kwargs viram top-level keys no JSON.
        """
        self.log.info(event, **kwargs)
    
    def log_error(self, event: str, error: Exception, **kwargs) -> None:
        """
        Loga erro com stack trace.
        """
        self.log.error(event, error=str(error), exc_info=error, **kwargs)
