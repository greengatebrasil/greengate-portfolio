"""
GreenGate - Motor de Validação Geoespacial

Este é o coração do sistema. Responsável por:
1. Receber um polígono (talhão)
2. Cruzar com todas as bases de referência
3. Calcular score de risco
4. Retornar resultado estruturado
"""

import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from uuid import UUID

from sqlalchemy import text, bindparam, Date, String
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import shape

from app.models.schemas import (
    GeoJSONPolygon,
    GeoCheckResult,
    GeoValidationResult,
    CheckType,
    CheckStatus,
    ComplianceStatus,
)
from app.core.config import settings
from app.core.logging_config import get_logger

log = get_logger(__name__)


# =============================================================================
# CONFIGURAÇÃO DOS CHECKS
# =============================================================================

# Peso de cada check no score final (soma = 100)
CHECK_WEIGHTS = {
    CheckType.DEFORESTATION_PRODES: 35,        # Desmatamento PRODES (principal)
    CheckType.DEFORESTATION_MAPBIOMAS: 25,     # Alertas MapBiomas
    CheckType.TERRA_INDIGENA: 15,              # Terras Indígenas
    CheckType.EMBARGO_IBAMA: 15,               # Embargos ambientais
    CheckType.QUILOMBOLA: 5,                   # Territórios Quilombolas
    CheckType.UNIDADE_CONSERVACAO: 5,          # Unidades de Conservação
    # APP_WATER removido (não implementado) - peso redistributribuído para PRODES
}

# Thresholds de sobreposição (% da área do plot) - mantidos para evolução futura
OVERLAP_THRESHOLDS = {
    # check_type: (warning_threshold, fail_threshold)
    CheckType.DEFORESTATION_PRODES: (0.0, 0.0),        # Zero tolerance
    CheckType.DEFORESTATION_MAPBIOMAS: (0.0, 0.0),     # Zero tolerance
    CheckType.TERRA_INDIGENA: (0.0, 0.0),              # Zero tolerance
    CheckType.EMBARGO_IBAMA: (0.0, 0.0),               # Zero tolerance
    CheckType.QUILOMBOLA: (0.0, 0.0),                  # Zero tolerance
    CheckType.UNIDADE_CONSERVACAO: (0.5, 5.0),         # Depende do tipo de UC
}


# =============================================================================
# MOTOR DE VALIDAÇÃO
# =============================================================================

