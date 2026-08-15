"""baseline — schéma actuel (aucune opération)

Cette migration ne modifie rien. Elle sert de point de référence :

  - Sur une base EXISTANTE (créée par init_db()/create_all d'une version
    antérieure) : lancez `alembic stamp head` pour marquer la base comme
    étant à ce niveau, SANS rien exécuter. Alembic considère alors que le
    schéma actuel (déjà en place) correspond à cette révision, et les
    migrations futures s'appliqueront à partir d'ici.

  - Sur une base TOUTE NEUVE : `init_db()` (appelé au démarrage du bot,
    voir main.py) crée déjà les tables via `Base.metadata.create_all`. Il
    suffit ensuite de lancer `alembic stamp head` une fois, pour la même
    raison que ci-dessus — pas besoin de rejouer cette migration.

Toute évolution de schéma FUTURE doit passer par une vraie migration
Alembic (`alembic revision --autogenerate -m "..."`), jamais par une
modification manuelle de la base ou des modèles seuls.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
