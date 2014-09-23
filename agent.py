# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 OpenStack Foundation.  All rights reserved
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
# @author: Marcelo Rodriguez, Brocade Communications Systems, Inc.
#

import os
import sys
import time
from oslo.config import cfg
from eventlet import greenthread
from neutron.db import api as db
from neutron.db import models_v2
from neutron.agent.common import config
from neutron.agent.linux import ip_lib
from neutron.agent.linux import utils
from neutron.common import exceptions
from neutron.common import utils as n_utils
from neutron.common import log
from neutron.openstack.common import excutils
from neutron.openstack.common import importutils
from neutron.openstack.common import log as logging
from neutron.plugins.common import constants
from neutron.services.loadbalancer.agent import agent_device_driver
from neutron.services.loadbalancer import constants as lb_const
from neutronclient.v2_0 import client as neutronclient
from novaclient.v1_1 import client as novaclient

from neutron.services.loadbalancer.drivers.brocade_vlb import (
        brocade_adx_driver_impl as driver_impl,
        brocade_adx_exceptions as adx_exception,
        models as vlb_db,
        driver as vlb_drv,
)

LOG = logging.getLogger(__name__)

DRIVER_NAME = 'brocade_vlb_driver'

cfg.CONF.register_opts([
    cfg.StrOpt('deployment_model', help='The deployment mode'),
    cfg.StrOpt('tenant_id', help='tenant id'),
    cfg.StrOpt('tenant_admin_name', help='tenant admin username'),
    cfg.StrOpt('tenant_admin_password', help='tenant admin password'),
    cfg.StrOpt('auth_url', help='auth_url')
    ],"brocade")

cfg.CONF.register_opts([
    cfg.StrOpt('flavor_id', help='Flavor id for the vADX'),
    cfg.StrOpt('image_id', help='Image id of the vADX'),
    cfg.StrOpt('management_network_id', help='Management network for the vADX'),
    cfg.StrOpt('data_network_id', help='Data network for the vADX'),
    cfg.StrOpt('username', help='Default username for the vADX'),
    cfg.StrOpt('password', help='Default password for the vADX'),
    cfg.IntOpt('nova_poll_interval', default=5,
        help=_('Number of seconds between consecutive Nova queries '
            'when waiting for loadbalancer instance status change.')),
    cfg.IntOpt('nova_spawn_timeout', default=300,
        help=_('Number of seconds to wait for Nova to activate '
            'instance before setting resource to error state.')),
    cfg.IntOpt('vlb_poll_interval', default=5,
        help=_('Number of seconds between consecutive vLB '
            'queries when waiting for router instance boot.')),
    cfg.IntOpt('vlb_boot_timeout', default=300,
        help=_('Number of seconds to wait for vLB to boot '
            'before setting resource to error state.')),
],"brocade_vlb")

