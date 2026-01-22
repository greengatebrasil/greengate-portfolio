"""
Service para gerenciamento de API Keys
"""
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError

from app.models.api_key import APIKey


class APIKeyService:
    """Service para gerenciar API Keys."""

    # Planos disponíveis
    PLANS = {
        'free': {
            'name': 'Gratuito',
            'monthly_quota': 3,  # 3 validações para testar o sistema
            'price': 0,
        },
        'professional': {
            'name': 'Profissional',
            'monthly_quota': 50,
            'price': 197,
        },
        'enterprise': {
            'name': 'Empresarial',
            'monthly_quota': None,  # Ilimitado
            'price': 497,
        },
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def generate_api_key() -> str:
        """
        Gera uma nova API key.

        Formato: gg_live_XXXXXXXXXXXXXXXXXXXXXXXX (32 chars após prefixo)
        Exemplo: gg_live_3f7a9b2c5e8d1f4a6b9c2e5f8a1d4b7c
        """
        random_part = secrets.token_hex(16)  # 32 chars hex
        return f"gg_live_{random_part}"

    @staticmethod
    def hash_api_key(api_key: str) -> str:
        """Hash SHA256 da API key para armazenamento seguro."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    @staticmethod
    def get_key_prefix(api_key: str) -> str:
        """Extrai prefixo visível da API key (primeiros 12 chars)."""
        return api_key[:12] + "..." if len(api_key) > 12 else api_key

    async def create_api_key(
        self,
        client_name: str,
        plan: str = 'free',
        client_email: Optional[str] = None,
        client_document: Optional[str] = None,
        expires_in_days: Optional[int] = None,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
        _retry_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Cria uma nova API key.

        Args:
            client_name: Nome do cliente
            plan: Plano (free, professional, enterprise)
            client_email: Email do cliente
            client_document: CPF/CNPJ
            expires_in_days: Dias até expirar (None = nunca expira)
            notes: Notas administrativas
            created_by: Admin que criou
            _retry_count: Contador interno de retries (não usar diretamente)

        Returns:
            Dict com api_key (plain text - ÚLTIMA CHANCE DE VER!) e dados

        Raises:
            ValueError: Se plano inválido
            RuntimeError: Se exceder limite de retries
        """
        if plan not in self.PLANS:
            raise ValueError(f"Plano inválido: {plan}. Opções: {list(self.PLANS.keys())}")

        if _retry_count >= 3:
            raise RuntimeError("Falha ao gerar API key única após 3 tentativas. Tente novamente.")

        # Gerar API key
        api_key = self.generate_api_key()
        key_hash = self.hash_api_key(api_key)
        key_prefix = self.get_key_prefix(api_key)

        # Dados do plano
        plan_data = self.PLANS[plan]
        monthly_quota = plan_data['monthly_quota']

        # Data de expiração
        expires_at = None
        if expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        # Criar registro
        api_key_record = APIKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            client_name=client_name,
            client_email=client_email,
            client_document=client_document,
            plan=plan,
            monthly_quota=monthly_quota,
            expires_at=expires_at,
            notes=notes,
            created_by=created_by,
        )

        self.db.add(api_key_record)

        try:
            await self.db.commit()
            await self.db.refresh(api_key_record)
        except IntegrityError:
            await self.db.rollback()
            # Retry até 3 vezes (improvável colisão de hash SHA256)
            return await self.create_api_key(
                client_name, plan, client_email, client_document,
                expires_in_days, notes, created_by,
                _retry_count=_retry_count + 1
            )

        return {
            'api_key': api_key,  # ⚠️ ATENÇÃO: Só é mostrado AGORA!
            'id': str(api_key_record.id),
            'key_prefix': key_prefix,
            'client_name': client_name,
            'plan': plan,
            'monthly_quota': monthly_quota,
            'expires_at': expires_at.isoformat() if expires_at else None,
            'created_at': api_key_record.created_at.isoformat(),
        }

    async def verify_api_key(self, api_key: str) -> Optional[APIKey]:
        """
        Verifica se uma API key é válida e retorna o registro.

        Args:
            api_key: API key em plain text

        Returns:
            APIKey record ou None se inválida
        """
        key_hash = self.hash_api_key(api_key)

        query = select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True,
            APIKey.is_revoked == False,
        )

        result = await self.db.execute(query)
        api_key_record = result.scalar_one_or_none()

        if not api_key_record:
            return None

        # Verificar expiração
        if api_key_record.expires_at and datetime.now(timezone.utc) > api_key_record.expires_at:
            return None

        return api_key_record

    async def track_usage(self, api_key_record: APIKey, auto_commit: bool = True) -> None:
        """
        Registra uso da API key.

        Incrementa contadores e atualiza last_used_at.

        IMPORTANTE: Usa UPDATE atômico para evitar race conditions.

        Args:
            api_key_record: Registro da API key
            auto_commit: Se True, faz commit automaticamente. Se False, deixa para o caller.
        """
        from sqlalchemy import update

        now = datetime.now(timezone.utc)

        # Verificar se precisa reset mensal
        needs_reset = False
        if api_key_record.last_reset_at:
            days_since_reset = (now - api_key_record.last_reset_at).days
            if days_since_reset >= 30:
                needs_reset = True

        # UPDATE ATÔMICO - incrementa diretamente no banco
        # Isso evita race condition entre múltiplos requests simultâneos
        if needs_reset:
            # Reset contador mensal
            stmt = update(APIKey).where(
                APIKey.id == api_key_record.id
            ).values(
                total_requests=APIKey.total_requests + 1,
                requests_this_month=1,  # Reseta para 1 (esta request)
                last_used_at=now,
                last_reset_at=now,
            )
        elif api_key_record.last_reset_at is None:
            # Primeira vez
            stmt = update(APIKey).where(
                APIKey.id == api_key_record.id
            ).values(
                total_requests=APIKey.total_requests + 1,
                requests_this_month=APIKey.requests_this_month + 1,
                last_used_at=now,
                last_reset_at=now,
            )
        else:
            # Normal - incrementa ambos
            stmt = update(APIKey).where(
                APIKey.id == api_key_record.id
            ).values(
                total_requests=APIKey.total_requests + 1,
                requests_this_month=APIKey.requests_this_month + 1,
                last_used_at=now,
            )

        await self.db.execute(stmt)

        # Só faz commit se auto_commit=True
        # Quando chamado do middleware com SELECT FOR UPDATE, auto_commit=False
        # para manter o lock até o commit explícito no middleware
        if auto_commit:
            await self.db.commit()

    async def check_quota(self, api_key_record: APIKey) -> Dict[str, Any]:
        """
        Verifica status de quota.

        Returns:
            Dict com informações de quota
        """
        return {
            'has_quota': api_key_record.has_quota_available,
            'monthly_quota': api_key_record.monthly_quota,
            'requests_this_month': api_key_record.requests_this_month,
            'quota_remaining': api_key_record.quota_remaining,
            'quota_percentage_used': api_key_record.quota_percentage_used,
            'total_requests': api_key_record.total_requests,
        }

    async def revoke_api_key(self, api_key_id: str) -> bool:
        """
        Revoga uma API key (soft delete).

        Args:
            api_key_id: UUID da API key

        Returns:
            True se revogada com sucesso
        """
        query = update(APIKey).where(
            APIKey.id == api_key_id
        ).values(
            is_revoked=True,
            revoked_at=datetime.now(timezone.utc),
        )

        result = await self.db.execute(query)
        await self.db.commit()

        return result.rowcount > 0

    async def list_api_keys(
        self,
        plan: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[APIKey]:
        """
        Lista API keys com filtros.

        Args:
            plan: Filtrar por plano
            is_active: Filtrar por status
            limit: Limite de resultados
            offset: Offset para paginação

        Returns:
            Lista de API keys
        """
        query = select(APIKey).order_by(APIKey.created_at.desc())

        if plan:
            query = query.where(APIKey.plan == plan)

        if is_active is not None:
            query = query.where(APIKey.is_active == is_active)

        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_usage_stats(self) -> Dict[str, Any]:
        """
        Retorna estatísticas de uso geral.

        Returns:
            Dict com stats
        """
        # Total de API keys
        total_query = select(func.count(APIKey.id))
        total_keys = (await self.db.execute(total_query)).scalar()

        # API keys ativas
        active_query = select(func.count(APIKey.id)).where(
            APIKey.is_active == True,
            APIKey.is_revoked == False,
        )
        active_keys = (await self.db.execute(active_query)).scalar()

        # Total de requests
        requests_query = select(func.sum(APIKey.total_requests))
        total_requests = (await self.db.execute(requests_query)).scalar() or 0

        # Requests este mês
        month_requests_query = select(func.sum(APIKey.requests_this_month))
        month_requests = (await self.db.execute(month_requests_query)).scalar() or 0

        # Por plano
        plan_query = select(
            APIKey.plan,
            func.count(APIKey.id).label('count')
        ).where(
            APIKey.is_active == True
        ).group_by(APIKey.plan)

        plan_result = await self.db.execute(plan_query)
        by_plan = {row.plan: row.count for row in plan_result}

        return {
            'total_keys': total_keys,
            'active_keys': active_keys,
            'total_requests': total_requests,
            'requests_this_month': month_requests,
            'by_plan': by_plan,
        }

    async def upgrade_plan(
        self,
        api_key_id: str,
        new_plan: str,
    ) -> APIKey:
        """
        Faz upgrade/downgrade de plano.

        Args:
            api_key_id: UUID da API key
            new_plan: Novo plano

        Returns:
            API key atualizada

        Raises:
            ValueError: Se plano inválido ou key não encontrada
        """
        if new_plan not in self.PLANS:
            raise ValueError(f"Plano inválido: {new_plan}")

        query = select(APIKey).where(APIKey.id == api_key_id)
        result = await self.db.execute(query)
        api_key_record = result.scalar_one_or_none()

        if not api_key_record:
            raise ValueError(f"API key não encontrada: {api_key_id}")

        # Atualizar plano e quota
        plan_data = self.PLANS[new_plan]
        api_key_record.plan = new_plan
        api_key_record.monthly_quota = plan_data['monthly_quota']

        # Reset contador mensal (dar quota nova imediatamente)
        api_key_record.requests_this_month = 0
        api_key_record.last_reset_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(api_key_record)

        return api_key_record
