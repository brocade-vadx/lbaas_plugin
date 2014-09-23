# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 Brocade Communication Systems, Inc.  All rights reserved.
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
#
# @author: Marcelo Rodriguez, Brocade Communications Systems,Inc.
#



import sqlalchemy as sa

from neutron.db import model_base
from neutron.db import models_v2
from neutron.db import api as db

class VLb(model_base.BASEV2):
    """Schema for brocade vyatta vlb."""

    tenant_id = sa.Column(sa.String(36))
    vlb_id = sa.Column(sa.String(36), primary_key=True, default="")
    pool_id = sa.Column(sa.String(36))
    name = sa.Column(sa.String(255), default="")
    data_net_id = sa.Column(sa.String(36))
    mgmt_ip = sa.Column(sa.String(36))

def create_vlb(pool_id, vlb_id, tenant_id, name, data_net_id, mgmt_ip):
    """ Create a vlb entrie """

    session = db.get_session()

    with session.begin(subtransactions=True):
        vlb = VLb(tenant_id = tenant_id,
                name = name,
                data_net_id = data_net_id,
                mgmt_ip = mgmt_ip,
                vlb_id = vlb_id,
                pool_id = pool_id)
        session.add(vlb)
    return vlb

def get_vlbs():
    """ get all vlbs associated to a tenant id """

    session = db.get_session()

    vlbs = (session.query(VLb).all())
    return vlbs

def get_vlb_from_pool_id(pool_id):
    ''' get the vlb associated to this pool_id '''

    session = db.get_session()

    vlb = (session.query(VLb).filter_by(pool_id=pool_id).first())

    return vlb

def delete_vlb(pool_id):
    """ delete an instance of the vlb """

    session = db.get_session()

    with session.begin(subtransactions=True):
        vlb = (session.query(VLb).filter_by(pool_id=pool_id).first())
        if vlb is not None:
            session.delete(vlb)