class AgentDeviceDriver(agent_device_driver.AgentDeviceDriver):
    """Abstract device driver that defines the API required by LBaaS agent."""

    def __init__(self, conf, plugin_rpc):
        LOG.debug("brocade_vlb_driver:: initialized")
        self.conf = conf
        self.plugin_rpc = plugin_rpc

    @classmethod
    def get_name(cls):
        """Returns unique name across all LBaaS device drivers."""
        return DRIVER_NAME

    @n_utils.synchronized('brocade-vlb-driver')
    def deploy_instance(self, pool):
        """Fully deploys a loadbalancer instance from a given config."""

        if vlb_db.get_vlb_from_pool_id(pool['pool']['id']) is not None:
            LOG.debug('This is an error')
            return
        name = 'vlb_{0}'.format(os.urandom(6).encode('hex'))
        nova_client = self._get_nova_client()
        neutron_client = self._get_neutron_client()

        subnet = neutron_client.show_subnet(pool['pool']['subnet_id'])

        LOG.debug('brocade_vlb_driver::deploy_instance %s' % name)
        vLb = nova_client.servers.create(name, self.conf.brocade_vlb.image_id,
                self.conf.brocade_vlb.flavor_id,
                nics=[ {'net-id': self.conf.brocade_vlb.management_network_id },
                            {'net-id': subnet['subnet']['network_id'] }]
                )

        def _vLb_active():
            while True:
                try:
                    instance = nova_client.servers.get(vLb.id)
                except Exception:
                    yield self.conf.brocade_vlb.nova_poll_interval
                    continue
                LOG.info(_("vLB Driver::Load Balancer instance status: %s")
                        %instance.status)
                if instance.status not in ('ACTIVE', 'ERROR'):
                    yield self.conf.brocade_vlb.nova_poll_interval
                elif instance.status == 'ERROR':
                    raise InstanceSpawnError()
                else:
                    break
        self._wait(_vLb_active, 
                timeout=self.conf.brocade_vlb.nova_spawn_timeout)
        LOG.info(_("vLB Driver::Waiting for the vLB app to initialize %s") %
                                        vLb.id)

        mgmt_ip = self._get_address(vLb,
                                self.conf.brocade_vlb.management_network_id)
        data_ip = self._get_address(vLb, subnet['subnet']['network_id'])
        vlb_db.create_vlb(pool['pool']['id'], vLb.id, vLb.tenant_id, vLb.name,
                data_ip, mgmt_ip)

	# Now wait for vlb to boot
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.create_pool(pool['pool'])
                    impl.ifconfig_e1(data_ip,subnet['subnet']['cidr'])
                    impl.create_static_route('0.0.0.0','0',subnet['subnet']['gateway_ip'])
                    impl.enable_source_nat()
                except Exception as e:
                    LOG.debug('vLB Driver::Load Balancer instance %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap, timeout=self.conf.brocade_vlb.vlb_boot_timeout)

        LOG.info(_("vLB Driver:vLB successfully deployed and configured"))

    @n_utils.synchronized('brocade-vlb-driver')
    def undeploy_instance(self, pool_id):
        """Fully undeploys the loadbalancer instance."""
        LOG.debug('vLB Driver::undeploy_instance')
        vlb_value = vlb_db.get_vlb_from_pool_id(pool_id['pool']['id'])
        nova_client = self._get_nova_client()
        instance = nova_client.servers.find(name=vlb_value['name'])
        instance.delete()

        vlb_db.delete_vlb(pool_id['pool']['id'])

    def get_stats(self, pool_id):
        LOG.debug('vLB Driver::get_stats')

    def remove_orphans(self, known_pool_ids):
        # Not all drivers will support this
        raise NotImplementedError()

    def create_vip(self, vip):
        LOG.debug('vLB Driver::create_vip')
        vlb = vlb_db.get_vlb_from_pool_id(vip['pool_id'])
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.create_vip(vip)
                except Exception as e:
                    LOG.debug('vLB Driver::create_vip trying to connect to'
                                            'vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap, timeout=self.conf.brocade_vlb.vlb_boot_timeout)

        LOG.info(_("vLB Driver:vLB finish creating vip"))


    def update_vip(self, old_vip, vip):
        LOG.debug('vLB Driver::update_vip')
        vlb = vlb_db.get_vlb_from_pool_id(vip['pool_id'])
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.update_vip(old_vip,vip)
                except Exception as e:
                    LOG.debug('vLB Driver::update_vip trying to connect to'
                                    ' vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap,timeout=self.conf.brocade_vlb.vlb_boot_timeout)

        LOG.info(_("vLB Driver:vLB finish updating vip"))

    def delete_vip(self, vip):
        LOG.debug('vLB Driver::delete_vip')
        vlb = vlb_db.get_vlb_from_pool_id(vip['pool_id'])
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.delete_vip(vip)
                except Exception as e:
                    LOG.debug('vLB Driver::delete_vip trying to connect to'
                                           'vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap,timeout=self.conf.brocade_vlb.vlb_boot_timeout)
        LOG.info(_("vLB Driver:vLB finish deleting vip"))

    def create_pool(self, pool):
        obj = {}
        obj['pool']=pool
        self.deploy_instance(obj)
    
    def update_pool(self, old_pool, pool):
        LOG.info('vLB Driver::update_pool')
        LOG.debug('>>>>>>>>>>>>>>>>>>>>> %s' % pool)
        vlb = vlb_db.get_vlb_from_pool_id(pool['id'])
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.update_pool(old_pool,pool)
                except UnsupportedFeature as e:
                    raise e
                except Exception as e:
                    LOG.debug('vLB Driver::create_member trying to connect to'
                            'vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap,timeout=self.conf.brocade_vlb.vlb_boot_timeout)
        LOG.info(_("vLB Driver:vLB finish updating pool"))
        
    
    def delete_pool(self, pool):
        LOG.info('vLB Driver::delete_pool')
        obj = {}
        obj['pool'] = pool
        self.undeploy_instance(obj)

    @log.log
    def create_member(self, member):
        LOG.info('vLB Driver::create_member')
        vlb = vlb_db.get_vlb_from_pool_id(member['pool_id'])
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.create_member(member)
                except UnsupportedFeature as e:
                    raise e
                except Exception as e:
                    LOG.debug('vLB Driver::create_member trying to connect to'
                        ' vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap,
               timeout=self.conf.brocade_vlb.vlb_boot_timeout)

        LOG.info(_("vLB Driver:vLB finish creating member"))

    def update_member(self, old_member, member):
        LOG.info('vLB Driver::updating_member')
        vlb = vlb_db.get_vlb_from_pool_id(member['pool_id'])
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.update_member(old_member,member)
                except UnsupportedFeature as e:
                    raise e
                except Exception as e:
                    LOG.debug('vLB Driver::update_member trying to connect to'
                             'vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap,
                    timeout=self.conf.brocade_vlb.vlb_boot_timeout)
        LOG.info(_("vLB Driver:vLB finish updating member"))

    def delete_member(self, member):
        LOG.info('vLB Driver::delete_member')
        vlb = vlb_db.get_vlb_from_pool_id(member['pool_id'])
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.delete_member(member)
                except UnsupportedFeature as e:
                    raise e
                except Exception as e:
                    LOG.debug('vLB Driver::delete_member trying to connect to'
                            ' vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap,
                    timeout=self.conf.brocade_vlb.vlb_boot_timeout)
        LOG.info(_("vLB Driver:vLB finish deleting member"))


    def create_pool_health_monitor(self, health_monitor, pool_id):
        LOG.info('vLB Driver::create_pool_health_monitor')
        vlb = vlb_db.get_vlb_from_pool_id(pool_id)
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.create_health_monitor(health_monitor, pool_id)
                except UnsupportedFeature as e:
                    raise e
                except Exception as e:
                    LOG.debug('vLB Driver::create_pool_health_monitor trying to'
                                        ' connect to vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap, timeout=self.conf.brocade_vlb.vlb_boot_timeout)

        LOG.info(_("vLB Driver:vLB finish creating healthmonitor"))

    def update_pool_health_monitor(self,
                                   old_health_monitor,
                                   health_monitor,
                                   pool_id):
        LOG.info('vLB Driver::update_pool_health_monitor')
        vlb = vlb_db.get_vlb_from_pool_id(pool_id)
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.update_health_monitor(health_monitor,
                            old_health_monitor, pool_id)

                except UnsupportedFeature as e:
                    raise e
                except Exception as e:
                    LOG.debug('vLB Driver::update_health_monitor trying to'
                        ' connect to vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap,
                    timeout=self.conf.brocade_vlb.vlb_boot_timeout)

        LOG.info(_("vLB Driver:vLB finish updating healthmonitor"))

    def delete_pool_health_monitor(self, health_monitor, pool_id):
        LOG.info('vLB Driver::delete_pool_health_monitor')
        vlb = vlb_db.get_vlb_from_pool_id(pool_id)
        mgmt_ip = vlb['mgmt_ip']
        def _vLb_soap():
            while True:
                try:
                    impl = driver_impl.BrocadeAdxDeviceDriverImpl(
                            self.conf.brocade_vlb.username,
                            self.conf.brocade_vlb.password,
                            mgmt_ip)
                    impl.delete_health_monitor(health_monitor, pool_id)

                except UnsupportedFeature as e:
                    raise e
                except Exception as e:
                    LOG.debug('vLB Driver::delete_pool_health_monitor trying '
                            ' to connect to  vLB - %s' % e)
                    yield self.conf.brocade_vlb.vlb_poll_interval
                    continue
                break
        self._wait(_vLb_soap,
                    timeout=self.conf.brocade_vlb.vlb_boot_timeout)

        LOG.info(_("vLB Driver:vLB finish deleting health monitor"))

    def _get_nova_client(self):
        LOG.debug(_("brocade_vlb_driver::Get Nova client"))
        return novaclient.Client(
                self.conf.brocade.tenant_admin_name,
                self.conf.brocade.tenant_admin_password,
                None,
                self.conf.brocade.auth_url,
                service_type='compute',
                tenant_id=self.conf.brocade.tenant_id)

    def _get_neutron_client(self):
        LOG.debug(_('brocade_vlb_driver::Get Neutron client'))
        return neutronclient.Client(
                username=self.conf.brocade.tenant_admin_name,
                password=self.conf.brocade.tenant_admin_password,
                tenant_id=self.conf.brocade.tenant_id,
                auth_url=self.conf.brocade.auth_url) 

    def _wait(self, query_fn, timeout=0):
        LOG.debug(_("brocade_vlb_driver:: Now we wait"))
        end = time.time() + timeout
        try:
            for interval in query_fn():
                greenthread.sleep(interval)
                if timeout > 0 and time.time() >= end:
                    raise InstanceBootTimeout()
        except Exception:
            pass

    def _get_address(self, instance, net_id):
        session = db.get_session()
        query = session.query(models_v2.Network)
        network = query.filter(models_v2.Network.id == net_id).one()
        address_map = instance.addresses[network['name']]

        address = address_map[0]["addr"]
        return address

class Wrap(object):
    """A light attribute wrapper for compatibility with the interface lib."""
    def __init__(self, d):
        self.__dict__.update(d)

    def __getitem__(self, key):
        return self.__dict__[key]
