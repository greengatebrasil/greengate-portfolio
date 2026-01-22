"""
GreenGate - API de Validação Geoespacial
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.database import Plot, Validation, ValidationCheck, Property
from app.models.schemas import (
    GeoJSONPolygon,
    GeoValidationResult,
    ValidationRequest,
    ValidationResponse,
    ValidationCheckResponse,
    ValidationSummary,
    BatchValidationResponse,
    BatchErrorDetail,
    ComplianceStatus,
    CheckType,
    CheckStatus,
    APIResponse,
    PaginatedResponse,
)
from app.services.validation_engine import GeoValidationEngine
from app.core.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/validations",
    tags=["Validações"],
    # API Key validada pelo APIKeyTrackerMiddleware
)


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/quick", response_model=GeoValidationResult)
async def quick_validate(
    geom: GeoJSONPolygon,
    db: AsyncSession = Depends(get_db),
):
    """
    Validação rápida de um polígono (sem salvar no banco).
    
    Use para:
    - Testar a API
    - Validar antes de cadastrar
    - Integrações que só precisam do resultado
    
    Retorna score de risco e detalhes de cada verificação.
    
    **Limites:**
    - Área máxima: 50.000 ha
    - Máximo de vértices: 10.000
    - Polígono deve ser válido (fechado, não auto-intersectante)
    
    **Exemplo de polígono válido:**
    ```json
    {
      "type": "Polygon",
      "coordinates": [[
        [-47.05, -22.90],
        [-47.05, -22.91],
        [-47.04, -22.91],
        [-47.04, -22.90],
        [-47.05, -22.90]
      ]]
    }
    ```
    """
    try:
        # Log da requisição (sem dados sensíveis)
        num_vertices = len(geom.coordinates[0]) if geom.coordinates else 0
        log.info("quick_validation_request", num_vertices=num_vertices)

        # Executar validação
        engine = GeoValidationEngine(db)
        result = await engine.validate_polygon(geom)

        log.info("validation_complete", status=result.status.value, score=result.risk_score)

        # Buscar datas de atualização dos dados e popular last_updated nos checks
        from app.services.data_freshness import get_data_freshness
        data_freshness = await get_data_freshness(db)

        # Mapeamento de check_type para layer_type
        # Os check_types vêm como enum values: deforestation_prodes, terra_indigena, etc.
        check_to_layer_map = {
            # PRODES
            'deforestation_prodes': 'prodes',
            'deforestation': 'prodes',
            'prodes': 'prodes',
            # MapBiomas
            'deforestation_mapbiomas': 'mapbiomas',
            'mapbiomas': 'mapbiomas',
            'mapbiomas_alert': 'mapbiomas',
            'mapbiomas_alerts': 'mapbiomas',
            # Terras Indígenas
            'terra_indigena': 'terra_indigena',
            'indigenous_territory': 'terra_indigena',
            # Unidades de Conservação
            'uc': 'uc',
            'unidade_conservacao': 'uc',
            'conservation_unit': 'uc',
            # Quilombolas
            'quilombola': 'quilombola',
            'settlement': 'quilombola',
            # Embargos IBAMA
            'embargo_ibama': 'embargo_ibama',
            'embargo': 'embargo_ibama',
        }

        # Popular last_updated em cada check
        for check in result.checks:
            # Usar .value para obter o valor string do enum (ex: "deforestation_prodes")
            check_type_str = check.check_type.value if hasattr(check.check_type, 'value') else str(check.check_type).lower()
            layer_type = check_to_layer_map.get(check_type_str)
            if layer_type and data_freshness and layer_type in data_freshness:
                check.last_updated = data_freshness[layer_type]
            log.debug("check_type_mapping", check_type=check_type_str, layer_type=layer_type, has_freshness=layer_type in data_freshness if data_freshness else False)

        # Adicionar data_freshness ao resultado para o frontend exibir
        result.data_freshness = data_freshness

        return result
        
    except ValueError as e:
        # Erro de validação de input (já formatado pelo Pydantic)
        log.warning("validation_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Erro inesperado
        log.error("unexpected_error_quick_validate", error=str(e), exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar validação. Tente novamente."
        )


@router.post("/validate", response_model=GeoValidationResult)
async def validate_with_key(
    geom: GeoJSONPolygon,
    db: AsyncSession = Depends(get_db),
):
    """
    Validação de polígono com API Key (contabiliza uso).

    Este endpoint requer API Key e contabiliza no uso mensal.
    Use para validações reais que devem ser rastreadas.

    Para testes sem contabilizar, use /quick com área de exemplo.
    """
    try:
        num_vertices = len(geom.coordinates[0]) if geom.coordinates else 0
        log.info("validate_with_key_request", num_vertices=num_vertices)

        # Executar validação
        engine = GeoValidationEngine(db)
        result = await engine.validate_polygon(geom)

        log.info("validation_complete", status=result.status.value, score=result.risk_score)

        # Buscar datas de atualização dos dados
        from app.services.data_freshness import get_data_freshness
        data_freshness = await get_data_freshness(db)

        # Mapeamento de check_type para layer_type
        check_to_layer_map = {
            'deforestation_prodes': 'prodes',
            'deforestation': 'prodes',
            'prodes': 'prodes',
            'deforestation_mapbiomas': 'mapbiomas',
            'mapbiomas': 'mapbiomas',
            'mapbiomas_alert': 'mapbiomas',
            'mapbiomas_alerts': 'mapbiomas',
            'terra_indigena': 'terra_indigena',
            'indigenous_territory': 'terra_indigena',
            'uc': 'uc',
            'unidade_conservacao': 'uc',
            'conservation_unit': 'uc',
            'quilombola': 'quilombola',
            'settlement': 'quilombola',
            'embargo_ibama': 'embargo_ibama',
            'embargo': 'embargo_ibama',
        }

        # Popular last_updated em cada check
        for check in result.checks:
            check_type_str = check.check_type.value if hasattr(check.check_type, 'value') else str(check.check_type).lower()
            layer_type = check_to_layer_map.get(check_type_str)
            if layer_type and data_freshness and layer_type in data_freshness:
                check.last_updated = data_freshness[layer_type]

        result.data_freshness = data_freshness
        return result

    except ValueError as e:
        log.warning("validation_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        log.error("unexpected_error_validate", error=str(e), exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar validação. Tente novamente."
        )


@router.post("/plot/{plot_id}", response_model=ValidationResponse)
async def validate_plot(
    plot_id: UUID,
    force: bool = Query(False, description="Forçar revalidação mesmo se ainda válido"),
    db: AsyncSession = Depends(get_db),
):
    """
    Valida um talhão cadastrado e salva o resultado.
    
    - Verifica sobreposição com todas as bases de referência
    - Calcula score de risco
    - Atualiza status do talhão
    - Retorna detalhes completos da validação
    """
    # Buscar plot
    result = await db.execute(select(Plot).where(Plot.id == plot_id))
    plot = result.scalar_one_or_none()
    
    if not plot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Talhão {plot_id} não encontrado"
        )
    
    # Verificar se já tem validação válida recente
    if not force and plot.last_validation_at:
        from datetime import datetime, timedelta, timezone
        from app.core.config import settings

        expiry = plot.last_validation_at + timedelta(days=settings.VALIDATION_EXPIRY_DAYS)
        if datetime.now(timezone.utc) < expiry and plot.compliance_status != ComplianceStatus.PENDING:
            # Buscar última validação
            val_result = await db.execute(
                select(Validation)
                .where(Validation.plot_id == plot_id)
                .order_by(Validation.validated_at.desc())
                .limit(1)
            )
            existing = val_result.scalar_one_or_none()
            if existing:
                # Carregar checks
                checks_result = await db.execute(
                    select(ValidationCheck).where(ValidationCheck.validation_id == existing.id)
                )
                checks = checks_result.scalars().all()
                
                return ValidationResponse(
                    id=existing.id,
                    plot_id=existing.plot_id,
                    status=ComplianceStatus(existing.status),
                    risk_score=existing.risk_score,
                    validated_at=existing.validated_at,
                    expires_at=existing.expires_at,
                    checks=[ValidationCheckResponse.model_validate(c) for c in checks],
                )
    
    # Executar validação
    geom_wkt_query = text("SELECT ST_AsText(geom) FROM plots WHERE id = :plot_id")
    geom_result = await db.execute(geom_wkt_query, {"plot_id": str(plot_id)})
    geom_wkt = geom_result.scalar()
    
    engine = GeoValidationEngine(db)
    validation_result = await engine.validate_plot(
        plot_id=plot_id,
        geom_wkt=geom_wkt,
        area_ha=float(plot.area_ha),
    )
    
    # Salvar validação
    from datetime import timedelta
    from app.core.config import settings
    
    validation = Validation(
        plot_id=plot_id,
        status=validation_result.status.value,
        risk_score=validation_result.risk_score,
        validated_at=validation_result.validated_at,
        geom_snapshot=func.ST_GeomFromText(geom_wkt, 4326),
        reference_data_version=validation_result.reference_data_version,
        expires_at=validation_result.validated_at + timedelta(days=settings.VALIDATION_EXPIRY_DAYS),
    )
    db.add(validation)
    await db.flush()  # Para obter o ID
    
    # Salvar checks
    for check in validation_result.checks:
        check_record = ValidationCheck(
            validation_id=validation.id,
            check_type=check.check_type.value,
            status=check.status.value,
            score=check.score,
            message=check.message,
            details=check.details,
            evidence=check.evidence,
        )
        db.add(check_record)
    
    # Atualizar status do plot
    plot.compliance_status = validation_result.status.value
    plot.risk_score = validation_result.risk_score
    plot.last_validation_at = validation_result.validated_at
    
    await db.commit()
    
    # Recarregar para resposta
    await db.refresh(validation)
    
    checks_result = await db.execute(
        select(ValidationCheck).where(ValidationCheck.validation_id == validation.id)
    )
    checks = checks_result.scalars().all()
    
    return ValidationResponse(
        id=validation.id,
        plot_id=validation.plot_id,
        status=ComplianceStatus(validation.status),
        risk_score=validation.risk_score,
        validated_at=validation.validated_at,
        expires_at=validation.expires_at,
        checks=[ValidationCheckResponse.model_validate(c) for c in checks],
    )


@router.post("/batch", response_model=BatchValidationResponse)
async def validate_batch(
    plot_ids: List[UUID],
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Valida múltiplos talhões em lote.

    Limitado a 100 talhões por requisição.

    Retorna detalhes de sucessos E falhas, permitindo que o cliente
    saiba exatamente quais validações foram bem-sucedidas e quais falharam.
    """
    if len(plot_ids) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Máximo de 100 talhões por requisição"
        )

    validations = []
    errors = []

    for plot_id in plot_ids:
        try:
            validation = await validate_plot(plot_id, force=force, db=db)

            # Buscar nomes para o summary
            plot_result = await db.execute(
                select(Plot, Property.name.label("property_name"))
                .join(Property)
                .where(Plot.id == plot_id)
            )
            row = plot_result.one_or_none()

            validations.append(ValidationSummary(
                id=validation.id,
                plot_id=validation.plot_id,
                plot_name=row.Plot.name if row else "N/A",
                property_name=row.property_name if row else "N/A",
                status=validation.status,
                risk_score=validation.risk_score,
                validated_at=validation.validated_at,
            ))
        except HTTPException as e:
            # Plot não encontrado ou erro de validação
            errors.append(BatchErrorDetail(
                plot_id=plot_id,
                error=e.detail if isinstance(e.detail, str) else str(e.detail),
                error_type="not_found" if e.status_code == 404 else "validation_error"
            ))
        except Exception as e:
            # Erro interno inesperado
            log.error("unexpected_error_batch_validate", plot_id=str(plot_id), error=str(e), exc_info=e)
            errors.append(BatchErrorDetail(
                plot_id=plot_id,
                error=str(e),
                error_type="internal_error"
            ))

    return BatchValidationResponse(
        success_count=len(validations),
        failed_count=len(errors),
        total=len(plot_ids),
        validations=validations,
        errors=errors
    )


