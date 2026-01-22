"""
GreenGate - PDF Generator
"""

import io
import os
import math
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, HRFlowable, KeepTogether, ListFlowable, ListItem
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon, Circle
from reportlab.graphics.charts.piecharts import Pie

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

# ============================================================
# PALETA EXECUTIVA PREMIUM
# ============================================================

COLORS = {
    # Verde - tons mais escuros e elegantes
    'primary': colors.HexColor('#059669'),        # Esmeralda escuro (header)
    'primary_dark': colors.HexColor('#047857'),   # Verde profundo
    'primary_light': colors.HexColor('#ECFDF5'),  # Verde muito pálido (fundo)
    'primary_accent': colors.HexColor('#10B981'), # Verde accent (uso moderado)
    
    # Status - tons suavizados
    'success': colors.HexColor('#059669'),        # Verde escuro
    'success_light': colors.HexColor('#D1FAE5'),  # Verde pálido
    'success_bg': colors.HexColor('#F0FDF4'),     # Fundo verde quase branco
    
    'danger': colors.HexColor('#DC2626'),         # Vermelho sóbrio
    'danger_light': colors.HexColor('#FCA5A5'),   # Vermelho pálido
    'danger_bg': colors.HexColor('#FEF2F2'),      # Fundo rosa muito pálido
    
    'warning': colors.HexColor('#B45309'),        # Âmbar escuro executivo
    'warning_light': colors.HexColor('#FBBF24'),  # Âmbar borda
    'warning_bg': colors.HexColor('#FFF9E6'),     # Fundo dourado pálido
    
    # Cinzas executivos
    'gray_900': colors.HexColor('#111827'),       # Quase preto (títulos)
    'gray_700': colors.HexColor('#374151'),       # Cinza escuro (texto)
    'gray_600': colors.HexColor('#4B5563'),       # Cinza médio-escuro
    'gray_500': colors.HexColor('#6B7280'),       # Cinza médio (labels)
    'gray_400': colors.HexColor('#9CA3AF'),       # Cinza claro
    'gray_300': colors.HexColor('#D1D5DB'),       # Borda sutil
    'gray_200': colors.HexColor('#E5E7EB'),       # Fundo tabela alternado
    'gray_100': colors.HexColor('#F3F4F6'),       # Fundo muito claro
    'gray_50': colors.HexColor('#F9FAFB'),        # Quase branco
    
    # Básicas
    'white': colors.white,
    'black': colors.black,
}

# Timezone Brasília
TZ_BRASILIA = timezone(timedelta(hours=-3))

# URL base verificação
VERIFICATION_BASE_URL = "https://api.greengate.com.br/api/v1/reports/verify"


# ============================================================
# TRADUÇÕES
# ============================================================

