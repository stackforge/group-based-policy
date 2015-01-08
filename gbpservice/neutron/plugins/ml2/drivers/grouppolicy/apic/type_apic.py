# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved.
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

from neutron.common import exceptions as exc
from neutron.openstack.common import log
from neutron.plugins.ml2 import driver_api as api
from oslo.config import cfg

from gbpservice.common import constants

LOG = log.getLogger(__name__)

flat_opts = [
    cfg.ListOpt('apic_networks',
                default=[],
                help=_("List of apic_network names on which apic "
                       "networks can be created. First in list is the default"
                       "apic network for tenants."))
]

cfg.CONF.register_opts(flat_opts, "ml2_type_apic")


class ApicTypeDriver(api.TypeDriver):

    def __init__(self):
        LOG.info(_("ML2 ApicTypeDriver initialization complete"))
        self.apic_networks = cfg.CONF.ml2_type_apic.apic_networks

    def get_type(self):
        return constants.TYPE_APIC

    def initialize(self):
        pass

    def is_partial_segment(self, segment):
        return False

    def validate_provider_segment(self, segment):
        physical_network = segment.get(api.PHYSICAL_NETWORK)
        if not physical_network:
            msg = _("physical_network required for flat provider network")
            raise exc.InvalidInput(error_message=msg)
        if physical_network not in self.apic_networks:
            msg = (_("physical_network '%s' unknown for apic provider network")
                   % physical_network)
            raise exc.InvalidInput(error_message=msg)

        for key, value in segment.iteritems():
            if value and key not in [api.NETWORK_TYPE,
                                     api.PHYSICAL_NETWORK]:
                msg = _("%s prohibited for apic provider network") % key
                raise exc.InvalidInput(error_message=msg)

    def reserve_provider_segment(self, session, segment):
        # No resources to reserve
        return segment

    def allocate_tenant_segment(self, session):
        result = {api.NETWORK_TYPE: constants.TYPE_APIC}
        if self.apic_networks:
            result[api.PHYSICAL_NETWORK] = self.apic_networks[0]
        return result

    def release_segment(self, session, segment):
        # No resources to release
        pass