"""
GreenGate - Schemas Pydantic (Validação e Serialização)
"""
from datetime import datetime
from typing import Optional, List, Any, Dict, Tuple
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, EmailStr, field_validator


# =============================================================================
# ENUMS
# =============================================================================

class PlanType(str, Enum):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class ComplianceStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WARNING = "warning"


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIP = "skip"


class CheckType(str, Enum):
    DEFORESTATION_PRODES = "deforestation_prodes"
    DEFORESTATION_MAPBIOMAS = "deforestation_mapbiomas"
    TERRA_INDIGENA = "terra_indigena"
    QUILOMBOLA = "quilombola"
    UNIDADE_CONSERVACAO = "uc"
    EMBARGO_IBAMA = "embargo_ibama"
    APP_WATER = "app_water"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# =============================================================================
# GEOJSON SCHEMAS
# =============================================================================

class GeoJSONPoint(BaseModel):
    type: str = "Point"
    coordinates: List[float]  # [longitude, latitude]


# =============================================================================
# CONSTANTES / LIMITES (com override via settings)
# =============================================================================

def _get_limits() -> Dict[str, Any]:
    """
    Carrega limites de settings (lazy load para evitar circular import).
    Se falhar, retorna valores default.
    """
    try:
        from app.core.config import settings
        return {
            "max_area_ha": settings.MAX_AREA_HA,
            "max_vertices": settings.MAX_GEOM_VERTICES,
            "brazil_bbox": (
                settings.BRAZIL_BBOX_MIN_LON,
                settings.BRAZIL_BBOX_MIN_LAT,
                settings.BRAZIL_BBOX_MAX_LON,
                settings.BRAZIL_BBOX_MAX_LAT,
            ),
        }
    except Exception:
        return {
            "max_area_ha": 10000,
            "max_vertices": 10000,
            "brazil_bbox": (-73.99, -33.75, -34.79, 5.27),
        }


POLYGON_MIN_VERTICES = 4  # Mínimo para polígono válido


def _count_vertices(coordinates: List, is_multi: bool = False) -> int:
    """Conta total de vértices em uma geometria (Polygon ou MultiPolygon)."""
    total = 0
    if is_multi:
        for polygon in coordinates:
            for ring in polygon:
                total += len(ring)
    else:
        for ring in coordinates:
            total += len(ring)
    return total


def _check_bbox_brazil(coordinates: List, is_multi: bool = False) -> bool:
    """Verifica se todas as coordenadas estão dentro do Brasil (bbox)."""
    limits = _get_limits()
    min_lon, min_lat, max_lon, max_lat = limits["brazil_bbox"]

    def check_ring(ring):
        for coord in ring:
            lon, lat = coord[0], coord[1]
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                return False
        return True

    if is_multi:
        for polygon in coordinates:
            for ring in polygon:
                if not check_ring(ring):
                    return False
    else:
        for ring in coordinates:
            if not check_ring(ring):
                return False
    return True