TRANSLATIONS = {
    'pt': {
        'report_title': 'Relatório de Triagem Ambiental',
        'subtitle': 'Filtro Decisório Inicial — Bases Oficiais',
        'generated_at': 'Gerado em',

        'quick_summary': 'RESUMO EXECUTIVO',
        'decision_synthesis': 'SÍNTESE PARA TOMADA DE DECISÃO',
        'overall_situation': 'Situação Geral',
        'decision_supported': 'Decisão Suportada',
        'analysis_type': 'Tipo de Análise',
        'confidence_level': 'Nível de Confiança',

        'situation_compliant': 'APTA',
        'situation_non_compliant': 'NÃO APTA',
        'situation_attention': 'APTA COM RESTRIÇÕES',

        'decision_proceed': 'Prosseguir para próxima etapa',
        'decision_detailed_analysis': 'Requerer análise técnica detalhada',
        'decision_additional_verification': 'Verificação adicional recomendada',

        'analysis_automated': 'Triagem automatizada',

        'confidence_high': 'Alto (bases oficiais, sem sobreposição crítica)',
        'confidence_medium': 'Médio (alertas identificados, requer validação)',
        'confidence_low': 'Baixo (restrições críticas identificadas)',

        'report_purpose_title': 'FINALIDADE DO RELATÓRIO',
        'report_purpose_text': 'Este documento tem como objetivo realizar uma triagem ambiental automatizada, permitindo descartar, priorizar ou avançar áreas com base em bases públicas oficiais, antes de análises técnicas aprofundadas.',

        'status': 'Status',
        'status_compliant': 'CONFORME',
        'status_non_compliant': 'NÃO CONFORME',
        'status_attention': 'ATENÇÃO REQUERIDA',
        'score': 'Score de Conformidade',
        'score_qualification': '(nenhuma restrição crítica identificada)',
        'score_qualification_attention': '(alertas requerem verificação adicional)',
        'score_qualification_rejected': '(REPROVADO: restrições críticas identificadas)',
        'area': 'Área',
        'location': 'Localização',
        'esg_risk': 'Risco ESG',
        'esg_low': 'Baixo',
        'esg_medium': 'Médio', 
        'esg_high': 'Alto',
        
        'what_means_title': 'INTERPRETAÇÃO',
        'what_means_compliant': 'Esta área não apresenta restrições críticas nas bases oficiais consultadas. Score de conformidade aprovado (≥75). Apta para operações comerciais sob critérios EUDR.',
        'what_means_non_compliant': 'ATENÇÃO: Foram identificadas restrições críticas (Terra Indígena, Embargo IBAMA, PRODES pós-2020, UC Proteção Integral, Quilombola) que tornam a área NÃO APTA. Restrições críticas resultam em score zero independente de outros critérios. Recomenda-se análise detalhada antes de prosseguir.',
        'what_means_non_compliant_dynamic': 'ATENÇÃO: Foram identificadas restrições críticas que tornam a área NÃO APTA: {restrictions}. Restrições críticas resultam em score reduzido. Recomenda-se análise detalhada antes de prosseguir.',
        'what_means_attention': 'A área apresenta alertas ou restrições menores que requerem verificação adicional. Score de conformidade entre 60-74. Consulte os detalhes das verificações para decisão final.',
        'what_means_attention_dynamic': 'A área apresenta alertas que requerem verificação adicional: {alerts}. Consulte os detalhes para decisão final.',
        
        'map_title': 'LOCALIZAÇÃO',
        'map_legend': 'Legenda',
        'map_polygon': 'Área analisada',
        'map_overlap': 'Sobreposição identificada',

        'verifications_title': 'CRITÉRIOS DECISÓRIOS AVALIADOS',
        'criteria_all_clear': 'Critérios eliminatórios avaliados: Nenhuma restrição crítica detectada.',
        'score_explanation': 'critérios aprovados',
        'verification': 'Item de Verificação',
        'result': 'Resultado',
        'overlap': 'Área Afetada',
        'result_approved': 'Aprovado',
        'result_rejected': 'Reprovado',
        'result_attention': 'Atenção',
        'result_not_verified': 'Não verificado',
        
        'check_deforestation_prodes': 'Desmatamento PRODES',
        'check_deforestation_deter': 'Alertas DETER',
        'check_mapbiomas_alerts': 'Alertas MapBiomas',
        'check_indigenous_lands': 'Terras Indígenas',
        'check_conservation_units': 'Unidades de Conservação',
        'check_legal_reserve': 'Reserva Legal',
        'check_app': 'APP (Área de Preservação)',
        'check_quilombola': 'Territórios Quilombolas',
        'check_embargo': 'Embargos IBAMA',
        'check_slave_labor': 'Lista Trabalho Escravo',
        'check_car': 'Cadastro Ambiental Rural',
        
        'land_use_title': 'HISTÓRICO DE USO DO SOLO',
        'land_use_note': 'IMPORTANTE: Dados referentes ao município, não à área específica analisada. Fonte: MapBiomas Collection 10.',
        'year': 'Ano',
        'forest': 'Floresta',
        'pasture': 'Pastagem',
        'agriculture': 'Agricultura',
        
        'sources_title': 'FONTES DE DADOS',
        'source': 'Base',
        'institution': 'Instituição',
        'update': 'Atualização',
        'sources_footer_1': 'Fontes oficiais e de acesso público',
        'sources_footer_2': 'Atualização conforme data indicada na tabela',
        'sources_footer_3': 'Metodologia reproduzível e auditável',
        
        'disclaimer_title': 'ESCOPO E LIMITAÇÕES',
        'disclaimer_1': 'Este relatório suporta decisões preliminares de natureza comercial, contratual e de triagem, considerando exclusivamente as bases oficiais listadas.',
        'disclaimer_2': 'A análise possui precisão limitada pela resolução dos dados fonte (30m para satélite) e pela data de atualização das bases consultadas.',
        'disclaimer_3': 'Para decisões de alta criticidade, recomenda-se análise técnica aprofundada, vistorias in loco e laudos especializados complementares.',
        'disclaimer_4': 'Este documento não substitui análises técnicas especializadas de solo, biodiversidade, hidrologia ou outras disciplinas técnicas.',
        'disclaimer_5': 'A GreenGate utiliza metodologia reproduzível e auditável, garantindo transparência sobre fontes, data de consulta e critérios aplicados.',
        
        'verification_title': 'AUTENTICIDADE',
        'report_code': 'Código do Relatório',
        'integrity_hash': 'Hash de Integridade',
        'scan_qr': 'Escaneie para verificar autenticidade',
        
        # Metadados técnicos
        'technical_metadata': 'METADADOS TÉCNICOS',
        'input_hash': 'Hash do Polígono',
        'report_hash': 'Hash do Relatório',
        'engine_version': 'Versão do Motor',
        'generated_at_label': 'Gerado em',
        
        'page': 'Página',
        'of': 'de',
        'footer_text': 'GreenGate — Inteligência Ambiental',

        # Metadados do relatório
        'property': 'Propriedade',
        'plot': 'Talhão',
        'report_code_label': 'Código',
    },
    'en': {
        'report_title': 'Environmental Screening Report',
        'subtitle': 'Initial Decision Filter — Official Databases',
        'generated_at': 'Generated on',

        'quick_summary': 'EXECUTIVE SUMMARY',
        'decision_synthesis': 'DECISION-MAKING SYNTHESIS',
        'overall_situation': 'Overall Situation',
        'decision_supported': 'Supported Decision',
        'analysis_type': 'Analysis Type',
        'confidence_level': 'Confidence Level',

        'situation_compliant': 'SUITABLE',
        'situation_non_compliant': 'NOT SUITABLE',
        'situation_attention': 'SUITABLE WITH RESTRICTIONS',

        'decision_proceed': 'Proceed to next stage',
        'decision_detailed_analysis': 'Require detailed technical analysis',
        'decision_additional_verification': 'Additional verification recommended',

        'analysis_automated': 'Automated screening',

        'confidence_high': 'High (official databases, no critical overlaps)',
        'confidence_medium': 'Medium (alerts identified, validation required)',
        'confidence_low': 'Low (critical restrictions identified)',

        'report_purpose_title': 'REPORT PURPOSE',
        'report_purpose_text': 'This document aims to perform automated environmental screening, allowing areas to be discarded, prioritized, or advanced based on official public databases, prior to in-depth technical analyses.',

        'status': 'Status',
        'status_compliant': 'COMPLIANT',
        'status_non_compliant': 'NON-COMPLIANT',
        'status_attention': 'ATTENTION REQUIRED',
        'score': 'Compliance Score',
        'score_qualification': '(no critical restrictions identified)',
        'score_qualification_attention': '(alerts require additional verification)',
        'score_qualification_rejected': '(FAILED: critical restrictions identified)',
        'area': 'Area',
        'location': 'Location',
        'esg_risk': 'ESG Risk',
        'esg_low': 'Low',
        'esg_medium': 'Medium',
        'esg_high': 'High',
        
        'what_means_title': 'INTERPRETATION',
        'what_means_compliant': 'This area has no critical restrictions in the official databases consulted. Compliance score approved (≥75). Suitable for commercial operations under EUDR criteria.',
        'what_means_non_compliant': 'WARNING: Critical restrictions were identified (Indigenous Lands, IBAMA Embargo, PRODES post-2020, Integral Protection Conservation Units, Quilombola Territories) that make the area NOT SUITABLE. Critical restrictions result in zero score regardless of other criteria. Detailed analysis is recommended before proceeding.',
        'what_means_non_compliant_dynamic': 'WARNING: Critical restrictions were identified that make the area NOT SUITABLE: {restrictions}. Critical restrictions result in reduced score. Detailed analysis is recommended before proceeding.',
        'what_means_attention': 'The area has alerts or minor restrictions requiring additional verification. Compliance score between 60-74. See verification details for final decision.',
        'what_means_attention_dynamic': 'The area has alerts requiring additional verification: {alerts}. See details for final decision.',
        
        'map_title': 'LOCATION',
        'map_legend': 'Legend',
        'map_polygon': 'Analyzed area',
        'map_overlap': 'Identified overlap',

        'verifications_title': 'DECISION CRITERIA EVALUATED',
        'criteria_all_clear': 'Eliminatory criteria evaluated: No critical restrictions detected.',
        'score_explanation': 'criteria approved',
        'verification': 'Verification Item',
        'result': 'Result',
        'overlap': 'Affected Area',
        'result_approved': 'Approved',
        'result_rejected': 'Rejected',
        'result_attention': 'Attention',
        'result_not_verified': 'Not verified',
        
        'check_deforestation_prodes': 'PRODES Deforestation',
        'check_deforestation_deter': 'DETER Alerts',
        'check_mapbiomas_alerts': 'MapBiomas Alerts',
        'check_indigenous_lands': 'Indigenous Lands',
        'check_conservation_units': 'Conservation Units',
        'check_legal_reserve': 'Legal Reserve',
        'check_app': 'APP (Preservation Area)',
        'check_quilombola': 'Quilombola Territories',
        'check_embargo': 'IBAMA Embargoes',
        'check_slave_labor': 'Slave Labor List',
        'check_car': 'Rural Environmental Registry',
        
        'land_use_title': 'LAND USE HISTORY',
        'land_use_note': 'IMPORTANT: Municipality-level data, not specific to the analyzed area. Source: MapBiomas Collection 10.',
        'year': 'Year',
        'forest': 'Forest',
        'pasture': 'Pasture',
        'agriculture': 'Agriculture',
        
        'sources_title': 'DATA SOURCES',
        'source': 'Source',
        'institution': 'Institution',
        'update': 'Updated',
        'sources_footer_1': 'Official and publicly accessible sources',
        'sources_footer_2': 'Updated as per date shown in table',
        'sources_footer_3': 'Reproducible and auditable methodology',
        
        'disclaimer_title': 'SCOPE AND LIMITATIONS',
        'disclaimer_1': 'This report supports preliminary decisions of commercial, contractual, and screening nature, considering exclusively the official databases listed.',
        'disclaimer_2': 'Analysis precision is limited by source data resolution (30m for satellite) and the update date of consulted databases.',
        'disclaimer_3': 'For high-criticality decisions, in-depth technical analysis, on-site inspections, and specialized complementary reports are recommended.',
        'disclaimer_4': 'This document does not replace specialized technical analyses of soil, biodiversity, hydrology, or other technical disciplines.',
        'disclaimer_5': 'GreenGate uses reproducible and auditable methodology, ensuring transparency about sources, consultation date, and applied criteria.',
        
        'verification_title': 'AUTHENTICITY',
        'report_code': 'Report Code',
        'integrity_hash': 'Integrity Hash',
        'scan_qr': 'Scan to verify authenticity',
        
        # Technical metadata
        'technical_metadata': 'TECHNICAL METADATA',
        'input_hash': 'Polygon Hash',
        'report_hash': 'Report Hash',
        'engine_version': 'Engine Version',
        'generated_at_label': 'Generated at',
        
        'page': 'Page',
        'of': 'of',
        'footer_text': 'GreenGate — Environmental Intelligence',

        # Report metadata
        'property': 'Property',
        'plot': 'Plot',
        'report_code_label': 'Code',
    }
}

DATA_SOURCES_COMPACT = [
    {'key': 'prodes', 'name': 'PRODES', 'institution': 'INPE', 'date': '2024-08'},
    {'key': 'mapbiomas', 'name': 'MapBiomas Alerta', 'institution': 'MapBiomas', 'date': '2025-01'},
    {'key': 'indigenous', 'name': 'Terras Indígenas', 'institution': 'FUNAI', 'date': '2024-12'},
    {'key': 'uc', 'name': 'Unidades Conservação', 'institution': 'ICMBio', 'date': '2024-10'},
    {'key': 'embargo', 'name': 'Embargos', 'institution': 'IBAMA', 'date': '2025-01'},
    {'key': 'quilombola', 'name': 'Quilombolas', 'institution': 'INCRA', 'date': '2024-11'},
    # Hidrografia/APP removida - qualidade dos dados insatisfatória
    # Lista Suja removida - não está sendo verificada no MVP
]

