"""
Endpoints administrativos para gerenciar API Keys

✅ PROTEGIDO: Requer autenticação admin via JWT
"""
from typing import Optional, List, Literal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import verify_admin
from app.services.api_key_service import APIKeyService
from app.models.api_key import APIKey


# Router protegido - Requer autenticação admin
router = APIRouter(
    prefix="/admin/api-keys",
    tags=["Admin - API Keys"],
    dependencies=[Depends(verify_admin)],  # ✅ PROTEÇÃO ATIVADA
)


# ============================================================================
# SCHEMAS
# ============================================================================

class CreateAPIKeyRequest(BaseModel):
    """Request para criar API key."""
    client_name: str
    plan: Literal['free', 'professional', 'enterprise'] = 'free'
    client_email: Optional[EmailStr] = None
    client_document: Optional[str] = None
    expires_in_days: Optional[int] = None
    notes: Optional[str] = None


class CreateAPIKeyResponse(BaseModel):
    """Response de API key criada."""
    api_key: str  # ⚠️ Só aparece aqui!
    id: str
    key_prefix: str
    client_name: str
    plan: str
    monthly_quota: Optional[int]
    expires_at: Optional[str]
    created_at: str
    warning: str = "ATENÇÃO: Guarde esta API key! Ela não será mostrada novamente."


class APIKeyInfo(BaseModel):
    """Informações de uma API key (sem a key)."""
    id: str
    key_prefix: str
    client_name: str
    client_email: Optional[str]
    client_document: Optional[str]
    plan: str
    monthly_quota: Optional[int]
    requests_this_month: int
    total_requests: int
    quota_remaining: Optional[int]
    is_active: bool
    is_revoked: bool
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]

    class Config:
        from_attributes = True


class UsageStatsResponse(BaseModel):
    """Estatísticas de uso."""
    total_keys: int
    active_keys: int
    total_requests: int
    requests_this_month: int
    by_plan: dict


