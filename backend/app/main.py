"""
GreenGate Geo-Compliance API

Aplicação principal FastAPI.
"""
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import json

from app.core.config import settings
from app.core.logging_config import setup_logging, get_logger
from app.core.rate_limit import RateLimitMiddleware, get_rate_limit_stats
from app.middleware.logger import RequestLoggingMiddleware
from app.middleware.limits import LimitUploadSizeMiddleware
from app.middleware.api_key_tracker import APIKeyTrackerMiddleware


# Inicializar logging estruturado ANTES de qualquer outra coisa
setup_logging()

# Logger para este módulo
log = get_logger(__name__)


# Custom JSON Response com UTF-8 garantido
class UTF8JSONResponse(JSONResponse):
    """JSONResponse que garante encoding UTF-8."""
    media_type = "application/json; charset=utf-8"
    
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,  # Permite caracteres UTF-8
            separators=(",", ":"),
        ).encode("utf-8")


# =============================================================================
# LIFESPAN (startup/shutdown)
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia ciclo de vida da aplicação."""
    # Startup
    log.info(
        "app_starting",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
    )
    
    yield
    
    # Shutdown
    log.info("app_stopping")


# =============================================================================
# APP INSTANCE
# =============================================================================

def create_app() -> FastAPI:
    """Factory para criar a aplicação FastAPI."""

    # Validações de segurança no startup
    if settings.SECRET_KEY == "CHANGE-THIS-IN-PRODUCTION-USE-OPENSSL-RAND-HEX-32":
        if not settings.DEBUG:
            raise RuntimeError(
                "SECRET_KEY não configurada! "
                "Gere uma chave segura com: openssl rand -hex 32 "
                "e configure a variável de ambiente SECRET_KEY"
            )
        else:
            log.warning(
                "security.secret_key_not_configured",
                message="SECRET_KEY usando valor padrão - OK em desenvolvimento, INSEGURO em produção!"
            )

    app = FastAPI(
        title=settings.APP_NAME,
        description="""
        ## API de Validação Geoespacial para Conformidade EUDR
        
        GreenGate valida automaticamente se áreas de produção agrícola estão 
        em conformidade com a regulamentação europeia anti-desmatamento (EUDR).
        
        ### Funcionalidades
        
        - **Validação Rápida**: Valide um polígono instantaneamente
        - **Gestão de Talhões**: Cadastre e gerencie talhões de produção
        - **Score de Risco**: Obtenha um score de 0-100 baseado em múltiplas verificações
        - **Relatórios**: Gere dossiês de conformidade para exportação
        
        ### Verificações Realizadas
        
        - Desmatamento PRODES (Amazônia)
        - Alertas MapBiomas
        - Terras Indígenas (FUNAI)
        - Territórios Quilombolas (INCRA)
        - Unidades de Conservação (MMA)
        - Embargos IBAMA
        - APPs (proximidade de água)
        """,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,  # UTF-8 garantido
    )
    
    # CORS
    # Configurável via ALLOWED_ORIGINS env var
    # Exemplo: ALLOWED_ORIGINS="https://greengate.com.br,https://www.greengate.com.br"
    # IMPORTANTE: Em produção, configure ALLOWED_ORIGINS com origens específicas!
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "x-api-key", "Accept"],
    )

    # Security Headers Middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # XSS Protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions policy
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response
    
    # Request Logging Middleware (gera request_id, loga requests)
    app.add_middleware(RequestLoggingMiddleware)

    # API Key Tracker Middleware (valida API key e rastreia uso)
    # IMPORTANTE: Validar API key antes de processar request
    app.add_middleware(APIKeyTrackerMiddleware)

    # Rate Limit Middleware (proteção contra abuso)
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(RateLimitMiddleware)

    # Limit Upload Size Middleware (proteção contra payloads grandes)
    # Adicionado por último = executado primeiro
    app.add_middleware(LimitUploadSizeMiddleware)
    
    # Exception handler global
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.error(
            "unhandled_exception",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        # Usar CORS origin das configurações (não wildcard)
        cors_origin = settings.cors_origins[0] if settings.cors_origins else "*"
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Erro interno do servidor",
                "detail": str(exc) if settings.DEBUG else None,
            },
            headers={
                "Access-Control-Allow-Origin": cors_origin,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )
    
    # Registrar routers
    register_routes(app)
    
    return app


def register_routes(app: FastAPI):
    """Registra todos os routers da API."""
    from app.api import validations
    from app.api import reports
    from app.api import admin_api_keys
    from app.api import auth
    from app.api import metadata
    
    # Endpoint raiz
    @app.get("/", tags=["Sistema"])
    async def root():
        """Informações básicas da API."""
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "online",
            "docs": "/docs",
        }
    
    # Health check básico
    @app.get("/health", tags=["Sistema"])
    async def health_check():
        """Verifica se a API está funcionando."""
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }
    
    # Health check detalhado (verifica dependências)
    @app.get("/health/detailed", tags=["Sistema"])
    async def health_check_detailed():
        """
        Verifica saúde de todas as dependências.
        Inclui métricas do pool de conexões.
        
        Útil para monitoramento e debugging.
        """
        from app.core.database import check_db_health, get_db
        from sqlalchemy import text
        
        health = {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "checks": {}
        }
        
        # Check database com métricas de pool
        db_health = await check_db_health()
        health["checks"]["database"] = db_health
        
        if db_health["status"] != "healthy":
            health["status"] = "degraded"
        
        # Check PostGIS
        try:
            async for db in get_db():
                result = await db.execute(text("SELECT PostGIS_Version()"))
                version = result.scalar()
                health["checks"]["postgis"] = {"status": "up", "version": version}
                break
        except Exception as e:
            health["checks"]["postgis"] = {"status": "down", "error": str(e)}
            health["status"] = "degraded"
        
        # Check reference data
        try:
            async for db in get_db():
                result = await db.execute(text(
                    "SELECT layer_type, COUNT(*) FROM reference_layers GROUP BY layer_type"
                ))
                rows = result.fetchall()
                layer_counts = {row[0]: row[1] for row in rows}
                health["checks"]["reference_data"] = {
                    "status": "up",
                    "layers": layer_counts,
                    "total": sum(layer_counts.values())
                }
                break
        except Exception as e:
            health["checks"]["reference_data"] = {"status": "unknown", "error": str(e)}
        
        # Rate limit stats
        if settings.RATE_LIMIT_ENABLED:
            health["checks"]["rate_limit"] = {
                "enabled": True,
                "limits": {
                    "authenticated": f"{settings.RATE_LIMIT_AUTHENTICATED}/min",
                    "anonymous": f"{settings.RATE_LIMIT_ANONYMOUS}/min",
                },
                **get_rate_limit_stats(),
            }
        
        return health
    
    # Endpoint de métricas simples
    @app.get("/metrics", tags=["Sistema"])
    async def metrics():
        """
        Métricas básicas da aplicação.
        
        Para integração com Prometheus/Grafana, usar bibliotecas dedicadas.
        """
        import os
        import psutil
        
        process = psutil.Process(os.getpid())
        
        return {
            "memory_mb": process.memory_info().rss / 1024 / 1024,
            "cpu_percent": process.cpu_percent(),
            "threads": process.num_threads(),
            "uptime_seconds": time.time() - process.create_time(),
        }
    
    # =========================================================================
    # API ROUTES
    # =========================================================================
    
    # Validações (protegido)
    app.include_router(
        validations.router,
        prefix=settings.API_PREFIX,
    )
    
    # Relatórios - router protegido (geração de PDF)
    app.include_router(
        reports.router,
        prefix=settings.API_PREFIX,
    )
    
    # Relatórios - router PÚBLICO (verificação de QR Code)
    app.include_router(
        reports.public_router,
        prefix=settings.API_PREFIX,
    )

    # Autenticação - Login admin
    app.include_router(
        auth.router,
        prefix=settings.API_PREFIX,
    )

    # Admin - API Keys (gerenciamento de API keys)
    # ✅ HABILITADO COM PROTEÇÃO JWT
    app.include_router(
        admin_api_keys.router,
        prefix=settings.API_PREFIX,
    )

    # Metadata - Endpoint PÚBLICO (datas de atualização dos dados)
    app.include_router(
        metadata.router,
        prefix=settings.API_PREFIX,
    )


# =============================================================================
# APP INSTANCE
# =============================================================================

app = create_app()


# =============================================================================
# MAIN (para desenvolvimento)
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