CHECK_TYPE_MAP = {
    # Deforestation
    'deforestation_prodes': 'check_deforestation_prodes',
    'DEFORESTATION_PRODES': 'check_deforestation_prodes',
    'prodes': 'check_deforestation_prodes',
    'PRODES': 'check_deforestation_prodes',
    'checktype.deforestation_prodes': 'check_deforestation_prodes',
    'CheckType.DEFORESTATION_PRODES': 'check_deforestation_prodes',
    
    'deforestation_deter': 'check_deforestation_deter',
    'deter': 'check_deforestation_deter',
    'DETER': 'check_deforestation_deter',
    
    # MapBiomas
    'mapbiomas_alerts': 'check_mapbiomas_alerts',
    'deforestation_mapbiomas': 'check_mapbiomas_alerts',
    'mapbiomas': 'check_mapbiomas_alerts',
    'MAPBIOMAS': 'check_mapbiomas_alerts',
    'checktype.mapbiomas_alerts': 'check_mapbiomas_alerts',
    
    # Indigenous lands
    'terra_indigena': 'check_indigenous_lands',
    'indigenous_lands': 'check_indigenous_lands',
    'ti': 'check_indigenous_lands',
    'TI': 'check_indigenous_lands',
    'checktype.terra_indigena': 'check_indigenous_lands',
    'CheckType.TERRA_INDIGENA': 'check_indigenous_lands',
    
    # Conservation units
    'uc': 'check_conservation_units',
    'UC': 'check_conservation_units',
    'conservation_units': 'check_conservation_units',
    'unidade_conservacao': 'check_conservation_units',
    'unidades_conservacao': 'check_conservation_units',
    'checktype.uc': 'check_conservation_units',
    'checktype.unidade_conservacao': 'check_conservation_units',
    'CheckType.UC': 'check_conservation_units',
    'CheckType.Unidade Conservacao': 'check_conservation_units',  # Formato observado
    
    # Legal reserve
    'legal_reserve': 'check_legal_reserve',
    'reserva_legal': 'check_legal_reserve',
    'rl': 'check_legal_reserve',
    
    # APP/Hidrografia - REMOVIDO (qualidade insatisfatória)
    # Será reimplementado com dados oficiais MT

    # Quilombola
    'quilombola': 'check_quilombola',
    'QUILOMBOLA': 'check_quilombola',
    'checktype.quilombola': 'check_quilombola',
    
    # Embargo
    'embargo': 'check_embargo',
    'EMBARGO': 'check_embargo',
    'embargo_ibama': 'check_embargo',
    'embargos': 'check_embargo',
    'checktype.embargo': 'check_embargo',
    'checktype.embargo_ibama': 'check_embargo',
    
    # Slave labor
    'slave_labor': 'check_slave_labor',
    'trabalho_escravo': 'check_slave_labor',
    'lista_suja': 'check_slave_labor',
    
    # CAR
    'car': 'check_car',
    'CAR': 'check_car',
    'sicar': 'check_car',
}


# ============================================================
# FUNÇÕES UTILITÁRIAS
# ============================================================

def get_brasilia_time() -> datetime:
    return datetime.now(TZ_BRASILIA)


def generate_report_code() -> str:
    import random
    now = get_brasilia_time()
    timestamp = now.strftime('%Y%m%d%H%M%S')
    suffix = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=4))
    return f"GG-{timestamp}-{suffix}"


