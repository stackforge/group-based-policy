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

from contextlib import contextmanager
import copy

from aim import aim_store
from aim.api import resource as aim_resource
from aim import context as aim_context
from neutron.db import api as db_api
from neutron_lib.plugins import directory
from oslo_log import log

LOG = log.getLogger(__name__)

VALIDATION_PASSED = "passed"
VALIDATION_REPAIRED = "repaired"
VALIDATION_FAILED = "failed"


class ValidationManager(object):

    def __init__(self):
        # REVISIT: Defer until after validating config?
        self.core_plugin = directory.get_plugin()
        self.md = self.core_plugin.mechanism_manager.mech_drivers[
            'apic_aim'].obj
        self.pd = self.md.gbp_driver

    def validate(self, repair=False):
        print("Validating deployment, repair: %s" % repair)

        self.result = VALIDATION_PASSED
        self.repair = repair

        # REVISIT: Validate configuration.

        # Start transaction.
        #
        # REVISIT: Set session's isolation level to serializable?
        self.session = (db_api.get_writer_session() if repair
                        else db_api.get_reader_session())
        self.session.begin()
        self.aim_mgr = self.md.aim
        self.actual_aim_ctx = aim_context.AimContext(self.session)
        self.expected_aim_ctx = aim_context.AimContext(
            None, ValidationAimStore(self))

        # Validate & repair GBP->Neutron mappings.
        if self.pd:
            self.pd.validate_neutron_mapping(self)

        # Start with no expected AIM resources.
        self._expected_aim_resources = {}

        # Validate Neutron->AIM mapping records and get expected AIM
        # resources.
        self.md.validate_aim_mapping(self)

        # Validate GBP->AIM mapping records and get expected AIM
        # resources.
        if self.pd:
            self.pd.validate_aim_mapping(self)

        # Validate that actual AIM resources match expected AIM
        # resources.
        if self.result is not VALIDATION_FAILED:
            self._validate_aim_resources()

        # REVISIT: Validate aim_lib DB records.

        # Commit or rollback transaction.
        if self.result is VALIDATION_REPAIRED:
            print("Committing repairs")
            self.session.commit()
        else:
            if self.repair and self.result is VALIDATION_FAILED:
                print("Rolling back attempted repairs")
            self.session.rollback()

        print("Validation result: %s" % self.result)
        return self.result

    def register_aim_resource_class(self, klass):
        self._expected_aim_resources.setdefault(klass, {})

    def expect_aim_resource(self, resource, replace=False):
        expected_resources = self._expected_aim_resources[resource.__class__]
        key = tuple(resource.identity)
        if not replace and key in expected_resources:
            # REVISIT: Allow if identical? Raise proper exception.
            raise "resource %s already expected" % resource
        expected_resources[key] = resource

    def expected_aim_resource(self, resource):
        expected_resources = self._expected_aim_resources[resource.__class__]
        key = tuple(resource.identity)
        return expected_resources.get(key)

    def expected_aim_resources(self, klass):
        return self._expected_aim_resources[klass].values()

    def should_repair(self, problem, action='Repairing'):
        if self.repair and self.result is not VALIDATION_FAILED:
            self.result = VALIDATION_REPAIRED
            print("%s %s" % (action, problem))
            return True
        else:
            self.result = VALIDATION_FAILED
            print("Failed due to %s" % problem)

    def repair_failed(self):
        self.result = VALIDATION_FAILED

    def _validate_aim_resources(self):
        for resource_class in self._expected_aim_resources.keys():
            self._validate_aim_resource_class(resource_class)

    def _validate_aim_resource_class(self, resource_class):
        expected_resources = self._expected_aim_resources[resource_class]
        actual_resources = self.aim_mgr.find(
            self.actual_aim_ctx, resource_class)

        for actual_resource in actual_resources:
            self._validate_actual_aim_resource(
                actual_resource, expected_resources)

        for expected_resource in expected_resources.values():
            self._handle_missing_aim_resource(expected_resource)

    def _validate_actual_aim_resource(self, actual_resource,
                                      expected_resources):
        key = tuple(actual_resource.identity)
        expected_resource = expected_resources.get(key)
        if not expected_resource:
            # Some infra resources do not have the monitored
            # attribute, but are treated as if they are monitored.
            if not getattr(actual_resource, 'monitored', True):
                self._handle_unexpected_aim_resource(actual_resource)
        else:
            # Some infra resources do not have the monitored
            # attribute, but are treated as if they are monitored.
            if getattr(expected_resource, 'monitored', True):
                # REVISIT: Make sure actual resource is monitored, but
                # ignore other differences.
                pass
            else:
                if not self._is_resource_correct(
                        expected_resource, actual_resource):
                    self._handle_incorrect_aim_resource(
                        expected_resource, actual_resource)
            del expected_resources[key]

    def _is_resource_correct(self, expected_resource, actual_resource):
        expected_values = expected_resource.__dict__
        actual_values = actual_resource.__dict__
        for attr_name, attr_type in expected_resource.other_attributes.items():
            expected_value = expected_values.get(attr_name)
            actual_value = actual_values.get(attr_name)
            if attr_type['type'] == 'array':
                # REVISIT: Order may be significant for some array
                # attributes, but most do not preserve order.
                if attr_type['items']['type'] == 'object':
                    expected_value = set(frozenset(x.items())
                                         for x in expected_value)
                    actual_value = set(frozenset(x.items())
                                       for x in actual_value)
                else:
                    expected_value = set(expected_value)
                    actual_value = set(actual_value)
            if expected_value != actual_value:
                return False
        return True

    def _handle_unexpected_aim_resource(self, actual_resource):
        if self.should_repair(
                "unexpected %(type)s: %(actual)r" %
                {'type': actual_resource._aci_mo_name,
                 'actual': actual_resource},
                "Deleting"):
            self.aim_mgr.delete(self.actual_aim_ctx, actual_resource)

    def _handle_incorrect_aim_resource(self, expected_resource,
                                       actual_resource):
        if self.should_repair(
                "incorrect %(type)s: %(actual)r which should be: "
                "%(expected)r" %
                {'type': expected_resource._aci_mo_name,
                 'actual': actual_resource,
                 'expected': expected_resource}):
            self.aim_mgr.create(
                self.actual_aim_ctx, expected_resource, overwrite=True)

    def _handle_missing_aim_resource(self, expected_resource):
        if self.should_repair(
                "missing %(type)s: %(expected)r" %
                {'type': expected_resource._aci_mo_name,
                 'expected': expected_resource}):
            self.aim_mgr.create(self.actual_aim_ctx, expected_resource)


