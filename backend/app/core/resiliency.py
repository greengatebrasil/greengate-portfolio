"""
GreenGate - Resiliência e Retry

Decorator para retry inteligente em operações de banco de dados.
- Retry apenas em erros de conexão (NÃO em timeouts ou erros de integridade)
- Observability via structlog com request_id
"""
import functools
from typing import Callable, TypeVar, ParamSpec

import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
    RetryCallState,
)
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    OperationalError,
)

from app.core.logging_config import get_logger

log = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


# =============================================================================
# RETRY PREDICATES
# =============================================================================

def is_retryable_db_error(exception: BaseException) -> bool:
    """
    Determina se o erro de banco é retentável.
    
    RETRY:
    - DBAPIError com connection_invalidated=True
    - ConnectionRefusedError
    
    NÃO RETRY:
    - Timeouts (QueryCanceledError)
    - IntegrityError
    - Outros erros de SQL
    """
    # Nunca retry em erros de integridade
    if isinstance(exception, IntegrityError):
        return False
    
    # ConnectionRefusedError - banco não disponível, retry
    if isinstance(exception, ConnectionRefusedError):
        return True
    
    # DBAPIError com conexão invalidada - retry
    if isinstance(exception, DBAPIError):
        if exception.connection_invalidated:
            return True
        
        # Verificar mensagem para timeouts (NÃO retry)
        error_msg = str(exception).lower()
        if "timeout" in error_msg or "canceling statement" in error_msg:
            return False
        
        # Conexão perdida - retry
        connection_lost_keywords = [
            "connection reset",
            "connection refused", 
            "connection closed",
            "server closed",
            "broken pipe",
        ]
        if any(kw in error_msg for kw in connection_lost_keywords):
            return True
    
    # Padrão: não retry
    return False


# =============================================================================
# OBSERVABILITY - BEFORE SLEEP CALLBACK
# =============================================================================

def log_retry_attempt(retry_state: RetryCallState) -> None:
    """
    Callback chamado ANTES de cada retry (after sleep).
    Loga com structlog incluindo attempt_number e request_id (se disponível).
    """
    # Tentar obter request_id do contexto structlog
    try:
        # structlog.contextvars mantém o request_id bindado pelo middleware
        context = structlog.contextvars.get_contextvars()
        request_id = context.get("request_id", "unknown")
    except Exception:
        request_id = "unknown"
    
    # Informações do retry
    attempt = retry_state.attempt_number
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    error_msg = str(exception)[:100] if exception else "unknown"
    
    # Tempo até o próximo retry
    wait_time = retry_state.next_action.sleep if retry_state.next_action else 0
    
    log.warning(
        "db_query_retry",
        message="Database query failed, retrying...",
        attempt_number=attempt,
        request_id=request_id,
        error=error_msg,
        error_type=type(exception).__name__ if exception else "unknown",
        wait_seconds=round(wait_time, 2),
    )


# =============================================================================
# RETRY DECORATOR
# =============================================================================

def db_query_retry(
    max_attempts: int = 3,
    min_wait: float = 0.1,
    max_wait: float = 1.0,
):
    """
    Decorator para retry em queries de banco de dados.
    
    Args:
        max_attempts: Número máximo de tentativas (default: 3)
        min_wait: Tempo mínimo de espera entre tentativas (default: 0.1s)
        max_wait: Tempo máximo de espera entre tentativas (default: 1.0s)
    
    Usage:
        @db_query_retry()
        async def fetch_data(db: AsyncSession):
            result = await db.execute(query)
            return result.fetchall()
    
    Retry Policy:
        - RETRY: DBAPIError (connection_invalidated), ConnectionRefusedError
        - NO RETRY: Timeouts, IntegrityErrors, SQL errors
        - Backoff: Exponencial (0.1s -> 0.2s -> 0.4s... até 1.0s)
    
    Observability:
        - Loga warning antes de cada retry com request_id e attempt_number
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @retry(
            retry=retry_if_exception(is_retryable_db_error),
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=min_wait, max=max_wait),
            before_sleep=log_retry_attempt,
            reraise=True,
        )
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


# =============================================================================
# EXEMPLO DE USO
# =============================================================================

# from app.core.resiliency import db_query_retry
#
# class MyService:
#     def __init__(self, db: AsyncSession):
#         self.db = db
#     
#     @db_query_retry()
#     async def get_user(self, user_id: int):
#         result = await self.db.execute(
#             select(User).where(User.id == user_id)
#         )
#         return result.scalar_one_or_none()