def generate_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def generate_geometry_hash(geometry: Dict) -> str:
    """Gera hash SHA-256 do polígono normalizado."""
    import json
    # Normalizar: ordenar keys, remover espaços
    normalized = json.dumps(geometry, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


# Versão do motor
ENGINE_VERSION = "8.2.0"
RULESET_VERSION = "2025-01-15"


def generate_qr_code(url: str, size: int = 150) -> Optional[io.BytesIO]:
    if not HAS_QRCODE:
        return None
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#111827", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer


def format_area(area_ha: float, lang: str = 'pt', show_zero: bool = True) -> str:
    """
    Formata área com precisão adequada:
    - ≥ 0.01 ha → mostrar em ha (2 casas)
    - 0 < ha < 0.01 → mostrar em m² + ha (ex: "30 m² (0,003 ha)")
    - = 0 → "0,00 ha" (padrão auditável)
    """
    if area_ha is None:
        return '—'

    if area_ha == 0:
        if lang == 'pt':
            return '0,00 ha'
        return '0.00 ha'
    
    # Área muito pequena: mostrar em m²
    if area_ha < 0.01:
        area_m2 = area_ha * 10000  # 1 ha = 10.000 m²
        if lang == 'pt':
            return f"{area_m2:,.0f} m² ({area_ha:,.4f} ha)".replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"{area_m2:,.0f} m² ({area_ha:,.4f} ha)"
    
    # Área normal
    if lang == 'pt':
        return f"{area_ha:,.2f} ha".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"{area_ha:,.2f} ha"


def get_check_name(check_type: str, lang: str = 'pt') -> str:
    """Retorna nome amigável do check, limpando formatos técnicos."""
    t = TRANSLATIONS.get(lang, TRANSLATIONS['pt'])
    
    # Limpar o check_type de prefixos e formatos estranhos
    clean = str(check_type)
    clean = clean.replace('CheckType.', '').replace('checktype.', '')
    clean = clean.replace('CheckStatus.', '').replace('checkstatus.', '')
    clean = clean.strip().lower()
    
    # Buscar no mapeamento
    key = CHECK_TYPE_MAP.get(clean)
    if not key:
        # Tentar com o original também
        key = CHECK_TYPE_MAP.get(check_type)
    if not key:
        # Tentar sem underscores
        key = CHECK_TYPE_MAP.get(clean.replace(' ', '_'))
    
    if key and key in t:
        return t[key]
    
    # Fallback: formatar o nome de forma legível
    fallback = clean.replace('_', ' ').replace('.', ' ').title()
    return fallback


def normalize_result(result: str, overlap_ha: float = 0, total_area_ha: float = 0) -> str:
    """
    Normaliza resultado para formato interno.
    
    Thresholds:
    - REJECTED: overlap ≥ 0.10 ha OU overlap ≥ 0.01% da área total
    - ATTENTION: 0 < overlap < 0.10 ha (interseção residual)
    - APPROVED: overlap = 0
    
    Se já vier como PASS/FAIL/WARNING, respeita (motor de validação decide).
    """
    clean = str(result).replace('CheckStatus.', '').replace('checkstatus.', '').strip().upper()
    
    # Se já tem status definido, respeitar
    if clean in ('PASS', 'PASSED', 'OK', 'APPROVED', 'APROVADO'):
        return 'APPROVED'
    elif clean in ('FAIL', 'FAILED', 'REJECTED', 'REPROVADO'):
        return 'REJECTED'
    elif clean in ('WARNING', 'ATTENTION', 'ALERT', 'ATENCAO', 'ATENÇÃO', 'REVIEW'):
        return 'ATTENTION'
    elif clean in ('SKIP', 'SKIPPED', 'NA', 'N/A', 'NOT_VERIFIED'):
        return 'SKIP'
    
    # Se não tem status mas tem overlap, calcular baseado em threshold
    if overlap_ha is not None and overlap_ha > 0:
        overlap_pct = (overlap_ha / total_area_ha * 100) if total_area_ha > 0 else 0
        
        # FAIL: overlap significativo
        if overlap_ha >= 0.10 or overlap_pct >= 0.01:
            return 'REJECTED'
        # REVIEW: overlap residual (pode ser erro de precisão)
        else:
            return 'ATTENTION'
    
    return 'SKIP'


def normalize_result_simple(result: str) -> str:
    """Normaliza resultado sem considerar área (compatibilidade)."""
    return normalize_result(result, 0, 0)


def get_result_display(result: str, lang: str = 'pt', overlap_ha: float = 0, total_area_ha: float = 0) -> Tuple[str, str, colors.Color, colors.Color]:
    """Retorna (texto, ícone, cor_texto, cor_fundo) para resultado."""
    t = TRANSLATIONS.get(lang, TRANSLATIONS['pt'])
    normalized = normalize_result(result, overlap_ha, total_area_ha)
    
    if normalized == 'APPROVED':
        return (t['result_approved'], '✓', COLORS['success'], COLORS['success_bg'])
    elif normalized == 'REJECTED':
        return (t['result_rejected'], '✗', COLORS['danger'], COLORS['danger_bg'])
    elif normalized == 'ATTENTION':
        return (t['result_attention'], '!', COLORS['warning'], COLORS['warning_bg'])
    else:
        return (t['result_not_verified'], '○', COLORS['gray_500'], COLORS['gray_100'])


def calculate_score(checks: List[Dict], total_area_ha: float = 0) -> Tuple[int, int, int, int]:
    """
    Calcula score baseado nos checks.
    
    Returns:
        (score, total_checks, approved_count, rejected_count)
    
    Regras:
    - Base: 100 pontos
    - Cada Atenção: -5 pontos
    - Cada Reprovado: -15 pontos
    - Mínimo: 0
    """
    if not checks:
        return (0, 0, 0, 0)
    
    total = len(checks)
    approved = 0
    rejected = 0
    attention = 0
    
    for check in checks:
        result = check.get('result', check.get('status', ''))
        overlap_ha = check.get('overlap_area_ha', check.get('overlap_area', 0)) or 0
        normalized = normalize_result(result, overlap_ha, total_area_ha)
        
        if normalized == 'APPROVED':
            approved += 1
        elif normalized == 'REJECTED':
            rejected += 1
        elif normalized == 'ATTENTION':
            attention += 1
    
    # Calcular score
    score = 100 - (attention * 5) - (rejected * 15)
    score = max(0, score)
    
    return (score, total, approved, rejected)


def get_overall_status(score: int, rejected_count: int) -> str:
    """
    Determina status geral baseado no score.

    ATENÇÃO: Esta função é um fallback. O status correto já vem
    do validation_engine que aplica a lógica completa (incluindo blockers críticos).

    Thresholds:
    - Score ≥ 75: COMPLIANT (aprovado)
    - Score 60-74: ATTENTION (apta com restrições)
    - Score < 60: NON_COMPLIANT (reprovado)
    """
    if score >= 75:
        return 'COMPLIANT'
    elif score >= 60:
        return 'ATTENTION'
    else:
        return 'NON_COMPLIANT'


def get_esg_risk(score: int, rejected_count: int) -> str:
    """
    Determina risco ESG baseado no score.

    Alinhado com os novos thresholds:
    - Score < 60: HIGH (reprovado)
    - Score 60-74: MEDIUM (atenção)
    - Score ≥ 75: LOW (aprovado)
    """
    if score < 60:
        return 'HIGH'
    elif score < 75:
        return 'MEDIUM'
    return 'LOW'


# ============================================================
# ESTILOS PREMIUM
# ============================================================

def create_styles() -> Dict[str, ParagraphStyle]:
    return {
        'title': ParagraphStyle(
            'Title',
            fontSize=24,
            fontName='Helvetica-Bold',
            textColor=COLORS['gray_900'],
            alignment=TA_CENTER,
            spaceAfter=10*mm,
        ),
        'subtitle': ParagraphStyle(
            'Subtitle',
            fontSize=10,
            fontName='Helvetica',
            textColor=COLORS['gray_500'],
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=6*mm,
        ),
        'section_title': ParagraphStyle(
            'SectionTitle',
            fontSize=11,
            fontName='Helvetica-Bold',
            textColor=COLORS['gray_900'],
            spaceBefore=5*mm,
            spaceAfter=2*mm,
        ),
        'body': ParagraphStyle(
            'Body',
            fontSize=9,
            fontName='Helvetica',
            textColor=COLORS['gray_700'],
            alignment=TA_JUSTIFY,
            leading=13,
        ),
        'body_small': ParagraphStyle(
            'BodySmall',
            fontSize=8,
            fontName='Helvetica',
            textColor=COLORS['gray_500'],
            leading=11,
        ),
        'centered': ParagraphStyle(
            'Centered',
            fontSize=9,
            fontName='Helvetica',
            textColor=COLORS['gray_700'],
            alignment=TA_CENTER,
        ),
        'label': ParagraphStyle(
            'Label',
            fontSize=8,
            fontName='Helvetica',
            textColor=COLORS['gray_500'],
        ),
        'value': ParagraphStyle(
            'Value',
            fontSize=10,
            fontName='Helvetica-Bold',
            textColor=COLORS['gray_900'],
        ),
        'footer': ParagraphStyle(
            'Footer',
            fontSize=7,
            fontName='Helvetica',
            textColor=COLORS['gray_400'],
            alignment=TA_CENTER,
        ),
    }


# ============================================================
# COMPONENTES PREMIUM
# ============================================================

def create_summary_card(
    status: str,
    score: int,
    area_ha: float,
    municipality: str,
    state: str,
    esg_risk: str,
    lang: str = 'pt',
    width: float = 170*mm
) -> Table:
    """Cartão de resumo com estilo executivo premium."""
    t = TRANSLATIONS.get(lang, TRANSLATIONS['pt'])
    
    # Status styling - mais sutil
    if status == 'COMPLIANT':
        status_text = t['status_compliant']
        status_color = COLORS['success']
        border_color = COLORS['gray_300']  # Borda sutil
        bg_color = COLORS['white']         # Fundo branco
        score_qual = t['score_qualification']
    elif status == 'NON_COMPLIANT':
        status_text = t['status_non_compliant']
        status_color = COLORS['danger']
        border_color = COLORS['danger_light']
        bg_color = COLORS['danger_bg']
        score_qual = t['score_qualification_rejected']
    else:
        status_text = t['status_attention']
        status_color = COLORS['warning']
        border_color = COLORS['warning_light']  # Âmbar claro #FBBF24
        bg_color = COLORS['warning_bg']         # Dourado pálido #FFF9E6
        score_qual = t['score_qualification_attention']
    
    # ESG Risk
    esg_text = t.get(f'esg_{esg_risk.lower()}', esg_risk)
    if esg_risk == 'HIGH':
        esg_color = COLORS['danger']
    elif esg_risk == 'MEDIUM':
        esg_color = COLORS['warning']
    else:
        esg_color = COLORS['success']
    
    location = f"{municipality} — {state}" if municipality else state
    
    # Layout em 2 linhas: Status grande em cima, métricas embaixo
    
    # Linha 1: Status
    status_para = Paragraph(
        f'<font face="Helvetica-Bold" size="18" color="{status_color.hexval()}">{status_text}</font>',
        ParagraphStyle('Status', alignment=TA_CENTER)
    )
    
    # Linha 2: Grid de métricas
    metric_label_style = ParagraphStyle('MetricLabel', fontSize=8, textColor=COLORS['gray_500'], alignment=TA_CENTER)
    metric_value_style = ParagraphStyle('MetricValue', fontSize=11, fontName='Helvetica-Bold', alignment=TA_CENTER)
    
    metrics_data = [
        [
            Paragraph(t['score'], metric_label_style),
            Paragraph(t['area'], metric_label_style),
            Paragraph(t['location'], metric_label_style),
            Paragraph(t['esg_risk'], metric_label_style),
        ],
        [
            Paragraph(f'<font face="Helvetica-Bold" size="14" color="{status_color.hexval()}">{score}</font><font size="10" color="#6B7280">/100</font>', metric_value_style),
            Paragraph(f'<font face="Helvetica-Bold" size="11" color="#111827">{format_area(area_ha, lang)}</font>', metric_value_style),
            Paragraph(f'<font size="10" color="#374151">{location}</font>', metric_value_style),
            Paragraph(f'<font face="Helvetica-Bold" size="11" color="{esg_color.hexval()}">{esg_text}</font>', metric_value_style),
        ],
        [
            Paragraph(f'<font size="7" color="#6B7280"><i>{score_qual}</i></font>', ParagraphStyle('ScoreQual', fontSize=7, alignment=TA_CENTER)),
            Paragraph('', ParagraphStyle('Empty')),
            Paragraph('', ParagraphStyle('Empty')),
            Paragraph('', ParagraphStyle('Empty')),
        ],
    ]
    
    metrics_table = Table(metrics_data, colWidths=[width*0.18, width*0.24, width*0.38, width*0.20])
    metrics_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 0),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
        ('TOPPADDING', (0, 1), (-1, 1), 2),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 0),
    ]))
    
    # Montar cartão
    card_content = [
        [status_para],
        [Spacer(1, 4*mm)],
        [metrics_table],
    ]
    
    card = Table(card_content, colWidths=[width])
    card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg_color),
        ('BOX', (0, 0), (-1, -1), 0.75, border_color),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 15),
        ('RIGHTPADDING', (0, 0), (-1, -1), 15),
    ]))
    
    return card


