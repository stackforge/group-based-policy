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

import netaddr

from apicapi import apic_manager
from keystoneclient.v2_0 import client as keyclient
from neutron.common import rpc as n_rpc
from neutron.extensions import providernet as pn
from neutron import manager
from neutron.openstack.common import lockutils
from neutron.openstack.common import log as logging
from neutron.plugins.ml2.drivers.cisco.apic import apic_model
from neutron.plugins.ml2.drivers.cisco.apic import config
from neutron.plugins.ml2 import models
from oslo.config import cfg

from gbp.neutron.api.rpc.handlers import gbp_rpc
from gbp.neutron.db.grouppolicy import group_policy_mapping_db as gpdb
from gbp.neutron.services.grouppolicy.common import constants as g_const
from gbp.neutron.services.grouppolicy.common import exceptions as gpexc
from gbp.neutron.services.grouppolicy.drivers import resource_mapping as api

LOG = logging.getLogger(__name__)


class L2PolicyMultipleEndpointGroupNotSupportedOnApicDriver(
        gpexc.GroupPolicyBadRequest):
    message = _("An L2 policy can't have multiple endpoint groups on APIC "
                "GBP driver.")


class RedirectActionNotSupportedOnApicDriver(gpexc.GroupPolicyBadRequest):
    message = _("Redirect action is currently not supported for APIC GBP "
                "driver.")


class PolicyRuleUpdateNotSupportedOnApicDriver(gpexc.GroupPolicyBadRequest):
    message = _("Policy rule update is not supported on for APIC GBP"
                "driver.")


class ExactlyOneActionPerRuleIsSupportedOnApicDriver(
        gpexc.GroupPolicyBadRequest):
    message = _("Exactly one action per rule is supported on APIC GBP driver.")


