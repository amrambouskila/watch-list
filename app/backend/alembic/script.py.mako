<%!
def literal(value):
    """repr with double quotes, so a generated revision already satisfies `ruff format`."""
    return repr(value).replace("'", '"')


def revises(value):
    """No trailing space when a revision has no parent - ruff format strips one out of the docstring."""
    if not value:
        return "Revises:"
    return "Revises: " + (value if isinstance(value, str) else ", ".join(value))
%>"""${message}

Revision ID: ${up_revision}
${revises(down_revision)}
Create Date: ${create_date}

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports + "\n" if imports else ""}\

# revision identifiers, used by Alembic.
revision: str = ${literal(up_revision)}
down_revision: str | Sequence[str] | None = ${literal(down_revision)}
branch_labels: str | Sequence[str] | None = ${literal(branch_labels)}
depends_on: str | Sequence[str] | None = ${literal(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
