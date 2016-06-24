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

DRIVERS_DIR = 'gbpservice.contrib.nfp.configurator.drivers.loadbalancer.v1'
SERVICE_TYPE = 'loadbalancer'
NEUTRON = 'neutron'

LBAAS_AGENT_RPC_TOPIC = 'lbaas_agent'
LBAAS_GENERIC_CONFIG_RPC_TOPIC = 'lbaas_generic_config'
LBAAS_PLUGIN_RPC_TOPIC = 'n-lbaas-plugin'
AGENT_TYPE_LOADBALANCER = 'OC Loadbalancer agent'

# Service operation status constants
ACTIVE = "ACTIVE"
DOWN = "DOWN"
CREATED = "CREATED"
PENDING_CREATE = "PENDING_CREATE"
PENDING_UPDATE = "PENDING_UPDATE"
PENDING_DELETE = "PENDING_DELETE"
INACTIVE = "INACTIVE"
ERROR = "ERROR"
STATUS_SUCCESS = "SUCCESS"

ACTIVE_PENDING_STATUSES = (
    ACTIVE,
    PENDING_CREATE,
    PENDING_UPDATE
)

""" HTTP request/response """
HAPROXY_AGENT_LISTEN_PORT = 1234
REQUEST_URL = "http://%s:%s/%s"
HTTP_REQ_METHOD_POST = 'POST'
HTTP_REQ_METHOD_GET = 'GET'
HTTP_REQ_METHOD_PUT = 'PUT'
HTTP_REQ_METHOD_DELETE = 'DELETE'
CONTENT_TYPE_HEADER = 'Content-type'
JSON_CONTENT_TYPE = 'application/json'

LB_METHOD_ROUND_ROBIN = 'ROUND_ROBIN'
LB_METHOD_LEAST_CONNECTIONS = 'LEAST_CONNECTIONS'
LB_METHOD_SOURCE_IP = 'SOURCE_IP'

PROTOCOL_TCP = 'TCP'
PROTOCOL_HTTP = 'HTTP'
PROTOCOL_HTTPS = 'HTTPS'

HEALTH_MONITOR_PING = 'PING'
HEALTH_MONITOR_TCP = 'TCP'
HEALTH_MONITOR_HTTP = 'HTTP'
HEALTH_MONITOR_HTTPS = 'HTTPS'

LBAAS = 'lbaas'

PROTOCOL_MAP = {
    PROTOCOL_TCP: 'tcp',
    PROTOCOL_HTTP: 'http',
    PROTOCOL_HTTPS: 'https',
}
BALANCE_MAP = {
    LB_METHOD_ROUND_ROBIN: 'roundrobin',
    LB_METHOD_LEAST_CONNECTIONS: 'leastconn',
    LB_METHOD_SOURCE_IP: 'source'
}
REQUEST_RETRIES = 0
REQUEST_TIMEOUT = 120

# Operations
CREATE = 'create'
UPDATE = 'update'
DELETE = 'delete'

""" Event ids """
EVENT_CREATE_POOL = 'CREATE_POOL'
EVENT_UPDATE_POOL = 'UPDATE_POOL'
EVENT_DELETE_POOL = 'DELETE_POOL'

EVENT_CREATE_VIP = 'CREATE_VIP'
EVENT_UPDATE_VIP = 'UPDATE_VIP'
EVENT_DELETE_VIP = 'DELETE_VIP'

EVENT_CREATE_MEMBER = 'CREATE_MEMBER'
EVENT_UPDATE_MEMBER = 'UPDATE_MEMBER'
EVENT_DELETE_MEMBER = 'DELETE_MEMBER'

EVENT_CREATE_POOL_HEALTH_MONITOR = 'CREATE_POOL_HEALTH_MONITOR'
EVENT_UPDATE_POOL_HEALTH_MONITOR = 'UPDATE_POOL_HEALTH_MONITOR'
EVENT_DELETE_POOL_HEALTH_MONITOR = 'DELETE_POOL_HEALTH_MONITOR'

EVENT_AGENT_UPDATED = 'AGENT_UPDATED'
EVENT_COLLECT_STATS = 'COLLECT_STATS'
