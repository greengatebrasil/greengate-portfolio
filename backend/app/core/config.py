"""
GreenGate - Configuração Central
"""
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    """Configurações do aplicativo - carregadas de variáveis de ambiente"""
    
    # App
    APP_NAME: str = "GreenGate Geo-Compliance"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # API
    API_PREFIX: str = "/api/v1"

    # CORS - Origens permitidas (separadas por vírgula)
    # Exemplo: "https://greengate.com.br,https://www.greengate.com.br"
    # Em desenvolvimento: "*" (permitir todas)
    ALLOWED_ORIGINS: str = "*"

    # API Key (simples, sem JWT por enquanto)
    API_KEY: Optional[str] = None  # Se None, não exige autenticação
    API_KEY_HEADER: str = "x-api-key"
    
    # Database
    # Railway fornece postgres://, precisamos converter para postgresql+asyncpg://
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/greengate"
    
    @field_validator('DATABASE_URL', mode='before')
    @classmethod
    def convert_database_url(cls, v: str) -> str:
        """Converte URL do Railway (postgres://) para asyncpg."""
        if v:
            # Railway/Heroku usam postgres://, SQLAlchemy asyncpg precisa postgresql+asyncpg://
            if v.startswith('postgres://'):
                v = v.replace('postgres://', 'postgresql+asyncpg://', 1)
            elif v.startswith('postgresql://') and '+asyncpg' not in v:
                v = v.replace('postgresql://', 'postgresql+asyncpg://', 1)
        return v
    
    # Database Pool (configuráveis via env)
    DB_POOL_SIZE: int = 10          # Conexões mantidas no pool
    DB_MAX_OVERFLOW: int = 5        # Conexões extras temporárias
    DB_POOL_TIMEOUT: int = 10       # Timeout para obter conexão do pool (segundos)
    DB_POOL_RECYCLE: int = 1800     # Reciclar conexões após N segundos (30 min)
    DB_COMMAND_TIMEOUT: int = 10    # Timeout para comandos SQL (segundos)
    
    # Payload & Geometry Limits
    MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024  # 5 MB
    MAX_GEOM_VERTICES: int = 10_000         # Máximo de vértices por geometria
    MAX_AREA_HA: float = 10_000.0           # Área máxima em hectares
    
    # Bounding Box do Brasil (rejeitar geometrias fora)
    BRAZIL_BBOX_MIN_LON: float = -73.99  # Oeste
    BRAZIL_BBOX_MAX_LON: float = -34.79  # Leste
    BRAZIL_BBOX_MIN_LAT: float = -33.75  # Sul
    BRAZIL_BBOX_MAX_LAT: float = 5.27    # Norte
    
    # Aliases para compatibilidade
    @property
    def DATABASE_POOL_SIZE(self) -> int:
        return self.DB_POOL_SIZE
    
    @property
    def DATABASE_MAX_OVERFLOW(self) -> int:
        return self.DB_MAX_OVERFLOW

    @property
    def cors_origins(self) -> list[str]:
        """Retorna lista de origens CORS permitidas."""
        if self.ALLOWED_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    # Auth (para JWT futuro)
    SECRET_KEY: str = "CHANGE-THIS-IN-PRODUCTION-USE-OPENSSL-RAND-HEX-32"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    ALGORITHM: str = "HS256"

    # Admin Authentication
    # Para gerar hash bcrypt: python -c "import bcrypt; print(bcrypt.hashpw(b'sua_senha', bcrypt.gensalt()).decode())"
    # IMPORTANTE: Configure via variável de ambiente em produção!
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD_HASH: str = "CONFIGURE_VIA_ENV_VAR"

    # Storage (S3/MinIO)
    STORAGE_BACKEND: str = "local"  # local, s3
    STORAGE_LOCAL_PATH: str = "./data/storage"
    S3_BUCKET: Optional[str] = None
    S3_ENDPOINT: Optional[str] = None
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    
    # External APIs
    MAPBIOMAS_API_URL: str = "https://alerta.mapbiomas.org/api/v1"
    
    # Validation Rules
    EUDR_CUTOFF_DATE: str = "2020-12-31"  # Data limite EUDR
    DEFAULT_BUFFER_WATER_METERS: int = 30  # APP padrão
    VALIDATION_EXPIRY_DAYS: int = 90  # Validade de uma validação
    
    # Rate Limits
    MAX_PLOTS_FREE_PLAN: int = 5
    MAX_AREA_HA_FREE_PLAN: int = 50
    MAX_VALIDATIONS_PER_HOUR: int = 100
    
    # Redis (para rate limiting e cache)
    REDIS_URL: Optional[str] = None  # Ex: redis://localhost:6379/0

    # Rate Limiting (por minuto)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTHENTICATED: int = 100   # Com API key: 100 req/min
    RATE_LIMIT_ANONYMOUS: int = 20        # Sem API key: 20 req/min
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Retorna instância cacheada das configurações"""
    return Settings()


settings = get_settings()
