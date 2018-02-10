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

"""auto bgp with ext-svi

Revision ID: 804d991a3564
Revises: 5fe2285071fd
Create Date: 2018-02-06 14:31:34.104417

"""

# revision identifiers, used by Alembic.
revision = '804d991a3564'
down_revision = '5fe2285071fd'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('apic_aim_network_extensions',
                  sa.Column('bgp_enable', sa.Boolean,
                            server_default=sa.false(),
                            nullable=False))
    op.add_column('apic_aim_network_extensions',
                  sa.Column('bgp_type', sa.Enum('DefaultExport', ''),
                            server_default="", nullable=False))
    op.add_column('apic_aim_network_extensions',
                  sa.Column('local_asn', sa.String(64), server_default="0",
                            nullable=False))
    op.add_column('apic_aim_network_extensions',
                  sa.Column('asn', sa.String(64), server_default="0",
                            nullable=False))
    pass


def downgrade():
    pass
