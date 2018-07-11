# Copyright (c) 2017 Cisco Systems Inc.
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

import copy

from aim.aim_lib.db import model as aim_lib_model
from aim.api import infra as aim_infra
from aim.api import resource as aim_resource
from aim import context as aim_context
from neutron.tests.unit.extensions import test_securitygroup
from neutron_lib import context as n_context

from gbpservice.neutron.db.grouppolicy import group_policy_db as gpdb
from gbpservice.neutron.plugins.ml2plus.drivers.apic_aim import db
from gbpservice.neutron.services.grouppolicy import (
    group_policy_driver_api as api)
from gbpservice.neutron.services.grouppolicy.drivers.cisco.apic import (
    aim_validation as av)
from gbpservice.neutron.tests.unit.services.grouppolicy import (
    test_aim_mapping_driver)
from gbpservice.neutron.tests.unit.services.sfc import test_aim_sfc_driver


class AimValidationTestMixin(object):

    def _validate(self):
        # Validate should pass.
        self.assertEqual(api.VALIDATION_PASSED, self.av_mgr.validate())

    def _validate_repair_validate(self):
        # Validate should fail.
        self.assertEqual(api.VALIDATION_FAILED, self.av_mgr.validate())

        # Repair.
        self.assertEqual(
            api.VALIDATION_REPAIRED, self.av_mgr.validate(repair=True))

        # Validate should pass.
        self.assertEqual(api.VALIDATION_PASSED, self.av_mgr.validate())

    def _validate_unrepairable(self):
        # Repair should fail.
        self.assertEqual(
            api.VALIDATION_FAILED, self.av_mgr.validate(repair=True))

    def _test_aim_resource(self, resource, unexpected_attr_name='name',
                           unexpected_attr_value='unexpected'):
        resource = copy.copy(resource)

        # Delete the AIM resource and test.
        self.aim_mgr.delete(self.aim_ctx, resource)
        self._validate_repair_validate()

        # Modify the AIM resource and test.
        self.aim_mgr.update(
            self.aim_ctx, resource, display_name='not what it was')
        self._validate_repair_validate()

        # Add unexpected AIM resource and test.
        setattr(resource, unexpected_attr_name, unexpected_attr_value)
        self.aim_mgr.create(self.aim_ctx, resource)
        self._validate_repair_validate()

        # Add unexpected monitored AIM resource and test.
        resource.monitored = True
        self.aim_mgr.create(self.aim_ctx, resource)
        self._validate()

        # Delete unexpected monitored AIM resource.
        self.aim_mgr.delete(self.aim_ctx, resource)


class AimValidationTestCase(test_aim_mapping_driver.AIMBaseTestCase,
                            test_securitygroup.SecurityGroupsTestCase,
                            AimValidationTestMixin):

    def setUp(self):
        super(AimValidationTestCase, self).setUp()
        self.av_mgr = av.ValidationManager()
        self.aim_ctx = aim_context.AimContext(self.db_session)