class GeoValidationEngine:
    """
    Motor de validação geoespacial.

    Executa validações contra bases de referência usando PostGIS.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._reference_versions: Dict[str, Any] = {}

    async def _load_reference_versions(self) -> Dict[str, Any]:
        """
        Carrega versões das bases de referência.

        Primeiro tenta buscar de dataset_versions (novo sistema).
        Fallback: conta registros de reference_layers (legado).

        Returns:
            Dict com layer_type -> {version, source_date, record_count, ingested_at}
        """
        versions: Dict[str, Any] = {}

        # 1) Tentar dataset_versions (se existir e tiver o schema esperado)
        try:
            async with self.db.begin_nested():
                query = text("""
                    SELECT
                        layer_type,
                        version,
                        source_date,
                        record_count,
                        ingested_at
                    FROM dataset_versions
                    WHERE is_active = true
                """)
                result = await self.db.execute(query)
                rows = result.fetchall()

                if rows:
                    for row in rows:
                        versions[row[0]] = {
                            "version": row[1],
                            "source_date": row[2].isoformat() if row[2] else None,
                            "record_count": row[3],
                            "ingested_at": row[4].isoformat() if row[4] else None,
                        }
                    log.debug("reference_versions_loaded_from_dataset_versions", count=len(versions))
                    return versions

        except Exception as e:
            # Não bloquear: só registrar e seguir para fallback
            log.warning("dataset_versions_unavailable_or_incompatible", error=str(e))

        # 2) Fallback: reference_layers (contagem por layer_type)
        try:
            async with self.db.begin_nested():
                query_fallback = text("""
                    SELECT
                        layer_type,
                        COUNT(*) as count,
                        MAX(reference_date) as max_reference_date,
                        MAX(ingested_at) as max_ingested_at
                    FROM reference_layers
                    WHERE is_active = true
                    GROUP BY layer_type
                """)
                result = await self.db.execute(query_fallback)
                rows = result.fetchall()

                for row in rows:
                    versions[row[0]] = {
                        "version": "legacy",
                        "record_count": int(row[1]),
                        "source_date": row[2].isoformat() if row[2] else None,
                        "ingested_at": row[3].isoformat() if row[3] else None,
                    }

                log.debug("reference_versions_loaded_fallback", count=len(versions))
                return versions

        except Exception as e:
            log.warning("reference_versions_load_failed", error=str(e))
            return {}

    async def validate_plot(
        self,
        plot_id: UUID,
        geom_wkt: str,
        area_ha: float,
    ) -> GeoValidationResult:
        """
        Executa validação completa de um talhão.

        Args:
            plot_id: ID do talhão
            geom_wkt: Geometria em WKT (POLYGON(...))
            area_ha: Área em hectares

        Returns:
            GeoValidationResult com todos os checks
        """
        start_time = time.time()
        checks: List[GeoCheckResult] = []

        # Carregar versões das bases de referência
        self._reference_versions = await self._load_reference_versions()

        # Lista de checks a executar
        check_functions = [
            (CheckType.DEFORESTATION_PRODES, self._check_deforestation_prodes),
            (CheckType.DEFORESTATION_MAPBIOMAS, self._check_deforestation_mapbiomas),
            (CheckType.TERRA_INDIGENA, self._check_terra_indigena),
            (CheckType.EMBARGO_IBAMA, self._check_embargo_ibama),
            (CheckType.QUILOMBOLA, self._check_quilombola),
            (CheckType.UNIDADE_CONSERVACAO, self._check_unidade_conservacao),
            # APP_WATER desabilitado - qualidade dos dados insatisfatória
            # (CheckType.APP_WATER, self._check_app_water),
        ]

        # Executar cada check sequencialmente
        for check_type, check_func in check_functions:
            result = await self._execute_check_safely(
                check_type=check_type,
                check_func=check_func,
                geom_wkt=geom_wkt,
                area_ha=area_ha,
            )
            checks.append(result)

        # Determinar status final
        status = self._determine_status(checks)

        # Score SEMPRE calculado (mesmo se REJECTED)
        risk_score = self._calculate_risk_score(checks)

        # FORÇAR score = 0 se houver blocker crítico
        # (Restrições absolutas: Terra Indígena, PRODES, Embargo, Quilombola, UC Integral)
        critical_blockers = [
            CheckType.TERRA_INDIGENA,
            CheckType.QUILOMBOLA,
            CheckType.EMBARGO_IBAMA,
            CheckType.DEFORESTATION_PRODES,
        ]

        has_critical_blocker = False
        for check in checks:
            if check.check_type in critical_blockers and check.status == CheckStatus.FAIL:
                has_critical_blocker = True
                break
            if check.check_type == CheckType.UNIDADE_CONSERVACAO and check.score == 0:
                has_critical_blocker = True
                break

        if has_critical_blocker:
            risk_score = 0  # Score ZERO para blockers críticos

        processing_time = int((time.time() - start_time) * 1000)

        failed_checks = [c.check_type.value for c in checks if c.status == CheckStatus.FAIL]
        skipped_checks = [c.check_type.value for c in checks if c.status == CheckStatus.SKIP]

        log.info(
            "validation_completed",
            plot_id=str(plot_id),
            status=status.value,
            risk_score=risk_score,
            processing_time_ms=processing_time,
            failed_checks=failed_checks,
            skipped_checks=skipped_checks,
            total_checks=len(checks),
            has_critical_blocker=has_critical_blocker,
        )

        return GeoValidationResult(
            plot_id=plot_id,
            status=status,
            risk_score=risk_score,
            checks=checks,
            validated_at=datetime.now(timezone.utc),
            reference_data_version=self._reference_versions,
            processing_time_ms=processing_time,
        )

    async def _execute_check_safely(
        self,
        check_type: CheckType,
        check_func,
        geom_wkt: str,
        area_ha: float,
    ) -> GeoCheckResult:
        """
        Executa um check de forma isolada com SAVEPOINT.
        Se falhar, faz rollback e retorna SKIP sem contaminar a sessão.
        """
        try:
            async with self.db.begin_nested():
                return await check_func(geom_wkt, area_ha)
        except Exception as e:
            log.warning(
                "check_failed_with_rollback",
                check_type=check_type.value,
                error=str(e),
            )
            return self._error_check_result(check_type, str(e))

    async def validate_polygon(
        self,
        geom: GeoJSONPolygon,
    ) -> GeoValidationResult:
        """
        Valida um polígono diretamente (sem salvar no banco).
        Útil para validação rápida via API.
        """
        # Usar métodos do schema (área geodésica + WKT consistente)
        geom_wkt = geom.to_wkt()
        area_ha = geom.get_area_ha()

        fake_id = UUID("00000000-0000-0000-0000-000000000000")
        return await self.validate_plot(fake_id, geom_wkt, area_ha)

    # =========================================================================
    # CHECKS INDIVIDUAIS
    # =========================================================================

    async def _check_deforestation_prodes(self, geom_wkt: str, area_ha: float) -> GeoCheckResult:
        """
        Verifica sobreposição com áreas desmatadas (PRODES/INPE).
        EUDR: Desmatamento pós 31/12/2020 é bloqueante.
        """
        check_type = CheckType.DEFORESTATION_PRODES

        overlap = await self._calculate_overlap(
            geom_wkt=geom_wkt,
            layer_type="prodes",
            plot_area_ha=area_ha,
            min_reference_date="2021-01-01",  # EUDR cutoff: pós 31/12/2020
        )

        if overlap["total_area_ha"] > 0.0001:  # Threshold: ignorar < 1m²
            # Extrair geometrias de interseção para visualização no mapa
            intersection_geoms = self._extract_intersection_geometries(overlap["features"])
            return GeoCheckResult(
                check_type=check_type,
                status=CheckStatus.FAIL,
                score=0,
                message=f"Sobreposição com área desmatada pós-2020 (PRODES): {overlap['total_area_ha']:.4f} ha",
                details={
                    "source": "PRODES/INPE",
                    "cutoff_date": "2020-12-31",
                },
                overlap_area_ha=overlap["total_area_ha"],
                overlap_percentage=overlap["percentage"],
                overlapping_features=overlap["features"],
                intersection_geometries=intersection_geoms,
            )

        return GeoCheckResult(
            check_type=check_type,
            status=CheckStatus.PASS,
            score=100,
            message="Nenhuma sobreposição com desmatamento PRODES pós-2020",
            details={"source": "PRODES/INPE"},
        )

    async def _check_deforestation_mapbiomas(self, geom_wkt: str, area_ha: float) -> GeoCheckResult:
        """
        Verifica sobreposição com alertas MapBiomas (pós-2020).
        """
        check_type = CheckType.DEFORESTATION_MAPBIOMAS

        overlap = await self._calculate_overlap(
            geom_wkt=geom_wkt,
            layer_type="mapbiomas",
            plot_area_ha=area_ha,
            min_reference_date="2021-01-01",  # EUDR cutoff: pós 31/12/2020
        )

        # Threshold mínimo: ignorar sobreposições menores que 0.0001 ha (1 m²)
        # Evita falsos positivos de interseções de borda/ponto
        if overlap["total_area_ha"] > 0.0001:  # Threshold: ignorar < 1m²
            intersection_geoms = self._extract_intersection_geometries(overlap["features"])
            return GeoCheckResult(
                check_type=check_type,
                status=CheckStatus.FAIL,
                score=0,
                message=f"Sobreposição com alerta MapBiomas pós-2020: {overlap['total_area_ha']:.4f} ha",
                details={"source": "MapBiomas Alerta"},
                overlap_area_ha=overlap["total_area_ha"],
                overlap_percentage=overlap["percentage"],
                overlapping_features=overlap["features"],
                intersection_geometries=intersection_geoms,
            )

        return GeoCheckResult(
            check_type=check_type,
            status=CheckStatus.PASS,
            score=100,
            message="Nenhuma sobreposição com alertas MapBiomas pós-2020",
            details={"source": "MapBiomas Alerta"},
        )

    async def _check_terra_indigena(self, geom_wkt: str, area_ha: float) -> GeoCheckResult:
        """
        Verifica sobreposição com Terras Indígenas. Qualquer sobreposição é bloqueante.
        """
        check_type = CheckType.TERRA_INDIGENA

        overlap = await self._calculate_overlap(
            geom_wkt=geom_wkt,
            layer_type="terra_indigena",
            plot_area_ha=area_ha,
        )

        if overlap["total_area_ha"] > 0.0001:  # Threshold: ignorar < 1m²
            ti_names = [f.get("name", "N/A") for f in overlap["features"][:3]]
            intersection_geoms = self._extract_intersection_geometries(overlap["features"])
            return GeoCheckResult(
                check_type=check_type,
                status=CheckStatus.FAIL,
                score=0,
                message=f"Sobreposição com Terra Indígena: {', '.join(ti_names)}",
                details={"source": "FUNAI", "terras_indigenas": ti_names},
                overlap_area_ha=overlap["total_area_ha"],
                overlap_percentage=overlap["percentage"],
                overlapping_features=overlap["features"],
                intersection_geometries=intersection_geoms,
            )

        return GeoCheckResult(
            check_type=check_type,
            status=CheckStatus.PASS,
            score=100,
            message="Nenhuma sobreposição com Terra Indígena",
            details={"source": "FUNAI"},
        )

    async def _check_embargo_ibama(self, geom_wkt: str, area_ha: float) -> GeoCheckResult:
        """
        Verifica sobreposição com áreas embargadas pelo IBAMA.
        Embargo ativo é bloqueante.
        """
        check_type = CheckType.EMBARGO_IBAMA

        overlap = await self._calculate_overlap(
            geom_wkt=geom_wkt,
            layer_type="embargo_ibama",
            plot_area_ha=area_ha,
        )

        if overlap["total_area_ha"] > 0.0001:  # Threshold: ignorar < 1m²
            intersection_geoms = self._extract_intersection_geometries(overlap["features"])
            return GeoCheckResult(
                check_type=check_type,
                status=CheckStatus.FAIL,
                score=0,
                message=f"Sobreposição com área embargada IBAMA: {overlap['total_area_ha']:.4f} ha",
                details={"source": "IBAMA", "embargos": overlap["features"][:5]},
                overlap_area_ha=overlap["total_area_ha"],
                overlap_percentage=overlap["percentage"],
                overlapping_features=overlap["features"],
                intersection_geometries=intersection_geoms,
            )

        return GeoCheckResult(
            check_type=check_type,
            status=CheckStatus.PASS,
            score=100,
            message="Nenhuma sobreposição com embargo IBAMA ativo",
            details={"source": "IBAMA"},
        )

    async def _check_quilombola(self, geom_wkt: str, area_ha: float) -> GeoCheckResult:
        """
        Verifica sobreposição com Territórios Quilombolas. Qualquer sobreposição é bloqueante.
        """
        check_type = CheckType.QUILOMBOLA

        overlap = await self._calculate_overlap(
            geom_wkt=geom_wkt,
            layer_type="quilombola",
            plot_area_ha=area_ha,
        )

        if overlap["total_area_ha"] > 0.0001:  # Threshold: ignorar < 1m²
            intersection_geoms = self._extract_intersection_geometries(overlap["features"])
            return GeoCheckResult(
                check_type=check_type,
                status=CheckStatus.FAIL,
                score=0,
                message=f"Sobreposição com Território Quilombola: {overlap['total_area_ha']:.4f} ha",
                details={"source": "INCRA"},
                overlap_area_ha=overlap["total_area_ha"],
                overlap_percentage=overlap["percentage"],
                overlapping_features=overlap["features"],
                intersection_geometries=intersection_geoms,
            )

        return GeoCheckResult(
            check_type=check_type,
            status=CheckStatus.PASS,
            score=100,
            message="Nenhuma sobreposição com Território Quilombola",
            details={"source": "INCRA"},
        )

    async def _check_unidade_conservacao(self, geom_wkt: str, area_ha: float) -> GeoCheckResult:
        """
        Verifica sobreposição com Unidades de Conservação.
        Proteção Integral => FAIL
        Uso Sustentável => WARNING
        """
        check_type = CheckType.UNIDADE_CONSERVACAO

        overlap = await self._calculate_overlap(
            geom_wkt=geom_wkt,
            layer_type="uc",
            plot_area_ha=area_ha,
        )

        if overlap["total_area_ha"] > 0.0001:  # Threshold: ignorar < 1m²
            has_integral = any(
                (f.get("extra_data") or {}).get("category") in ["PARNA", "ESEC", "REBIO", "EE", "MN"]
                or f.get("category") in ["PARNA", "ESEC", "REBIO", "EE", "MN"]
                for f in overlap["features"]
            )
            intersection_geoms = self._extract_intersection_geometries(overlap["features"])

            if has_integral:
                return GeoCheckResult(
                    check_type=check_type,
                    status=CheckStatus.FAIL,
                    score=0,
                    message=f"Sobreposição com UC de Proteção Integral: {overlap['total_area_ha']:.4f} ha",
                    details={"source": "MMA/ICMBio", "tipo": "protecao_integral"},
                    overlap_area_ha=overlap["total_area_ha"],
                    overlap_percentage=overlap["percentage"],
                    overlapping_features=overlap["features"],
                    intersection_geometries=intersection_geoms,
                )

            return GeoCheckResult(
                check_type=check_type,
                status=CheckStatus.WARNING,
                score=70,
                message=f"Sobreposição com UC de Uso Sustentável: {overlap['total_area_ha']:.4f} ha",
                details={"source": "MMA/ICMBio", "tipo": "uso_sustentavel"},
                overlap_area_ha=overlap["total_area_ha"],
                overlap_percentage=overlap["percentage"],
                overlapping_features=overlap["features"],
                intersection_geometries=intersection_geoms,
            )

        return GeoCheckResult(
            check_type=check_type,
            status=CheckStatus.PASS,
            score=100,
            message="Nenhuma sobreposição com Unidade de Conservação",
            details={"source": "MMA/ICMBio"},
        )

    async def _check_app_water(self, geom_wkt: str, area_ha: float) -> GeoCheckResult:
        """
        Verifica distância de corpos d'água (APP).
        Código Florestal: distância mínima configurável.
        """
        check_type = CheckType.APP_WATER
        buffer_meters = settings.DEFAULT_BUFFER_WATER_METERS

        # Otimização: bbox first (ST_Expand) + ST_DWithin em geography (métrico)
        buffer_degrees = (buffer_meters / 111000) * 1.5  # margem conservadora

        query = text("""
            WITH nearby AS (
                SELECT rl.geom
                FROM reference_layers rl
                WHERE rl.layer_type = 'hidrografia'
                  AND rl.is_active = true
                  AND rl.geom && ST_Expand(ST_GeomFromText(:geom_wkt, 4326), :buffer_degrees)
            )
            SELECT
                COUNT(*) as count,
                MIN(
                    ST_Distance(
                        ST_GeomFromText(:geom_wkt, 4326)::geography,
                        nearby.geom::geography
                    )
                ) as min_distance_m
            FROM nearby
            WHERE ST_DWithin(
                ST_GeomFromText(:geom_wkt, 4326)::geography,
                nearby.geom::geography,
                :buffer_meters
            )
        """)

        result = await self.db.execute(
            query,
            {"geom_wkt": geom_wkt, "buffer_meters": buffer_meters, "buffer_degrees": buffer_degrees},
        )
        row = result.fetchone()

        if row and row.count and row.count > 0:
            min_dist = float(row.min_distance_m or 0)
            return GeoCheckResult(
                check_type=check_type,
                status=CheckStatus.WARNING,
                score=60,
                message=f"Talhão a menos de {buffer_meters}m de corpo d'água (dist. mín: {min_dist:.1f}m)",
                details={
                    "source": "ANA/Hidrografia",
                    "buffer_required_m": buffer_meters,
                    "min_distance_m": min_dist,
                },
            )

        return GeoCheckResult(
            check_type=check_type,
            status=CheckStatus.PASS,
            score=100,
            message=f"Talhão respeita distância mínima de {buffer_meters}m de corpos d'água",
            details={"source": "ANA/Hidrografia"},
        )

    # =========================================================================
    # MÉTODOS AUXILIARES
    # =========================================================================

    async def _calculate_overlap(
        self,
        geom_wkt: str,
        layer_type: str,
        plot_area_ha: Optional[float] = None,
        min_reference_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calcula sobreposição entre o polígono e uma camada de referência.

        Args:
            geom_wkt: Geometria em WKT
            layer_type: Tipo de camada (prodes, mapbiomas, etc.)
            plot_area_ha: Área do plot em hectares (opcional, calculada se não fornecida)
            min_reference_date: Data mínima de referência no formato 'YYYY-MM-DD' (opcional)
                               Usado para filtrar apenas registros após determinada data (ex: EUDR cutoff)

        Returns:
            {
                "total_area_ha": float,
                "percentage": float,
                "features": [{"id": ..., "name": ..., "overlap_ha": ..., "extra_data": ..., "intersection_geojson": ...}, ...]
            }
        """
        # Query parametrizada - sem concatenação de strings SQL
        # O filtro de data é aplicado condicionalmente
        # Nota: bindparam com tipo explícito é necessário para asyncpg inferir o tipo corretamente
        query = text("""
            WITH plot AS (
                SELECT ST_GeomFromText(:geom_wkt, 4326) as geom
            ),
            intersections AS (
                SELECT
                    rl.id,
                    rl.source_name,
                    rl.extra_data,
                    ST_Intersection(rl.geom, plot.geom) as intersection_geom,
                    ST_Area(ST_Intersection(rl.geom, plot.geom)::geography) / 10000 as overlap_ha
                FROM reference_layers rl, plot
                WHERE rl.layer_type = :layer_type
                  AND rl.is_active = true
                  AND ST_Intersects(rl.geom, plot.geom)
                  AND (
                      CAST(:min_reference_date AS TEXT) IS NULL
                      OR rl.reference_date >= CAST(:min_reference_date AS DATE)
                  )
            )
            SELECT
                COALESCE(SUM(overlap_ha), 0) as total_overlap_ha,
                json_agg(
                    json_build_object(
                        'id', id::text,
                        'name', source_name,
                        'overlap_ha', overlap_ha,
                        'extra_data', extra_data,
                        'intersection_geojson', ST_AsGeoJSON(intersection_geom)::json
                    )
                ) FILTER (WHERE overlap_ha > 0) as features
            FROM intersections
        """).bindparams(
            bindparam("min_reference_date", type_=String)
        )

        result = await self.db.execute(query, {
            "geom_wkt": geom_wkt,
            "layer_type": layer_type,
            "min_reference_date": min_reference_date,
        })
        row = result.fetchone()

        total_overlap = float(row.total_overlap_ha) if row and row.total_overlap_ha else 0.0
        features = row.features if row and row.features else []

        # Se não veio área (ou veio inválida), calcular via PostGIS
        plot_area = float(plot_area_ha) if plot_area_ha and plot_area_ha > 0 else None
        if plot_area is None:
            area_query = text("""
                SELECT ST_Area(ST_GeomFromText(:geom_wkt, 4326)::geography) / 10000 as area_ha
            """)
            area_result = await self.db.execute(area_query, {"geom_wkt": geom_wkt})
            plot_area = float(area_result.scalar() or 1.0)

        percentage = (total_overlap / plot_area) * 100 if plot_area and plot_area > 0 else 0.0

        return {
            "total_area_ha": total_overlap,
            "percentage": percentage,
            "features": features,
        }

    def _extract_intersection_geometries(self, features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extrai geometrias de interseção dos features para visualização no mapa.

        Cada feature retornado pela query contém 'intersection_geojson' com a geometria
        exata da sobreposição. Esta função formata para uso direto pelo frontend.

        Returns:
            Lista de objetos com:
            - geometry: GeoJSON geometry (Polygon/MultiPolygon)
            - name: Nome da feature (para label no mapa)
            - overlap_ha: Área de sobreposição em hectares
        """
        geometries = []
        for feature in features or []:
            geojson = feature.get("intersection_geojson")
            if geojson:
                geometries.append({
                    "geometry": geojson,
                    "name": feature.get("name", "N/A"),
                    "overlap_ha": feature.get("overlap_ha", 0),
                    "id": feature.get("id"),
                })
        return geometries

    def _calculate_risk_score(self, checks: List[GeoCheckResult]) -> int:
        """
        Calcula score ponderado (0-100, onde 100 = melhor).
        Observação: Status (APPROVED/REJECTED) é independente do score.
        """
        total_weight = 0
        weighted_score = 0

        for check in checks:
            weight = CHECK_WEIGHTS.get(check.check_type, 0)
            total_weight += weight
            weighted_score += int(check.score) * weight

        if total_weight == 0:
            return 50

        return int(weighted_score / total_weight)

    def _determine_status(self, checks: List[GeoCheckResult]) -> ComplianceStatus:
        """
        Determina status final baseado em checks críticos + score.

        CRITICAL BLOCKERS (instant rejection + score = 0):
        - Terra Indígena (proteção constitucional)
        - Quilombola (proteção constitucional)
        - Embargo IBAMA (restrição legal ativa)
        - PRODES pós-2020 (requisito EUDR)
        - UC Proteção Integral (score=0 indica integral)

        SCORE-BASED (outros casos):
        - Score ≥ 75: APPROVED
        - Score 60-74: WARNING (apta com restrições)
        - Score < 60: REJECTED
        """
        # 1. Verificar blockers críticos (restrições legais/constitucionais absolutas)
        critical_blockers = [
            CheckType.TERRA_INDIGENA,
            CheckType.QUILOMBOLA,
            CheckType.EMBARGO_IBAMA,
            CheckType.DEFORESTATION_PRODES,
        ]

        has_critical_blocker = False

        for check in checks:
            # Blocker crítico com FAIL
            if check.check_type in critical_blockers and check.status == CheckStatus.FAIL:
                has_critical_blocker = True
                break

            # UC Proteção Integral (score 0 indica integral, score 70 indica sustentável)
            if check.check_type == CheckType.UNIDADE_CONSERVACAO and check.score == 0:
                has_critical_blocker = True
                break

        # Se tem blocker crítico, retornar REJECTED
        # (o score será forçado para 0 no método validate_plot)
        if has_critical_blocker:
            return ComplianceStatus.REJECTED

        # 2. Calcular score para decisão final
        score = self._calculate_risk_score(checks)

        # 3. Determinar status baseado no score
        if score >= 75:
            # Score alto - aprovado (pode ter warnings menores)
            if any(c.status == CheckStatus.WARNING for c in checks):
                return ComplianceStatus.WARNING  # Aprovado com ressalvas
            return ComplianceStatus.APPROVED

        elif score >= 60:
            # Score médio - atenção necessária
            return ComplianceStatus.WARNING

        else:
            # Score baixo - reprovado (múltiplas restrições)
            return ComplianceStatus.REJECTED

    def _error_check_result(self, check_type: CheckType, error: str) -> GeoCheckResult:
        """Retorna resultado de erro para um check que falhou."""
        return GeoCheckResult(
            check_type=check_type,
            status=CheckStatus.SKIP,
            score=50,
            message=f"Não foi possível executar verificação: {error}",
            details={"error": error},
        )


# =============================================================================
# FUNÇÕES DE CONVENIÊNCIA
# =============================================================================

async def validate_plot_geometry(
    db: AsyncSession,
    plot_id: UUID,
    geom_wkt: str,
    area_ha: float,
) -> GeoValidationResult:
    """Função helper para validar um plot."""
    engine = GeoValidationEngine(db)
    return await engine.validate_plot(plot_id, geom_wkt, area_ha)


async def quick_validate_polygon(
    db: AsyncSession,
    geom: GeoJSONPolygon,
) -> GeoValidationResult:
    """Função helper para validação rápida de polígono."""
    engine = GeoValidationEngine(db)
    return await engine.validate_polygon(geom)
