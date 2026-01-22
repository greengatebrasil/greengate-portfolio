"""
Middleware para rastrear uso de API Keys
"""
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.database import async_session_maker
from app.services.api_key_service import APIKeyService


class APIKeyTrackerMiddleware(BaseHTTPMiddleware):
    """
    Middleware para rastrear uso de API Keys.

    - Valida API key
    - Verifica quota
    - Registra uso
    - Adiciona headers de quota
    """

    # Endpoints que não requerem API key (exact match)
    PUBLIC_PATHS = {
        "/",
        "/health",
        "/health/detailed",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/reports/verify",  # Verificação de relatórios é pública
        "/api/v1/metadata/data-freshness",  # Datas de atualização dos dados (público)
        "/api/v1/validations/quick",  # Validação rápida pública (área de exemplo)
        # /api/v1/auth/* e /api/v1/admin/* são tratados via startswith abaixo
    }

    async def dispatch(self, request: Request, call_next):
        """Processa request."""

        # Ignorar OPTIONS (preflight CORS) - sempre permitir
        if request.method == "OPTIONS":
            return await call_next(request)

        # Ignorar paths públicos (exact match ou startswith para paths específicos)
        if (request.url.path in self.PUBLIC_PATHS or
            request.url.path.startswith("/docs") or
            request.url.path.startswith("/redoc") or
            request.url.path.startswith("/api/v1/auth/") or  # Autenticação admin (JWT)
            request.url.path.startswith("/api/v1/admin/") or  # Endpoints admin (JWT)
            request.url.path.startswith("/api/v1/reports/verify/")):  # Verificacao publica QR Code
            return await call_next(request)

        # Extrair API key do header
        api_key = request.headers.get('x-api-key')

        if not api_key:
            # Sem API key → retornar 403 com headers CORS
            return Response(
                content='{"detail": "API Key não fornecida. Use o header x-api-key."}',
                status_code=status.HTTP_403_FORBIDDEN,
                media_type="application/json",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                }
            )

        # Validar API key e verificar quota COM LOCK (evita race condition)
        # IMPORTANTE: Manter db session aberta para manter o lock
        # OTIMIZAÇÃO: Query única com SELECT FOR UPDATE (reduz de 2 queries para 1)
        db = async_session_maker()
        try:
            from sqlalchemy import select
            from app.models.api_key import APIKey as APIKeyModel
            from datetime import datetime, timezone

            service = APIKeyService(db)

            # Hash da API key para busca
            key_hash = service.hash_api_key(api_key)
            now = datetime.now(timezone.utc)

            # QUERY ÚNICA: Valida key + adquire lock em uma operação
            # Substitui verify_api_key() + SELECT FOR UPDATE separados
            stmt = select(APIKeyModel).where(
                APIKeyModel.key_hash == key_hash,
                APIKeyModel.is_active == True,
                APIKeyModel.is_revoked == False,
            ).with_for_update()

            result = await db.execute(stmt)
            api_key_locked = result.scalar_one_or_none()

            if not api_key_locked:
                # API key inválida ou não encontrada
                await db.close()
                return Response(
                    content='{"detail": "API Key inválida ou expirada."}',
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    media_type="application/json",
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Credentials": "true",
                        "Access-Control-Allow-Methods": "*",
                        "Access-Control-Allow-Headers": "*",
                    }
                )

            # Verificar expiração (inline, sem query)
            if api_key_locked.expires_at and now > api_key_locked.expires_at:
                await db.close()
                return Response(
                    content='{"detail": "API Key expirada."}',
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    media_type="application/json",
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Credentials": "true",
                        "Access-Control-Allow-Methods": "*",
                        "Access-Control-Allow-Headers": "*",
                    }
                )

            # Verificar quota com a row LOCKED
            quota_info_before = await service.check_quota(api_key_locked)

            if not quota_info_before['has_quota']:
                # Calcular reset timestamp ANTES de fechar sessão
                reset_timestamp = '0'
                if api_key_locked.last_reset_at:
                    reset_timestamp = str(int(api_key_locked.last_reset_at.timestamp()) + (30 * 86400))

                # Já excedeu quota - libera lock com rollback
                await db.rollback()
                await db.close()

                return Response(
                    content=(
                        '{"detail": "Quota mensal excedida. '
                        f'Limite: {quota_info_before["monthly_quota"]}, '
                        f'Usado: {quota_info_before["requests_this_month"]}. '
                        'Faça upgrade do plano ou aguarde o reset mensal."}'
                    ),
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    media_type="application/json",
                    headers={
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Credentials': 'true',
                        'Access-Control-Allow-Methods': '*',
                        'Access-Control-Allow-Headers': '*',
                        'X-RateLimit-Limit': str(quota_info_before['monthly_quota']),
                        'X-RateLimit-Remaining': '0',
                        'X-RateLimit-Reset': reset_timestamp,
                    }
                )

            # Salvar valores ANTES do commit (sessão ainda ativa)
            monthly_quota = api_key_locked.monthly_quota
            current_requests = api_key_locked.requests_this_month
            current_total_requests = api_key_locked.total_requests

            # Calcular reset timestamp com segurança
            if api_key_locked.last_reset_at:
                last_reset_timestamp = int(api_key_locked.last_reset_at.timestamp()) + (30 * 86400)
            else:
                last_reset_timestamp = 0

            # TEM quota - incrementar (row ainda locked)
            # auto_commit=False para NÃO liberar o lock aqui
            await service.track_usage(api_key_locked, auto_commit=False)

            # COMMIT EXPLÍCITO - libera o lock AGORA (após track_usage)
            await db.commit()

            # Calcular valores após incremento (requests_this_month foi incrementado em 1)
            requests_after_increment = current_requests + 1
            if monthly_quota is not None:
                quota_remaining = max(0, monthly_quota - requests_after_increment)
            else:
                quota_remaining = None  # Ilimitado

            # Preparar quota_info para o request state (sem depender de refresh)
            quota_info = {
                'has_quota': quota_remaining is None or quota_remaining > 0,
                'monthly_quota': monthly_quota,
                'requests_this_month': requests_after_increment,
                'quota_remaining': quota_remaining,
                'quota_percentage_used': (requests_after_increment / monthly_quota * 100) if monthly_quota else None,
                'total_requests': current_total_requests + 1,
            }

            # Adicionar informações ao request state (para uso nos endpoints)
            # Não podemos passar api_key_locked porque está detached da sessão
            request.state.quota_info = quota_info

        except Exception as e:
            raise  # Re-raise para não silenciar o erro

        finally:
            # Sempre fechar a sessão (executa sempre, mesmo com exception)
            await db.close()

        # Processar request
        response = await call_next(request)

        # Adicionar headers de quota na resposta
        if monthly_quota is not None:
            response.headers['X-RateLimit-Limit'] = str(monthly_quota)
            response.headers['X-RateLimit-Remaining'] = str(quota_remaining)
            response.headers['X-RateLimit-Reset'] = str(last_reset_timestamp)

        return response
