# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from aim.api import infra as aim_infra
from aim.api import service_graph as aim_sg
from networking_sfc.extensions import flowclassifier as flowc_ext
from networking_sfc.extensions import sfc as sfc_ext
from networking_sfc.services.flowclassifier.common import (
    config as flc_cfg)  # noqa
from networking_sfc.services.sfc.common import (
    config as sfc_cfg)  # noqa
from neutron import manager

from gbpservice.neutron.services.grouppolicy import config
from gbpservice.neutron.tests.unit.services.grouppolicy import (
    test_aim_mapping_driver as test_aim_base)


class TestAIMServiceFunctionChainingBase(test_aim_base.AIMBaseTestCase):

    def setUp(self, *args, **kwargs):
        config.cfg.CONF.set_override('drivers', ['aim'], group='sfc')
        config.cfg.CONF.set_override('drivers', ['aim'],
                                     group='flowclassifier')
        config.cfg.CONF.set_override(
            'network_vlan_ranges', ['physnet1:100:200'], group='ml2_type_vlan')
        ml2_options = {'mechanism_drivers': ['apic_aim', 'openvswitch'],
                       'extension_drivers': ['apic_aim', 'port_security',
                                             'dns'],
                       'type_drivers': ['opflex', 'local', 'vlan'],
                       'tenant_network_types': ['opflex']}
        # TODO(ivar): should be tested for opflex networks as well!
        super(TestAIMServiceFunctionChainingBase, self).setUp(
            *args, ml2_options=ml2_options, **kwargs)
        self._sfc_driver = None
        self._flowc_driver = None
        self._sfc_plugin = None
        self._flowc_plugin = None

        self.hlink1 = aim_infra.HostLink(host_name='h1', interface_name='eth0',
                           path='topology/pod-1/paths-101/pathep-[eth1/1]')
        self.hlink2 = aim_infra.HostLink(host_name='h2', interface_name='eth0',
                           path='topology/pod-1/paths-102/pathep-[eth1/1]')
        self.aim_mgr.create(self._aim_context, self.hlink1)
        self.aim_mgr.create(self._aim_context, self.hlink2)

    @property
    def sfc_plugin(self):
        if not self._sfc_plugin:
            plugins = manager.NeutronManager.get_service_plugins()
            self._sfc_plugin = plugins.get(sfc_ext.SFC_EXT)
        return self._sfc_plugin

    @property
    def flowc_plugin(self):
        if not self._flowc_plugin:
            plugins = manager.NeutronManager.get_service_plugins()
            self._flowc_plugin = plugins.get(flowc_ext.FLOW_CLASSIFIER_EXT)
        return self._flowc_plugin

    @property
    def sfc_driver(self):
        # aim_mapping policy driver reference
        if not self._sfc_driver:
            self._sfc_driver = (
                self.sfc_plugin.driver_manager.drivers['aim'].obj)
        return self._sfc_driver

    @property
    def flowc_driver(self):
        # aim_mapping policy driver reference
        if not self._flowc_driver:
            self._flowc_driver = (
                self.flowc_plugin.driver_manager.drivers['aim'].obj)
        return self._flowc_driver


class TestPortPair(TestAIMServiceFunctionChainingBase):

    def test_port_pair_validation(self):
        net1 = self._make_network(self.fmt, 'net1', True)
        self._make_subnet(self.fmt, net1, '192.168.0.1', '192.168.0.0/24')
        p1 = self._make_port(self.fmt, net1['network']['id'])['port']

        net2 = self._make_network(self.fmt, 'net2', True)
        self._make_subnet(self.fmt, net1, '192.168.1.1', '192.168.1.0/24')
        p2 = self._make_port(self.fmt, net2['network']['id'])['port']
        self._bind_port_to_host(p1['id'], 'h1')
        self._bind_port_to_host(p2['id'], 'h2')
        self.create_port_pair(ingress=p1['id'], egress=p2['id'],
                              expected_res_status=201)
        # Same network ports
        p3 = self._make_port(self.fmt, net2['network']['id'])['port']
        p4 = self._make_port(self.fmt, net2['network']['id'])['port']
        self._bind_port_to_host(p3['id'], 'h1')
        self._bind_port_to_host(p4['id'], 'h2')
        self.create_port_pair(ingress=p3['id'], egress=p4['id'],
                              expected_res_status=500)
        # Also unbound ports can be used
        p5 = self._make_port(self.fmt, net1['network']['id'])['port']
        self.create_port_pair(ingress=p3['id'], egress=p5['id'],
                              expected_res_status=400)