def create_decision_card(
    status: str,
    rejected_count: int,
    lang: str = 'pt',
    width: float = 170*mm
) -> Table:
    """
    Cartão de síntese para tomada de decisão.

    Objetivo: Deixar claro que este é um filtro automatizado inicial,
    não uma análise técnica completa.
    """
    t = TRANSLATIONS.get(lang, TRANSLATIONS['pt'])

    # Determinar situação, decisão e confiança baseado no status
    if status == 'COMPLIANT':
        situation_text = t['situation_compliant']
        situation_color = COLORS['success']
        decision_text = t['decision_proceed']
        confidence_text = t['confidence_high']
        confidence_color = COLORS['success']
        bg_color = COLORS['success_bg']
        border_color = COLORS['success']
    elif status == 'NON_COMPLIANT':
        situation_text = t['situation_non_compliant']
        situation_color = COLORS['danger']
        decision_text = t['decision_detailed_analysis']
        confidence_text = t['confidence_low']
        confidence_color = COLORS['danger']
        bg_color = COLORS['danger_bg']
        border_color = COLORS['danger']
    else:  # ATTENTION
        situation_text = t['situation_attention']
        situation_color = COLORS['warning']
        decision_text = t['decision_additional_verification']
        confidence_text = t['confidence_medium']
        confidence_color = COLORS['warning']
        bg_color = COLORS['warning_bg']
        border_color = COLORS['warning']

    label_style = ParagraphStyle('DecisionLabel', fontSize=8, textColor=COLORS['gray_600'], alignment=TA_LEFT)
    value_style = ParagraphStyle('DecisionValue', fontSize=10, fontName='Helvetica-Bold', alignment=TA_LEFT)

    rows_data = [
        [
            Paragraph(f"<font size='8' color='#4B5563'>{t['overall_situation']}:</font>", label_style),
            Paragraph(f"<font face='Helvetica-Bold' size='12' color='{situation_color.hexval()}'>{situation_text}</font>", value_style),
        ],
        [
            Paragraph(f"<font size='8' color='#4B5563'>{t['decision_supported']}:</font>", label_style),
            Paragraph(f"<font size='10' color='#111827'>{decision_text}</font>", value_style),
        ],
        [
            Paragraph(f"<font size='8' color='#4B5563'>{t['analysis_type']}:</font>", label_style),
            Paragraph(f"<font size='10' color='#374151'>{t['analysis_automated']}</font>", value_style),
        ],
        [
            Paragraph(f"<font size='8' color='#4B5563'>{t['confidence_level']}:</font>", label_style),
            Paragraph(f"<font size='9' color='{confidence_color.hexval()}'>{confidence_text}</font>", value_style),
        ],
    ]

    decision_table = Table(rows_data, colWidths=[width*0.30, width*0.70])
    decision_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    # Wrapper com fundo e borda
    card = Table([[decision_table]], colWidths=[width])
    card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg_color),
        ('BOX', (0, 0), (-1, -1), 1.5, border_color),
        ('TOPPADDING', (0, 0), (-1, -1), 15),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
        ('LEFTPADDING', (0, 0), (-1, -1), 18),
        ('RIGHTPADDING', (0, 0), (-1, -1), 18),
    ]))

    return card


def create_map_drawing(
    polygon_coords: List[List[float]],
    overlaps: List[Dict] = None,
    width: float = 170*mm,
    height: float = 75*mm
) -> Drawing:
    """Mapa com estilo mais clean."""
    drawing = Drawing(width, height)
    
    # Fundo muito sutil
    drawing.add(Rect(0, 0, width, height, 
                     fillColor=COLORS['gray_50'], 
                     strokeColor=COLORS['gray_200'], 
                     strokeWidth=0.5))
    
    if not polygon_coords or len(polygon_coords) < 3:
        drawing.add(String(width/2, height/2, "Localização não disponível", 
                          fontSize=9, fillColor=COLORS['gray_400'], textAnchor='middle'))
        return drawing
    
    # Calcular bounds
    lons = [p[0] for p in polygon_coords]
    lats = [p[1] for p in polygon_coords]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    
    padding = 20
    draw_width = width - 2 * padding
    draw_height = height - 2 * padding
    
    lon_range = max_lon - min_lon or 0.001
    lat_range = max_lat - min_lat or 0.001
    
    scale_x = draw_width / lon_range
    scale_y = draw_height / lat_range
    scale = min(scale_x, scale_y) * 0.85
    
    center_x = (min_lon + max_lon) / 2
    center_y = (min_lat + max_lat) / 2
    offset_x = width / 2
    offset_y = height / 2
    
    def to_screen(lon, lat):
        x = offset_x + (lon - center_x) * scale
        y = offset_y + (lat - center_y) * scale
        return (x, y)
    
    # Sobreposições (vermelho suave)
    if overlaps:
        for overlap in overlaps:
            overlap_coords = overlap.get('coords', [])
            if overlap_coords and len(overlap_coords) >= 3:
                points = []
                for coord in overlap_coords:
                    x, y = to_screen(coord[0], coord[1])
                    points.extend([x, y])
                
                drawing.add(Polygon(
                    points,
                    fillColor=colors.Color(0.86, 0.15, 0.15, alpha=0.25),
                    strokeColor=COLORS['danger'],
                    strokeWidth=1.5
                ))
    
    # Polígono principal (verde elegante)
    points = []
    for coord in polygon_coords:
        x, y = to_screen(coord[0], coord[1])
        points.extend([x, y])
    
    drawing.add(Polygon(
        points,
        fillColor=colors.Color(0.02, 0.59, 0.41, alpha=0.2),  # Verde translúcido
        strokeColor=COLORS['primary'],
        strokeWidth=2
    ))
    
    # Centróide
    cx, cy = to_screen(center_x, center_y)
    drawing.add(Circle(cx, cy, 3, fillColor=COLORS['primary_dark'], strokeColor=COLORS['white'], strokeWidth=1))
    
    # Coordenadas
    coord_text = f"{abs(center_y):.4f}°{'S' if center_y < 0 else 'N'}, {abs(center_x):.4f}°{'W' if center_x < 0 else 'E'}"
    drawing.add(String(width - 8, 8, coord_text, fontSize=7, fillColor=COLORS['gray_400'], textAnchor='end'))
    
    return drawing


def create_verification_table(
    checks: List[Dict],
    lang: str = 'pt',
    width: float = 170*mm,
    total_area_ha: float = 0
) -> Table:
    """Tabela de verificações com estilo executivo."""
    t = TRANSLATIONS.get(lang, TRANSLATIONS['pt'])
    
    # Header com cinza escuro (não verde)
    header_style = ParagraphStyle('TH', fontSize=8, fontName='Helvetica-Bold', textColor=COLORS['white'])
    
    rows = [[
        Paragraph(t['verification'], header_style),
        Paragraph(t['result'], header_style),
        Paragraph(t['overlap'], header_style),
    ]]
    
    for check in checks:
        check_type = str(check.get('check_type', check.get('type', '')))
        check_name = get_check_name(check_type, lang)
        result = check.get('result', check.get('status', ''))
        overlap_ha = check.get('overlap_area_ha', check.get('overlap_area', 0)) or 0
        
        # Usar nova lógica de resultado com threshold
        result_text, icon, text_color, bg_color = get_result_display(result, lang, overlap_ha, total_area_ha)
        
        # Formatar área com precisão adequada
        overlap_text = format_area(overlap_ha, lang, show_zero=False)
        
        rows.append([
            Paragraph(f"<font size='9' color='#374151'>{check_name}</font>", ParagraphStyle('TD')),
            Paragraph(f"<font face='Helvetica-Bold' size='9' color='{text_color.hexval()}'>{icon} {result_text}</font>", 
                     ParagraphStyle('TDResult', alignment=TA_CENTER)),
            Paragraph(f"<font size='8' color='#6B7280'>{overlap_text}</font>", 
                     ParagraphStyle('TDOverlap', alignment=TA_RIGHT)),
        ])
    
    table = Table(rows, colWidths=[width*0.55, width*0.25, width*0.20])
    
    style = [
        # Header cinza escuro
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['gray_700']),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
        
        # Alignment
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        
        # Bordas sutis
        ('LINEBELOW', (0, 0), (-1, 0), 1, COLORS['gray_700']),
        ('LINEBELOW', (0, 1), (-1, -1), 0.5, COLORS['gray_200']),
    ]
    
    # Fundo alternado muito sutil
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(('BACKGROUND', (0, i), (-1, i), COLORS['gray_50']))
    
    table.setStyle(TableStyle(style))
    return table


