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

import mock
from neutron import context as nctx
from neutron.db import api as db_api
from neutron.db import model_base
from neutron import manager
from neutron.plugins.common import constants as pconst
from neutron.tests.unit.plugins.ml2 import test_plugin as n_test_plugin
import webob.exc

from gbpservice.neutron.services.grouppolicy import config
from gbpservice.neutron.services.servicechain.plugins.msc import (
    config as sc_cfg)
from gbpservice.neutron.tests.unit.services.grouppolicy import (
    test_grouppolicy_plugin as test_plugin)


CORE_PLUGIN = ('gbpservice.neutron.tests.unit.services.grouppolicy.'
               'test_resource_mapping.NoL3NatSGTestPlugin')


class CommonNeutronBaseTestCase(test_plugin.GroupPolicyPluginTestBase):

    def setUp(self, policy_drivers=None,
              core_plugin=n_test_plugin.PLUGIN_NAME, ml2_options=None,
              sc_plugin=None):
        policy_drivers = policy_drivers or ['neutron_resources']
        config.cfg.CONF.set_override('policy_drivers',
                                     policy_drivers,
                                     group='group_policy')
        sc_cfg.cfg.CONF.set_override('servicechain_drivers',
                                     ['dummy'], group='servicechain')
        config.cfg.CONF.set_override('allow_overlapping_ips', True)
        super(CommonNeutronBaseTestCase, self).setUp(core_plugin=core_plugin,
                                                     ml2_options=ml2_options,
                                                     sc_plugin=sc_plugin)
        engine = db_api.get_engine()
        model_base.BASEV2.metadata.create_all(engine)
        res = mock.patch('neutron.db.l3_db.L3_NAT_dbonly_mixin.'
                         '_check_router_needs_rescheduling').start()
        res.return_value = None
        self._plugin = manager.NeutronManager.get_plugin()
        self._plugin.remove_networks_from_down_agents = mock.Mock()
        self._plugin.is_agent_down = mock.Mock(return_value=False)
        self._context = nctx.get_admin_context()
        plugins = manager.NeutronManager.get_service_plugins()
        self._gbp_plugin = plugins.get(pconst.GROUP_POLICY)
        self._l3_plugin = plugins.get(pconst.L3_ROUTER_NAT)
        config.cfg.CONF.set_override('debug', True)
        config.cfg.CONF.set_override('verbose', True)

    def get_plugin_context(self):
        return self._plugin, self._context


class TestL2Policy(CommonNeutronBaseTestCase):

    def test_l2_policy_lifecycle(self):
        l2p = self.create_l2_policy(name="l2p1")
        l2p_id = l2p['l2_policy']['id']
        network_id = l2p['l2_policy']['network_id']
        self.assertIsNotNone(network_id)
        req = self.new_show_request('networks', network_id, fmt=self.fmt)
        res = self.deserialize(self.fmt, req.get_response(self.api))
        self.assertIsNotNone(res['network']['id'])
        self.show_l2_policy(l2p_id, expected_res_status=200)
        self.update_l2_policy(l2p_id, expected_res_status=200,
                              name="new name")
        self.delete_l2_policy(l2p_id, expected_res_status=204)
        self.show_l2_policy(l2p_id, expected_res_status=404)
        req = self.new_show_request('networks', network_id, fmt=self.fmt)
        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNotFound.code, res.status_int)