@router.get("/history/{plot_id}", response_model=List[ValidationSummary])
async def get_validation_history(
    plot_id: UUID,
    limit: int = Query(10, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna histórico de validações de um talhão.
    """
    # Verificar se plot existe
    plot_result = await db.execute(
        select(Plot, Property.name.label("property_name"))
        .join(Property)
        .where(Plot.id == plot_id)
    )
    row = plot_result.one_or_none()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Talhão {plot_id} não encontrado"
        )
    
    # Buscar validações
    validations_result = await db.execute(
        select(Validation)
        .where(Validation.plot_id == plot_id)
        .order_by(Validation.validated_at.desc())
        .limit(limit)
    )
    validations = validations_result.scalars().all()
    
    return [
        ValidationSummary(
            id=v.id,
            plot_id=v.plot_id,
            plot_name=row.Plot.name,
            property_name=row.property_name,
            status=ComplianceStatus(v.status),
            risk_score=v.risk_score,
            validated_at=v.validated_at,
        )
        for v in validations
    ]


@router.get("/{validation_id}", response_model=ValidationResponse)
async def get_validation(
    validation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna detalhes completos de uma validação específica.

    Inclui as datas de última atualização de cada camada de dados
    no campo `data_freshness`.
    """
    result = await db.execute(
        select(Validation).where(Validation.id == validation_id)
    )
    validation = result.scalar_one_or_none()

    if not validation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validação {validation_id} não encontrada"
        )

    # Carregar checks
    checks_result = await db.execute(
        select(ValidationCheck).where(ValidationCheck.validation_id == validation_id)
    )
    checks = checks_result.scalars().all()

    # Buscar datas de atualização dos dados
    from app.services.data_freshness import get_data_freshness
    data_freshness = await get_data_freshness(db)

    # Mapeamento de check_type para layer_type (lowercase)
    check_to_layer_map = {
        'deforestation_prodes': 'prodes',
        'deforestation': 'prodes',
        'prodes': 'prodes',
        'deforestation_mapbiomas': 'mapbiomas',
        'mapbiomas': 'mapbiomas',
        'mapbiomas_alert': 'mapbiomas',
        'terra_indigena': 'terra_indigena',
        'indigenous_territory': 'terra_indigena',
        'uc': 'uc',
        'unidade_conservacao': 'uc',
        'quilombola': 'quilombola',
        'settlement': 'quilombola',
        'embargo_ibama': 'embargo_ibama',
        'embargo': 'embargo_ibama',
    }

    # Converter checks para response, adicionando last_updated
    checks_response = []
    for c in checks:
        check_dict = ValidationCheckResponse.model_validate(c).model_dump()

        # Adicionar last_updated baseado no check_type (lowercase)
        check_type_str = str(c.check_type).lower()
        layer_type = check_to_layer_map.get(check_type_str)
        if layer_type and data_freshness and layer_type in data_freshness:
            check_dict['last_updated'] = data_freshness[layer_type]

        checks_response.append(ValidationCheckResponse(**check_dict))

    return ValidationResponse(
        id=validation.id,
        plot_id=validation.plot_id,
        status=ComplianceStatus(validation.status),
        risk_score=validation.risk_score,
        validated_at=validation.validated_at,
        expires_at=validation.expires_at,
        checks=checks_response,
        data_freshness=data_freshness,
    )
