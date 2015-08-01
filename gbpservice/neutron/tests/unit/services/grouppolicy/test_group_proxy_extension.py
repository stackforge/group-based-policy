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

from gbpservice.neutron.tests.unit.services.grouppolicy import (
    test_extension_driver_api as test_ext_base)


class ExtensionDriverTestCase(test_ext_base.ExtensionDriverTestBase):

    _extension_drivers = ['proxy_group']
    _extension_path = None

    def test_proxy_group_extension(self):
        ptg = self.create_policy_target_group()['policy_target_group']
        self.assertIsNone(ptg['proxy_group_id'])
        self.assertIsNone(ptg['proxied_group_id'])
        self.assertIsNone(ptg['proxy_type'])

        ptg_proxy = self.create_policy_target_group(
            proxied_group_id=ptg['id'])['policy_target_group']
        self.assertIsNone(ptg_proxy['proxy_group_id'])
        self.assertEqual(ptg['id'], ptg_proxy['proxied_group_id'])
        self.assertEqual('l3', ptg_proxy['proxy_type'])

        # Verify relationship added
        ptg = self.show_policy_target_group(ptg['id'])['policy_target_group']
        self.assertEqual(ptg_proxy['id'], ptg['proxy_group_id'])
        self.assertIsNone(ptg['proxied_group_id'])

        pt = self.create_policy_target(
            policy_target_group_id=ptg_proxy['id'])['policy_target']
        self.assertFalse(pt['proxy_gateway'])
        self.assertFalse(pt['group_default_gateway'])
        pt = self.create_policy_target(
            policy_target_group_id=ptg_proxy['id'],
            proxy_gateway=True, group_default_gateway=True)['policy_target']
        self.assertTrue(pt['proxy_gateway'])
        self.assertTrue(pt['group_default_gateway'])
        pt = self.show_policy_target(pt['id'])['policy_target']
        self.assertTrue(pt['proxy_gateway'])
        self.assertTrue(pt['group_default_gateway'])

    def test_proxy_group_multiple_proxies(self):
        # same PTG proxied multiple times will fail
        ptg = self.create_policy_target_group()['policy_target_group']
        self.create_policy_target_group(proxied_group_id=ptg['id'])
        # Second proxy will fail
        res = self.create_policy_target_group(proxied_group_id=ptg['id'],
                                              expected_res_status=400)
        self.assertEqual('InvalidProxiedGroup', res['NeutronError']['type'])

    def test_proxy_group_chain_proxy(self):
        # Verify no error is raised when chaining multiple proxy PTGs
        ptg0 = self.create_policy_target_group()['policy_target_group']
        ptg1 = self.create_policy_target_group(
            proxied_group_id=ptg0['id'],
            expected_res_status=201)['policy_target_group']
        self.create_policy_target_group(proxied_group_id=ptg1['id'],
                                        expected_res_status=201)

    def test_proxy_group_no_update(self):
        ptg0 = self.create_policy_target_group()['policy_target_group']
        ptg1 = self.create_policy_target_group()['policy_target_group']
        ptg_proxy = self.create_policy_target_group(
            proxied_group_id=ptg0['id'])['policy_target_group']
        self.update_policy_target_group(
            ptg_proxy['id'], proxied_group_id=ptg1['id'],
            expected_res_status=400)

    def test_different_proxy_type(self):
        ptg = self.create_policy_target_group()['policy_target_group']
        ptg_proxy = self.create_policy_target_group(
            proxied_group_id=ptg['id'], proxy_type='l2')['policy_target_group']
        self.assertEqual('l2', ptg_proxy['proxy_type'])

        ptg_proxy = self.show_policy_target_group(
            ptg_proxy['id'])['policy_target_group']
        self.assertEqual('l2', ptg_proxy['proxy_type'])

    def test_proxy_type_fails(self):
        ptg = self.create_policy_target_group()['policy_target_group']
        res = self.create_policy_target_group(proxy_type='l2',
                                              expected_res_status=400)
        self.assertEqual('ProxyTypeSetWithoutProxiedPTG',
                         res['NeutronError']['type'])

        self.create_policy_target_group(proxied_group_id=ptg['id'],
                                        proxy_type='notvalid',
                                        expected_res_status=400)

    def test_proxy_gateway_no_proxy(self):
        ptg = self.create_policy_target_group()['policy_target_group']
        res = self.create_policy_target(
            policy_target_group_id=ptg['id'], proxy_gateway=True,
            expected_res_status=400)
        self.assertEqual('InvalidProxyGatewayGroup',
                         res['NeutronError']['type'])