"""add rls policy for client_users

Revision ID: 20260121_1430
Revises: 2c3b4b9a1e9a
Create Date: 2026-01-21
"""
from alembic import op

revision = '20260121_1430'
down_revision = '2c3b4b9a1e9a'

def upgrade():
    op.execute("ALTER TABLE public.client_users ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY client_users_org_isolation ON public.client_users
        USING (org_id = current_setting('app.current_org_id', true)::uuid)
    """)

def downgrade():
    op.execute("DROP POLICY IF EXISTS client_users_org_isolation ON public.client_users")
    op.execute("ALTER TABLE public.client_users DISABLE ROW LEVEL SECURITY")
