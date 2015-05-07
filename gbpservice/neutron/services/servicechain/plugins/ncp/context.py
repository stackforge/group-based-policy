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

from neutron import context as n_context
from neutron import manager

from gbpservice.neutron.extensions import group_policy
from gbpservice.neutron.services.servicechain.plugins.ncp import model


def get_gbp_plugin():
    return manager.NeutronManager.get_service_plugins().get("GROUP_POLICY")


def get_node_driver_context(sc_plugin, context, sc_instance,
                            current_node, original_node=None,
                            management_group=None, service_targets=None):
    specs = sc_plugin.get_servicechain_specs(
        context, filters={'id': sc_instance['servicechain_specs']})
    position = _calculate_node_position(specs, current_node['id'])
    provider = _get_ptg_or_ep(context, sc_instance['provider_ptg_id'])
    consumer = _get_ptg_or_ep(context, sc_instance['consumer_ptg_id'])
    if not service_targets:
        service_targets = model.get_service_targets(
            context.session, servicechain_instance_id=sc_instance['id'],
            position=position, servicechain_node_id=current_node['id'])

    return NodeDriverContext(sc_plugin=sc_plugin,
                             context=context,
                             service_chain_instance=sc_instance,
                             service_chain_specs=specs,
                             current_service_chain_node=current_node,
                             provider_group=provider,
                             consumer_group=consumer,
                             management_group=management_group,
                             original_service_chain_node=original_node,
                             service_targets=service_targets,
                             position=position)


def _get_ptg_or_ep(context, group_id):
    group = None
    if group_id:
        try:
            group = get_gbp_plugin().get_policy_target_group(context, group_id)
        except group_policy.PolicyTargetGroupNotFound:
            # Could be EP
            group = get_gbp_plugin().get_policy_target_group(context, group_id)
    return group


def _calculate_node_position(specs, node_id):
    for spec in specs:
        pos = 0
        for node in spec['nodes']:
            pos += 1
            if node_id == node:
                return pos


class NodeDriverContext(object):
    """ Context passed down to NCC Node Drivers."""

    def __init__(self, sc_plugin, context, service_chain_instance,
                 service_chain_specs, current_service_chain_node, position,
                 provider_group, consumer_group=None, management_group=None,
                 original_service_chain_node=None, service_targets=None):
        self._gbp_plugin = None
        self._sc_plugin = sc_plugin
        self._plugin_context = context
        self._admin_context = None
        self._service_chain_instance = service_chain_instance
        self._current_service_chain_node = current_service_chain_node
        self._original_service_chain_node = original_service_chain_node
        self._service_targets = service_targets
        self._service_chain_specs = service_chain_specs
        self._provider_group = provider_group
        self._consumer_group = consumer_group
        self._management_group = management_group
        self._relevant_specs = None
        self._position = position

    @property
    def gbp_plugin(self):
        if not self._gbp_plugin:
            self._gbp_plugin = get_gbp_plugin()
        return self._gbp_plugin

    @property
    def sc_plugin(self):
        return self._sc_plugin

    @property
    def plugin_context(self):
        return self._plugin_context

    @property
    def plugin_session(self):
        return self._plugin_context.session

    @property
    def session(self):
        return self.plugin_session

    @property
    def admin_context(self):
        if not self._admin_context:
            self._admin_context = n_context.get_admin_context()
        return self._admin_context

    @property
    def admin_session(self):
        return self.admin_context.session

    @property
    def instance(self):
        return self._service_chain_instance

    @property
    def current_node(self):
        return self._current_service_chain_node

    @property
    def current_position(self):
        raise self._position

    @property
    def original_node(self):
        return self._original_service_chain_node

    @property
    def relevant_specs(self):
        """Get specs on the SCI containing this particular Node."""
        if not self._relevant_specs:
            self._relevant_specs = [x for x in self._service_chain_specs if
                                    self.current_node['id'] in x['nodes']]
        return self._relevant_specs

    @property
    def provider(self):
        return self._provider_group

    @property
    def consumer(self):
        return self._consumer_group

    @property
    def management(self):
        return self._management_group

    def get_service_targets(self, update=False):
        """ Returns the service targets assigned for this service if any.
        The result looks like the following:
        {
            "provider": [pt_uuids],
            "consumer": [pt_uuids],
            "management": [pt_uuids],
        }
        """
        if update:
            self._service_targets = model.get_service_targets(
                self.session, servicechain_instance_id=self.instance['id'],
                position=self.current_position,
                servicechain_node_id=self.current_node['id'])
        return self._service_targets