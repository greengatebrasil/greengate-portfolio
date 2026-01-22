"""
GreenGate - API de Relatórios v7.1

Endpoints para geração de relatórios de diligência prévia em PDF.
Suporte a idiomas (PT/EN), QR Code, Hash SHA-256.

v7.1: Correção para passar geometry ao PDF (mapa funciona)
"""
import os
import hashlib
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from uuid import UUID, uuid4
import io

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Body
from fastapi.responses import StreamingResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.schemas import (
    GeoJSONPolygon,
    GeoValidationResult,
    ReportRequest,
    ReportResponse,
)
from app.services.validation_engine import GeoValidationEngine
from app.services.reports.pdf_generator import DueDiligenceReportGenerator
from app.services.audit import AuditService
from app.core.logging_config import get_logger

log = get_logger(__name__)


# =============================================================================
# ROUTER PROTEGIDO (requer API key via APIKeyTrackerMiddleware)
# =============================================================================
router = APIRouter(
    prefix="/reports",
    tags=["Relatórios"],
)


# =============================================================================
# ROUTER PÚBLICO (sem API key) - Para verificação de laudos
# =============================================================================
public_router = APIRouter(
    prefix="/reports",
    tags=["Verificação Pública"],
)


# =============================================================================
# ENDPOINTS PROTEGIDOS
# =============================================================================

