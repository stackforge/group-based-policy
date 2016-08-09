# Copyright (c) 2016 Cisco Systems Inc.
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

from aim import aim_manager
from aim.api import resource as aim_resource
from aim import context as aim_context
from neutron._i18n import _LE
from neutron._i18n import _LI
from neutron._i18n import _LW
from neutron.agent.linux import dhcp
from neutron.common import constants as n_constants
from neutron.common import rpc as n_rpc
# from neutron.db import models_v2
from neutron.extensions import portbindings
from neutron import manager
from neutron.plugins.ml2 import driver_api as api
from neutron.plugins.ml2 import rpc as ml2_rpc
from opflexagent import constants as ofcst
from opflexagent import rpc as o_rpc
from oslo_log import log

from gbpservice.neutron.plugins.ml2plus import driver_api as api_plus
from gbpservice.neutron.plugins.ml2plus.drivers.apic_aim import apic_mapper
from gbpservice.neutron.plugins.ml2plus.drivers.apic_aim import cache
from gbpservice.neutron.plugins.ml2plus.drivers.apic_aim.extensions import (
    cisco_apic)
from gbpservice.neutron.plugins.ml2plus.drivers.apic_aim import model

LOG = log.getLogger(__name__)
AP_NAME = 'NeutronAP'
UNROUTED_VRF_NAME = 'UnroutedVRF'
COMMON_TENANT_NAME = 'common'
AGENT_TYPE_DVS = 'DVS agent'
VIF_TYPE_DVS = 'dvs'
PROMISCUOUS_TYPES = [n_constants.DEVICE_OWNER_DHCP,
                     n_constants.DEVICE_OWNER_LOADBALANCER]


