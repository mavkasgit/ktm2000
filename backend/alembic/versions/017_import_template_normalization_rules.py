"""add_normalization_rules_to_import_templates

Revision ID: 017_normalization_rules
Revises: 016_remove_template_profile_ref
Create Date: 2026-05-17 12:30:00.000000
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "017_normalization_rules"
down_revision: Union[str, None] = "016_remove_template_profile_ref"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_RULES = {
    "version": 1,
    "operation": {
        "rules": [
            {
                "priority": 100,
                "contains": ["без рассеив"],
                "result": {
                    "operation_code": "PACK",
                    "operation_name": "Упаковка",
                    "additional_pack_operations": [
                        {
                            "operation_code": "PACK_CUSTOM",
                            "operation_name_template": "Доп. упаковочная операция: {raw}",
                        }
                    ],
                    "normalized_pack_op_family": "CUSTOM",
                },
            },
            {
                "priority": 90,
                "contains": ["окн"],
                "result": {
                    "operation_code": "PRESS_WINDOW",
                    "operation_name": "Пресс окно",
                    "additional_pack_operations": [],
                    "normalized_pack_op_family": "NONE",
                },
            },
            {
                "priority": 80,
                "contains": ["греб"],
                "result": {
                    "operation_code": "PRESS_COMB",
                    "operation_name": "Пресс гребенка",
                    "additional_pack_operations": [],
                    "normalized_pack_op_family": "NONE",
                },
            },
            {
                "priority": 70,
                "contains": ["сверл", "сверло"],
                "result": {
                    "operation_code": "DRILL",
                    "operation_name": "Сверловка",
                    "additional_pack_operations": [],
                    "normalized_pack_op_family": "NONE",
                },
            },
            {
                "priority": 60,
                "contains": ["клей"],
                "result": {
                    "operation_code": "PACK",
                    "operation_name": "Упаковка",
                    "additional_pack_operations": [
                        {
                            "operation_code": "PACK_GLUE",
                            "operation_name": "Упаковка с клеевой операцией",
                        }
                    ],
                    "normalized_pack_op_family": "GLUE",
                },
            },
            {
                "priority": 50,
                "contains": ["рассеив"],
                "result": {
                    "operation_code": "PACK",
                    "operation_name": "Упаковка",
                    "additional_pack_operations": [
                        {
                            "operation_code": "PACK_DIFFUSER",
                            "operation_name": "Упаковка с рассеивателем",
                        }
                    ],
                    "normalized_pack_op_family": "DIFFUSER",
                },
            },
        ],
        "fallback": {
            "operation_code": "PACK",
            "operation_name": "Упаковка",
            "additional_pack_operations": [
                {
                    "operation_code": "PACK_CUSTOM",
                    "operation_name_template": "Доп. упаковочная операция: {raw}",
                }
            ],
            "normalized_pack_op_family": "CUSTOM",
        },
    },
    "output_kind": {
        "rules": [
            {"priority": 100, "contains": ["гп", "гп."], "result": "finished_good"},
            {"priority": 90, "contains": ["пф", "пф."], "result": "semi_finished_shipment"},
        ],
        "fallback": "raw",
    },
}


def upgrade() -> None:
    op.add_column(
        "import_templates",
        sa.Column(
            "normalization_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    rules_json = json.dumps(DEFAULT_RULES, ensure_ascii=False)
    op.execute(
        sa.text(
            "UPDATE import_templates SET normalization_rules = CAST(:rules_json AS jsonb) "
            "WHERE normalization_rules = '{}'::jsonb OR normalization_rules IS NULL"
        ).bindparams(rules_json=rules_json)
    )


def downgrade() -> None:
    op.drop_column("import_templates", "normalization_rules")