class GeoJSONPolygon(BaseModel):
    """
    GeoJSON Polygon com validações robustas para produção.

    Limites (settings):
    - Área máxima: settings.MAX_AREA_HA
    - Vértices máximos: settings.MAX_GEOM_VERTICES
    - Coordenadas: válidas e dentro do Brasil (bbox)
    """
    type: str = "Polygon"
    coordinates: List[List[List[float]]]  # [[[lon, lat], [lon, lat], ...]]

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v != "Polygon":
            raise ValueError(f"Tipo deve ser 'Polygon', recebido: '{v}'")
        return v

    @field_validator("coordinates")
    @classmethod
    def validate_polygon(cls, v):
        limits = _get_limits()
        max_area_ha = limits["max_area_ha"]
        max_vertices = limits["max_vertices"]

        # 1. Estrutura básica
        if not v or not v[0]:
            raise ValueError("Polígono deve ter pelo menos um anel de coordenadas")

        ring = v[0]
        num_vertices = len(ring)

        # 2. Número mínimo de pontos
        if num_vertices < POLYGON_MIN_VERTICES:
            raise ValueError(
                f"Polígono deve ter pelo menos {POLYGON_MIN_VERTICES} pontos, recebido: {num_vertices}"
            )

        # 3. Número máximo de pontos (proteção contra DoS)
        total_vertices = _count_vertices(v, is_multi=False)
        if total_vertices > max_vertices:
            raise ValueError(
                f"Polígono excede limite de {max_vertices} vértices (recebido: {total_vertices}). "
                "Simplifique a geometria."
            )

        # 4. Polígono fechado
        if ring[0] != ring[-1]:
            raise ValueError("Polígono deve ser fechado (primeiro ponto = último ponto)")

        # 5. Validar cada coordenada
        for i, coord in enumerate(ring):
            if len(coord) < 2:
                raise ValueError(f"Coordenada {i} inválida: deve ter [lon, lat]")

            lon, lat = coord[0], coord[1]

            if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
                raise ValueError(f"Coordenada {i}: lon/lat devem ser números")

            if not (-180 <= lon <= 180):
                raise ValueError(f"Coordenada {i}: longitude {lon} inválida (entre -180 e 180)")
            if not (-90 <= lat <= 90):
                raise ValueError(f"Coordenada {i}: latitude {lat} inválida (entre -90 e 90)")

        # 6. Verificar bbox Brasil
        if not _check_bbox_brazil(v, is_multi=False):
            raise ValueError(
                "Geometria fora da área de cobertura (Brasil). Verifique se as coordenadas estão corretas."
            )

        # 7. Validar geometria com Shapely + área geodésica
        try:
            from shapely.geometry import shape
            from shapely.validation import explain_validity

            geom = shape({"type": "Polygon", "coordinates": v})

            if not geom.is_valid:
                raise ValueError(f"Geometria inválida: {explain_validity(geom)}")

            # Área geodésica (WGS84) se pyproj existir; fallback com correção latitude
            try:
                from pyproj import Geod
                geod = Geod(ellps="WGS84")
                area_m2, _ = geod.geometry_area_perimeter(geom)
                area_ha = abs(area_m2) / 10000
            except Exception:
                import math
                centroid = geom.centroid
                lat_rad = math.radians(centroid.y)
                m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad)
                m_per_deg_lon = 111412.84 * math.cos(lat_rad)
                area_ha = abs(geom.area * m_per_deg_lat * m_per_deg_lon) / 10000

            if area_ha > max_area_ha:
                raise ValueError(
                    f"Área do polígono (~{area_ha:,.0f} ha) excede limite de {max_area_ha:,} ha. "
                    "Divida em talhões menores."
                )

        except ImportError:
            # Shapely não disponível - validação básica apenas
            pass

        return v

    def to_wkt(self) -> str:
        """Converte para WKT (Well-Known Text)."""
        from shapely.geometry import shape
        return shape(self.model_dump()).wkt

    def get_area_ha(self) -> float:
        """
        Retorna área em hectares usando cálculo geodésico (WGS84).
        """
        from shapely.geometry import shape

        geom = shape(self.model_dump())

        try:
            from pyproj import Geod
            geod = Geod(ellps="WGS84")
            area_m2, _ = geod.geometry_area_perimeter(geom)
            return abs(area_m2) / 10000
        except Exception:
            import math
            centroid = geom.centroid
            lat_rad = math.radians(centroid.y)
            m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad)
            m_per_deg_lon = 111412.84 * math.cos(lat_rad)
            return abs(geom.area * m_per_deg_lat * m_per_deg_lon) / 10000

    def get_centroid(self) -> Tuple[float, float]:
        """Retorna centróide (lon, lat)."""
        from shapely.geometry import shape
        geom = shape(self.model_dump())
        return (geom.centroid.x, geom.centroid.y)


