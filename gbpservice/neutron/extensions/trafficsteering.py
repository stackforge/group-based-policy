# Copyright 2015, Instituto de Telecomunicacoes - Polo de Aveiro - ATNoG.
# All rights reserved.
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


import abc
import six

from neutron.api import extensions
from neutron.api.v2 import attributes as attr
from neutron.api.v2 import resource_helper
from neutron.common import exceptions as nexc
from neutron.plugins.common import constants
from neutron.services import service_base
from oslo_log import log


LOG = log.getLogger(__name__)


class TrafficSteeringInvalidProtocolValue(nexc.InvalidInput):
    message = _("Invalid value for protocol %(protocol)s")


class TrafficSteeringInvalidTypeOfServiceValue(nexc.InvalidInput):
    message = _("Invalid ToS value: %(tos)s")


class PortChainNotFound(nexc.NotFound):
    message = _("Port chain %(port_chain_id)s could not be found.")


def _validate_uuid_list_list(data, valid_values=None):
    if not isinstance(data, list):
        msg = _("'%s' is not a list of list of uuids") % data
        LOG.debug(msg)
        return msg

    for item in data:
        msg = attr._validate_uuid_list(item, valid_values)
        if msg:
            LOG.debug(msg)
            return msg


def convert_port_to_string(value):
    if value is None:
        return
    else:
        return str(value)


attr.validators['type:uuid_list_list'] = _validate_uuid_list_list


RESOURCE_ATTRIBUTE_MAP = {
    'port_chains': {
        'id': {'allow_post': False, 'allow_put': False,
               'validate': {'type:uuid': None}, 'is_visible': True},
        'tenant_id': {'allow_post': True, 'allow_put': False,
                      'required_by_policy': True, 'is_visible': True},
        'name': {'allow_post': True, 'allow_put': True,
                 'validate': {'type:string': None}, 'is_visible': True,
                 'default': ''},
        'description': {'allow_post': True, 'allow_put': True,
                        'validate': {'type:string': None},
                        'is_visible': True, 'default': ''},
        'ports': {'allow_post': True, 'allow_put': True,
                  'validate': {'type:uuid_list_list': None},
                  'convert_to': attr.convert_none_to_empty_list,
                  'is_visible': True}
    }
}


class Trafficsteering(extensions.ExtensionDescriptor):

    @classmethod
    def get_name(cls):
        return "Traffic Steering Port Chaining Abstraction"

    @classmethod
    def get_alias(cls):
        return "traffic-steering"

    @classmethod
    def get_description(cls):
        return _("Extension for Traffic Steering Port Chaining Abstraction")

    @classmethod
    def get_namespace(cls):
        # REVISIT(igordcard)
        return "http://docs.openstack.org/ext/neutron/trafficsteering/api/v1.0"

    @classmethod
    def get_updated(cls):
        return "2015-05-11T10:00:00-00:00"

    @classmethod
    def get_resources(cls):
        # TODO(igordcard): API should not be public in the final version.
        plural_mappings = resource_helper.build_plural_mappings(
            {}, RESOURCE_ATTRIBUTE_MAP)
        attr.PLURALS.update(plural_mappings)
        return resource_helper.build_resource_info(plural_mappings,
                                                   RESOURCE_ATTRIBUTE_MAP,
                                                   constants.TRAFFIC_STEERING)

    @classmethod
    def get_plugin_interface(cls):
        return TrafficSteeringPluginBase

    def update_attributes_map(self, attributes):
        super(Trafficsteering, self).update_attributes_map(
            attributes, extension_attrs_map=RESOURCE_ATTRIBUTE_MAP)

    def get_extended_resources(self, version):
        if version == "2.0":
            return RESOURCE_ATTRIBUTE_MAP
        else:
            return {}


@six.add_metaclass(abc.ABCMeta)
class TrafficSteeringPluginBase(service_base.ServicePluginBase):

    def get_plugin_name(self):
        return constants.TRAFFIC_STEERING

    def get_plugin_type(self):
        return constants.TRAFFIC_STEERING

    def get_plugin_description(self):
        return 'Traffic Steering plugin'

    @abc.abstractmethod
    def get_port_chains(self, context, filters=None, fields=None):
        pass

    @abc.abstractmethod
    def get_port_chain(self, context, id, fields=None):
        pass

    @abc.abstractmethod
    def create_port_chain(self, context, port_chain):
        pass

    @abc.abstractmethod
    def update_port_chain(self, context, id, port_chain):
        pass

    @abc.abstractmethod
    def delete_port_chain(self, context, id):
        pass
