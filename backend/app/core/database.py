"""
GreenGate - Database Connection

Configuração resiliente com:
- Connection pooling otimizado (configurável via env)
- Timeouts no nível do driver asyncpg
- Health checks de conexão (pool_pre_ping)
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging_config import get_logger

log = get_logger(__name__)


# =============================================================================
# ENGINE CONFIGURATION
# =============================================================================

# Configurações de timeout para asyncpg (driver-level)
ASYNCPG_CONNECT_ARGS = {
    # Timeout para comandos individuais (segundos)
    "command_timeout": settings.DB_COMMAND_TIMEOUT,
    # Timeout para statements no PostgreSQL (milissegundos)
    "server_settings": {
        "statement_timeout": str(settings.DB_COMMAND_TIMEOUT * 1000),  # Converter para ms
    },
}

# Engine assíncrono com pooling resiliente
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    
    # Pool Configuration (carregado de settings)
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    
    # CRÍTICO: Verifica conexão antes de usar (detecta conexões mortas)
    pool_pre_ping=True,
    
    # Timeouts do driver asyncpg
    connect_args=ASYNCPG_CONNECT_ARGS,
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency que fornece uma sessão de banco de dados.
    
    Uso com FastAPI:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            log.warning("db_session_rollback", error=str(e))
            raise
        finally:
            await session.close()


# =============================================================================
# HEALTH CHECK
# =============================================================================

async def check_db_health() -> dict:
    """
    Verifica saúde do banco de dados.
    Retorna status e métricas do pool.
    """
    from sqlalchemy import text
    
    try:
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()
        
        # Métricas do pool
        pool = engine.pool
        return {
            "status": "healthy",
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
    except Exception as e:
        log.error("db_health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
        }


# =============================================================================
# INITIALIZATION
# =============================================================================

async def init_db():
    """
    Inicializa o banco de dados.
    Em produção, usar Alembic para migrations.
    """
    from sqlalchemy import text
    from app.models.database import Base
    
    async with engine.begin() as conn:
        # Criar extensão PostGIS se não existir
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))
        
        # Criar tabelas
        await conn.run_sync(Base.metadata.create_all)
    
    log.info("db_initialized")