@router.post("/due-diligence/quick")
async def generate_quick_report(
    request: Request,
    body: Dict[str, Any] = Body(...),
    plot_name: str = Query("Talhão Analisado", description="Nome do talhão", max_length=200),
    crop_type: Optional[str] = Query(None, description="Tipo de cultura", max_length=100),
    property_name: Optional[str] = Query(None, description="Nome da propriedade", max_length=200),
    state: Optional[str] = Query(None, description="Estado (UF)", max_length=50),
    lang: str = Query("pt", description="Idioma do relatório (pt ou en)", max_length=5),
    db: AsyncSession = Depends(get_db),
):
    """
    Gera relatório de diligência prévia ambiental em PDF para um polígono.
    
    Aceita dois formatos:
    1. GeoJSON direto: {"type": "Polygon", "coordinates": [...]}
    2. Com property_info: {"geometry": {...}, "property_info": {...}, "lang": "pt"}
    
    Parâmetros:
    - lang: "pt" (Português) ou "en" (English)
    
    O laudo é automaticamente registrado na tabela de auditoria.
    """
    try:
        # =====================================================================
        # DETECTAR FORMATO DO BODY
        # =====================================================================
        geometry_data = None
        property_info_data = {}

        # Formato novo: {"geometry": {...}, "property_info": {...}, "lang": "pt"}
        if 'geometry' in body:
            geometry_data = body['geometry']
            property_info_data = body.get('property_info', {}) or {}
            # Idioma pode vir no body também
            if 'lang' in body:
                lang = body['lang']
            log.info("format_detected", format="geometry_property_info", lang=lang)
        # Formato antigo: {"type": "Polygon", "coordinates": [...]}
        elif 'type' in body and 'coordinates' in body:
            geometry_data = body
            log.info("format_detected", format="geojson_direct", lang=lang)
        else:
            raise ValueError("Formato de geometria não reconhecido")
        
        # Validar idioma
        if lang not in ['pt', 'en']:
            lang = 'pt'
        
        # Converter para GeoJSONPolygon
        geom = GeoJSONPolygon(**geometry_data)
        
        # Guardar geometry_geojson para uso posterior (mapa no PDF)
        geometry_geojson = geom.model_dump()
        
        # =====================================================================
        # EXTRAIR INFORMAÇÕES
        # =====================================================================
        farm_name = (
            property_info_data.get('farm_name') or 
            property_info_data.get('name') or 
            property_name
        )
        
        plot_name_final = (
            property_info_data.get('plot_name') or 
            plot_name
        )
        
        municipality = property_info_data.get('municipality')
        state_final = property_info_data.get('state') or state or 'MT'
        car_code = property_info_data.get('car_code')
        
        # 1. Executar validação
        log.info("generating_report", lang=lang, farm_name=farm_name, plot_name=plot_name_final)
        
        engine = GeoValidationEngine(db)
        validation_result = await engine.validate_polygon(geom)
        
        log.info("validation_completed", status=str(validation_result.status), score=validation_result.risk_score)
        
        # 2. Preparar informações
        try:
            area_ha = geom.get_area_ha()
            centroid = geom.get_centroid()
        except Exception as e:
            log.warning("error_calculating_area_centroid", error=str(e))
            area_ha = None
            centroid = None
        
        # 2.1. Buscar município automaticamente se não informado
        if not municipality and centroid:
            try:
                from sqlalchemy import text
                log.info("searching_municipality", lon=centroid[0], lat=centroid[1])
                
                # Buscar município mais próximo (até 100km)
                mun_query = text("""
                    SELECT nm_mun as name, sigla_uf as state,
                           ST_Distance(
                               geom::geography, 
                               ST_SetSRID(ST_Point(:lon, :lat), 4326)::geography
                           ) / 1000 as dist_km
                    FROM municipios
                    ORDER BY geom <-> ST_SetSRID(ST_Point(:lon, :lat), 4326)
                    LIMIT 1
                """)
                mun_result = await db.execute(mun_query, {"lon": centroid[0], "lat": centroid[1]})
                mun_row = mun_result.fetchone()
                
                if mun_row and mun_row.dist_km < 100:
                    municipality = mun_row.name
                    state_final = mun_row.state
                    log.info("municipality_detected", municipality=municipality, state=state_final, dist_km=round(mun_row.dist_km, 1))
                else:
                    log.warning("no_municipality_found_within_100km")
                    
            except Exception as e:
                log.warning("error_searching_municipality", error=str(e))
        
        # 2.2. Buscar histórico de uso do solo pelo município
        land_use_history = []
        if municipality:
            try:
                from sqlalchemy import text
                log.info("searching_land_use_history", municipality=municipality)

                # Busca case-insensitive e normalizada
                land_use_query = text("""
                    SELECT year, forest_pct, pasture_pct, agriculture_pct
                    FROM land_use_history
                    WHERE LOWER(TRIM(municipality_name)) = LOWER(TRIM(:municipality))
                    ORDER BY year DESC
                """)
                land_use_result = await db.execute(land_use_query, {"municipality": municipality})
                rows = land_use_result.fetchall()

                if not rows:
                    # Tentar com LIKE se busca exata falhar
                    log.info("exact_search_failed_trying_like")
                    like_query = text("""
                        SELECT year, forest_pct, pasture_pct, agriculture_pct
                        FROM land_use_history
                        WHERE municipality_name ILIKE :municipality_pattern
                        ORDER BY year DESC
                        LIMIT 50
                    """)
                    land_use_result = await db.execute(like_query, {"municipality_pattern": f"%{municipality}%"})
                    rows = land_use_result.fetchall()

                    if rows:
                        log.info("found_with_like", records=len(rows))

                for row in rows:
                    land_use_history.append({
                        "year": row.year,
                        "forest_pct": float(row.forest_pct) if row.forest_pct else 0,
                        "pasture_pct": float(row.pasture_pct) if row.pasture_pct else 0,
                        "agriculture_pct": float(row.agriculture_pct) if row.agriculture_pct else 0,
                    })

                if land_use_history:
                    log.info("land_use_history_found", records=len(land_use_history), municipality=municipality)
                else:
                    log.warning("no_land_use_history_found", municipality=municipality)

            except Exception as e:
                log.error("error_fetching_land_use_history", error=str(e), exc_info=e)
        
        plot_info = {
            "name": plot_name_final,
            "farm_name": farm_name,
            "plot_name": plot_name_final,
            "area_ha": area_ha,
            "crop_type": crop_type,
            "municipality": municipality,
            "state": state_final,
            "car_code": car_code,
            "centroid": {"lat": centroid[1], "lon": centroid[0]} if centroid else None,
            "land_use_history": land_use_history,
        }
        
        property_info = {
            "name": farm_name,
            "farm_name": farm_name,
            "plot_name": plot_name_final,
            "state": state_final,
            "municipality": municipality,
            "car_code": car_code,
            "land_use_history": land_use_history,
        }
        
        # 3. Gerar PDF usando a nova classe wrapper
        log.info("starting_pdf_generation", version="8.2", lang=lang)
        
        try:
            # Converter validation_result para dict se necessário
            if hasattr(validation_result, 'model_dump'):
                validation_dict = validation_result.model_dump()
            elif hasattr(validation_result, 'dict'):
                validation_dict = validation_result.dict()
            else:
                validation_dict = dict(validation_result)
            
            # Adicionar informações extras ao validation_dict
            validation_dict['area_ha'] = area_ha
            validation_dict['centroid'] = {"lat": centroid[1], "lon": centroid[0]} if centroid else None
            validation_dict['geometry'] = geometry_geojson  # IMPORTANTE: Para desenhar o mapa no PDF
            
            # Usar o novo gerador
            generator = DueDiligenceReportGenerator(db)
            result = await generator.generate(
                validation_result=validation_dict,
                property_info=property_info,
                lang=lang,
            )
            
            # Novo formato: retorna tuple (pdf_bytes, report_code, content_hash)
            if isinstance(result, tuple):
                pdf_bytes, report_code, content_hash = result
            else:
                # Compatibilidade com versão antiga
                pdf_bytes = result
                report_code = f"GG-{datetime.now().strftime('%Y%m%d%H%M%S')}-XXXX"
                content_hash = hashlib.sha256(pdf_bytes).hexdigest()
                
        except Exception as pdf_error:
            log.error("pdf_generation_error", error=str(pdf_error), exc_info=pdf_error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro na geração do PDF: {str(pdf_error)}"
            )
        
        # 4. Registrar na auditoria
        try:
            client_ip = request.client.host if request.client else None
            api_key = request.headers.get("x-api-key")
            user_agent = request.headers.get("user-agent")
            
            audit_service = AuditService(db)
            audit_record = await audit_service.record_validation_report(
                validation_result=validation_result,
                geometry_geojson=geometry_geojson,
                pdf_bytes=pdf_bytes,
                plot_info=plot_info,
                property_info=property_info,
                request_ip=client_ip,
                api_key=api_key,
                user_agent=user_agent,
                report_code=report_code,
                content_hash=content_hash,
            )
            
            log.info("report_registered", report_code=audit_record.report_code)
            report_code = audit_record.report_code
            
        except Exception as audit_error:
            log.error("audit_registration_error", error=str(audit_error), exc_info=audit_error)
            # Continua mesmo se auditoria falhar
        
        # 5. Nome do arquivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if farm_name and plot_name_final:
            safe_farm = "".join(c for c in farm_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_plot = "".join(c for c in plot_name_final if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_farm = safe_farm.replace(' ', '_')[:20]
            safe_plot = safe_plot.replace(' ', '_')[:20]
            filename = f"GreenGate_{safe_farm}_{safe_plot}_{timestamp}.pdf"
        else:
            filename = f"GreenGate_Report_{timestamp}.pdf"
        
        log.info("report_generated", filename=filename, size_bytes=len(pdf_bytes))
        
        # 6. Retornar PDF
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Length": str(len(pdf_bytes)),
        }
        
        if report_code:
            headers["X-Report-Code"] = report_code
        if content_hash:
            headers["X-Content-Hash"] = content_hash[:16] + "..."
        
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers=headers,
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        log.warning("validation_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        log.error("unexpected_error", error=str(e), exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao gerar relatório: {str(e)}"
        )


@router.post("/verify/{report_code}/geometry")
async def verify_report_geometry(
    report_code: str,
    geom: GeoJSONPolygon,
    db: AsyncSession = Depends(get_db),
):
    """
    Verifica se uma geometria corresponde a um laudo específico.
    """
    geometry_geojson = geom.model_dump()
    
    audit_service = AuditService(db)
    result = await audit_service.verify_report(report_code, geometry_geojson)
    
    return result


@router.get("/reproduce/{report_code}")
async def get_reproducible_data(
    report_code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna dados para reproduzir uma validação.
    """
    audit_service = AuditService(db)
    result = await audit_service.reproduce_validation(report_code)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Laudo {report_code} não encontrado"
        )
    
    return result


@router.post("/due-diligence/preview")
async def preview_report_data(
    geom: GeoJSONPolygon,
    plot_name: str = Query("Talhão Analisado", max_length=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Preview dos dados do relatório (sem gerar PDF).
    """
    engine = GeoValidationEngine(db)
    validation_result = await engine.validate_polygon(geom)
    
    try:
        area_ha = geom.get_area_ha()
        centroid = geom.get_centroid()
    except Exception:
        area_ha = None
        centroid = None
    
    return {
        "validation": validation_result.model_dump(),
        "plot_info": {
            "name": plot_name,
            "area_ha": area_ha,
            "centroid": centroid,
        },
        "report_metadata": {
            "generated_at": datetime.now().isoformat(),
            "format": "pdf",
            "version": "8.2",
        }
    }


@router.get("/status")
async def report_service_status():
    """
    Status do serviço de relatórios.
    """
    return {
        "status": "operational",
        "supported_formats": ["pdf"],
        "supported_languages": ["pt", "en"],
        "report_types": ["due_diligence"],
        "features": ["qr_code", "hash_verification", "bilingual", "audit_trail", "map_visualization"],
        "version": "8.2.0",
    }


# =============================================================================
# ENDPOINTS PÚBLICOS (sem autenticação) - QR Code aponta para cá
# =============================================================================

@public_router.get("/verify/{report_code}")
async def verify_report(
    report_code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Verifica se um laudo existe e retorna informações básicas.
    
    PÚBLICO - Não requer API key.
    Útil para validar autenticidade de um laudo.
    """
    audit_service = AuditService(db)
    report = await audit_service.get_report_by_code(report_code)
    
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Laudo {report_code} não encontrado"
        )
    
    return {
        "valid": True,
        "report_code": report.report_code,
        "status": report.status,
        "risk_score": report.risk_score,
        "created_at": report.created_at.isoformat(),
        "expires_at": report.expires_at.isoformat() if report.expires_at else None,
        "is_expired": report.expires_at and datetime.now(timezone.utc) > report.expires_at,
        "plot_name": report.plot_name,
        "property_name": report.property_name,
        "state": report.state,
        "geometry_hash": report.geometry_hash[:16] + "..." if report.geometry_hash else None,
        "pdf_hash": report.pdf_hash[:16] + "..." if report.pdf_hash else None,
    }


@public_router.get("/verify/{report_code}/page", response_class=HTMLResponse)
async def verify_report_page(
    report_code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Página HTML de verificação de autenticidade.
    
    PÚBLICO - Não requer API key.
    Exibe informações do laudo de forma visual (QR Code aponta aqui).
    Design atualizado com cores verdes GreenGate.
    """
    audit_service = AuditService(db)
    report = await audit_service.get_report_by_code(report_code)
    
    if not report:
        # Relatório não encontrado
        html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Não Encontrado - GreenGate</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌿</text></svg>">
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#FFEBEE,#FFCDD2);min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}}
        .container{{background:#fff;border-radius:16px;box-shadow:0 10px 40px rgba(0,0,0,.15);max-width:500px;width:100%;overflow:hidden;text-align:center}}
        .header{{background:linear-gradient(135deg,#047857,#059669);color:#fff;padding:24px}}
        .logo{{font-size:28px;font-weight:bold}}
        .error{{background:#DC2626;color:#fff;padding:32px}}
        .error .icon{{font-size:56px;display:block;margin-bottom:12px}}
        .content{{padding:32px 24px}}
        .code{{font-family:monospace;background:#F5F5F5;padding:12px 20px;border-radius:8px;display:inline-block;margin:20px 0}}
        .footer{{background:#FAFAFA;padding:16px;font-size:11px;color:#9CA3AF}}
    </style>
</head>
<body>
    <div class="container">
        <div class="header"><div class="logo">🌿 GreenGate</div></div>
        <div class="error">
            <span class="icon">✗</span>
            <span style="font-size:18px;font-weight:bold">RELATÓRIO NÃO ENCONTRADO</span>
        </div>
        <div class="content">
            <p style="color:#374151">O código informado não corresponde a nenhum relatório.</p>
            <div class="code">{report_code}</div>
            <p style="color:#374151">Verifique se o código está correto.</p>
        </div>
        <div class="footer">© 2025 GreenGate — greengate.com.br</div>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html, status_code=404)
    
    # Relatório encontrado
    is_compliant = report.status == "approved"
    status_color = "#059669" if is_compliant else "#DC2626" if report.status == "rejected" else "#B45309"
    status_text = "CONFORME" if is_compliant else "NÃO CONFORME" if report.status == "rejected" else "ATENÇÃO"
    status_icon = "✓" if is_compliant else "✗" if report.status == "rejected" else "!"
    
    created_at = report.created_at.strftime("%d/%m/%Y às %H:%M")
    score = report.risk_score or 0
    
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verificação - GreenGate</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌿</text></svg>">
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#ECFDF5,#D1FAE5);min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}}
        .container{{background:#fff;border-radius:16px;box-shadow:0 10px 40px rgba(0,0,0,.12);max-width:500px;width:100%;overflow:hidden}}
        .header{{background:linear-gradient(135deg,#047857,#059669);color:#fff;padding:24px;text-align:center}}
        .logo{{font-size:28px;font-weight:700}}
        .verified{{background:{status_color};color:#fff;padding:24px;text-align:center}}
        .verified .icon{{font-size:56px;display:block;margin-bottom:12px}}
        .verified .text{{font-size:20px;font-weight:700}}
        .content{{padding:24px}}
        .row{{display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid #E5E7EB}}
        .row:last-child{{border-bottom:none}}
        .label{{color:#6B7280;font-size:13px}}
        .value{{font-weight:600;color:#111827;text-align:right;font-size:14px}}
        .hash-section{{margin-top:20px;padding-top:16px;border-top:2px dashed #E5E7EB}}
        .hash{{font-family:monospace;font-size:9px;word-break:break-all;color:#6B7280;background:#F9FAFB;padding:12px;border-radius:8px;margin-top:8px;border:1px solid #E5E7EB}}
        .footer{{background:#F9FAFB;padding:16px;text-align:center;font-size:11px;color:#9CA3AF;border-top:1px solid #E5E7EB}}
        .score{{font-size:18px;color:{status_color};font-weight:700}}
        .status{{color:{status_color};font-weight:700}}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">🌿 GreenGate</div>
            <div style="font-size:12px;opacity:.9;margin-top:4px">Inteligência Ambiental</div>
        </div>
        <div class="verified">
            <span class="icon">{status_icon}</span>
            <span class="text">RELATÓRIO VERIFICADO</span>
        </div>
        <div class="content">
            <div class="row"><span class="label">Status</span><span class="value status">{status_text}</span></div>
            <div class="row"><span class="label">Índice de Conformidade</span><span class="value score">{score}/100</span></div>
            <div class="row"><span class="label">Código</span><span class="value" style="font-family:monospace;font-size:11px">{report.report_code}</span></div>
            <div class="row"><span class="label">Data de Geração</span><span class="value">{created_at}</span></div>
            <div class="row"><span class="label">Propriedade</span><span class="value">{report.property_name or '—'}</span></div>
            <div class="row"><span class="label">Talhão</span><span class="value">{report.plot_name or '—'}</span></div>
            <div class="row"><span class="label">Estado</span><span class="value">{report.state or 'MT'}</span></div>
            <div class="hash-section">
                <span class="label">🔒 Hash de Integridade (SHA-256)</span>
                <div class="hash">{report.pdf_hash if report.pdf_hash else 'N/A'}</div>
            </div>
        </div>
        <div class="footer">
            <strong>Este documento é autêntico</strong><br>
            Verificado nos sistemas GreenGate<br><br>
            © 2025 GreenGate — greengate.com.br
        </div>
    </div>
</body>
</html>"""
    
    return HTMLResponse(content=html)
