# Copyright 2015 OpenStack Foundation
#
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

"""add_disable_gateway_attr_to_l2p

Revision ID: 7ef98f287d6
Create Date: 2015-11-29 02:00:06.217136

"""

# revision identifiers, used by Alembic.
revision = '7ef98f287d6'
down_revision = '5a24894af57c'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('sc_nodes', sa.Column('gp_l2_policies', sa.String(36)))


def downgrade():
    pass
