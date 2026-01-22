"""
GreenGate - Rate Limiting

Sliding window com suporte a Redis (produção) e fallback em memória (dev).

Para produção multi-worker, REDIS_URL deve estar configurado.
Sem Redis, cada worker terá seu próprio estado (não recomendado para prod).

Limites:
- Com API key: 100 req/min
- Sem API key (anônimo): 20 req/min
"""
import time
from collections import defaultdict
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class RateLimitInfo:
    """Informações de rate limit para uma requisição."""
    allowed: bool
    limit: int
    remaining: int
    reset_at: int  # Unix timestamp


class RateLimiterBackend:
    """Interface base para backends de rate limiting."""

    def check(
        self,
        client_id: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitInfo:
        raise NotImplementedError

    def get_stats(self) -> Dict:
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiterBackend):
    """
    Rate limiter com sliding window em memória.

    Thread-safe para uso com asyncio (GIL protege operações).
    NÃO FUNCIONA com múltiplos workers - usar Redis em produção.
    """

    def __init__(self):
        # {client_id: [timestamp, timestamp, ...]}
        self._requests: Dict[str, list] = defaultdict(list)
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # Cleanup a cada 60s

    def _maybe_cleanup(self):
        """Limpa entradas antigas periodicamente."""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup_all()
            self._last_cleanup = now

    def _cleanup_all(self):
        """Remove todas as entradas expiradas."""
        now = time.time()
        window = 60  # 1 minuto
        cutoff = now - window

        empty_keys = []
        for client_id, timestamps in self._requests.items():
            self._requests[client_id] = [t for t in timestamps if t > cutoff]
            if not self._requests[client_id]:
                empty_keys.append(client_id)

        # Remover clientes sem requisições
        for key in empty_keys:
            del self._requests[key]

    def check(
        self,
        client_id: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitInfo:
        """
        Verifica e registra requisição.

        Args:
            client_id: Identificador do cliente (API key ou IP)
            limit: Máximo de requisições na janela
            window_seconds: Tamanho da janela em segundos

        Returns:
            RateLimitInfo com status e métricas
        """
        self._maybe_cleanup()

        now = time.time()
        cutoff = now - window_seconds

        # Limpar requisições antigas deste cliente
        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > cutoff
        ]

        current_count = len(self._requests[client_id])
        reset_at = int(now + window_seconds)

        if current_count >= limit:
            # Limite atingido
            if self._requests[client_id]:
                oldest = min(self._requests[client_id])
                reset_at = int(oldest + window_seconds)

            return RateLimitInfo(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=reset_at,
            )

        # Registrar requisição
        self._requests[client_id].append(now)

        return RateLimitInfo(
            allowed=True,
            limit=limit,
            remaining=limit - current_count - 1,
            reset_at=reset_at,
        )

    def get_stats(self) -> Dict:
        """Retorna estatísticas do rate limiter."""
        return {
            "backend": "memory",
            "active_clients": len(self._requests),
            "total_tracked": sum(len(v) for v in self._requests.values()),
        }


