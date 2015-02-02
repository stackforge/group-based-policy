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

import ast
import time

from neutron.common import log
from neutron.openstack.common import jsonutils
from neutron.openstack.common import log as logging
from neutron.plugins.common import constants as pconst


from gbpservice.neutron.services.servicechain.common import exceptions as exc
from gbpservice.neutron.services.servicechain.drivers import simplechain_driver


LOG = logging.getLogger(__name__)
sc_supported_type = [pconst.LOADBALANCER, 'FIREWALL_TRANSPARENT', 'IDS']
TRANSPARENT_PT = "transparent"
SERVICE_PT = "service"
PROVIDER_PT_NAME = "provider_%s_%s"
CONSUMER_PT_NAME = "consumer_%s_%s"


class ChainWithTwoArmAppliance(simplechain_driver.SimpleChainDriver):


    @log.log
    def create_servicechain_node_precommit(self, context):
        if context.current['service_type'] not in sc_supported_type:
            raise exc.InvalidServiceTypeForReferenceDriver()

    def _fetch_template_and_params(self, context, sc_instance,
                                   sc_spec, sc_node, order):
        stack_template = sc_node.get('config')
        # TODO(Sumit):Raise an exception ??
        if not stack_template:
            LOG.error(_("Service Config is not defined for the service"
                        " chain Node"))
            return
        stack_template = jsonutils.loads(stack_template)
        config_param_values = sc_instance.get('config_param_values', {})
        stack_params = {}
        # config_param_values has the parameters for all Nodes. Only apply
        # the ones relevant for this Node
        if config_param_values:
            config_param_values = jsonutils.loads(config_param_values)
        config_param_names = sc_spec.get('config_param_names', [])
        if config_param_names:
            config_param_names = ast.literal_eval(config_param_names)

        pt_type = TRANSPARENT_PT
        if sc_node['service_type'] == pconst.LOADBALANCER:
            pt_type = SERVICE_PT
            member_ips = []
            provider_ptg_id = sc_instance.get("provider_ptg_id")
            # If we have the key "PoolMemberIP*" in template input parameters,
            # fetch the list of IPs of all PTs in the PTG
            for key in config_param_names or []:
                if "PoolMemberIP" in key:
                    member_ips = self._get_member_ips(context, provider_ptg_id)
                    break

            member_count = 0
            for key in config_param_names or []:
                if "PoolMemberIP" in key:
                    value = (member_ips[member_count]
                             if len(member_ips) > member_count else '0')
                    member_count = member_count + 1
                    config_param_values[key] = value
                elif key == "Subnet":
                    value = self._get_ptg_subnet(context, provider_ptg_id)
                    config_param_values[key] = value
        else:
            provider_ptg_id = sc_instance.get("provider_ptg_id")
            consumer_ptg_id = sc_instance.get("consumer_ptg_id")
            for key in config_param_names or []:
                if "provider_ptg" in key:
                    config_param_values[key] = provider_ptg_id
                elif key == "consumer_ptg":
                    config_param_values[key] = consumer_ptg_id

        for key in config_param_names or []:
            if key == "provider_pt_name":
                config_param_values[key] = PROVIDER_PT_NAME % (order, pt_type)
            elif key == "consumer_pt_name":
                config_param_values[key] = CONSUMER_PT_NAME % (order, pt_type)

        node_params = (stack_template.get('Parameters')
                       or stack_template.get('parameters'))
        if node_params:
            for parameter in config_param_values.keys():
                if parameter in node_params.keys():
                    stack_params[parameter] = config_param_values[parameter]
        return (stack_template, stack_params)
