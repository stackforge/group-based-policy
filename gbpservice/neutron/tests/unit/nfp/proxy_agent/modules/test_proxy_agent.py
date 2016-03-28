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

from gbpservice.nfp.proxy_agent.modules import proxy_agent
import mock
from neutron import context as ctx
import unittest

rpc_manager = proxy_agent.RpcHandler


class TestContext(object):

    def get_context(self):
        try:
            return ctx.Context('some_user', 'some_tenant')
        except Exception:
            return ctx.Context('some_user', 'some_tenant')

"Common class for proxy agent test cases"


class ConfigAgentProxyTestCase(unittest.TestCase):

    def setUp(self):
        self.manager = rpc_manager('conf', 'sc')
        self.context = TestContext().get_context()
        self.imprt_rc = 'gbpservice.nfp.proxy_agent.lib.RestClientOverUnix'

    def _post(self, path, body, delete=False):
        return (200, '')

    def test_create_network_function_config(self):
        _data = "data"
        with mock.patch(self.imprt_rc + '.post') as mock_post:
            mock_post.side_effect = self._post
            self.manager.create_network_function_config(self.context, _data)

    def test_delete_network_function_config(self):
        _data = "data"
        with mock.patch(self.imprt_rc + '.post') as mock_post:
            mock_post.side_effect = self._post
            self.manager.delete_network_function_config(self.context, _data)

    def test_create_network_function_device_config(self):
        _data = "data"
        with mock.patch(self.imprt_rc + '.post') as mock_post:
            mock_post.side_effect = self._post
            self.manager.create_network_function_device_config(
                self.context, _data)

    def test_delete_network_function_device_config(self):
        _data = "data"
        with mock.patch(self.imprt_rc + '.post') as mock_post:
            mock_post.side_effect = self._post
            self.manager.delete_network_function_device_config(
                self.context, _data)

if __name__ == "__main__":
    unittest.main()
