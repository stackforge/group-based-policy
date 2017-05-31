#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

"""apic_aim_persist

Revision ID: cc09261e0fb5
Revises: c460c5682e74
Create Date: 2017-05-15 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'cc09261e0fb5'
down_revision = 'c460c5682e74'

from alembic import op
import sqlalchemy as sa


def upgrade():

    op.create_table(
        'apic_aim_address_scope_mappings',
        sa.Column('scope_id', sa.String(36), nullable=False),
        sa.Column('vrf_name', sa.String(64), nullable=True),
        sa.Column('vrf_tenant_name', sa.String(64), nullable=True),
        sa.Column('vrf_owned', sa.Boolean, nullable=False),
        sa.ForeignKeyConstraint(
            ['scope_id'], ['address_scopes.id'],
            name='apic_aim_address_scope_mappings_fk_scope_id',
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('scope_id'))

    op.create_table(
        'apic_aim_network_mappings',
        sa.Column('network_id', sa.String(36), nullable=False),
        sa.Column('bd_name', sa.String(64), nullable=True),
        sa.Column('bd_tenant_name', sa.String(64), nullable=True),
        sa.Column('epg_name', sa.String(64), nullable=True),
        sa.Column('epg_tenant_name', sa.String(64), nullable=True),
        sa.Column('epg_app_profile_name', sa.String(64), nullable=True),
        sa.Column('vrf_name', sa.String(64), nullable=True),
        sa.Column('vrf_tenant_name', sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(
            ['network_id'], ['networks.id'],
            name='apic_aim_network_mappings_fk_network_id',
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('network_id'))

    # REVISIT: Migrate data?

    op.drop_table('apic_aim_addr_scope_extensions')


def downgrade():
    pass