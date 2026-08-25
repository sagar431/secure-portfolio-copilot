"""Allow the expanded approved portfolio tool catalog in safe agent history.

Revision ID: 20260823_0015
Revises: 20260823_0014
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260823_0015"
down_revision: str | None = "20260823_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOOLS = (
    "tool_name IN ('portfolio.search_authorized_documents',"
    "'portfolio.get_document_excerpt','portfolio.calculate_ebitda_margin',"
    "'portfolio.calculate_revenue_growth','portfolio.calculate_net_profit_margin',"
    "'portfolio.query_financial_metrics','portfolio.calculate_debt_to_equity',"
    "'portfolio.calculate_cash_runway','portfolio.calculate_cagr',"
    "'portfolio.search_memory','portfolio.propose_memory')"
)

_OLD_TOOLS = (
    "tool_name IN ('portfolio.search_authorized_documents',"
    "'portfolio.get_document_excerpt','portfolio.calculate_ebitda_margin',"
    "'portfolio.calculate_revenue_growth','portfolio.calculate_net_profit_margin')"
)


def upgrade() -> None:
    op.drop_constraint("ck_agent_steps_tool", "agent_steps", type_="check")
    op.create_check_constraint("ck_agent_steps_tool", "agent_steps", _TOOLS)


def downgrade() -> None:
    op.drop_constraint("ck_agent_steps_tool", "agent_steps", type_="check")
    op.create_check_constraint("ck_agent_steps_tool", "agent_steps", _OLD_TOOLS)