class RedisRateLimiter(RateLimiterBackend):
    """
    Rate limiter com sliding window usando Redis.

    Funciona corretamente com múltiplos workers em produção.
    Usa sorted sets do Redis para sliding window eficiente.
    """

    def __init__(self, redis_url: str):
        import redis
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = "greengate:ratelimit:"

        # Testar conexão
        try:
            self._redis.ping()
            log.info("rate_limiter_redis_connected", redis_url=redis_url[:20] + "...")
        except redis.ConnectionError as e:
            log.error("rate_limiter_redis_failed", error=str(e))
            raise

    def check(
        self,
        client_id: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitInfo:
        """
        Verifica e registra requisição usando Redis sorted set.

        Usa ZADD com score=timestamp para sliding window.
        """
        now = time.time()
        cutoff = now - window_seconds
        key = f"{self._key_prefix}{client_id}"

        # Pipeline para atomicidade
        pipe = self._redis.pipeline()

        # 1. Remover entradas antigas (score < cutoff)
        pipe.zremrangebyscore(key, "-inf", cutoff)

        # 2. Contar requisições na janela
        pipe.zcard(key)

        # 3. Obter timestamp mais antigo (para calcular reset_at)
        pipe.zrange(key, 0, 0, withscores=True)

        results = pipe.execute()
        current_count = results[1]
        oldest_entries = results[2]

        reset_at = int(now + window_seconds)
        if oldest_entries:
            oldest_timestamp = oldest_entries[0][1]
            reset_at = int(oldest_timestamp + window_seconds)

        if current_count >= limit:
            # Limite atingido
            return RateLimitInfo(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=reset_at,
            )

        # 4. Registrar nova requisição
        # Usar timestamp com microsegundos como score e member único
        member = f"{now}:{id(self)}"
        self._redis.zadd(key, {member: now})

        # 5. Definir TTL na chave (para auto-limpeza)
        self._redis.expire(key, window_seconds + 10)

        return RateLimitInfo(
            allowed=True,
            limit=limit,
            remaining=limit - current_count - 1,
            reset_at=reset_at,
        )

    def get_stats(self) -> Dict:
        """Retorna estatísticas do rate limiter."""
        try:
            # Contar chaves de rate limit
            keys = self._redis.keys(f"{self._key_prefix}*")
            total_tracked = 0
            for key in keys[:100]:  # Limitar para performance
                total_tracked += self._redis.zcard(key)

            return {
                "backend": "redis",
                "active_clients": len(keys),
                "total_tracked": total_tracked,
            }
        except Exception as e:
            return {
                "backend": "redis",
                "error": str(e),
            }


def create_rate_limiter() -> RateLimiterBackend:
    """
    Factory para criar o rate limiter apropriado.

    Usa Redis se REDIS_URL estiver configurado, senão fallback para memória.
    """
    if settings.REDIS_URL:
        try:
            return RedisRateLimiter(settings.REDIS_URL)
        except Exception as e:
            log.warning(
                "rate_limiter_redis_fallback",
                error=str(e),
                message="Falling back to in-memory rate limiter"
            )
            return InMemoryRateLimiter()
    else:
        log.info(
            "rate_limiter_memory",
            message="Using in-memory rate limiter (not recommended for multi-worker)"
        )
        return InMemoryRateLimiter()


# Instância global
rate_limiter = create_rate_limiter()


def _get_cors_origin() -> str:
    """Retorna a origem CORS apropriada para headers de erro."""
    origins = settings.cors_origins
    if origins and origins[0] != "*":
        return origins[0]
    return "*"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware que aplica rate limiting em todas as requisições.

    Limites:
    - Com API key válida: RATE_LIMIT_AUTHENTICATED req/min
    - Sem API key: RATE_LIMIT_ANONYMOUS req/min

    Headers adicionados em TODAS as respostas:
    - X-RateLimit-Limit
    - X-RateLimit-Remaining
    - X-RateLimit-Reset
    """

    # Paths que não contam para rate limit
    EXEMPT_PATHS = {"/health", "/health/detailed", "/docs", "/redoc", "/openapi.json", "/"}

    async def dispatch(self, request: Request, call_next):
        # Paths isentos (exact match)
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Isentar endpoints admin (já protegidos por JWT)
        if request.url.path.startswith("/api/v1/admin/") or request.url.path.startswith("/api/v1/auth/"):
            return await call_next(request)

        # Identificar cliente
        client_id, is_authenticated = self._get_client_id(request)

        # Definir limite baseado em autenticação
        if is_authenticated:
            limit = settings.RATE_LIMIT_AUTHENTICATED
        else:
            limit = settings.RATE_LIMIT_ANONYMOUS

        # Verificar rate limit
        info = rate_limiter.check(client_id, limit, window_seconds=60)

        # Headers de rate limit
        rate_headers = {
            "X-RateLimit-Limit": str(info.limit),
            "X-RateLimit-Remaining": str(info.remaining),
            "X-RateLimit-Reset": str(info.reset_at),
        }

        if not info.allowed:
            # Rate limit excedido
            retry_after = info.reset_at - int(time.time())

            log.warning(
                "rate_limit_exceeded",
                client_id=client_id[:20] + "..." if len(client_id) > 20 else client_id,
                is_authenticated=is_authenticated,
                limit=limit,
                path=request.url.path,
            )

            # Usar CORS origin das configurações (não wildcard)
            cors_origin = _get_cors_origin()

            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    "retry_after": retry_after,
                },
                headers={
                    **rate_headers,
                    "Retry-After": str(retry_after),
                    "Access-Control-Allow-Origin": cors_origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                },
            )

        # Executar request
        response = await call_next(request)

        # Adicionar headers de rate limit à resposta
        for key, value in rate_headers.items():
            response.headers[key] = value

        return response

    def _get_client_id(self, request: Request) -> Tuple[str, bool]:
        """
        Extrai identificador do cliente.

        Returns:
            (client_id, is_authenticated)
        """
        # Verificar API key
        api_key = request.headers.get("x-api-key")
        if api_key and settings.API_KEY and api_key == settings.API_KEY:
            # API key válida - usar hash como ID
            return f"key:{api_key[:8]}", True

        # Fallback para IP
        ip = self._get_client_ip(request)
        return f"ip:{ip}", False

    def _get_client_ip(self, request: Request) -> str:
        """Extrai IP do cliente (considerando proxies)."""
        # X-Forwarded-For (proxy/load balancer)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        # X-Real-IP (nginx)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # IP direto
        if request.client:
            return request.client.host

        return "unknown"


def get_rate_limit_stats() -> Dict:
    """Retorna estatísticas do rate limiter para health check."""
    return rate_limiter.get_stats()
