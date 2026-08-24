"""point the ppip source at its JSON API

`tenders.go.ke` is a Vue SPA — the HTML we fetched was a 1.3KB shell, so the
table parser found nothing and the source sat degraded. Its XHR endpoint is
public and allowed by robots.txt, so the source now reads that instead.

This is a data migration because the seeder only inserts sources it has never
seen; an existing row keeps whatever adapter and URL it was created with, and
PPIP would have stayed broken on every database that already ran the seed.

Only the shipped row is touched: `is_custom = false` guards a source the client
added by hand at the same key. `health` is left as it is — it stays degraded
from the failed scrapes until the next sweep proves otherwise, which is honest.

Revision ID: c1a7d3e40b52
Revises: b5f2c1a97e04
Create Date: 2026-08-24 15:10:00.000000
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "c1a7d3e40b52"
down_revision: str | Sequence[str] | None = "b5f2c1a97e04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API_URL = "https://tenders.go.ke/api/active-tenders"
SPA_URL = "https://tenders.go.ke/website/tenders/index"


def upgrade() -> None:
    op.execute(
        text(
            """
            UPDATE tender_sources
               SET adapter = 'PpipApiSource',
                   listing_url = :api_url,
                   base_url = :api_url,
                   fallback_urls = '{}'
             WHERE key = 'ppip' AND is_custom IS FALSE
            """
        ).bindparams(api_url=API_URL)
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            UPDATE tender_sources
               SET adapter = 'TableTenderSource',
                   listing_url = :spa_url,
                   base_url = :spa_url,
                   fallback_urls = ARRAY[:api_url]::text[]
             WHERE key = 'ppip' AND is_custom IS FALSE
            """
        ).bindparams(spa_url=SPA_URL, api_url=API_URL)
    )