class ValidationAimStore(aim_store.AimStore):

    def __init__(self, validation_mgr):
        self._mgr = validation_mgr
        self.db_session = ValidationSession(validation_mgr)

    def add(self, db_obj):
        self._mgr.expect_aim_resource(db_obj, True)

    def delete(self, db_obj):
        assert(False)

    def query(self, db_obj_type, resource_klass, in_=None, notin_=None,
              order_by=None, lock_update=False, **filters):
        assert(in_ is None)
        assert(notin_ is None)
        assert(order_by is None)
        if filters:
            if (set(filters.keys()) ==
                set(resource_klass.identity_attributes.keys())):
                identity = resource_klass(**filters)
                resource = self._mgr.expected_aim_resource(identity)
                return [resource] if resource else []
            else:
                return [r for r in
                        self._mgr.expected_aim_resources(resource_klass)
                        if all([getattr(r, k) == v for k, v in
                                filters.items()])]
        else:
            return self._mgr.expected_aim_resources(resource_klass)

    def count(self, db_obj_type, resource_klass, in_=None, notin_=None,
              **filters):
        assert(False)

    def delete_all(self, db_obj_type, resource_klass, in_=None, notin_=None,
                   **filters):
        assert(False)

    def from_attr(self, db_obj, resource_klass, attribute_dict):
        for k, v in attribute_dict.items():
            setattr(db_obj, k, v)

    def to_attr(self, resource_klass, db_obj):
        assert(False)

    def make_resource(self, cls, db_obj, include_aim_id=False):
        return copy.deepcopy(db_obj)

    def make_db_obj(self, resource):
        result = copy.deepcopy(resource)
        if isinstance(result, aim_resource.EndpointGroup):
            # Since aim.db.models.EndpointGroup.to_attr() maintains
            # openstack_vmm_domain_names for backward compatibility,
            # we do so here.
            result.openstack_vmm_domain_names = [d['name'] for d in
                                                 result.vmm_domains
                                                 if d['type'] == 'OpenStack']
        return result


@contextmanager
def _begin():
    yield


class ValidationSession(object):

    def __init__(self, validation_mgr):
        self._mgr = validation_mgr

    def begin(self, subtransactions=False, nested=False):
        return _begin()

    def add(self, instance):
        print("add")
        print(" instance: %s" % instance)

    def query(self, *entities, **kwargs):
        return ValidationQuery(self._mgr, entities, kwargs)


class ValidationQuery(object):

    def __init__(self, validation_mgr, entities, args):
        self._mgr = validation_mgr
        self._entities = entities
        self._args = args
        self._filters = {}

    def filter_by(self, **kwargs):
        self._filters.update(kwargs)
        return self

    def all(self):
        print("all")
        print(" entities: %s" % self._entities)
        print(" args: %s" % self._args)
        print(" filters: %s" % self._filters)
        return []