def create_land_use_table(
    history: List[Dict],
    lang: str = 'pt',
    width: float = 170*mm
) -> Optional[Table]:
    """Tabela de uso do solo com estilo executivo."""
    if not history:
        return None
    
    t = TRANSLATIONS.get(lang, TRANSLATIONS['pt'])
    
    header_style = ParagraphStyle('TH', fontSize=8, fontName='Helvetica-Bold', textColor=COLORS['white'])
    
    rows = [[
        Paragraph(t['year'], header_style),
        Paragraph(t['forest'], header_style),
        Paragraph(t['pasture'], header_style),
        Paragraph(t['agriculture'], header_style),
    ]]
    
    sorted_history = sorted(history, key=lambda x: x.get('year', 0), reverse=True)[:6]
    
    for record in sorted_history:
        year = record.get('year', '-')
        forest = float(record.get('forest_pct', 0) or 0)
        pasture = float(record.get('pasture_pct', 0) or 0)
        agriculture = float(record.get('agriculture_pct', 0) or 0)
        
        # Cores mais suaves para floresta
        if forest >= 50:
            forest_color = COLORS['success'].hexval()
        elif forest >= 30:
            forest_color = COLORS['warning'].hexval()
        else:
            forest_color = COLORS['danger'].hexval()
        
        cell_style = ParagraphStyle('TD', fontSize=9, alignment=TA_CENTER)
        
        rows.append([
            Paragraph(f"<font size='9'><b>{year}</b></font>", cell_style),
            Paragraph(f"<font size='9' color='{forest_color}'><b>{forest:.1f}%</b></font>", cell_style),
            Paragraph(f"<font size='9' color='#6B7280'>{pasture:.1f}%</font>", cell_style),
            Paragraph(f"<font size='9' color='#6B7280'>{agriculture:.1f}%</font>", cell_style),
        ])
    
    table = Table(rows, colWidths=[width*0.2, width*0.27, width*0.27, width*0.26])
    
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['gray_700']),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, 0), 1, COLORS['gray_700']),
        ('LINEBELOW', (0, 1), (-1, -1), 0.5, COLORS['gray_200']),
    ]
    
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(('BACKGROUND', (0, i), (-1, i), COLORS['gray_50']))
    
    table.setStyle(TableStyle(style))
    return table


def create_sources_table(lang: str = 'pt', width: float = 170*mm, data_freshness: Optional[Dict[str, datetime]] = None) -> Table:
    """
    Tabela de fontes com estilo executivo.

    Args:
        lang: Idioma (pt ou en)
        width: Largura da tabela
        data_freshness: Dict com datas de atualização reais do banco {layer_type: datetime}
    """
    t = TRANSLATIONS.get(lang, TRANSLATIONS['pt'])

    header_style = ParagraphStyle('TH', fontSize=8, fontName='Helvetica-Bold', textColor=COLORS['white'])

    rows = [[
        Paragraph(t['source'], header_style),
        Paragraph(t['institution'], header_style),
        Paragraph(t['update'], header_style),
    ]]

    # Mapeamento de layer_type para nomes amigáveis e instituições
    layer_info = {
        'prodes': {'name': 'PRODES', 'institution': 'INPE'},
        'mapbiomas': {'name': 'MapBiomas Alerta', 'institution': 'MapBiomas'},
        'terra_indigena': {'name': 'Terras Indígenas', 'institution': 'FUNAI'},
        'uc': {'name': 'Unidades Conservação', 'institution': 'ICMBio'},
        'embargo_ibama': {'name': 'Embargos', 'institution': 'IBAMA'},
        'quilombola': {'name': 'Quilombolas', 'institution': 'INCRA'},
    }

    # Se tem data_freshness do banco, usar as datas reais
    if data_freshness:
        for layer_type, date_updated in sorted(data_freshness.items()):
            info = layer_info.get(layer_type, {'name': layer_type, 'institution': '—'})

            # Formatar data como DD/MM/YYYY
            if isinstance(date_updated, datetime):
                date_str = date_updated.strftime('%d/%m/%Y')
            else:
                date_str = '—'

            rows.append([
                Paragraph(f"<font size='8' color='#374151'>{info['name']}</font>", ParagraphStyle('TD')),
                Paragraph(f"<font size='8' color='#6B7280'>{info['institution']}</font>", ParagraphStyle('TD')),
                Paragraph(f"<font size='8' color='#6B7280'>{date_str}</font>", ParagraphStyle('TD', alignment=TA_CENTER)),
            ])
    else:
        # Fallback: usar dados estáticos (compatibilidade)
        for source in DATA_SOURCES_COMPACT:
            rows.append([
                Paragraph(f"<font size='8' color='#374151'>{source['name']}</font>", ParagraphStyle('TD')),
                Paragraph(f"<font size='8' color='#6B7280'>{source['institution']}</font>", ParagraphStyle('TD')),
                Paragraph(f"<font size='8' color='#6B7280'>{source['date']}</font>", ParagraphStyle('TD', alignment=TA_CENTER)),
            ])

    table = Table(rows, colWidths=[width*0.40, width*0.35, width*0.25])

    style = [
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['gray_700']),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('LINEBELOW', (0, 0), (-1, 0), 1, COLORS['gray_700']),
        ('LINEBELOW', (0, 1), (-1, -1), 0.5, COLORS['gray_200']),
    ]

    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(('BACKGROUND', (0, i), (-1, i), COLORS['gray_50']))

    table.setStyle(TableStyle(style))
    return table


# ============================================================
# GERAÇÃO DO PDF
# ============================================================