class ApicMappingDriver(api.ResourceMappingDriver):
    """Apic Mapping driver for Group Policy plugin.

    This driver implements group policy semantics by mapping group
    policy resources to various other neutron resources, and leverages
    Cisco APIC's backend for enforcing the policies.
    """

    me = None
    manager = None

    @staticmethod
    def get_apic_manager(client=True):
        if not ApicMappingDriver.manager:
            apic_config = cfg.CONF.ml2_cisco_apic
            network_config = {
                'vlan_ranges': cfg.CONF.ml2_type_vlan.network_vlan_ranges,
                'switch_dict': config.create_switch_dictionary(),
                'vpc_dict': config.create_vpc_dictionary(),
                'external_network_dict':
                    config.create_external_network_dictionary(),
            }
            apic_system_id = cfg.CONF.apic_system_id
            keyclient_param = keyclient if client else None
            keystone_authtoken = (cfg.CONF.keystone_authtoken if client else
                                  None)
            ApicMappingDriver.manager = apic_manager.APICManager(
                apic_model.ApicDbModel(), logging, network_config, apic_config,
                keyclient_param, keystone_authtoken, apic_system_id)
            ApicMappingDriver.manager.ensure_infra_created_on_apic()
            ApicMappingDriver.manager.ensure_bgp_pod_policy_created_on_apic()
        return ApicMappingDriver.manager

    def initialize(self):
        super(ApicMappingDriver, self).initialize()
        self.endpoints = [gbp_rpc.GBPServerRpcCallback(self)]
        self.topic = gbp_rpc.TOPIC_GBP
        self.conn = n_rpc.create_connection(new=True)
        self.conn.create_consumer(self.topic, self.endpoints,
                                  fanout=False)
        self.conn.consume_in_threads()
        self.apic_manager = ApicMappingDriver.get_apic_manager()
        self.name_mapper = self.apic_manager.apic_mapper
        self._gbp_plugin = None
        ApicMappingDriver.me = self

    @property
    def gbp_plugin(self):
        if not self._gbp_plugin:
            self._gbp_plugin = (manager.NeutronManager.get_service_plugins()
                                .get("GROUP_POLICY"))
        return self._gbp_plugin

    @staticmethod
    def get_initialized_instance():
        return ApicMappingDriver.me

    def get_gbp_details(self, context, **kwargs):
        """This method implements the logic of port binding in GBP context."""
        port_id = (kwargs.get('port_id') or
                   self._core_plugin._device_to_port_id(kwargs['device']))
        port = self._core_plugin.get_port(context, port_id)
        # retrieve EPG and network from a given Port
        epg, network = self._port_to_epg_network(context, port,
                                                 kwargs['host'])
        if not epg:
            return

        return {g_const.DEVICE_OWNER_GP_POLICY_TARGET: True,
                'port_id': port_id,
                'mac_address': port['mac_address'],
                'epg_id': epg['id'],
                'segmentation_id': network[pn.SEGMENTATION_ID],
                'network_type': network[pn.NETWORK_TYPE],
                'l2_policy_id': epg['l2_policy_id'],
                'tenant_id': port['tenant_id'],
                'host': port['binding:host_id']
                }

    def create_dhcp_endpoint_if_needed(self, plugin_context, port):
        session = plugin_context.session
        if (self._port_is_owned(session, port['id'])):
            # Nothing to do
            return

        # Retrieve EPG
        filters = {'network_id': [port['network_id']]}
        epgs = self.gbp_plugin.get_endpoint_groups(plugin_context,
                                                   filters=filters)
        if epgs:
            epg = epgs[0]
            # Create Endpoint
            attrs = {'endpoint':
                     {'tenant_id': port['tenant_id'],
                      'name': 'dhcp-%s' % epg['id'],
                      'description': _("Implicitly created DHCP endpoint"),
                      'endpoint_group_id': epg['id'],
                      'port_id': port['id']}}
            self.gbp_plugin.create_endpoint(plugin_context, attrs)

    def create_policy_action_precommit(self, context):
        # TODO(ivar): allow redirect for service chaining
        if context.current['action_type'] == g_const.GP_ACTION_REDIRECT:
            raise RedirectActionNotSupportedOnApicDriver()

    def create_policy_rule_precommit(self, context):
        if ('policy_actions' in context.current and
                len(context.current['policy_actions']) != 1):
            # TODO(ivar): to be fixed when redirect is supported
            raise ExactlyOneActionPerRuleIsSupportedOnApicDriver()

    def create_policy_rule_postcommit(self, context):
        action = context._plugin.get_policy_action(
            context._plugin_context, context.current['policy_actions'][0])
        classifier = context._plugin.get_policy_classifier(
            context._plugin_context,
            context.current['policy_classifier_id'])
        if action['action_type'] == g_const.GP_ACTION_ALLOW:
            port_min, port_max = (
                gpdb.GroupPolicyMappingDbPlugin._get_min_max_ports_from_range(
                    classifier['port_range']))
            attrs = {'etherT': 'ip',
                     'prot': classifier['protocol'].lower()}
            if port_min and port_max:
                attrs['dToPort'] = port_max
                attrs['dFromPort'] = port_min
            tenant = self.name_mapper.tenant(context,
                                             context.current['tenant_id'])
            policy_rule = self.name_mapper.policy_rule(context,
                                                       context.current['id'])
            self.apic_manager.create_tenant_filter(policy_rule, owner=tenant,
                                                   **attrs)

    def create_contract_postcommit(self, context):
        # Create APIC contract
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        contract = self.name_mapper.contract(context, context.current['id'])
        with self.apic_manager.apic.transaction(None) as trs:
            self.apic_manager.create_contract(contract, owner=tenant,
                                              transaction=trs)
            self._apply_contract_rules(context, context.current,
                                       context.current['policy_rules'],
                                       transaction=trs)

    def create_endpoint_postcommit(self, context):
        # The path needs to be created at bind time, this will be taken
        # care by the GBP ML2 apic driver.
        super(ApicMappingDriver, self).create_endpoint_postcommit(context)
        self._manage_endpoint_port(context._plugin_context, context.current)

    def create_endpoint_group_postcommit(self, context):
        super(ApicMappingDriver, self).create_endpoint_group_postcommit(
            context)
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        l2_policy = self.name_mapper.l2_policy(context,
                                               context.current['l2_policy_id'])
        epg = self.name_mapper.endpoint_group(context, context.current['id'])

        with self.apic_manager.apic.transaction(None) as trs:
            self.apic_manager.ensure_epg_created(tenant, epg,
                                                 bd_name=l2_policy)
            subnets = self._subnet_ids_to_objects(context._plugin_context,
                                                  context.current['subnets'])
            self._manage_epg_subnets(context._plugin_context, context.current,
                                     subnets, [], transaction=trs)
            self._manage_epg_contracts(
                context._plugin_context, context.current,
                context.current['provided_contracts'],
                context.current['consumed_contracts'], [], [], transaction=trs)

    def create_l2_policy_postcommit(self, context):
        super(ApicMappingDriver, self).create_l2_policy_postcommit(context)
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        l3_policy = self.name_mapper.l3_policy(context,
                                               context.current['l3_policy_id'])
        l2_policy = self.name_mapper.l2_policy(context, context.current['id'])

        self.apic_manager.ensure_bd_created_on_apic(tenant, l2_policy,
                                                    ctx_owner=tenant,
                                                    ctx_name=l3_policy)

    def create_l3_policy_postcommit(self, context):
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        l3_policy = self.name_mapper.l3_policy(context, context.current['id'])

        self.apic_manager.ensure_context_enforced(tenant, l3_policy)

    def delete_policy_rule_postcommit(self, context):
        # TODO(ivar): delete Contract subject entries to avoid reference leak
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        policy_rule = self.name_mapper.policy_rule(context,
                                                   context.current['id'])
        self.apic_manager.delete_tenant_filter(policy_rule, owner=tenant)

    def delete_contract_precommit(self, context):
        # Intercept Parent Call
        pass

    def delete_contract_postcommit(self, context):
        # TODO(ivar): disassociate EPGs to avoid reference leak
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        contract = self.name_mapper.contract(context, context.current['id'])
        self.apic_manager.delete_contract(contract, owner=tenant)

    def delete_endpoint_postcommit(self, context):
        port = self._core_plugin.get_port(context._plugin_context,
                                          context.current['port_id'])
        if port['binding:host_id']:
            self.process_path_deletion(context._plugin_context, port)
        # Delete Neutron's port
        super(ApicMappingDriver, self).delete_endpoint_postcommit(context)

    def delete_endpoint_group_postcommit(self, context):
        if context.current['subnets']:
            subnets = self._subnet_ids_to_objects(context._plugin_context,
                                                  context.current['subnets'])
            self._manage_epg_subnets(context._plugin_context, context.current,
                                     [], subnets)
        for subnet_id in context.current['subnets']:
            self._cleanup_subnet(context._plugin_context, subnet_id, None)
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        epg = self.name_mapper.endpoint_group(context, context.current['id'])

        self.apic_manager.delete_epg_for_network(tenant, epg)

    def delete_l2_policy_postcommit(self, context):
        super(ApicMappingDriver, self).delete_l2_policy_postcommit(context)
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        l2_policy = self.name_mapper.l2_policy(context, context.current['id'])

        self.apic_manager.delete_bd_on_apic(tenant, l2_policy)

    def delete_l3_policy_postcommit(self, context):
        tenant = self.name_mapper.tenant(context, context.current['tenant_id'])
        l3_policy = self.name_mapper.l3_policy(context, context.current['id'])

        self.apic_manager.ensure_context_deleted(tenant, l3_policy)

    def update_endpoint_postcommit(self, context):
        # TODO(ivar): redo binding procedure if the EPG is modified,
        # not doable unless driver extension framework is in place
        pass

    def update_policy_rule_precommit(self, context):
        # TODO(ivar): add support for action update on policy rules
        raise PolicyRuleUpdateNotSupportedOnApicDriver()

    def update_endpoint_group_postcommit(self, context):
        # TODO(ivar): refactor parent to avoid code duplication
        orig_provided_contracts = context.original['provided_contracts']
        curr_provided_contracts = context.current['provided_contracts']
        orig_consumed_contracts = context.original['consumed_contracts']
        curr_consumed_contracts = context.current['consumed_contracts']

        new_provided_contracts = list(set(curr_provided_contracts) -
                                      set(orig_provided_contracts))
        new_consumed_contracts = list(set(curr_consumed_contracts) -
                                      set(orig_consumed_contracts))
        removed_provided_contracts = list(set(orig_provided_contracts) -
                                          set(curr_provided_contracts))
        removed_consumed_contracts = list(set(orig_consumed_contracts) -
                                          set(curr_consumed_contracts))

        orig_subnets = context.original['subnets']
        curr_subnets = context.current['subnets']
        new_subnets = list(set(curr_subnets) - set(orig_subnets))
        removed_subnets = list(set(orig_subnets) - set(curr_subnets))

        with self.apic_manager.apic.transaction(None) as trs:
            self._manage_epg_contracts(
                context._plugin_context, context.current,
                new_provided_contracts, new_consumed_contracts,
                removed_provided_contracts, removed_consumed_contracts,
                transaction=trs)

            new_subnets = self._subnet_ids_to_objects(
                context._plugin_context, new_subnets)
            removed_subnets = self._subnet_ids_to_objects(
                context._plugin_context, removed_subnets)

            self._manage_epg_subnets(context._plugin_context, context.current,
                                     new_subnets, removed_subnets)

    def process_subnet_changed(self, context, old, new):
        if old['gateway_ip'] != new['gateway_ip']:
            epg = self._subnet_to_epg(context, new['id'])
            if epg:
                # Is GBP owned, reflect on APIC
                self._manage_epg_subnets(context, epg, [new], [old])

    def process_port_changed(self, context, old, new):
        # Port's EP can't change unless EP is deleted/created, therefore the
        # binding will mostly be the same except for the host
        if old['binding:host_id'] != new['binding:host_id']:
            ep = self._port_id_to_ep(context, new['id'])
            if ep:
                if old['binding:host_id']:
                    self.process_path_deletion(context, old)
                self._manage_endpoint_port(context, ep)

    def process_path_deletion(self, context, port):
        port_details = self.get_gbp_details(
            context, port_id=port['id'], host=port['binding:host_id'])
        self._delete_path_if_last(context, port_details)

    def _apply_contract_rules(self, context, contract, policy_rules,
                              transaction=None):
        # TODO(ivar): refactor parent to avoid code duplication
        if contract['parent_id']:
            parent = context._plugin.get_contract(
                context._plugin_context, contract['parent_id'])
            policy_rules = policy_rules & set(parent['policy_rules'])
        # Don't add rules unallowed by the parent
        self._manage_contract_rules(context, contract, policy_rules,
                                    transaction=transaction)

    def _remove_contract_rules(self, context, contract, policy_rules,
                               transaction=None):
        self._manage_contract_rules(context, contract, policy_rules,
                                    unset=True, transaction=transaction)

    def _manage_contract_rules(self, context, contract, policy_rules,
                               unset=False, transaction=None):
        # REVISIT(ivar): figure out what should be moved in apicapi instead
        if policy_rules:
            tenant = self.name_mapper.tenant(context,
                                             context.current['tenant_id'])
            contract = self.name_mapper.contract(context,
                                                 context.current['id'])
            in_dir = [g_const.GP_DIRECTION_BI, g_const.GP_DIRECTION_IN]
            out_dir = [g_const.GP_DIRECTION_BI, g_const.GP_DIRECTION_OUT]
            filters = {'id': policy_rules}
            for rule in context._plugin.get_policy_rules(
                    context._plugin_context, filters=filters):
                policy_rule = self.name_mapper.policy_rule(context, rule['id'])
                classifier = context._plugin.get_policy_classifier(
                    context._plugin_context, rule['policy_classifier_id'])
                with self.apic_manager.apic.transaction(transaction) as trs:
                    if classifier['direction'] in in_dir:
                        # Contract and subject are the same thing in this case
                        self.apic_manager.manage_contract_subject_in_filter(
                            contract, contract, policy_rule, owner=tenant,
                            transaction=trs, unset=unset)
                    if classifier['direction'] in out_dir:
                        # Contract and subject are the same thing in this case
                        self.apic_manager.manage_contract_subject_out_filter(
                            contract, contract, policy_rule, owner=tenant,
                            transaction=trs, unset=unset)

    @lockutils.synchronized('apic-portlock')
    def _manage_endpoint_port(self, plugin_context, ep):
        port = self._core_plugin.get_port(plugin_context, ep['port_id'])
        if port.get('binding:host_id'):
            port_details = self.get_gbp_details(
                plugin_context, port_id=port['id'], host=port['binding:host_id'])
            if port_details:
                # TODO(ivar): change APICAPI to not expect a resource context
                plugin_context._plugin = self.gbp_plugin
                plugin_context._plugin_context = plugin_context
                tenant_id = self.name_mapper.tenant(plugin_context,
                                                    port['tenant_id'])
                epg = self.name_mapper.endpoint_group(
                    plugin_context, port_details['epg_id'])
                bd = self.name_mapper.l2_policy(
                    plugin_context, port_details['l2_policy_id'])
                seg = port_details['segmentation_id']
                # Create a static path attachment for the host/epg/switchport
                with self.apic_manager.apic.transaction() as trs:
                    self.apic_manager.ensure_path_created_for_port(
                        tenant_id, epg, port['binding:host_id'], seg,
                        bd_name=bd,
                        transaction=trs)

    def _manage_epg_contracts(self, plugin_context, epg, added_provided,
                              added_consumed, removed_provided,
                              removed_consumed, transaction=None):
        # TODO(ivar): change APICAPI to not expect a resource context
        plugin_context._plugin = self.gbp_plugin
        plugin_context._plugin_context = plugin_context
        mapped_tenant = self.name_mapper.tenant(plugin_context,
                                                epg['tenant_id'])
        mapped_epg = self.name_mapper.endpoint_group(plugin_context,
                                                     epg['id'])
        provided = [added_provided, removed_provided]
        consumed = [added_consumed, removed_consumed]
        methods = [self.apic_manager.set_contract_for_epg,
                   self.apic_manager.unset_contract_for_epg]
        with self.apic_manager.apic.transaction(transaction) as trs:
            for x in xrange(len(provided)):
                for c in provided[x]:
                    c = self.name_mapper.contract(plugin_context, c)
                    methods[x](mapped_tenant, mapped_epg, c, provider=True,
                               transaction=trs)
            for x in xrange(len(consumed)):
                for c in consumed[x]:
                    c = self.name_mapper.contract(plugin_context, c)
                    methods[x](mapped_tenant, mapped_epg, c, provider=False,
                               transaction=trs)

    def _manage_epg_subnets(self, plugin_context, epg, added_subnets,
                            removed_subnets, transaction=None):
        # TODO(ivar): change APICAPI to not expect a resource context
        plugin_context._plugin = self.gbp_plugin
        plugin_context._plugin_context = plugin_context
        mapped_tenant = self.name_mapper.tenant(plugin_context,
                                                epg['tenant_id'])
        mapped_l2p = self.name_mapper.l2_policy(plugin_context,
                                                epg['l2_policy_id'])
        subnets = [added_subnets, removed_subnets]
        methods = [self.apic_manager.ensure_subnet_created_on_apic,
                   self.apic_manager.ensure_subnet_deleted_on_apic]
        with self.apic_manager.apic.transaction(transaction) as trs:
            for x in xrange(len(subnets)):
                for s in subnets[x]:
                    methods[x](mapped_tenant, mapped_l2p, self._gateway_ip(s),
                               transaction=trs)

    def _get_active_path_count(self, plugin_context, port_info):
        return plugin_context.session.query(
            models.PortBinding).filter_by(
                host=port_info['host'],
                segment=port_info['segmentation_id']).count()

    @lockutils.synchronized('apic-portlock')
    def _delete_port_path(self, context, atenant_id, l2p, port_info):
        if not self._get_active_path_count(context, port_info):
            self.apic_manager.ensure_path_deleted_for_port(
                atenant_id, l2p, port_info['host'])

    def _delete_path_if_last(self, context, port_info):
        if not self._get_active_path_count(context, port_info):
            # TODO(ivar): change APICAPI to not expect a resource context
            context._plugin = self.gbp_plugin
            context._plugin_context = context
            atenant_id = self.name_mapper.tenant(context,
                                                 port_info['tenant_id'])
            l2p = self.name_mapper.endpoint_group(context,
                                                  port_info['l2_policy_id'])
            self._delete_port_path(context, atenant_id, l2p, port_info)

    def _ensure_default_security_group(self, context, tenant_id):
        # TODO(ivar): override to provide 'ALLOW ALL' SG for all the GBP ports
        return super(ApicMappingDriver, self)._ensure_default_security_group(
            context, tenant_id)

    def _handle_contracts(self, context):
        pass

    def _gateway_ip(self, subnet):
        cidr = netaddr.IPNetwork(subnet['cidr'])
        return '%s/%s' % (subnet['gateway_ip'], str(cidr.prefixlen))

    def _subnet_ids_to_objects(self, plugin_context, ids):
        return [x for x in self._core_plugin.get_subnets(
                plugin_context, filters={'id': ids})]

    def _port_to_epg_network(self, context, port, host=None):
        epg = self._port_id_to_epg(context, port['id'])
        if not epg:
            # Not GBP port
            return None, None
        network = self._l2p_id_to_network(context, epg['l2_policy_id'])
        return epg, network

    def _port_id_to_ep(self, context, port_id):
        ep = (context.session.query(gpdb.EndpointMapping).
              filter_by(port_id=port_id).first())
        if ep:
            db_utils = gpdb.GroupPolicyMappingDbPlugin()
            return db_utils._make_endpoint_dict(ep)

    def _port_id_to_epg(self, context, port_id):
        ep = self._port_id_to_ep(context, port_id)
        if ep:
            return self.gbp_plugin.get_endpoint_group(
                context, ep['endpoint_group_id'])
        return

    def _l2p_id_to_network(self, context, l2p_id):
        l2_policy = self.gbp_plugin.get_l2_policy(context, l2p_id)
        return self._core_plugin.get_network(context, l2_policy['network_id'])

    def _network_id_to_l2p(self, context, network_id):
        l2ps = self.gbp_plugin.get_l2_policies(
            context, filters={'network_id': [network_id]})
        return l2ps[0] if l2ps else None

    def _subnet_to_epg(self, context, subnet_id):
        epg = (context.session.query(gpdb.EndpointGroupMapping).
               join(gpdb.EndpointGroupMapping.subnets).
               filter(gpdb.EndpointGroupSubnetAssociation.subnet_id ==
                      subnet_id).
               first())
        if epg:
            db_utils = gpdb.GroupPolicyMappingDbPlugin()
            return db_utils._make_endpoint_group_dict(epg)