class TestNeutronMapping(AimValidationTestCase):

    def setUp(self):
        super(TestNeutronMapping, self).setUp()

    def _test_routed_subnet(self, subnet_id, gw_ip):
        # Get the AIM Subnet.
        subnet = self._show('subnets', subnet_id)['subnet']
        sn_dn = subnet['apic:distinguished_names'][gw_ip]
        sn = aim_resource.Subnet.from_dn(sn_dn)

        # Test the AIM Subnet.
        self._test_aim_resource(sn, 'gw_ip_mask', '4.3.2.1/24')

    def _test_unscoped_vrf(self, router_id):
        # Get the router's unscoped AIM VRF.
        router = self._show('routers', router_id)['router']
        vrf_dn = router['apic:distinguished_names']['no_scope-VRF']
        vrf = aim_resource.VRF.from_dn(vrf_dn)

        # Test the AIM VRF.
        self._test_aim_resource(vrf)

    def test_static_resources(self):
        # Validate with initial static resources.
        self._validate()

        # Delete the common Tenant and test.
        tenant = aim_resource.Tenant(name='common')
        self.aim_mgr.delete(self.aim_ctx, tenant)
        self._validate_repair_validate()

        # Test unrouted AIM VRF.
        vrf = aim_resource.VRF(
            name=self.driver.aim_mech_driver.apic_system_id + '_UnroutedVRF',
            tenant_name='common')
        self._test_aim_resource(vrf)

        # Test the any Filter.
        filter_name = (self.driver.aim_mech_driver.apic_system_id +
                       '_AnyFilter')
        filter = aim_resource.Filter(
            name=filter_name,
            tenant_name='common')
        self._test_aim_resource(filter)

        # Test the any FilterEntry.
        entry = aim_resource.FilterEntry(
            name='AnyFilterEntry',
            filter_name=filter_name,
            tenant_name='common')
        self._test_aim_resource(entry)

        # Test the default SecurityGroup.
        sg_name = (self.driver.aim_mech_driver.apic_system_id +
                   '_DefaultSecurityGroup')
        sg = aim_resource.SecurityGroup(
            name=sg_name,
            tenant_name='common')
        self._test_aim_resource(sg)

        # Test the default SecurityGroupSubject.
        sg_subject = aim_resource.SecurityGroupSubject(
            name='default',
            security_group_name=sg_name,
            tenant_name='common')
        self._test_aim_resource(sg_subject)

        # Test one default SecurityGroupRule.
        sg_rule = aim_resource.SecurityGroupRule(
            name='arp_egress',
            security_group_subject_name='default',
            security_group_name=sg_name,
            tenant_name='common')
        self._test_aim_resource(sg_rule)

    def _test_project_resources(self, project_id):
        # Validate with initial project resources.
        self._validate()

        # Test AIM Tenant.
        tenant_name = self.driver.aim_mech_driver.name_mapper.project(
            None, project_id)
        tenant = aim_resource.Tenant(name=tenant_name)
        self._test_aim_resource(tenant)

        # Test AIM ApplicationProfile.
        ap = aim_resource.ApplicationProfile(
            tenant_name=tenant_name, name='OpenStack')
        self._test_aim_resource(ap)

    def test_project_resources(self):
        # REVISIT: Currently, a project's AIM Tenant and
        # ApplicationProfile are created in ensure_tenant just before
        # any Neutron/GBP resource is created using that project, and
        # are not cleaned up when the last Neutron/GBP resource
        # needing them is deleted. Instead, they are cleaned up when a
        # notification is received from Keystone that the project has
        # been deleted. We should consider managing these AIM
        # resources more dynamically. If we do, this test will need to
        # be reworked.

        # Test address scope.
        scope = self._make_address_scope(
            self.fmt, 4, name='as1', tenant_id='as_proj')['address_scope']
        self._test_project_resources(scope['project_id'])

        # Test network.
        net_resp = self._make_network(
            self.fmt, 'net1', True, tenant_id='net_proj')
        net = net_resp['network']
        self._test_project_resources(net['project_id'])

        # Test subnet.
        subnet = self._make_subnet(
            self.fmt, net_resp, '10.0.1.1', '10.0.1.0/24',
            tenant_id='subnet_proj')['subnet']
        self._test_project_resources(subnet['project_id'])

        # Test port. Since Neutron creates the default SG for the
        # port's project even when security_groups=[] is passed, we
        # need to delete the default SG to ensure the port is the only
        # resource owned by port_prog.
        port = self._make_port(
            self.fmt, net['id'], security_groups=[],
            tenant_id='port_proj')['port']
        sgs = self._list(
            'security-groups',
            query_params='project_id=port_proj')['security_groups']
        self.assertEqual(1, len(sgs))
        self._delete('security-groups', sgs[0]['id'])
        self._test_project_resources(port['project_id'])

        # Test security group.
        sg = self._make_security_group(
            self.fmt, 'sg1', 'desc1', tenant_id='sg_proj')['security_group']
        self._test_project_resources(sg['project_id'])

        # Test subnetpool.
        sp = self._make_subnetpool(
            self.fmt, ['10.0.0.0/8'], name='sp1', tenant_id='sp_proj',
            default_prefixlen=24)['subnetpool']
        self._test_project_resources(sp['project_id'])

        # Test router.
        router = self._make_router(
            self.fmt, 'router_proj', 'router1')['router']
        self._test_project_resources(router['project_id'])

        # Test floatingip.
        kwargs = {'router:external': True}
        ext_net_resp = self._make_network(
            self.fmt, 'ext_net', True, arg_list=self.extension_attributes,
            **kwargs)
        ext_net = ext_net_resp['network']
        self._make_subnet(
            self.fmt, ext_net_resp, '100.100.100.1', '100.100.100.0/24')
        fip = self._make_floatingip(
            self.fmt, ext_net['id'], tenant_id='fip_proj')['floatingip']
        self._test_project_resources(fip['project_id'])

    def test_address_scope(self):
        # Create address scope.
        scope = self._make_address_scope(
            self.fmt, 4, name='as1')['address_scope']
        scope_id = scope['id']
        vrf_dn = scope['apic:distinguished_names']['VRF']
        self._validate()

        # Delete the address scope's mapping record and test.
        (self.db_session.query(db.AddressScopeMapping).
         filter_by(scope_id=scope_id).
         delete())
        self._validate_repair_validate()

        # Test AIM VRF.
        vrf = aim_resource.VRF.from_dn(vrf_dn)
        self._test_aim_resource(vrf)

    # REVISIT: Test isomorphic address scopes.

    def _test_network_resources(self, net_resp):
        net = net_resp['network']
        net_id = net['id']
        bd_dn = net['apic:distinguished_names']['BridgeDomain']
        epg_dn = net['apic:distinguished_names']['EndpointGroup']

        # Create unrouted subnet.
        subnet = self._make_subnet(
            self.fmt, net_resp, '10.0.2.1', '10.0.2.0/24')['subnet']
        self._validate()

        # Delete the network's mapping record and test.
        (self.db_session.query(db.NetworkMapping).
         filter_by(network_id=net_id).
         delete())
        self._validate_repair_validate()

        # Corrupt the network's mapping record's BD and test.
        with self.db_session.begin():
            mapping = (self.db_session.query(db.NetworkMapping).
                       filter_by(network_id=net_id).
                       one())
            mapping.bd_tenant_name = 'bad_bd_tenant_name'
        self._validate_repair_validate()

        # Corrupt the network's mapping record's EPG and test.
        with self.db_session.begin():
            mapping = (self.db_session.query(db.NetworkMapping).
                       filter_by(network_id=net_id).
                       one())
            mapping.epg_app_profile_name = 'bad_epg_app_profilename'
        self._validate_repair_validate()

        # Corrupt the network's mapping record's VRF and test.
        with self.db_session.begin():
            mapping = (self.db_session.query(db.NetworkMapping).
                       filter_by(network_id=net_id).
                       one())
            mapping.vrf_name = 'bad_vrf_name'
        self._validate_repair_validate()

        # Test AIM BridgeDomain.
        bd = aim_resource.BridgeDomain.from_dn(bd_dn)
        self._test_aim_resource(bd)

        # Test AIM EndpointGroup.
        epg = aim_resource.EndpointGroup.from_dn(epg_dn)
        self._test_aim_resource(epg)

        # Test AIM Subnet.
        if not net['router:external']:
            # Add unexpect AIM Subnet if not external.
            sn = self.driver.aim_mech_driver._map_subnet(
                subnet, '10.0.2.1', bd)
            self.aim_mgr.create(self.aim_ctx, sn)
            self._validate_repair_validate()
        else:
            # Test AIM Subnet if external.
            #
            # REVISIT: If Subnet DN were included in
            # apic:distinguished_names, which it should be, could just
            # use _test_routed_subnet().
            #
            sn = aim_resource.Subnet(
                tenant_name = bd.tenant_name,
                bd_name = bd.name,
                gw_ip_mask='10.0.2.1/24')
            self._test_aim_resource(sn, 'gw_ip_mask', '10.0.3.1/24')

    def test_unrouted_network(self):
        # Create network.
        net_resp = self._make_network(self.fmt, 'net1', True)
        self._validate()

        # Test AIM resources.
        self._test_network_resources(net_resp)

    def _test_external_network(self):
        # Create AIM HostDomainMappingV2.
        hd_mapping = aim_infra.HostDomainMappingV2(
            host_name='*', domain_name='vm2', domain_type='OpenStack')
        self.aim_mgr.create(self.aim_ctx, hd_mapping)

        # Create external network.
        kwargs = {'router:external': True,
                  'apic:distinguished_names':
                  {'ExternalNetwork': 'uni/tn-common/out-l1/instP-n1'}}
        net_resp = self._make_network(
            self.fmt, 'ext_net', True, arg_list=self.extension_attributes,
            **kwargs)
        self._validate()

        # Test standard network AIM resources.
        self._test_network_resources(net_resp)

        # Test AIM L3Outside.
        l3out = aim_resource.L3Outside(tenant_name='common', name='l1')
        self._test_aim_resource(l3out)

        # Test AIM ExternalNetwork.
        en = aim_resource.ExternalNetwork(
            tenant_name='common', l3out_name='l1', name='n1')
        self._test_aim_resource(en)

        # Test AIM ExternalSubnet.
        esn = aim_resource.ExternalSubnet(
            tenant_name='common', l3out_name='l1', external_network_name='n1',
            cidr='0.0.0.0/0')
        self._test_aim_resource(esn, 'cidr', '1.2.3.4/0')

        # Test AIM VRF.
        vrf = aim_resource.VRF(tenant_name='common', name='openstack_EXT-l1')
        self._test_aim_resource(vrf)

        # Test AIM ApplicationProfile.
        ap = aim_resource.ApplicationProfile(
            tenant_name='common', name='openstack_OpenStack')
        self._test_aim_resource(ap)

        # Test AIM Contract.
        contract = aim_resource.Contract(
            tenant_name='common', name='openstack_EXT-l1')
        self._test_aim_resource(contract)

        # Test AIM ContractSubject.
        subject = aim_resource.ContractSubject(
            tenant_name='common', contract_name='openstack_EXT-l1',
            name='Allow')
        self._test_aim_resource(subject)

        # Test AIM Filter.
        filter = aim_resource.Filter(
            tenant_name='common', name='openstack_EXT-l1')
        self._test_aim_resource(filter)

        # Test AIM FilterEntry.
        entry = aim_resource.FilterEntry(
            tenant_name='common', filter_name='openstack_EXT-l1', name='Any')
        self._test_aim_resource(entry)

    def test_external_network(self):
        self._test_external_network()

    def test_preexisting_external_network(self):
        # Create pre-existing AIM VRF.
        vrf = aim_resource.VRF(tenant_name='common', name='v1', monitored=True)
        self.aim_mgr.create(self.aim_ctx, vrf)

        # Create pre-existing AIM L3Outside.
        l3out = aim_resource.L3Outside(
            tenant_name='common', name='l1', vrf_name='v1', monitored=True)
        self.aim_mgr.create(self.aim_ctx, l3out)

        # Create pre-existing AIM ExternalNetwork.
        ext_net = aim_resource.ExternalNetwork(
            tenant_name='common', l3out_name='l1', name='n1', monitored=True)
        self.aim_mgr.create(self.aim_ctx, ext_net)

        # Create pre-existing AIM ExternalSubnet.
        ext_sn = aim_resource.ExternalSubnet(
            tenant_name='common', l3out_name='l1', external_network_name='n1',
            cidr='0.0.0.0/0', monitored=True)
        self.aim_mgr.create(self.aim_ctx, ext_sn)

        self._test_external_network()

    def test_svi_network(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create SVI network.
        kwargs = {'apic:svi': 'True'}
        self._make_network(
            self.fmt, 'net', True, arg_list=self.extension_attributes,
            **kwargs)

        # Test that validation fails.
        self._validate_unrepairable()

    def test_router(self):
        # Create router.
        router = self._make_router(
            self.fmt, self._tenant_id, 'router1')['router']
        contract_dn = router['apic:distinguished_names']['Contract']
        subject_dn = router['apic:distinguished_names']['ContractSubject']
        self._validate()

        # Test AIM Contract.
        contract = aim_resource.Contract.from_dn(contract_dn)
        self._test_aim_resource(contract)

        # Test AIM ContractSubject.
        subject = aim_resource.ContractSubject.from_dn(subject_dn)
        self._test_aim_resource(subject)

    def test_scoped_routing(self):
        # Create shared address scope and subnetpool as tenant_1.
        scope = self._make_address_scope(
            self.fmt, 4, admin=True, name='as1', tenant_id='tenant_1',
            shared=True)['address_scope']
        pool = self._make_subnetpool(
            self.fmt, ['10.0.0.0/8'], admin=True, name='sp1',
            tenant_id='tenant_1', address_scope_id=scope['id'],
            default_prefixlen=24, shared=True)['subnetpool']
        pool_id = pool['id']

        # Create network and subnet as tenant_2.
        net_resp = self._make_network(
            self.fmt, 'net1', True, tenant_id='tenant_2')
        subnet = self._make_subnet(
            self.fmt, net_resp, '10.0.1.1', '10.0.1.0/24',
            subnetpool_id=pool_id, tenant_id='tenant_2')['subnet']
        subnet_id = subnet['id']

        # Create extra unrouted subnet.
        self._make_subnet(
            self.fmt, net_resp, '10.0.2.1', '10.0.2.0/24',
            subnetpool_id=pool_id, tenant_id='tenant_2')

        # Create external network.
        #
        kwargs = {'router:external': True,
                  'apic:distinguished_names':
                  {'ExternalNetwork': 'uni/tn-common/out-l1/instP-n1'}}
        ext_net = self._make_network(
            self.fmt, 'ext_net', True, arg_list=self.extension_attributes,
            **kwargs)['network']

        # Create extra external network to test CloneL3Out record below.
        #
        kwargs = {'router:external': True,
                  'apic:distinguished_names':
                  {'ExternalNetwork': 'uni/tn-common/out-l2/instP-n2'}}
        self._make_network(
            self.fmt, 'extra_ext_net', True,
            arg_list=self.extension_attributes, **kwargs)

        # Create router as tenant_2.
        kwargs = {'apic:external_provided_contracts': ['p1', 'p2'],
                  'apic:external_consumed_contracts': ['c1', 'c2'],
                  'external_gateway_info': {'network_id': ext_net['id']}}
        router = self._make_router(
            self.fmt, 'tenant_2', 'router1',
            arg_list=self.extension_attributes, **kwargs)['router']
        router_id = router['id']

        # Validate before adding subnet to router.
        self._validate()

        # Add subnet to router.
        self.l3_plugin.add_router_interface(
            n_context.get_admin_context(), router_id,
            {'subnet_id': subnet_id})
        self._validate()

        # Test AIM Subnet.
        self._test_routed_subnet(subnet_id, '10.0.1.1')

        # Determine clone L3Outside identity based on VRF.
        vrf_dn = scope['apic:distinguished_names']['VRF']
        vrf = aim_resource.VRF.from_dn(vrf_dn)
        tenant_name = vrf.tenant_name
        l3out_name = 'l1-%s' % vrf.name

        # Test AIM L3Outside.
        l3out = aim_resource.L3Outside(
            tenant_name=tenant_name, name=l3out_name)
        self._test_aim_resource(l3out)

        # Test AIM ExternalNetwork.
        en = aim_resource.ExternalNetwork(
            tenant_name=tenant_name, l3out_name=l3out_name, name='n1')
        self._test_aim_resource(en)

        # Test AIM ExternalSubnet.
        esn = aim_resource.ExternalSubnet(
            tenant_name=tenant_name, l3out_name=l3out_name,
            external_network_name='n1', cidr='0.0.0.0/0')
        self._test_aim_resource(esn, 'cidr', '1.2.3.4/0')

        # Delete the CloneL3Out record and test.
        (self.db_session.query(aim_lib_model.CloneL3Out).
         filter_by(tenant_name=tenant_name, name=l3out_name).
         delete())
        self._validate_repair_validate()

        # Corrupt the CloneL3Out record and test.
        with self.db_session.begin():
            record = (self.db_session.query(aim_lib_model.CloneL3Out).
                      filter_by(tenant_name=tenant_name, name=l3out_name).
                      one())
            record.source_name = 'l2'
        self._validate_repair_validate()

        # Add monitored L3Out and unexpected CloneL3Out record and test.
        with self.db_session.begin():
            unexpected_l3out_name = 'l2-%s' % vrf.name
            unexpected_l3out = aim_resource.L3Outside(
                tenant_name=tenant_name, name=unexpected_l3out_name,
                monitored=True)
            self.aim_mgr.create(self.aim_ctx, unexpected_l3out)
            record = aim_lib_model.CloneL3Out(
                source_tenant_name='common', source_name='l2',
                name=unexpected_l3out_name, tenant_name=tenant_name)
            self.db_session.add(record)
        self._validate_repair_validate()

    def test_unscoped_routing(self):
        # Create shared network and unscoped subnet as tenant_1.
        net_resp = self._make_network(
            self.fmt, 'net1', True, tenant_id='tenant_1', shared=True)
        subnet = self._make_subnet(
            self.fmt, net_resp, '10.0.1.1', '10.0.1.0/24',
            tenant_id='tenant_1')['subnet']
        subnet1_id = subnet['id']

        # Create unshared network and unscoped subnet as tenant_2.
        net_resp = self._make_network(
            self.fmt, 'net2', True, tenant_id='tenant_2')
        subnet = self._make_subnet(
            self.fmt, net_resp, '10.0.2.1', '10.0.2.0/24',
            tenant_id='tenant_2')['subnet']
        subnet2_id = subnet['id']

        # Create extra unrouted subnet.
        self._make_subnet(
            self.fmt, net_resp, '10.0.3.1', '10.0.3.0/24',
            tenant_id='tenant_2')

        # Create external network.
        kwargs = {'router:external': True,
                  'apic:distinguished_names':
                  {'ExternalNetwork': 'uni/tn-common/out-l1/instP-n1'}}
        ext_net = self._make_network(
            self.fmt, 'ext_net', True, arg_list=self.extension_attributes,
            **kwargs)['network']

        # Create router as tenant_2.
        kwargs = {'apic:external_provided_contracts': ['p1', 'p2'],
                  'apic:external_consumed_contracts': ['c1', 'c2'],
                  'external_gateway_info': {'network_id': ext_net['id']}}
        router = self._make_router(
            self.fmt, 'tenant_2', 'router1',
            arg_list=self.extension_attributes, **kwargs)['router']
        router_id = router['id']

        # Validate before adding subnet to router.
        self._validate()

        # Add unshared subnet to router.
        self.l3_plugin.add_router_interface(
            n_context.get_admin_context(), router_id,
            {'subnet_id': subnet2_id})
        self._validate()

        # Test AIM Subnet and VRF.
        self._test_routed_subnet(subnet2_id, '10.0.2.1')
        self._test_unscoped_vrf(router_id)

        # Add shared subnet to router.
        self.l3_plugin.add_router_interface(
            n_context.get_admin_context(), router_id,
            {'subnet_id': subnet1_id})
        self._validate()

        # Test AIM Subnets and VRF.
        self._test_routed_subnet(subnet2_id, '10.0.2.1')
        self._test_routed_subnet(subnet1_id, '10.0.1.1')
        self._test_unscoped_vrf(router_id)

    def test_security_group(self):
        # Create security group with a rule.
        sg = self._make_security_group(
            self.fmt, 'sg1', 'security group 1')['security_group']
        rule1 = self._build_security_group_rule(
            sg['id'], 'ingress', 'tcp', '22', '23')
        rules = {'security_group_rules': [rule1['security_group_rule']]}
        sg_rule = self._make_security_group_rule(
            self.fmt, rules)['security_group_rules'][0]
        self._validate()

        # Test the AIM SecurityGroup.
        tenant_name = self.driver.aim_mech_driver.name_mapper.project(
            None, sg['project_id'])
        sg_name = sg['id']
        aim_sg = aim_resource.SecurityGroup(
            name=sg_name, tenant_name=tenant_name)
        self._test_aim_resource(aim_sg)

        # Test the AIM SecurityGroupSubject.
        aim_subject = aim_resource.SecurityGroupSubject(
            name='default', security_group_name=sg_name,
            tenant_name=tenant_name)
        self._test_aim_resource(aim_subject)

        # Test the AIM SecurityGroupRule.
        aim_rule = aim_resource.SecurityGroupRule(
            name=sg_rule['id'],
            security_group_subject_name='default',
            security_group_name=sg_name,
            tenant_name=tenant_name)
        self._test_aim_resource(aim_rule)


class TestGbpMapping(AimValidationTestCase):

    def setUp(self):
        super(TestGbpMapping, self).setUp()

    def test_l3_policy(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create L3P.
        self.create_l3_policy()

        # Test that validation fails.
        self._validate_unrepairable()

    def test_l2_policy(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create L2P.
        l2p = self.create_l2_policy()['l2_policy']

        # Dissassociate and delete the implicitly-created L3P.
        self.db_session.query(gpdb.L2Policy).filter_by(id=l2p['id']).update(
            {'l3_policy_id': None})
        self.delete_l3_policy(l2p['l3_policy_id'])

        # Test that validation fails.
        self._validate_unrepairable()

    def test_policy_target_group(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create PTG.
        self.create_policy_target_group()

        # Dissassociating and deleting the implicitly-created L3P and
        # L2P would require removing the router interface that has
        # been created, which is not worth the effort for this
        # temporary test implementation. Manual inspection of the
        # validation output shows that validation is failing due to
        # the PTG, as well as the other resources.

        # Test that validation fails.
        self._validate_unrepairable()

    def test_policy_target(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create PTG.
        ptg = self.create_policy_target_group()['policy_target_group']

        # Create PT.
        self.create_policy_target(policy_target_group_id=ptg['id'])

        # Dissassociating and deleting the PTG, L3P and L2P is not
        # worth the effort for this temporary test
        # implementation. Manual inspection of the validation output
        # shows that validation is failing due to the PT, as well as
        # the other resources.

        # Test that validation fails.
        self._validate_unrepairable()

    def test_application_policy_group(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create APG.
        self.create_application_policy_group()

        # Test that validation fails.
        self._validate_unrepairable()

    def test_policy_classifier(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create PC.
        self.create_policy_classifier()

        # Test that validation fails.
        self._validate_unrepairable()

    def test_policy_rule_set(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create PRS.
        self.create_policy_rule_set()

        # Test that validation fails.
        self._validate_unrepairable()

    def test_external_segment(self):
        # REVISIT: Test validation of actual mapping once
        # implemented. No AIM resources are created directly, but
        # external_routes maps to the cisco_apic.EXTERNAL_CIDRS
        # network extension.

        # Create external network and subnet.
        kwargs = {'router:external': True,
                  'apic:distinguished_names':
                  {'ExternalNetwork': 'uni/tn-common/out-l1/instP-n1'}}
        net_resp = self._make_network(
            self.fmt, 'ext_net', True, arg_list=self.extension_attributes,
            **kwargs)
        subnet = self._make_subnet(
            self.fmt, net_resp, '10.0.0.1', '10.0.0.0/24')['subnet']

        # Create ES.
        self.create_external_segment(
            subnet_id=subnet['id'],
            external_routes=[{'destination': '129.0.0.0/24', 'nexthop': None}])

        # Test that validation fails.
        self._validate_unrepairable()

    def test_external_policy(self):
        # REVISIT: Test validation of actual mapping once implemented.

        # Create EP.
        self.create_external_policy()

        # Test that validation fails.
        self._validate_unrepairable()


class TestSfcMapping(test_aim_sfc_driver.TestAIMServiceFunctionChainingBase,
                     AimValidationTestMixin):

    def setUp(self):
        super(TestSfcMapping, self).setUp()
        self.av_mgr = av.ValidationManager()
        self.aim_ctx = aim_context.AimContext(self.db_session)

    def test_flow_classifier(self):
        # REVISIT: Test validation of actual mapping once
        # implemented. This resource is currently not mapped to AIM
        # until used in a port chain, but there are plans to map it
        # more proactively.

        # Create FC.
        self._create_simple_flowc()

        # Test that validation fails.
        self._validate_unrepairable()

    def test_port_port_pair_group(self):
        # REVISIT: Test validation of actual mapping once
        # implemented. This resource is currently not mapped to AIM
        # until used in a port chain, but there are plans to map it
        # more proactively.

        # Create PPG.
        self._create_simple_ppg(pairs=1)

        # Test that validation fails.
        self._validate_unrepairable()

    def test_port_chain(self):
        # REVISIT: Test validation of actual mapping once
        # implemented.

        # Create PC (along with PPG and FC).
        self._create_simple_port_chain(ppgs=1)

        # Deleting the PPG and FC, if possible, would ensure that the
        # PC itself is causing validation to fail, but is not worth
        # the effort for this temporary test implementation. Manual
        # inspection of the validation output shows that validation is
        # failing due to the PC, as well as the other resources.

        # Test that validation fails.
        self._validate_unrepairable()