async def generate_due_diligence_report(
    validation_result: Dict[str, Any] = None,
    property_info: Optional[Dict[str, Any]] = None,
    lang: str = 'pt',
    db = None,
) -> Tuple[bytes, str, str]:
    """Gera relatório PDF executivo premium."""

    if validation_result is None:
        validation_result = {}
    if property_info is None:
        property_info = {}

    t = TRANSLATIONS.get(lang, TRANSLATIONS['pt'])
    report_code = generate_report_code()

    # Buscar datas de atualização dos dados
    data_freshness = None
    if db is not None:
        try:
            from app.services.data_freshness import get_data_freshness
            data_freshness = await get_data_freshness(db)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao buscar data_freshness: {e}")
            # Continua sem data_freshness (usa fallback estático)
    
    # Extrair dados
    checks = validation_result.get('checks', [])
    area_ha = validation_result.get('area_ha', 0) or 0

    farm_name = property_info.get('farm_name', '')
    plot_name = property_info.get('plot_name', '')
    municipality = property_info.get('municipality', '')
    state = property_info.get('state', 'MT')
    land_use_history = property_info.get('land_use_history', [])

    # USAR o score que já vem do validation_result (já foi calculado corretamente com pesos)
    score = validation_result.get('risk_score', 0)

    # Calcular apenas as contagens para o PDF
    _, total_checks, approved_count, rejected_count = calculate_score(checks, area_ha)

    # USAR o status que já vem do validation_result (já aplicou lógica de blockers críticos)
    overall_status = validation_result.get('status', 'rejected')

    # Normalizar status para o formato do PDF
    status_map = {
        'approved': 'COMPLIANT',
        'warning': 'ATTENTION',
        'rejected': 'NON_COMPLIANT',
    }
    overall_status = status_map.get(overall_status, 'NON_COMPLIANT')

    # Calcular risco ESG baseado no score correto
    esg_risk = get_esg_risk(score, rejected_count)
    
    # Gerar hash do polígono de input
    geometry = validation_result.get('geometry', {})
    input_hash = generate_geometry_hash(geometry) if geometry else None
    
    # Coordenadas
    polygon_coords = []
    geometry = validation_result.get('geometry', {})
    if geometry and 'coordinates' in geometry:
        coords = geometry.get('coordinates', [])
        if coords and len(coords) > 0:
            polygon_coords = coords[0] if isinstance(coords[0][0], list) else coords
    
    # Sobreposições - usar intersection_geometries (novo) ou overlap_geometry (legado)
    overlaps = []
    for check in checks:
        overlap_ha = check.get('overlap_area_ha', 0) or 0
        if overlap_ha > 0:
            # Tentar primeiro intersection_geometries (novo formato)
            intersection_geoms = check.get('intersection_geometries', [])
            if intersection_geoms:
                for geom_item in intersection_geoms:
                    geom = geom_item.get('geometry', {})
                    if geom and 'coordinates' in geom:
                        geom_type = geom.get('type', 'Polygon')
                        if geom_type == 'Polygon':
                            coords = geom['coordinates']
                            if coords and len(coords) > 0:
                                overlaps.append({
                                    'coords': coords[0],
                                    'type': check.get('check_type', ''),
                                    'area_ha': geom_item.get('overlap_ha', 0),
                                    'name': geom_item.get('name', ''),
                                })
                        elif geom_type == 'MultiPolygon':
                            # Desenhar cada polígono do MultiPolygon
                            for poly_coords in geom['coordinates']:
                                if poly_coords and len(poly_coords) > 0:
                                    overlaps.append({
                                        'coords': poly_coords[0],
                                        'type': check.get('check_type', ''),
                                        'area_ha': geom_item.get('overlap_ha', 0),
                                        'name': geom_item.get('name', ''),
                                    })
            else:
                # Fallback para formato legado (overlap_geometry)
                overlap_coords = check.get('overlap_geometry', {}).get('coordinates', [])
                if overlap_coords:
                    overlaps.append({
                        'coords': overlap_coords[0] if overlap_coords else [],
                        'type': check.get('check_type', ''),
                        'area_ha': overlap_ha,
                    })
    
    # Data
    now = get_brasilia_time()
    date_str = now.strftime('%d/%m/%Y às %H:%M') if lang == 'pt' else now.strftime('%m/%d/%Y at %H:%M')
    
    # Criar PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=15*mm,
        bottomMargin=15*mm,
    )

    # Metadados do PDF
    doc.title = f"GreenGate - {t['report_title']}"
    doc.author = "GreenGate Environmental Screening"
    doc.subject = t['subtitle']
    doc.creator = "GreenGate API - greengate.com.br"

    width = doc.width
    styles = create_styles()
    elements = []
    
    # ================================================================
    # PÁGINA 1 - CAPA EXECUTIVA
    # ================================================================
    
    # Logo texto - verde escuro
    elements.append(Paragraph(
        '<font face="Helvetica-Bold" size="16" color="#059669">GreenGate</font>',
        ParagraphStyle('Logo', alignment=TA_CENTER, spaceAfter=10*mm)
    ))
    
    # Título principal
    elements.append(Paragraph(t['report_title'], styles['title']))

    # Subtítulo (espaço adequado)
    elements.append(Paragraph(t['subtitle'], styles['subtitle']))

    # NOVO: Finalidade do Relatório
    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph(f"<b>{t['report_purpose_title']}</b>", styles['section_title']))
    purpose_table = Table([[Paragraph(f"<font size='9' color='#374151'>{t['report_purpose_text']}</font>", styles['body'])]], colWidths=[width])
    purpose_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLORS['gray_50']),
        ('BOX', (0, 0), (-1, -1), 0.5, COLORS['gray_300']),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(purpose_table)

    # Linha visível
    elements.append(Spacer(1, 5*mm))
    elements.append(HRFlowable(width=width*0.4, thickness=1.2, color=COLORS['gray_200'], hAlign='CENTER', spaceAfter=8*mm))
    
    # Cartão de Resumo
    elements.append(Paragraph(f"<b>{t['quick_summary']}</b>", styles['section_title']))
    summary_card = create_summary_card(
        status=overall_status,
        score=score,
        area_ha=area_ha,
        municipality=municipality,
        state=state,
        esg_risk=esg_risk,
        lang=lang,
        width=width
    )
    elements.append(summary_card)
    elements.append(Spacer(1, 6*mm))

    # NOVO: Síntese para Tomada de Decisão
    elements.append(Paragraph(f"<b>{t['decision_synthesis']}</b>", styles['section_title']))
    decision_card = create_decision_card(
        status=overall_status,
        rejected_count=rejected_count,
        lang=lang,
        width=width
    )
    elements.append(decision_card)
    elements.append(Spacer(1, 6*mm))

    # Interpretação DINÂMICA
    elements.append(Paragraph(f"<b>{t['what_means_title']}</b>", styles['section_title']))

    # Construir interpretação baseada nos checks reais
    if overall_status == 'COMPLIANT':
        what_means = t['what_means_compliant']
    elif overall_status == 'NON_COMPLIANT':
        # Listar restrições críticas encontradas
        critical_checks = []
        for check in checks:
            result = check.get('result', check.get('status', ''))
            overlap_ha = check.get('overlap_area_ha', check.get('overlap_area', 0)) or 0
            normalized = normalize_result(result, overlap_ha, area_ha)
            if normalized == 'REJECTED':
                check_name = get_check_name(check.get('check_type', ''), lang)
                critical_checks.append(f"{check_name} ({format_area(overlap_ha, lang)})")

        if critical_checks:
            restrictions_list = ', '.join(critical_checks)
            what_means = t['what_means_non_compliant_dynamic'].format(restrictions=restrictions_list)
        else:
            what_means = t['what_means_non_compliant']
    else:
        # Listar alertas de atenção
        attention_checks = []
        for check in checks:
            result = check.get('result', check.get('status', ''))
            overlap_ha = check.get('overlap_area_ha', check.get('overlap_area', 0)) or 0
            normalized = normalize_result(result, overlap_ha, area_ha)
            if normalized == 'ATTENTION':
                check_name = get_check_name(check.get('check_type', ''), lang)
                attention_checks.append(f"{check_name} ({format_area(overlap_ha, lang)})")

        if attention_checks:
            alerts_list = ', '.join(attention_checks)
            what_means = t['what_means_attention_dynamic'].format(alerts=alerts_list)
        else:
            what_means = t['what_means_attention']
    
    # Box simples com borda sutil
    what_means_table = Table([[Paragraph(f"<font size='9' color='#374151'>{what_means}</font>", styles['body'])]], colWidths=[width])
    what_means_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLORS['gray_50']),
        ('BOX', (0, 0), (-1, -1), 0.5, COLORS['gray_300']),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(what_means_table)
    elements.append(Spacer(1, 5*mm))
    
    # Mapa
    elements.append(Paragraph(f"<b>{t['map_title']}</b>", styles['section_title']))
    map_drawing = create_map_drawing(polygon_coords, overlaps, width, 70*mm)
    elements.append(map_drawing)
    
    # Legenda se houver sobreposições
    if overlaps:
        legend_text = f"<font size='7' color='#9CA3AF'>● {t['map_polygon']}  ·  </font><font size='7' color='#DC2626'>● {t['map_overlap']}</font>"
        elements.append(Paragraph(legend_text, ParagraphStyle('Legend', alignment=TA_CENTER, spaceBefore=2*mm)))
    
    # Metadados
    elements.append(Spacer(1, 5*mm))
    meta_parts = []
    if farm_name:
        meta_parts.append(f"<b>{t['property']}:</b> {farm_name}")
    if plot_name:
        meta_parts.append(f"<b>{t['plot']}:</b> {plot_name}")
    meta_parts.append(f"<b>{t['report_code_label']}:</b> {report_code}")
    
    elements.append(Paragraph(
        f"<font size='8' color='#6B7280'>{' · '.join(meta_parts)}</font>",
        ParagraphStyle('Meta', alignment=TA_CENTER)
    ))
    elements.append(Paragraph(
        f"<font size='7' color='#9CA3AF'>{t['generated_at']} {date_str} (Brasília)</font>",
        ParagraphStyle('DateTime', alignment=TA_CENTER, spaceBefore=2*mm)
    ))
    
    elements.append(PageBreak())
    
    # ================================================================
    # PÁGINA 2 - VERIFICAÇÕES + USO DO SOLO
    # ================================================================
    
    elements.append(Paragraph(f"<b>{t['verifications_title']}</b>", styles['section_title']))

    # Se todos os critérios passaram, mostrar mensagem especial
    if overall_status == 'COMPLIANT' and rejected_count == 0:
        criteria_text = f"<font size='9' color='#059669'><b>{t['criteria_all_clear']}</b></font>"
        elements.append(Paragraph(criteria_text, ParagraphStyle('CriteriaAllClear', alignment=TA_LEFT, spaceAfter=4*mm)))
    else:
        # Score explicação normal
        score_text = f"<font size='9' color='#6B7280'>{approved_count}/{total_checks} {t['score_explanation']} · Score: <b>{score}/100</b></font>"
        elements.append(Paragraph(score_text, ParagraphStyle('ScoreExplanation', alignment=TA_LEFT, spaceAfter=4*mm)))

    # Tabela
    elements.append(create_verification_table(checks, lang, width, area_ha))
    elements.append(Spacer(1, 8*mm))
    
    # Histórico uso do solo
    if land_use_history:
        elements.append(Paragraph(f"<b>{t['land_use_title']}</b>", styles['section_title']))
        land_use_table = create_land_use_table(land_use_history, lang, width)
        if land_use_table:
            elements.append(land_use_table)
            elements.append(Paragraph(
                f"<font size='7' color='#9CA3AF'><i>{t['land_use_note']}</i></font>",
                ParagraphStyle('LandUseNote', alignment=TA_CENTER, spaceBefore=3*mm)
            ))
    
    elements.append(PageBreak())
    
    # ================================================================
    # PÁGINA 3 - FONTES + TERMO + VERIFICAÇÃO
    # ================================================================
    
    # Fontes
    elements.append(Paragraph(f"<b>{t['sources_title']}</b>", styles['section_title']))
    elements.append(create_sources_table(lang, width, data_freshness))
    elements.append(Spacer(1, 3*mm))
    
    # Marcadores de qualidade (sem bullets, mais elegante)
    quality_markers = [t['sources_footer_1'], t['sources_footer_2'], t['sources_footer_3']]
    elements.append(Paragraph(
        f"<font size='8' color='#059669'>✓</font> <font size='8' color='#6B7280'>{' · '.join(quality_markers)}</font>",
        ParagraphStyle('QualityMarkers', alignment=TA_LEFT, spaceBefore=2*mm)
    ))
    
    elements.append(Spacer(1, 10*mm))
    
    # Termo
    elements.append(Paragraph(f"<b>{t['disclaimer_title']}</b>", styles['section_title']))
    
    disclaimer_items = []
    for i in range(1, 6):
        key = f'disclaimer_{i}'
        disclaimer_items.append(f"• {t[key]}")
    
    disclaimer_text = '<br/>'.join([f"<font size='8' color='#6B7280'>{item}</font>" for item in disclaimer_items])
    
    disclaimer_table = Table([[Paragraph(disclaimer_text, ParagraphStyle('Disclaimer', leading=12))]], colWidths=[width])
    disclaimer_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLORS['gray_50']),
        ('BOX', (0, 0), (-1, -1), 0.5, COLORS['gray_300']),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(disclaimer_table)
    
    elements.append(Spacer(1, 10*mm))
    
    # Verificação de autenticidade
    elements.append(Paragraph(f"<b>{t['verification_title']}</b>", styles['section_title']))
    
    verification_url = f"{VERIFICATION_BASE_URL}/{report_code}/page"
    qr_buffer = generate_qr_code(verification_url)
    
    if qr_buffer:
        qr_image = Image(qr_buffer, width=32*mm, height=32*mm)
        
        info_content = [
            Paragraph(f"<font size='8' color='#6B7280'>{t['report_code']}</font>", styles['body_small']),
            Paragraph(f"<font face='Courier' size='11' color='#111827'>{report_code}</font>", styles['body']),
            Spacer(1, 3*mm),
            Paragraph(f"<font size='7' color='#9CA3AF'>{t['scan_qr']}</font>", styles['body_small']),
        ]
        
        verification_layout = Table(
            [[info_content, qr_image]],
            colWidths=[width - 40*mm, 38*mm]
        )
        verification_layout.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(verification_layout)
    else:
        elements.append(Paragraph(f"<b>{t['report_code']}:</b> {report_code}", styles['body']))
    
    # Metadados técnicos (para compliance)
    elements.append(Spacer(1, 6*mm))
    elements.append(Paragraph(f"<b>{t['technical_metadata']}</b>", styles['section_title']))
    
    # Hash do input (polígono)
    input_hash_short = input_hash[:16] + '...' if input_hash else 'N/A'
    
    metadata_rows = [
        [f"{t['input_hash']}:", f"<font face='Courier' size='7'>{input_hash_short}</font>"],
        [f"{t['engine_version']}:", f"<font face='Courier' size='7'>{ENGINE_VERSION}</font>"],
        [f"{t['generated_at_label']}:", f"<font size='7'>{date_str} (Brasília)</font>"],
    ]
    
    for label, value in metadata_rows:
        elements.append(Paragraph(
            f"<font size='7' color='#6B7280'>{label}</font> {value}",
            ParagraphStyle('MetadataRow', fontSize=7, spaceBefore=1*mm)
        ))
    
    # Rodapé
    elements.append(Spacer(1, 15*mm))
    elements.append(HRFlowable(width=width, thickness=0.5, color=COLORS['gray_200']))
    elements.append(Paragraph(
        f"<font size='7' color='#9CA3AF'>{t['footer_text']} · © 2025</font>",
        styles['footer']
    ))
    
    # Build
    def add_page_number(canvas, doc):
        canvas.saveState()
        page_num = canvas.getPageNumber()
        text = f"{t['page']} {page_num}"
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(COLORS['gray_400'])
        canvas.drawRightString(doc.pagesize[0] - 20*mm, 10*mm, text)
        canvas.restoreState()
    
    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    content_hash = generate_content_hash(pdf_bytes)
    
    return (pdf_bytes, report_code, content_hash)