class UpgradePlanRequest(BaseModel):
    """Request para upgrade de plano."""
    new_plan: Literal['free', 'professional', 'enterprise']


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/", response_model=CreateAPIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: CreateAPIKeyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    🔐 Cria uma nova API key.

    **ATENÇÃO:** A API key só é mostrada UMA VEZ nesta resposta!

    **Planos disponíveis:**
    - `free`: 10 validações/mês (grátis)
    - `professional`: 50 validações/mês
    - `enterprise`: Ilimitado

    **Exemplo:**
    ```json
    {
      "client_name": "Fazenda Santa Maria Ltda",
      "plan": "professional",
      "client_email": "contato@fazenda.com",
      "client_document": "12345678000190",
      "expires_in_days": 365,
      "notes": "Cliente desde 2025"
    }
    ```
    """
    service = APIKeyService(db)

    try:
        result = await service.create_api_key(
            client_name=request.client_name,
            plan=request.plan,
            client_email=request.client_email,
            client_document=request.client_document,
            expires_in_days=request.expires_in_days,
            notes=request.notes,
            created_by="admin",  # TODO: Pegar do token JWT
        )

        return CreateAPIKeyResponse(**result)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/", response_model=List[APIKeyInfo])
async def list_api_keys(
    plan: Optional[str] = Query(None, description="Filtrar por plano"),
    is_active: Optional[bool] = Query(None, description="Filtrar por status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    📋 Lista todas as API keys com filtros.

    **Filtros:**
    - `plan`: free, professional, enterprise
    - `is_active`: true/false
    - `limit`: máx registros (padrão 100)
    - `offset`: paginação
    """
    service = APIKeyService(db)
    keys = await service.list_api_keys(
        plan=plan,
        is_active=is_active,
        limit=limit,
        offset=offset
    )

    return [
        APIKeyInfo(
            id=str(k.id),
            key_prefix=k.key_prefix,
            client_name=k.client_name,
            client_email=k.client_email,
            client_document=k.client_document,
            plan=k.plan,
            monthly_quota=k.monthly_quota,
            requests_this_month=k.requests_this_month,
            total_requests=k.total_requests,
            quota_remaining=k.quota_remaining,
            is_active=k.is_active,
            is_revoked=k.is_revoked,
            created_at=k.created_at,
            expires_at=k.expires_at,
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.get("/stats", response_model=UsageStatsResponse)
async def get_usage_stats(
    db: AsyncSession = Depends(get_db),
):
    """
    📊 Retorna estatísticas de uso geral.

    **Métricas:**
    - Total de API keys criadas
    - API keys ativas
    - Total de requests (histórico)
    - Requests este mês
    - Distribuição por plano
    """
    service = APIKeyService(db)
    stats = await service.get_usage_stats()
    return UsageStatsResponse(**stats)


@router.post("/{api_key_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    🚫 Revoga uma API key (soft delete).

    A API key se torna inutilizável imediatamente.
    Não pode ser reativada (criar nova se necessário).
    """
    service = APIKeyService(db)

    revoked = await service.revoke_api_key(api_key_id)

    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key não encontrada: {api_key_id}"
        )


@router.post("/{api_key_id}/upgrade", response_model=APIKeyInfo)
async def upgrade_plan(
    api_key_id: str,
    request: UpgradePlanRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    ⬆️ Faz upgrade/downgrade de plano.

    **Planos:**
    - `free` → `professional` (upgrade)
    - `professional` → `enterprise` (upgrade)
    - `enterprise` → `professional` (downgrade)

    **Efeito:**
    - Quota é ajustada imediatamente
    - Contador mensal é resetado (quota nova disponível já)
    """
    service = APIKeyService(db)

    try:
        updated = await service.upgrade_plan(
            api_key_id=api_key_id,
            new_plan=request.new_plan
        )

        return APIKeyInfo(
            id=str(updated.id),
            key_prefix=updated.key_prefix,
            client_name=updated.client_name,
            client_email=updated.client_email,
            client_document=updated.client_document,
            plan=updated.plan,
            monthly_quota=updated.monthly_quota,
            requests_this_month=updated.requests_this_month,
            total_requests=updated.total_requests,
            quota_remaining=updated.quota_remaining,
            is_active=updated.is_active,
            is_revoked=updated.is_revoked,
            created_at=updated.created_at,
            expires_at=updated.expires_at,
            last_used_at=updated.last_used_at,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/plans", response_model=dict)
async def get_available_plans():
    """
    💰 Retorna planos disponíveis e preços.
    """
    return {
        "plans": APIKeyService.PLANS
    }


class UpdateAPIKeyRequest(BaseModel):
    """Request para atualizar API key."""
    client_name: Optional[str] = None
    client_email: Optional[EmailStr] = None
    client_document: Optional[str] = None
    notes: Optional[str] = None


@router.put("/{api_key_id}", response_model=APIKeyInfo)
async def update_api_key(
    api_key_id: str,
    request: UpdateAPIKeyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    ✏️ Atualiza informações de uma API key.

    Permite editar: nome do cliente, email, documento e notas.
    Não altera plano (use /upgrade) ou status.
    """
    from sqlalchemy import select, update
    from app.models.api_key import APIKey as APIKeyModel

    # Buscar API key
    query = select(APIKeyModel).where(APIKeyModel.id == api_key_id)
    result = await db.execute(query)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key não encontrada: {api_key_id}"
        )

    # Atualizar campos fornecidos
    update_data = {}
    if request.client_name is not None:
        update_data["client_name"] = request.client_name
    if request.client_email is not None:
        update_data["client_email"] = request.client_email
    if request.client_document is not None:
        update_data["client_document"] = request.client_document
    if request.notes is not None:
        update_data["notes"] = request.notes

    if update_data:
        stmt = update(APIKeyModel).where(APIKeyModel.id == api_key_id).values(**update_data)
        await db.execute(stmt)
        await db.commit()
        await db.refresh(api_key)

    return APIKeyInfo(
        id=str(api_key.id),
        key_prefix=api_key.key_prefix,
        client_name=api_key.client_name,
        client_email=api_key.client_email,
        client_document=api_key.client_document,
        plan=api_key.plan,
        monthly_quota=api_key.monthly_quota,
        requests_this_month=api_key.requests_this_month,
        total_requests=api_key.total_requests,
        quota_remaining=api_key.quota_remaining,
        is_active=api_key.is_active,
        is_revoked=api_key.is_revoked,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
    )


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    api_key_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    🗑️ Deleta permanentemente uma API key (hard delete).

    **ATENÇÃO:** Esta ação é IRREVERSÍVEL!
    Só permite deletar keys que já foram revogadas.
    """
    from sqlalchemy import select, delete
    from app.models.api_key import APIKey as APIKeyModel

    # Verificar se existe e está revogada
    query = select(APIKeyModel).where(APIKeyModel.id == api_key_id)
    result = await db.execute(query)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key não encontrada: {api_key_id}"
        )

    if not api_key.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Só é possível deletar API keys que foram revogadas primeiro."
        )

    # Hard delete
    stmt = delete(APIKeyModel).where(APIKeyModel.id == api_key_id)
    await db.execute(stmt)
    await db.commit()


@router.post("/{api_key_id}/reactivate", response_model=APIKeyInfo)
async def reactivate_api_key(
    api_key_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    ♻️ Reativa uma API key revogada.

    Retorna a key ao estado ativo. Útil se revogou por engano.
    """
    from sqlalchemy import select, update
    from app.models.api_key import APIKey as APIKeyModel

    query = select(APIKeyModel).where(APIKeyModel.id == api_key_id)
    result = await db.execute(query)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key não encontrada: {api_key_id}"
        )

    if not api_key.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta API key já está ativa."
        )

    # Reativar
    stmt = update(APIKeyModel).where(APIKeyModel.id == api_key_id).values(
        is_revoked=False,
        revoked_at=None,
        is_active=True,
    )
    await db.execute(stmt)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyInfo(
        id=str(api_key.id),
        key_prefix=api_key.key_prefix,
        client_name=api_key.client_name,
        client_email=api_key.client_email,
        client_document=api_key.client_document,
        plan=api_key.plan,
        monthly_quota=api_key.monthly_quota,
        requests_this_month=api_key.requests_this_month,
        total_requests=api_key.total_requests,
        quota_remaining=api_key.quota_remaining,
        is_active=api_key.is_active,
        is_revoked=api_key.is_revoked,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
    )


@router.post("/{api_key_id}/reset-quota", response_model=APIKeyInfo)
async def reset_quota(
    api_key_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    🔄 Reseta a quota mensal de uma API key.

    Zera o contador de requests do mês, dando quota nova imediatamente.
    Útil para dar créditos extras a um cliente.
    """
    from sqlalchemy import select, update
    from datetime import datetime, timezone
    from app.models.api_key import APIKey as APIKeyModel

    query = select(APIKeyModel).where(APIKeyModel.id == api_key_id)
    result = await db.execute(query)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key não encontrada: {api_key_id}"
        )

    # Reset quota
    stmt = update(APIKeyModel).where(APIKeyModel.id == api_key_id).values(
        requests_this_month=0,
        last_reset_at=datetime.now(timezone.utc),
    )
    await db.execute(stmt)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyInfo(
        id=str(api_key.id),
        key_prefix=api_key.key_prefix,
        client_name=api_key.client_name,
        client_email=api_key.client_email,
        client_document=api_key.client_document,
        plan=api_key.plan,
        monthly_quota=api_key.monthly_quota,
        requests_this_month=api_key.requests_this_month,
        total_requests=api_key.total_requests,
        quota_remaining=api_key.quota_remaining,
        is_active=api_key.is_active,
        is_revoked=api_key.is_revoked,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
    )


@router.post("/stamp-migrations", response_model=dict)
async def stamp_migrations():
    """
    ✅ Marca migrations como aplicadas SEM executá-las.

    **Use quando:** O banco já tem as tabelas criadas e você só precisa
    marcar que as migrations foram executadas.

    **Efeito:** Atualiza a tabela alembic_version para refletir que
    todas as migrations até 005_performance_indexes já foram aplicadas.

    **Seguro:** Não altera nada no banco, só atualiza o controle de versão.
    """
    import subprocess
    from pathlib import Path

    try:
        current_dir = Path(__file__).parent.parent.parent
        alembic_ini = current_dir / "alembic.ini"

        if not alembic_ini.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"alembic.ini não encontrado em {current_dir}"
            )

        # Marcar como aplicado até a última migration
        result = subprocess.run(
            ["alembic", "stamp", "head"],
            cwd=str(current_dir),
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            # Log interno para debugging (não expor para o cliente)
            from app.core.logging_config import get_logger
            log = get_logger(__name__)
            log.error("stamp_migration_failed", stdout=result.stdout, stderr=result.stderr)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stamp falhou. Verifique os logs do servidor para mais detalhes."
            )

        return {
            "success": True,
            "message": "Migrations marcadas como aplicadas com sucesso!",
            "info": "Banco não foi modificado, apenas controle de versão atualizado",
            "output": result.stdout,
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stamp timeout (>30s)"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao marcar migrations: {str(e)}"
        )


@router.post("/run-migrations", response_model=dict)
async def run_migrations():
    """
    🔧 Roda migrations do banco de dados (alembic upgrade head).

    **ATENÇÃO:** Execute apenas UMA VEZ após deploy em banco VAZIO.

    **Se der erro de tabela duplicada:** Use /stamp-migrations ao invés deste.

    Cria índices de performance e aplica mudanças no schema.
    """
    import subprocess
    import os
    from pathlib import Path

    try:
        # Encontrar diretório do alembic (backend/backend/)
        current_dir = Path(__file__).parent.parent.parent
        alembic_ini = current_dir / "alembic.ini"

        if not alembic_ini.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"alembic.ini não encontrado em {current_dir}"
            )

        # Rodar alembic upgrade head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=str(current_dir),
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            # Log interno para debugging (não expor para o cliente)
            from app.core.logging_config import get_logger
            log = get_logger(__name__)
            log.error("run_migration_failed", stdout=result.stdout, stderr=result.stderr)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Migration falhou. Verifique os logs do servidor para mais detalhes."
            )

        return {
            "success": True,
            "message": "Migrations aplicadas com sucesso!",
            "output": result.stdout,
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Migration timeout (>60s)"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao rodar migrations: {str(e)}"
        )
