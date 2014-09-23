# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack Foundation.
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
#
# @author: Marcelo Rodriguez, Brocade Communications Systems,Inc.
#


import StringIO
import base64
from suds.client import Client
from suds.transport.http import HttpAuthenticated
from suds import client as suds_client
from suds.sax import element as suds_element
from suds.plugin import MessagePlugin

from neutron.openstack.common import log as logging

LOG = logging.getLogger(__name__)

class RemoveEmptyTags(MessagePlugin):
    def marshalled(self, context):
        context.envelope[1].prune()

class AdxService:
    "ADX Service Initialization Class"
    ns0 = ('ns0', 'http://schemas.xmlsoap.org/soap/envelope123/')

    def __init__(self, adxIpAddress, userName, password):
        self.adxIpAddress = adxIpAddress
        self.userName = userName
        self.password = password
        self.wsdl_base = "http://" + adxIpAddress + "/wsdl/"
        self.sys_service_wsdl = "sys_service.wsdl"
        self.slb_service_wsdl = "slb_service.wsdl"
        self.net_service_wsdl = "network_service.wsdl"

    def createSlbServiceClient(self):
        def soapHeader():
            requestHeader = suds_element.Element('RequestHeader',
                                                 ns=AdxService.ns0)
            context = suds_element.Element('context').setText('default')
            requestHeader.append(context)
            return requestHeader

        url = self.wsdl_base + self.slb_service_wsdl
        location = "http://" + self.adxIpAddress + "/WS/SLB"
        transport = HttpAuthenticated( username=self.userName,
                password=self.password)
        self.transport = transport

        client = suds_client.Client(url, transport=transport,
                                    service='AdcSlb',
                                    location=location, 
                                    timeout=300,
                                    plugins=[RemoveEmptyTags()])
        requestHeader = soapHeader()
        client.set_options(soapheaders=requestHeader)
        return client

    def createSysServiceClient(self):
        def soapHeader():
            requestHeader = suds_element.Element('RequestHeader',
                                                 ns=AdxService.ns0)
            context = suds_element.Element('context').setText('default')
            requestHeader.append(context)
            return requestHeader

        url = self.wsdl_base + self.sys_service_wsdl
        location = "http://" + self.adxIpAddress + "/WS/SYS"
        transport = HttpAuthenticated( username=self.userName,
                                password=self.password)
        self.transport = transport

        client = suds_client.Client(url, transport=self.transport,
                                    service='AdcSysInfo',
                                    location=location, 
                                    timeout=300,
                                    plugins=[RemoveEmptyTags()])
    
        requestHeader = soapHeader()
        client.set_options(soapheaders=requestHeader)
        return client

    def createNetServiceClient(self):
        def soapHeader():
            requestHeader = suds_element.Element('RequestHeader',
                    ns=AdxService.ns0)
            context = suds_element.Element('context').setText('default')
            requestHeader.append(context)
            return requestHeader

        url = self.wsdl_base + self.net_service_wsdl
        location = "http://" + self.adxIpAddress + "/WS/NET"
        transport = HttpAuthenticated( username=self.userName,
                password=self.password)
        self.transport = transport

        client = suds_client.Client(url, transport=self.transport,
                service='AdcNet',
                location=location,
                timeout=300,
                plugins=[RemoveEmptyTags()])

        requestHeader = soapHeader()
        client.set_options(soapheaders=requestHeader)
        return client