class TestPortPairGroup(TestAIMServiceFunctionChainingBase):

    def _create_simple_ppg(self, pairs=2):
        nets = []
        # Pairs go in 2 networks
        for i in range(2):
            net = self._make_network(self.fmt, 'net1', True)
            self._make_subnet(self.fmt, net, '192.168.%s.1' % i,
                              '192.168.%s.0/24' % i)
            nets.append(net)

        port_pairs = []
        for i in range(pairs):
            p1 = self._make_port(self.fmt, nets[0]['network']['id'])['port']
            self._bind_port_to_host(p1['id'], 'h%s' % ((i % 2) + 1))
            p2 = self._make_port(self.fmt, nets[1]['network']['id'])['port']
            self._bind_port_to_host(p2['id'], 'h%s' % ((i % 2) + 1))
            pp = self.create_port_pair(ingress=p1['id'], egress=p2['id'],
                                        expected_res_status=201)['port_pair']
            port_pairs.append(pp)
        # This goes through
        return self.create_port_pair_group(
            port_pairs=[pp['id'] for pp in port_pairs],
            expected_res_status=201)['port_pair_group']

    def test_ppg_validation(self):
        # Correct creation
        net1 = self._make_network(self.fmt, 'net1', True)
        self._make_subnet(self.fmt, net1, '192.168.0.1', '192.168.0.0/24')
        net2 = self._make_network(self.fmt, 'net2', True)
        self._make_subnet(self.fmt, net2, '192.168.1.1', '192.168.1.0/24')

        # Service 1
        p11 = self._make_port(self.fmt, net1['network']['id'])['port']
        self._bind_port_to_host(p11['id'], 'h1')
        p12 = self._make_port(self.fmt, net2['network']['id'])['port']
        self._bind_port_to_host(p12['id'], 'h1')
        pp1 = self.create_port_pair(ingress=p11['id'], egress=p12['id'],
                                    expected_res_status=201)['port_pair']
        # Service 2
        p21 = self._make_port(self.fmt, net1['network']['id'])['port']
        self._bind_port_to_host(p21['id'], 'h2')
        p22 = self._make_port(self.fmt, net2['network']['id'])['port']
        self._bind_port_to_host(p22['id'], 'h2')
        pp2 = self.create_port_pair(ingress=p21['id'], egress=p22['id'],
                                    expected_res_status=201)['port_pair']
        # This goes through
        ppg1 = self.create_port_pair_group(
            port_pairs=[pp1['id'], pp2['id']],
            expected_res_status=201)['port_pair_group']
        # Use invalid pairs
        net3 = self._make_network(self.fmt, 'net1', True)
        self._make_subnet(self.fmt, net3, '192.168.0.1', '192.168.0.0/24')
        p31 = self._make_port(self.fmt, net3['network']['id'])['port']
        self._bind_port_to_host(p31['id'], 'h1')
        pp3 = self.create_port_pair(ingress=p21['id'], egress=p31['id'],
                                    expected_res_status=201)['port_pair']
        self.delete_port_pair_group(ppg1['id'])
        self.create_port_pair_group(port_pairs=[pp1['id'], pp3['id']],
                                    expected_res_status=500)
        # Works with only one PP
        ppg2 = self.create_port_pair_group(
            port_pairs=[pp3['id']],
            expected_res_status=201)['port_pair_group']
        # But update fails
        self.update_port_pair_group(
            ppg2['id'], port_pairs=[pp3['id'], pp1['id']],
            expected_res_status=500)

    def test_ppg_mapping(self):
        ppg = self._create_simple_ppg()
        tn = ppg['tenant_id']
        apic_tn = 'prj_' + tn
        # Verify expected AIM model
        ctx = self._aim_context
        # DeviceCluster. Only one created
        dcs = self.aim_mgr.find(ctx, aim_sg.DeviceCluster)
        self.assertEqual(1, len(dcs))
        dc = dcs[0]
        # Verify that's the expected one
        self.assertEqual(dc.tenant_name, apic_tn)
        self.assertEqual(dc.name, 'ppg_' + ppg['id'])
        # With 2 pairs, there are 2 concreate devices
        dcs = self.aim_mgr.find(ctx, aim_sg.ConcreteDevice)
        self.assertEqual(2, len(dcs))
        self.assertIsNotNone(self.aim_mgr.get(
            ctx, aim_sg.ConcreteDevice(tenant_name=apic_tn,
                                       device_cluster_name=dc.name,
                                       name='pp_' + ppg['port_pairs'][0])))
        self.assertIsNotNone(self.aim_mgr.get(
            ctx, aim_sg.ConcreteDevice(tenant_name=apic_tn,
                                       device_cluster_name='ppg_' + ppg['id'],
                                       name='pp_' + ppg['port_pairs'][1])))
        # Each of these CD have 2 CDIs, inspect for the first port pair
        pp1_dcis = self.aim_mgr.find(
            ctx, aim_sg.ConcreteDeviceInterface,
                tenant_name=apic_tn, device_cluster_name=dc.name,
                device_name='pp_' + ppg['port_pairs'][0])
        self.assertEqual(2, len(pp1_dcis))
        self.assertEqual('topology/pod-1/paths-101/pathep-[eth1/1]',
                         pp1_dcis[0].path)
        self.assertEqual('topology/pod-1/paths-101/pathep-[eth1/1]',
                         pp1_dcis[1].path)
        # Second port pair
        pp2_dcis = self.aim_mgr.find(
            ctx, aim_sg.ConcreteDeviceInterface,
                tenant_name=apic_tn, device_cluster_name=dc.name,
                device_name='pp_' + ppg['port_pairs'][1])
        self.assertEqual(2, len(pp2_dcis))
        self.assertEqual('topology/pod-1/paths-102/pathep-[eth1/1]',
                         pp2_dcis[0].path)
        self.assertEqual('topology/pod-1/paths-102/pathep-[eth1/1]',
                         pp2_dcis[1].path)
        # No extra CDI created
        self.assertEqual(
            4, len(self.aim_mgr.find(ctx, aim_sg.ConcreteDeviceInterface)))
        # 1 PPG means 1 service, which has 2 DeviceClusterInterfaces
        # comprehensive of all the above ConcreteDeviceInterfaces
        idci = self.aim_mgr.get(ctx, aim_sg.DeviceClusterInterface(
            tenant_name=dc.tenant_name, device_cluster_name=dc.name,
            name='ingress'))
        edci = self.aim_mgr.get(ctx, aim_sg.DeviceClusterInterface(
            tenant_name=dc.tenant_name, device_cluster_name=dc.name,
            name='egress'))
        self.assertIsNotNone(idci)
        self.assertIsNotNone(edci)
        self.assertEqual(
            2, len(self.aim_mgr.find(ctx, aim_sg.DeviceClusterInterface)))
        # Retrieve the port pairs
        pp1 = self.show_port_pair(ppg['port_pairs'][0])['port_pair']
        pp2 = self.show_port_pair(ppg['port_pairs'][1])['port_pair']
        # Ingress CDIs
        ingr1 = self.aim_mgr.get(
            ctx, aim_sg.ConcreteDeviceInterface(
                tenant_name=apic_tn, device_cluster_name=dc.name,
                device_name='pp_' + pp1['id'], name='prt_' + pp1['ingress']))
        ingr2 = self.aim_mgr.get(
            ctx, aim_sg.ConcreteDeviceInterface(
                tenant_name=apic_tn, device_cluster_name=dc.name,
                device_name='pp_' + pp2['id'], name='prt_' + pp2['ingress']))
        self.assertEqual({ingr1.dn, ingr2.dn}, set(idci.concrete_interfaces))

        # Egress CDIs
        egr1 = self.aim_mgr.get(
            ctx, aim_sg.ConcreteDeviceInterface(
                tenant_name=apic_tn, device_cluster_name=dc.name,
                device_name='pp_' + pp1['id'], name='prt_' + pp1['egress']))
        egr2 = self.aim_mgr.get(
            ctx, aim_sg.ConcreteDeviceInterface(
                tenant_name=apic_tn, device_cluster_name=dc.name,
                device_name='pp_' + pp2['id'], name='prt_' + pp2['egress']))
        self.assertEqual({egr1.dn, egr2.dn}, set(edci.concrete_interfaces))
        # Redirect Policy Ingress
        irp = self.aim_mgr.get(ctx, aim_sg.ServiceRedirectPolicy(
            tenant_name=dc.tenant_name, name='ingr_ppg_' + ppg['id']))
        erp = self.aim_mgr.get(ctx, aim_sg.ServiceRedirectPolicy(
            tenant_name=dc.tenant_name, name='egr_ppg_' + ppg['id']))
        self.assertEqual(
            2, len(self.aim_mgr.find(ctx, aim_sg.ServiceRedirectPolicy)))
        self.assertIsNotNone(irp)
        self.assertIsNotNone(erp)

        # Ingress Ports
        iprt1 = self._show_port(pp1['ingress'])
        iprt2 = self._show_port(pp2['ingress'])
        self.assertEqual(
            sorted([{'ip': iprt1['fixed_ips'][0]['ip_address'],
                     'mac': iprt1['mac_address']},
                    {'ip': iprt2['fixed_ips'][0]['ip_address'],
                     'mac': iprt2['mac_address']}]),
            irp.destinations)
        # Egress Ports
        eprt1 = self._show_port(pp1['egress'])
        eprt2 = self._show_port(pp2['egress'])
        self.assertEqual(
            sorted([{'ip': eprt1['fixed_ips'][0]['ip_address'],
                     'mac': eprt1['mac_address']},
                    {'ip': eprt2['fixed_ips'][0]['ip_address'],
                     'mac': eprt2['mac_address']}]),
            erp.destinations)
        # Nothing left after deletion
        self.delete_port_pair_group(ppg['id'])
        self.assertEqual(
            0, len(self.aim_mgr.find(ctx, aim_sg.ServiceRedirectPolicy)))
        self.assertEqual(
            0, len(self.aim_mgr.find(ctx, aim_sg.DeviceClusterInterface)))
        self.assertEqual(
            0, len(self.aim_mgr.find(ctx, aim_sg.ConcreteDeviceInterface)))
        self.assertEqual(
            0, len(self.aim_mgr.find(ctx, aim_sg.ConcreteDevice)))
        self.assertEqual(
            0, len(self.aim_mgr.find(ctx, aim_sg.DeviceCluster)))
