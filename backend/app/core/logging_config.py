"""
GreenGate - Configuração de Logging Estruturado

Usa structlog para logs JSON em produção e console colorido em dev.
Suporta correlation via request_id e contexto de negócio.
"""
import logging
import sys
import re
from typing import Any, Dict

import structlog
from structlog.types import Processor

from app.core.config import settings


# =============================================================================
# PROCESSADORES CUSTOMIZADOS
# =============================================================================

# Padrões para mascarar dados sensíveis
SENSITIVE_PATTERNS = [
    (re.compile(r'(api[_-]?key)["\s:=]+["\']?([a-zA-Z0-9\-_]{8,})["\']?', re.I), r'\1=***MASKED***'),
    (re.compile(r'(password|passwd|pwd|secret|token)["\s:=]+["\']?([^\s"\']+)["\']?', re.I), r'\1=***MASKED***'),
    (re.compile(r'(authorization)["\s:=]+["\']?(bearer\s+)?([a-zA-Z0-9\-_.]+)["\']?', re.I), r'\1=***MASKED***'),
]


def mask_sensitive_data(logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mascara dados sensíveis nos logs.
    Processa strings e valores que podem conter secrets.
    """
    def mask_value(value: Any) -> Any:
        if isinstance(value, str):
            result = value
            for pattern, replacement in SENSITIVE_PATTERNS:
                result = pattern.sub(replacement, result)
            return result
        elif isinstance(value, dict):
            return {k: mask_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [mask_value(item) for item in value]
        return value
    
    # Mascarar campos específicos
    sensitive_keys = {'api_key', 'password', 'secret', 'token', 'authorization'}
    
    for key in list(event_dict.keys()):
        if key.lower() in sensitive_keys:
            event_dict[key] = '***MASKED***'
        else:
            event_dict[key] = mask_value(event_dict[key])
    
    return event_dict


def add_app_context(logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adiciona contexto da aplicação aos logs.
    """
    event_dict['app'] = settings.APP_NAME
    event_dict['version'] = settings.APP_VERSION
    event_dict['environment'] = 'development' if settings.DEBUG else 'production'
    return event_dict


def order_keys(logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ordena as chaves do log para consistência.
    Coloca campos importantes primeiro.
    """
    priority_keys = [
        'timestamp', 'level', 'event', 'request_id',
        'path', 'method', 'status_code', 'duration_ms',
        'app', 'version', 'environment',
    ]
    
    ordered = {}
    
    # Primeiro, adiciona chaves prioritárias
    for key in priority_keys:
        if key in event_dict:
            ordered[key] = event_dict.pop(key)
    
    # Depois, o resto em ordem alfabética
    for key in sorted(event_dict.keys()):
        ordered[key] = event_dict[key]
    
    return ordered


# =============================================================================
# CONFIGURAÇÃO PRINCIPAL
# =============================================================================

def get_log_level() -> int:
    """Retorna log level baseado no ambiente."""
    if settings.DEBUG:
        return logging.DEBUG
    return logging.INFO


def configure_structlog() -> None:
    """
    Configura structlog para a aplicação.
    
    - Produção: JSON
    - Desenvolvimento: Console colorido
    """
    # Processadores compartilhados
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # Merge context de request_id
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        mask_sensitive_data,
        add_app_context,
    ]
    
    if settings.DEBUG:
        # Desenvolvimento: Console colorido e legível
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            )
        ]
    else:
        # Produção: JSON estruturado
        processors = shared_processors + [
            order_keys,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(get_log_level()),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def configure_uvicorn_logging() -> None:
    """
    Configura loggers do uvicorn para usar o mesmo formato.
    """
    log_level = get_log_level()
    
    # Configurar handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    
    if settings.DEBUG:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    else:
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
        )
    
    handler.setFormatter(formatter)
    
    # Aplicar a uvicorn loggers
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        logger = logging.getLogger(logger_name)
        logger.handlers = [handler]
        logger.setLevel(log_level)
        logger.propagate = False


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """
    Retorna um logger configurado.
    
    Uso:
        from app.core.logging_config import get_logger
        log = get_logger(__name__)
        log.info("evento", campo1="valor1", campo2=123)
    """
    return structlog.get_logger(name)


# =============================================================================
# INICIALIZAÇÃO
# =============================================================================

def setup_logging() -> None:
    """
    Inicializa todo o sistema de logging.
    Deve ser chamado no startup da aplicação.
    """
    configure_structlog()
    configure_uvicorn_logging()
    
    # Log inicial
    log = get_logger("greengate.startup")
    log.info(
        "logging_configured",
        log_level="DEBUG" if settings.DEBUG else "INFO",
        format="console" if settings.DEBUG else "json",
    )