class ApicMechanismDriver(api_plus.MechanismDriver):

    def __init__(self):
        LOG.info(_LI("APIC AIM MD __init__"))

    def initialize(self):
        LOG.info(_LI("APIC AIM MD initializing"))
        self.project_name_cache = cache.ProjectNameCache()
        self.db = model.DbModel()
        self.name_mapper = apic_mapper.APICNameMapper(self.db, log)
        self.aim = aim_manager.AimManager()

        # REVISIT(rkukura): Read from config or possibly from AIM?
        self.enable_dhcp_opt = True
        self.enable_metadata_opt = True

        self._setup_opflex_rpc_listeners()

    def _setup_opflex_rpc_listeners(self):
        self.opflex_endpoints = [o_rpc.GBPServerRpcCallback(self)]
        self.opflex_topic = o_rpc.TOPIC_OPFLEX
        self.opflex_conn = n_rpc.create_connection(new=True)
        self.opflex_conn.create_consumer(
            self.opflex_topic, self.opflex_endpoints, fanout=False)
        self.opflex_conn.consume_in_threads()

    def ensure_tenant(self, plugin_context, tenant_id):
        LOG.info(_LI("APIC AIM MD ensuring tenant_id: %s"), tenant_id)

        self.project_name_cache.ensure_project(tenant_id)

        # TODO(rkukura): Move the following to precommit methods so
        # AIM tenants and application profiles are created whenever
        # needed.
        session = plugin_context.session
        with session.begin(subtransactions=True):
            project_name = self.project_name_cache.get_project_name(tenant_id)
            LOG.debug("Got project_name: %s", project_name)
            tenant_aname = self.name_mapper.tenant(session, tenant_id,
                                                   project_name)
            LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                     {'id': tenant_id, 'apic_name': tenant_aname})

            aim_ctx = aim_context.AimContext(session)

            tenant = aim_resource.Tenant(name=tenant_aname)
            if not self.aim.get(aim_ctx, tenant):
                self.aim.create(aim_ctx, tenant)

            ap = aim_resource.ApplicationProfile(tenant_name=tenant_aname,
                                                 name=AP_NAME)
            if not self.aim.get(aim_ctx, ap):
                self.aim.create(aim_ctx, ap)

    def create_network_precommit(self, context):
        LOG.info(_LI("APIC AIM MD creating network: %s"), context.current)

        session = context._plugin_context.session

        tenant_id = context.current['tenant_id']
        tenant_aname = self.name_mapper.tenant(session, tenant_id)
        LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                 {'id': tenant_id, 'apic_name': tenant_aname})

        id = context.current['id']
        name = context.current['name']
        aname = self.name_mapper.network(session, id, name)
        LOG.info(_LI("Mapped network_id %(id)s with name %(name)s to "
                     "%(apic_name)s"),
                 {'id': id, 'name': name, 'apic_name': aname})
        dname = self._make_display_name(name)

        aim_ctx = aim_context.AimContext(session)

        vrf = self._get_unrouted_vrf(aim_ctx)

        bd = aim_resource.BridgeDomain(
            tenant_name=tenant_aname,
            name=aname,
            display_name=dname,
            vrf_name=vrf.name,
            enable_arp_flood=True,
            enable_routing=False,
            limit_ip_learn_to_subnets=True)
        self.aim.create(aim_ctx, bd)

        epg = aim_resource.EndpointGroup(
            tenant_name=tenant_aname,
            app_profile_name=AP_NAME,
            name=aname,
            display_name=dname,
            bd_name=aname)
        self.aim.create(aim_ctx, epg)

    def update_network_precommit(self, context):
        LOG.info(_LI("APIC AIM MD updating network: %s"),
                 context.current)

        if context.current['name'] != context.original['name']:
            session = context._plugin_context.session

            tenant_id = context.current['tenant_id']
            tenant_aname = self.name_mapper.tenant(session, tenant_id)
            LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                     {'id': tenant_id, 'apic_name': tenant_aname})

            aname = self.name_mapper.network(session,
                                             context.current['id'])
            LOG.info(_LI("Mapped network_id %(id)s to %(apic_name)s"),
                     {'id': id, 'apic_name': aname})

            dname = self._make_display_name(context.current['name'])

            aim_ctx = aim_context.AimContext(session)

            bd = aim_resource.BridgeDomain(tenant_name=tenant_aname,
                                           name=aname)
            bd = self.aim.update(aim_ctx, bd, display_name=dname)

            epg = aim_resource.EndpointGroup(tenant_name=tenant_aname,
                                             app_profile_name=AP_NAME,
                                             name=aname)
            epg = self.aim.update(aim_ctx, epg, display_name=dname)

    def delete_network_precommit(self, context):
        LOG.info(_LI("APIC AIM MD deleting network: %s"), context.current)

        session = context._plugin_context.session

        tenant_id = context.current['tenant_id']
        tenant_aname = self.name_mapper.tenant(session, tenant_id)
        LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                 {'id': tenant_id, 'apic_name': tenant_aname})

        id = context.current['id']
        aname = self.name_mapper.network(session, id)
        LOG.info(_LI("Mapped network_id %(id)s to %(apic_name)s"),
                 {'id': id, 'apic_name': aname})

        aim_ctx = aim_context.AimContext(session)

        epg = aim_resource.EndpointGroup(tenant_name=tenant_aname,
                                         app_profile_name=AP_NAME,
                                         name=aname)
        self.aim.delete(aim_ctx, epg)

        bd = aim_resource.BridgeDomain(tenant_name=tenant_aname,
                                       name=aname)
        self.aim.delete(aim_ctx, bd)

        self.name_mapper.delete_apic_name(session, id)

    def extend_network_dict(self, session, base_model, result):
        LOG.info(_LI("APIC AIM MD extending dict for network: %s"), result)

        sync_state = cisco_apic.SYNC_SYNCED

        tenant_id = result['tenant_id']
        tenant_aname = self.name_mapper.tenant(session, tenant_id)
        LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                 {'id': tenant_id, 'apic_name': tenant_aname})
        if not tenant_aname:
            return

        id = result['id']
        aname = self.name_mapper.network(session, id)
        LOG.info(_LI("Mapped network_id %(id)s to %(apic_name)s"),
                 {'id': id, 'apic_name': aname})
        if not aname:
            return

        aim_ctx = aim_context.AimContext(session)

        bd = aim_resource.BridgeDomain(tenant_name=tenant_aname,
                                       name=aname)
        bd = self.aim.get(aim_ctx, bd)
        LOG.debug("got BD with DN: %s", bd.dn)

        epg = aim_resource.EndpointGroup(tenant_name=tenant_aname,
                                         app_profile_name=AP_NAME,
                                         name=aname)
        epg = self.aim.get(aim_ctx, epg)
        LOG.debug("got EPG with DN: %s", epg.dn)

        result[cisco_apic.DIST_NAMES] = {cisco_apic.BD: bd.dn,
                                         cisco_apic.EPG: epg.dn}

        bd_status = self.aim.get_status(aim_ctx, bd)
        sync_state = self._merge_status(sync_state, bd_status)
        epg_status = self.aim.get_status(aim_ctx, epg)
        sync_state = self._merge_status(sync_state, epg_status)
        result[cisco_apic.SYNC_STATE] = sync_state

    def create_subnet_precommit(self, context):
        LOG.info(_LI("APIC AIM MD creating subnet: %s"), context.current)

    def update_subnet_precommit(self, context):
        LOG.info(_LI("APIC AIM MD updating subnet: %s"), context.current)

    def delete_subnet_precommit(self, context):
        LOG.info(_LI("APIC AIM MD deleting subnet: %s"), context.current)

    def extend_subnet_dict(self, session, base_model, result):
        LOG.info(_LI("APIC AIM MD extending dict for subnet: %s"), result)

        sync_state = cisco_apic.SYNC_SYNCED

        result[cisco_apic.DIST_NAMES] = {}
        result[cisco_apic.SYNC_STATE] = sync_state

    def create_address_scope_precommit(self, context):
        LOG.info(_LI("APIC AIM MD creating address scope: %s"),
                 context.current)

        session = context._plugin_context.session

        tenant_id = context.current['tenant_id']
        tenant_aname = self.name_mapper.tenant(session, tenant_id)
        LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                 {'id': tenant_id, 'apic_name': tenant_aname})

        id = context.current['id']
        name = context.current['name']
        aname = self.name_mapper.address_scope(session, id, name)
        LOG.info(_LI("Mapped address_scope_id %(id)s with name %(name)s to "
                     "%(apic_name)s"),
                 {'id': id, 'name': name, 'apic_name': aname})

        aim_ctx = aim_context.AimContext(session)

        vrf = aim_resource.VRF(
            tenant_name=tenant_aname,
            name=aname,
            display_name=self._make_display_name(name))
        self.aim.create(aim_ctx, vrf)
        vrf_dn = vrf.dn
        vrf_status = self.aim.get_status(aim_ctx, vrf)
        sync_state = cisco_apic.SYNC_SYNCED
        sync_state = self._merge_status(sync_state, vrf_status)

        # ML2Plus does not extend address scope dict after precommit.
        context.current[cisco_apic.DIST_NAMES] = {cisco_apic.VRF:
                                                  vrf_dn}
        context.current[cisco_apic.SYNC_STATE] = sync_state

    def update_address_scope_precommit(self, context):
        LOG.info(_LI("APIC AIM MD updating address_scope: %s"),
                 context.current)

        if context.current['name'] != context.original['name']:
            session = context._plugin_context.session

            tenant_id = context.current['tenant_id']
            tenant_aname = self.name_mapper.tenant(session, tenant_id)
            LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                     {'id': tenant_id, 'apic_name': tenant_aname})

            aname = self.name_mapper.address_scope(session,
                                                   context.current['id'])
            LOG.info(_LI("Mapped address_scope_id %(id)s to %(apic_name)s"),
                     {'id': id, 'apic_name': aname})

            dname = self._make_display_name(context.current['name'])

            aim_ctx = aim_context.AimContext(session)

            vrf = aim_resource.VRF(tenant_name=tenant_aname,
                                   name=aname)
            vrf = self.aim.update(aim_ctx, vrf, display_name=dname)

    def delete_address_scope_precommit(self, context):
        LOG.info(_LI("APIC AIM MD deleting address scope: %s"),
                 context.current)

        session = context._plugin_context.session

        tenant_id = context.current['tenant_id']
        tenant_aname = self.name_mapper.tenant(session, tenant_id)
        LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                 {'id': tenant_id, 'apic_name': tenant_aname})

        id = context.current['id']
        aname = self.name_mapper.address_scope(session, id)
        LOG.info(_LI("Mapped address_scope_id %(id)s to %(apic_name)s"),
                 {'id': id, 'apic_name': aname})

        aim_ctx = aim_context.AimContext(session)

        vrf = aim_resource.VRF(tenant_name=tenant_aname,
                               name=aname)
        self.aim.delete(aim_ctx, vrf)

        self.name_mapper.delete_apic_name(session, id)

    def extend_address_scope_dict(self, session, base_model, result):
        LOG.info(_LI("APIC AIM MD extending dict for address scope: %s"),
                 result)

        sync_state = cisco_apic.SYNC_SYNCED

        tenant_id = result['tenant_id']
        tenant_aname = self.name_mapper.tenant(session, tenant_id)
        LOG.info(_LI("Mapped tenant_id %(id)s to %(apic_name)s"),
                 {'id': tenant_id, 'apic_name': tenant_aname})
        if not tenant_aname:
            return

        id = result['id']
        aname = self.name_mapper.address_scope(session, id)
        LOG.info(_LI("Mapped address_scope_id %(id)s to %(apic_name)s"),
                 {'id': id, 'apic_name': aname})
        if not aname:
            return

        aim_ctx = aim_context.AimContext(session)

        vrf = aim_resource.VRF(tenant_name=tenant_aname,
                               name=aname)
        vrf = self.aim.get(aim_ctx, vrf)
        if vrf:
            vrf_dn = vrf.dn
            LOG.debug("got VRF with DN: %s", vrf_dn)
            vrf_status = self.aim.get_status(aim_ctx, vrf)
            sync_state = self._merge_status(sync_state, vrf_status)
        else:
            # This should always get replaced with the real DN during
            # precommit.
            vrf_dn = "AIM VRF not yet created"
        result[cisco_apic.DIST_NAMES] = {cisco_apic.VRF: vrf_dn}
        result[cisco_apic.SYNC_STATE] = sync_state

    def bind_port(self, context):
        LOG.debug("Attempting to bind port %(port)s on network %(net)s",
                  {'port': context.current['id'],
                   'net': context.network.current['id']})

        # TODO(rkukura): Add support for baremetal hosts, SR-IOV and
        # other situations requiring dynamic segments.

        # Check the VNIC type.
        vnic_type = context.current.get(portbindings.VNIC_TYPE,
                                        portbindings.VNIC_NORMAL)
        if vnic_type not in [portbindings.VNIC_NORMAL]:
            LOG.debug("Refusing to bind due to unsupported vnic_type: %s",
                      vnic_type)
            return

        # For compute ports, try to bind DVS agent first.
        if context.current['device_owner'].startswith('compute:'):
            if self._agent_bind_port(context, AGENT_TYPE_DVS,
                                     self._dvs_bind_port):
                return

        # Try to bind OpFlex agent.
        self._agent_bind_port(context, ofcst.AGENT_TYPE_OPFLEX_OVS,
                              self._opflex_bind_port)

    def _agent_bind_port(self, context, agent_type, bind_strategy):
        for agent in context.host_agents(agent_type):
            LOG.debug("Checking agent: %s", agent)
            if agent['alive']:
                for segment in context.segments_to_bind:
                    if bind_strategy(context, segment, agent):
                        LOG.debug("Bound using segment: %s", segment)
            else:
                LOG.warning(_LW("Refusing to bind port %(port)s to dead "
                                "agent: %(agent)s"),
                            {'port': context.current['id'], 'agent': agent})

    def _opflex_bind_port(self, context, segment, agent):
        network_type = segment[api.NETWORK_TYPE]
        if network_type == ofcst.TYPE_OPFLEX:
            opflex_mappings = agent['configurations'].get('opflex_networks')
            LOG.debug("Checking segment: %(segment)s "
                      "for physical network: %(mappings)s ",
                      {'segment': segment, 'mappings': opflex_mappings})
            if (opflex_mappings is not None and
                segment[api.PHYSICAL_NETWORK] not in opflex_mappings):
                return False
        elif network_type != 'local':
            return False

        context.set_binding(segment[api.ID],
                            portbindings.VIF_TYPE_OVS,
                            {portbindings.CAP_PORT_FILTER: False,
                             portbindings.OVS_HYBRID_PLUG: False})

    def _dvs_bind_port(self, context, segment, agent):
        # TODO(rkukura): Implement DVS port binding
        return False

    # RPC Method
    def get_gbp_details(self, context, **kwargs):
        LOG.debug("APIC AIM MD handling get_gbp_details for: %s", kwargs)
        try:
            return self._get_gbp_details(context, kwargs)
        except Exception as e:
            device = kwargs.get('device')
            LOG.error(_LE("An exception has occurred while retrieving device "
                          "gbp details for %s"), device)
            LOG.exception(e)
            return {'device': device}

    def request_endpoint_details(self, context, **kwargs):
        LOG.debug("APIC AIM MD handling get_endpoint_details for: %s", kwargs)
        try:
            request = kwargs.get('request')
            result = {'device': request['device'],
                      'timestamp': request['timestamp'],
                      'request_id': request['request_id'],
                      'gbp_details': None,
                      'neutron_details': None}
            result['gbp_details'] = self._get_gbp_details(context, request)
            result['neutron_details'] = ml2_rpc.RpcCallbacks(
                None, None).get_device_details(context, **request)
            return result
        except Exception as e:
            LOG.error(_LE("An exception has occurred while requesting device "
                          "gbp details for %s"), request.get('device'))
            LOG.exception(e)
            return None

    def _get_gbp_details(self, context, request):
        device = request.get('device')
        host = request.get('host')

        core_plugin = manager.NeutronManager.get_plugin()
        port_id = core_plugin._device_to_port_id(context, device)
        port_context = core_plugin.get_bound_port_context(context, port_id,
                                                          host)
        if not port_context:
            LOG.warning(_LW("Device %(device)s requested by agent "
                            "%(agent_id)s not found in database"),
                        {'device': port_id,
                         'agent_id': request.get('agent_id')})
            return {'device': device}

        port = port_context.current
        if port[portbindings.HOST_ID] != host:
            LOG.warning(_LW("Device %(device)s requested by agent "
                            "%(agent_id)s not found bound for host %(host)s"),
                        {'device': port_id, 'host': host,
                         'agent_id': request.get('agent_id')})
            return

        session = context.session
        with session.begin(subtransactions=True):
            # REVISIT(rkukura): Should AIM resources be
            # validated/created here if necessary? Also need to avoid
            # creating any new name mappings without first getting
            # their resource names.

            # TODO(rkukura): For GBP, we need to use the EPG
            # associated with the port's PT's PTG. For now, we just use the
            # network's default EPG.

            # TODO(rkukura): Use common tenant for shared networks.

            # TODO(rkukura): Scope the tenant's AIM name.

            network = port_context.network.current
            epg_tenant_aname = self.name_mapper.tenant(session,
                                                       network['tenant_id'])
            epg_aname = self.name_mapper.network(session, network['id'])

        promiscuous_mode = port['device_owner'] in PROMISCUOUS_TYPES

        details = {'allowed_address_pairs': port['allowed_address_pairs'],
                   'app_profile_name': AP_NAME,
                   'device': device,
                   'enable_dhcp_optimization': self.enable_dhcp_opt,
                   'enable_metadata_optimization': self.enable_metadata_opt,
                   'endpoint_group_name': epg_aname,
                   'host': host,
                   'l3_policy_id': network['tenant_id'],  # TODO(rkukura)
                   'mac_address': port['mac_address'],
                   'port_id': port_id,
                   'promiscuous_mode': promiscuous_mode,
                   'ptg_tenant': epg_tenant_aname,
                   'subnets': self._get_subnet_details(core_plugin, context,
                                                       port)}

        if port['device_owner'].startswith('compute:') and port['device_id']:
            # REVISIT(rkukura): Do we need to map to name using nova client?
            details['vm-name'] = port['device_id']

        # TODO(rkukura): Mark active allowed_address_pairs

        # TODO(rkukura): Add the following details common to the old
        # GBP and ML2 drivers: floating_ip, host_snat_ips, ip_mapping,
        # vrf_name, vrf_subnets, vrf_tenant.

        # TODO(rkukura): Add the following details unique to the old
        # ML2 driver: attestation, interface_mtu.

        # TODO(rkukura): Add the following details unique to the old
        # GBP driver: extra_details, extra_ips, fixed_ips,
        # l2_policy_id.

        return details

    def _get_subnet_details(self, core_plugin, context, port):
        subnets = core_plugin.get_subnets(
            context,
            filters={'id': [ip['subnet_id'] for ip in port['fixed_ips']]})
        for subnet in subnets:
            dhcp_ips = set()
            for port in core_plugin.get_ports(
                    context, filters={
                        'network_id': [subnet['network_id']],
                        'device_owner': [n_constants.DEVICE_OWNER_DHCP]}):
                dhcp_ips |= set([x['ip_address'] for x in port['fixed_ips']
                                 if x['subnet_id'] == subnet['id']])
            dhcp_ips = list(dhcp_ips)
            if not subnet['dns_nameservers']:
                # Use DHCP namespace port IP
                subnet['dns_nameservers'] = dhcp_ips
            # Ser Default route if needed
            metadata = default = False
            if subnet['ip_version'] == 4:
                for route in subnet['host_routes']:
                    if route['destination'] == '0.0.0.0/0':
                        default = True
                    if route['destination'] == dhcp.METADATA_DEFAULT_CIDR:
                        metadata = True
                # Set missing routes
                if not default:
                    subnet['host_routes'].append(
                        {'destination': '0.0.0.0/0',
                         'nexthop': subnet['gateway_ip']})
                if not metadata and dhcp_ips and not self.enable_metadata_opt:
                    subnet['host_routes'].append(
                        {'destination': dhcp.METADATA_DEFAULT_CIDR,
                         'nexthop': dhcp_ips[0]})
            subnet['dhcp_server_ips'] = dhcp_ips
        return subnets

    def _merge_status(self, sync_state, status):
        if status.is_error():
            sync_state = cisco_apic.SYNC_ERROR
        elif status.is_build() and sync_state is not cisco_apic.SYNC_ERROR:
            sync_state = cisco_apic.SYNC_BUILD
        return sync_state

    def _gateway_ip_mask(self, subnet):
        gateway_ip = subnet['gateway_ip']
        if gateway_ip:
            prefix_len = subnet['cidr'].split('/')[1]
            return gateway_ip + '/' + prefix_len

    def _make_display_name(self, name):
        return name[:59]

    def _get_common_tenant(self, aim_ctx):
        attrs = aim_resource.Tenant(name=COMMON_TENANT_NAME,
                                    display_name='Common Tenant')
        tenant = self.aim.get(aim_ctx, attrs)
        if not tenant:
            LOG.info(_LI("Creating common tenant"))
            tenant = self.aim.create(aim_ctx, attrs)
        return tenant

    def _get_unrouted_vrf(self, aim_ctx):
        tenant = self._get_common_tenant(aim_ctx)
        attrs = aim_resource.VRF(tenant_name=tenant.name,
                                 name=UNROUTED_VRF_NAME,
                                 display_name='Common Unrouted Context')
        vrf = self.aim.get(aim_ctx, attrs)
        if not vrf:
            LOG.info(_LI("Creating common unrouted VRF"))
            vrf = self.aim.create(aim_ctx, attrs)
        return vrf