class DueDiligenceReportGenerator:
    def __init__(self, db=None):
        self.db = db
    
    async def generate(
        self,
        validation_result: Dict[str, Any],
        property_info: Optional[Dict[str, Any]] = None,
        lang: str = 'pt',
    ) -> Tuple[bytes, str, str]:
        return await generate_due_diligence_report(
            validation_result=validation_result,
            property_info=property_info,
            lang=lang,
            db=self.db,
        )


# ============================================================
# TESTE
# ============================================================

if __name__ == '__main__':
    import asyncio
    
    test_validation = {
        'area_ha': 697.89,
        'centroid': {'lat': -11.86, 'lon': -55.52},
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[
                [-55.6, -11.8], [-55.4, -11.8], [-55.4, -11.9], [-55.6, -11.9], [-55.6, -11.8]
            ]]
        },
        'checks': [
            {'check_type': 'deforestation_prodes', 'result': 'PASS', 'overlap_area_ha': 0},
            {'check_type': 'mapbiomas_alerts', 'result': 'PASS', 'overlap_area_ha': 0},
            {'check_type': 'terra_indigena', 'result': 'PASS', 'overlap_area_ha': 0},
            {'check_type': 'uc', 'result': 'PASS', 'overlap_area_ha': 0},
            {'check_type': 'embargo_ibama', 'result': 'PASS', 'overlap_area_ha': 0},
            {'check_type': 'quilombola', 'result': 'PASS', 'overlap_area_ha': 0},
            {'check_type': 'app_water', 'result': 'WARNING', 'overlap_area_ha': 2.5},
        ]
    }
    
    test_property = {
        'farm_name': 'Fazenda Santa Maria',
        'plot_name': 'Talhão 01 — Soja',
        'municipality': 'Sinop',
        'state': 'MT',
        'land_use_history': [
            {'year': 2024, 'forest_pct': 21.67, 'pasture_pct': 16.11, 'agriculture_pct': 59.44},
            {'year': 2020, 'forest_pct': 23.61, 'pasture_pct': 18.06, 'agriculture_pct': 55.56},
            {'year': 2010, 'forest_pct': 33.33, 'pasture_pct': 23.61, 'agriculture_pct': 40.28},
            {'year': 2000, 'forest_pct': 50.00, 'pasture_pct': 26.39, 'agriculture_pct': 20.83},
            {'year': 1990, 'forest_pct': 77.78, 'pasture_pct': 12.50, 'agriculture_pct': 6.94},
            {'year': 1985, 'forest_pct': 88.89, 'pasture_pct': 4.17, 'agriculture_pct': 1.39},
        ],
    }
    
    async def main():
        pdf_bytes, code, hash = await generate_due_diligence_report(
            test_validation,
            test_property,
            lang='pt'
        )
        
        with open('test_report_v8_1.pdf', 'wb') as f:
            f.write(pdf_bytes)
        
        print(f"✓ PDF gerado: test_report_v8_1.pdf ({len(pdf_bytes)} bytes)")
        print(f"  Código: {code}")
        print(f"  Hash: {hash[:32]}...")
    
    asyncio.run(main())
