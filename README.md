Brocade vADX OpenStack LBaas Plugin/Agent

Installation
------------

Configure the new vlb table in the neutron database.

    Login to the mysql server with:

    mysql -u root -p neutron

    At the mysql> prompt, type the following table definition.

    CREATE TABLE vlbs (tenant_id varchar(255) DEFAULT NULL, \
    id varchar(36) NOT NULL PRIMARY KEY, \
    name varchar(255) DEFAULT NULL, \
    data_net_id varchar(36) NOT NULL, \
    mgmt_ip varchar(16) NOT NULL);

    You can check that the table was successfully created by showing the table
    description or excecuting a simple query with:

    select * from vlbs;

    or 

    desc vlbs;

    Configure Neutron to use the brocade_vlb plugin by editing the file located at
    /etc/neutron/neutron.conf. Look for [service_providers] section, and enable the
    plugin.

    ------------------------------------------------------------------------

    [service_providers]
    service_provider =
    LOADBALANCER:Brocade_vlb:neutron.services.loadbalancer.drivers.brocade_vlb.plugin.LoadBalancerPluginDriver:de
    fault

    ------------------------------------------------------------------------

    Now edit the /etc/neutron/lbaas_agent.ini, enable the device_driver and
    configure the agent settings.

    ------------------------------------------------------------------------

    [DEFAULT]
    device_driver =
    neutron.services.loadbalancer.drivers.brocade_vlb.agent.AgentDeviceDriver

    [brocade]
    deployment_model = one_arm_non_shared
    tenant_admin_name = admin_user
    tenant_admin_password = password_of_the_admin_user
    tenant_id = XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
    auth_url = http://openstack:35357/v2.0

    [brocade_vlb]
    username = admin
    password = brocade
    flavor_id = 29366762-da7b-44bd-97f8-722463d9b3a5
    image_id = ec3711e8-5545-4ac6-8441-f4647e07d8f6
    management_network_id = 0ed632cd-dcc0-4f1f-aa56-bb6ca01ecaeb
    ------------------------------------------------------------------------

    tenant_id is the tenant in which all the vLB instance will be created.
    flavor_id is the id of the flavor required to create an instance of the Brocade
    vLB.
    image_id is the image id of the Brocade vLB.

    restart the neutron server and lbaas agent.

    service neutron-server restart
    service neutron-lbaas-agent restart

    Confirm that the lbaas agent is working properly.

    neutron agent-list
    +--------------------------------------+--------------------+-----------+-------+----------------+
    | id                                   | agent_type         | host      | alive
    | admin_state_up |
    +--------------------------------------+--------------------+-----------+-------+----------------+
    | XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX | Loadbalancer agent | openstack | :-)
    | True           |
    | XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX | L3 agent           | openstack | :-)
    | True           |
    | XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX | DHCP agent         | openstack | :-)
    | True           |
    | XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX | Linux bridge agent | openstack | :-)
    | True           |
    | XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX | Metadata agent     | openstack | :-)
    | True           |
    +--------------------------------------+--------------------+-----------+-------+----------------+