class GeoJSONMultiPolygon(BaseModel):
    """
    GeoJSON MultiPolygon com validações robustas.

    Para propriedades com múltiplos talhões não contíguos.
    """
    type: str = "MultiPolygon"
    coordinates: List[List[List[List[float]]]]  # [[[[lon, lat], ...]]]

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v != "MultiPolygon":
            raise ValueError(f"Tipo deve ser 'MultiPolygon', recebido: '{v}'")
        return v

    @field_validator("coordinates")
    @classmethod
    def validate_multipolygon(cls, v):
        limits = _get_limits()
        max_area_ha = limits["max_area_ha"]
        max_vertices = limits["max_vertices"]

        if not v:
            raise ValueError("MultiPolygon deve ter pelo menos um polígono")

        total_vertices = _count_vertices(v, is_multi=True)
        if total_vertices > max_vertices:
            raise ValueError(
                f"MultiPolygon excede limite de {max_vertices} vértices (recebido: {total_vertices}). "
                "Simplifique a geometria."
            )

        if not _check_bbox_brazil(v, is_multi=True):
            raise ValueError(
                "Geometria fora da área de cobertura (Brasil). Verifique se as coordenadas estão corretas."
            )

        try:
            from shapely.geometry import shape
            from shapely.validation import explain_validity

            geom = shape({"type": "MultiPolygon", "coordinates": v})

            if not geom.is_valid:
                raise ValueError(f"Geometria inválida: {explain_validity(geom)}")

            try:
                from pyproj import Geod
                geod = Geod(ellps="WGS84")
                area_m2, _ = geod.geometry_area_perimeter(geom)
                area_ha = abs(area_m2) / 10000
            except Exception:
                import math
                centroid = geom.centroid
                lat_rad = math.radians(centroid.y)
                m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad)
                m_per_deg_lon = 111412.84 * math.cos(lat_rad)
                area_ha = abs(geom.area * m_per_deg_lat * m_per_deg_lon) / 10000

            if area_ha > max_area_ha:
                raise ValueError(
                    f"Área total (~{area_ha:,.0f} ha) excede limite de {max_area_ha:,} ha."
                )

        except ImportError:
            pass

        return v

    def to_wkt(self) -> str:
        """Converte para WKT."""
        from shapely.geometry import shape
        return shape(self.model_dump()).wkt

    def get_area_ha(self) -> float:
        """Retorna área em hectares usando cálculo geodésico."""
        from shapely.geometry import shape

        geom = shape(self.model_dump())

        try:
            from pyproj import Geod
            geod = Geod(ellps="WGS84")
            area_m2, _ = geod.geometry_area_perimeter(geom)
            return abs(area_m2) / 10000
        except Exception:
            import math
            centroid = geom.centroid
            lat_rad = math.radians(centroid.y)
            m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad)
            m_per_deg_lon = 111412.84 * math.cos(lat_rad)
            return abs(geom.area * m_per_deg_lat * m_per_deg_lon) / 10000


class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    geometry: GeoJSONPolygon
    properties: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# ORGANIZATION SCHEMAS
# =============================================================================

class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    document: Optional[str] = Field(None, max_length=20)  # CNPJ


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationResponse(OrganizationBase):
    id: UUID
    plan: PlanType
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# USER SCHEMAS
# =============================================================================

class UserBase(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=255)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    organization_id: Optional[UUID] = None


class UserResponse(UserBase):
    id: UUID
    organization_id: Optional[UUID]
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# =============================================================================
# PROPERTY SCHEMAS
# =============================================================================

class PropertyBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    car_code: Optional[str] = Field(None, max_length=50)
    state: str = Field(..., min_length=2, max_length=2)
    city: Optional[str] = Field(None, max_length=255)


class PropertyCreate(PropertyBase):
    geom: Optional[GeoJSONPolygon] = None


class PropertyResponse(PropertyBase):
    id: UUID
    organization_id: UUID
    area_ha: Optional[float]
    is_active: bool
    created_at: datetime

    total_plots: Optional[int] = 0
    approved_plots: Optional[int] = 0
    pending_plots: Optional[int] = 0

    class Config:
        from_attributes = True


# =============================================================================
# PLOT SCHEMAS
# =============================================================================

class PlotBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: Optional[str] = Field(None, max_length=50)
    crop_type: Optional[str] = Field(None, max_length=100)
    planting_year: Optional[int] = Field(None, ge=1900, le=2100)


class PlotCreate(PlotBase):
    property_id: UUID
    geom: GeoJSONPolygon


class PlotResponse(PlotBase):
    id: UUID
    property_id: UUID
    area_ha: float
    centroid: Optional[GeoJSONPoint] = None

    compliance_status: ComplianceStatus
    risk_score: Optional[int]
    last_validation_at: Optional[datetime]

    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PlotDetail(PlotResponse):
    last_validation: Optional["ValidationResponse"] = None
    property_name: Optional[str] = None


# =============================================================================
# VALIDATION SCHEMAS
# =============================================================================

