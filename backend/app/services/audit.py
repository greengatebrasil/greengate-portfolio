"""
GreenGate - Serviço de Auditoria de Laudos (CAIXA PRETA)

Registra automaticamente cada laudo gerado para:
- Rastreabilidade completa (QUEM, O QUE, QUANDO)
- Verificação de autenticidade (hashes)
- Reprodutibilidade total (geometria completa + versões)
- Compliance EUDR

v7.1: Aceita report_code externo para sincronizar com PDF
"""
import hashlib
import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.database import ValidationReport
from app.models.schemas import GeoValidationResult, GeoJSONPolygon
from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.resiliency import db_query_retry

log = get_logger(__name__)


def generate_report_code() -> str:
    """
    Gera código único para o laudo.
    Formato: GG-YYYYMMDDHHMMSS-XXXX (timestamp + 4 caracteres)
    
    IMPORTANTE: Deve ser o MESMO formato usado pelo pdf_generator!
    """
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(secrets.choice(chars) for _ in range(4))
    return f"GG-{timestamp}-{random_part}"


def hash_geojson(geojson: dict) -> str:
    """Gera SHA256 hash do GeoJSON (normalizado/ordenado)."""
    # Normalizar JSON para hash consistente
    normalized = json.dumps(geojson, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def hash_pdf(pdf_bytes: bytes) -> str:
    """Gera SHA256 hash do PDF."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def hash_api_key(api_key: str) -> str:
    """
    Gera hash da API key para auditoria.
    NÃO armazena a key em si, apenas o hash.
    """
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()


def calculate_bbox(geojson: dict) -> List[float]:
    """
    Calcula bounding box de um GeoJSON Polygon.
    Retorna [minx, miny, maxx, maxy]
    """
    coords = geojson.get("coordinates", [[]])
    if not coords or not coords[0]:
        return None
    
    # Flatten para pegar todos os pontos
    points = coords[0]  # Anel externo
    
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    
    return [min(xs), min(ys), max(xs), max(ys)]


def calculate_centroid(geojson: dict) -> str:
    """
    Calcula centróide aproximado de um GeoJSON Polygon.
    Retorna string "lat, lon"
    """
    coords = geojson.get("coordinates", [[]])
    if not coords or not coords[0]:
        return None
    
    points = coords[0]
    
    avg_x = sum(p[0] for p in points) / len(points)
    avg_y = sum(p[1] for p in points) / len(points)
    
    return f"{avg_y:.6f}, {avg_x:.6f}"  # lat, lon


class AuditService:
    """Serviço para registrar laudos na tabela de auditoria (CAIXA PRETA)."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def record_validation_report(
        self,
        validation_result: GeoValidationResult,
        geometry_geojson: dict,
        pdf_bytes: Optional[bytes] = None,
        plot_info: Optional[Dict[str, Any]] = None,
        property_info: Optional[Dict[str, Any]] = None,
        request_ip: Optional[str] = None,
        api_key: Optional[str] = None,
        user_agent: Optional[str] = None,
        report_code: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> ValidationReport:
        """
        Registra um laudo na tabela de auditoria.
        
        Args:
            validation_result: Resultado da validação
            geometry_geojson: Geometria COMPLETA em GeoJSON
            pdf_bytes: Bytes do PDF gerado (opcional)
            plot_info: Info do talhão (nome, área, cultura)
            property_info: Info da propriedade (nome, estado)
            request_ip: IP do cliente
            api_key: API key usada (será hasheada)
            user_agent: User-Agent do cliente
            report_code: Código do relatório (se já gerado pelo pdf_generator)
            content_hash: Hash do conteúdo (se já calculado)
        
        Returns:
            ValidationReport criado
        """
        # Usar código fornecido ou gerar novo
        if report_code:
            final_report_code = report_code
            log.info("using_provided_report_code", report_code=final_report_code)
        else:
            final_report_code = generate_report_code()
            log.info("generating_new_report_code", report_code=final_report_code)

        # Garantir unicidade do código
        attempts = 0
        while await self._code_exists(final_report_code) and attempts < 10:
            log.warning("report_code_exists_regenerating", report_code=final_report_code)
            final_report_code = generate_report_code()
            attempts += 1
        
        if attempts >= 10:
            raise ValueError("Não foi possível gerar código único após 10 tentativas")
        
        # Extrair status como string
        status_str = (
            validation_result.status.value 
            if hasattr(validation_result.status, 'value') 
            else str(validation_result.status)
        )
        
        # Criar resumo DETALHADO dos checks
        checks_summary = {}
        for check in validation_result.checks:
            check_type = (
                check.check_type.value 
                if hasattr(check.check_type, 'value') 
                else str(check.check_type)
            )
            check_status = (
                check.status.value 
                if hasattr(check.status, 'value') 
                else str(check.status)
            )
            checks_summary[check_type] = {
                "status": check_status,
                "score": check.score,
                "overlap_ha": check.overlap_area_ha,
                "overlap_pct": check.overlap_percentage,
                "message": check.message,
            }
        
        # Extrair info do talhão
        plot_name = None
        crop_type = None
        area_ha = None
        
        if plot_info:
            plot_name = plot_info.get("name") or plot_info.get("plot_name")
            crop_type = plot_info.get("crop_type")
            area_ha = plot_info.get("area_ha")
        
        # Extrair info da propriedade
        property_name = None
        state = None
        municipality = None
        
        if property_info:
            property_name = property_info.get("name") or property_info.get("farm_name")
            state = property_info.get("state")
            municipality = property_info.get("municipality")
        
        # Calcular bbox e centroid
        bbox = calculate_bbox(geometry_geojson)
        centroid = calculate_centroid(geometry_geojson)
        
        # Calcular hash do PDF se fornecido
        pdf_hash_final = content_hash or (hash_pdf(pdf_bytes) if pdf_bytes else None)
        
        # Criar registro
        report = ValidationReport(
            report_code=final_report_code,
            status=status_str,
            risk_score=validation_result.risk_score,
            
            # Geometria COMPLETA
            geometry_geojson=geometry_geojson,
            geometry_hash=hash_geojson(geometry_geojson),
            geometry_area_ha=area_ha,
            geometry_centroid=centroid,
            geometry_bbox=bbox,
            
            # PDF
            pdf_hash=pdf_hash_final,
            pdf_size_bytes=len(pdf_bytes) if pdf_bytes else None,
            pdf_signature=None,  # Futuro
            
            # Versões
            datasets_version=validation_result.reference_data_version or {},
            ruleset_version="v1.0",
            api_version=settings.APP_VERSION,
            
            # Checks detalhados
            checks_summary=checks_summary,
            processing_time_ms=validation_result.processing_time_ms,
            
            # Quem consultou
            request_ip=request_ip,
            api_key_hash=hash_api_key(api_key) if api_key else None,
            user_agent=user_agent,
            
            # Info do talhão
            plot_name=plot_name,
            crop_type=crop_type,
            property_name=property_name,
            state=state,
            
            # Timestamps
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.VALIDATION_EXPIRY_DAYS),
        )
        
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        
        log.info("report_registered_successfully", report_code=report.report_code)
        
        return report
    
    async def _code_exists(self, code: str) -> bool:
        """Verifica se o código já existe."""
        result = await self.db.execute(
            select(ValidationReport.id).where(ValidationReport.report_code == code)
        )
        return result.scalar_one_or_none() is not None
    
    async def get_report_by_code(self, code: str) -> Optional[ValidationReport]:
        """Busca laudo pelo código."""
        log.info("searching_report", code=code)
        result = await self.db.execute(
            select(ValidationReport).where(ValidationReport.report_code == code)
        )
        report = result.scalar_one_or_none()
        if report:
            log.info("report_found", report_code=report.report_code)
        else:
            log.warning("report_not_found", code=code)
        return report
    
    async def verify_report(self, code: str, geometry_geojson: dict) -> Dict[str, Any]:
        """
        Verifica autenticidade de um laudo.
        
        Compara o hash da geometria fornecida com o hash armazenado.
        """
        report = await self.get_report_by_code(code)
        
        if not report:
            return {
                "valid": False,
                "error": "Laudo não encontrado",
            }
        
        # Verificar se expirou
        if report.expires_at and datetime.now(timezone.utc) > report.expires_at:
            return {
                "valid": False,
                "error": "Laudo expirado",
                "expired_at": report.expires_at.isoformat(),
            }
        
        # Verificar hash da geometria
        provided_hash = hash_geojson(geometry_geojson)
        
        if provided_hash != report.geometry_hash:
            return {
                "valid": False,
                "error": "Geometria não corresponde ao laudo",
            }
        
        return {
            "valid": True,
            "report_code": report.report_code,
            "status": report.status,
            "risk_score": report.risk_score,
            "created_at": report.created_at.isoformat(),
            "expires_at": report.expires_at.isoformat() if report.expires_at else None,
        }
    
    async def reproduce_validation(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Retorna todos os dados necessários para reproduzir uma validação.
        
        Útil para auditoria e debug.
        """
        report = await self.get_report_by_code(code)
        
        if not report:
            return None
        
        return {
            "report_code": report.report_code,
            "geometry_geojson": report.geometry_geojson,
            "geometry_bbox": report.geometry_bbox,
            "datasets_version": report.datasets_version,
            "ruleset_version": report.ruleset_version,
            "api_version": report.api_version,
            "checks_summary": report.checks_summary,
            "created_at": report.created_at.isoformat(),
        }