class ValidationCheckResponse(BaseModel):
    id: UUID
    check_type: CheckType
    status: CheckStatus
    score: Optional[int]
    message: Optional[str]
    details: Dict[str, Any] = Field(default_factory=dict)
    last_updated: Optional[datetime] = Field(
        None,
        description="Data da última atualização da camada de dados usada nesta verificação"
    )

    class Config:
        from_attributes = True


class ValidationResponse(BaseModel):
    id: UUID
    plot_id: UUID
    status: ComplianceStatus
    risk_score: int
    validated_at: datetime
    expires_at: Optional[datetime]

    checks: List[ValidationCheckResponse] = Field(default_factory=list)
    data_freshness: Optional[Dict[str, datetime]] = Field(
        None,
        description="Datas de última atualização de cada camada de dados"
    )

    class Config:
        from_attributes = True


class ValidationRequest(BaseModel):
    plot_id: UUID
    force: bool = False


class ValidationBatchRequest(BaseModel):
    plot_ids: List[UUID] = Field(..., max_length=100)
    force: bool = False


class ValidationSummary(BaseModel):
    id: UUID
    plot_id: UUID
    plot_name: str
    property_name: str
    status: ComplianceStatus
    risk_score: int
    validated_at: datetime


class BatchErrorDetail(BaseModel):
    """Detalhes de erro em validação batch"""
    plot_id: UUID
    error: str
    error_type: str  # "not_found", "validation_error", "internal_error"


class BatchValidationResponse(BaseModel):
    """Resposta de validação em lote com sucessos e falhas"""
    success_count: int
    failed_count: int
    total: int
    validations: List[ValidationSummary]
    errors: List[BatchErrorDetail]


# =============================================================================
# VALIDATION ENGINE - Internal Schemas
# =============================================================================

class GeoCheckResult(BaseModel):
    """Resultado de uma verificação geoespacial individual"""
    check_type: CheckType
    status: CheckStatus
    score: int = Field(..., ge=0, le=100)
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)

    overlap_area_ha: Optional[float] = None
    overlap_percentage: Optional[float] = None
    overlapping_features: List[Dict[str, Any]] = Field(default_factory=list)

    # Geometrias de interseção em GeoJSON - para visualização no mapa
    intersection_geometries: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de geometrias GeoJSON mostrando exatamente onde cada sobreposição ocorre"
    )

    # Data de última atualização da camada de dados (populado pelo endpoint)
    last_updated: Optional[datetime] = Field(
        None,
        description="Data da última atualização da camada de dados consultada"
    )


class GeoValidationResult(BaseModel):
    """Resultado completo de uma validação geoespacial"""
    plot_id: UUID
    status: ComplianceStatus
    risk_score: int = Field(..., ge=0, le=100)

    checks: List[GeoCheckResult]

    validated_at: datetime
    reference_data_version: Dict[str, Any] = Field(default_factory=dict)
    processing_time_ms: int

    # Data freshness - datas de última atualização de cada layer
    data_freshness: Optional[Dict[str, datetime]] = None

    def has_blocking_issues(self) -> bool:
        return any(c.status == CheckStatus.FAIL for c in self.checks)


# =============================================================================
# REPORT SCHEMAS
# =============================================================================

class ReportRequest(BaseModel):
    plot_id: Optional[UUID] = None
    property_id: Optional[UUID] = None
    validation_id: Optional[UUID] = None
    report_type: str = "compliance_single"
    format: str = "pdf"


class ReportResponse(BaseModel):
    id: UUID
    report_type: str
    format: str
    title: Optional[str]
    file_path: Optional[str]
    file_hash: Optional[str]
    generated_at: datetime
    download_url: Optional[str] = None

    class Config:
        from_attributes = True


# =============================================================================
# DASHBOARD / STATS SCHEMAS
# =============================================================================

class DashboardStats(BaseModel):
    total_properties: int
    total_plots: int
    total_area_ha: float

    plots_by_status: Dict[str, int]
    recent_validations: List[ValidationSummary]
    pending_alerts: int
    avg_risk_score: Optional[float]


# =============================================================================
# API RESPONSE WRAPPERS
# =============================================================================

class APIResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    message: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    pages: int


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


PlotDetail.model_rebuild()
