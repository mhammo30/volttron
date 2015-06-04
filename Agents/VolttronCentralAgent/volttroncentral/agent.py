# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2013, Battelle Memorial Institute
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are
# those of the authors and should not be interpreted as representing official
# policies, either expressed or implied, of the FreeBSD Project.
#

# This material was prepared as an account of work sponsored by an
# agency of the United States Government.  Neither the United States
# Government nor the United States Department of Energy, nor Battelle,
# nor any of their employees, nor any jurisdiction or organization
# that has cooperated in the development of these materials, makes
# any warranty, express or implied, or assumes any legal liability
# or responsibility for the accuracy, completeness, or usefulness or
# any information, apparatus, product, software, or process disclosed,
# or represents that its use would not infringe privately owned rights.
#
# Reference herein to any specific commercial product, process, or
# service by trade name, trademark, manufacturer, or otherwise does
# not necessarily constitute or imply its endorsement, recommendation,
# r favoring by the United States Government or any agency thereof,
# or Battelle Memorial Institute. The views and opinions of authors
# expressed herein do not necessarily state or reflect those of the
# United States Government or any agency thereof.
#
# PACIFIC NORTHWEST NATIONAL LABORATORY
# operated by BATTELLE for the UNITED STATES DEPARTMENT OF ENERGY
# under Contract DE-AC05-76RL01830

#}}}

import datetime
import logging
import sys
import requests
import threading
import os
import os.path as p
import uuid

import gevent
import tornado
import tornado.ioloop
import tornado.web
from tornado.web import url
from zmq.utils import jsonapi

from authenticate import Authenticate

from volttron.platform.agent import utils
from volttron.platform.async import AsyncCall
from volttron.platform.vipagent import *

# from volttron.platform import vip, jsonrpc
# from volttron.platform.agent.vipagent import (BaseAgent, RPCAgent, periodic,
#                                               onevent, jsonapi, export)
# from volttron.platform.agent import utils

from webserver import (ManagerWebApplication, ManagerRequestHandler,
                       StatusHandler, SessionHandler, RpcResponse)

from volttron.platform.control import list_agents
from volttron.platform.jsonrpc import (INTERNAL_ERROR, INVALID_PARAMS,
                                       INVALID_REQUEST, METHOD_NOT_FOUND,
                                       PARSE_ERROR, UNHANDLED_EXCEPTION)

utils.setup_logging()
_log = logging.getLogger(__name__)
WEB_ROOT = p.abspath(p.join(p.dirname(__file__), 'webroot'))


class PlatformRegistry:
    '''Container class holding registered vip platforms and services.
    '''

    def __init__(self, stale=5*60):
        self._vips = {}
        self._uuids = {}

    def get_vip_addresses(self):
        '''Returns all of the known vip addresses.
        '''
        return self._vips.keys()

    def get_platforms(self):
        '''Returns all of the registerd platforms dictionaries.
        '''
        return self._uuids.values()

    def get_platform(self, platform_uuid):
        '''Returns a platform associated with a specific uuid instance.
        '''
        return self._uuids.get(platform_uuid, None)

    def update_agent_list(self, platform_uuid, agent_list):
        '''Update the agent list node for the platform uuid that is passed.
        '''
        self._uuids[platform_uuid]['agent_list'] = agent_list.get()

    def register(self, vip_address, vip_identity, agentid, **kwargs):
        '''Registers a platform agent with the registry.

        An agentid must be non-None or a ValueError is raised

        Keyword arguments:
        vip_address -- the registering agent's address.
        agentid     -- a human readable agent description.
        kwargs      -- additional arguments that should be stored in a
                       platform agent's record.

        returns     The registered platform node.
        '''
        if vip_address not in self._vips.keys():
            self._vips[vip_address] = {}
        node = self._vips[vip_address]
#         if vip_identity in node:
#             raise ValueError('Duplicate vip_address vip_identity for {}-{}'
#                              .format(vip_address, vip_identity))
        if agentid is None:
            raise ValueError('Invalid agentid specified')

        platform_uuid = str(uuid.uuid4())
        node[vip_identity] = {'agentid': agentid,
                              'vip_address': vip_address,
                              'vip_identity': vip_identity,
                              'uuid': platform_uuid,
                              'other': kwargs
                              }
        self._uuids[platform_uuid] = node[vip_identity]

        _log.debug('Added ({}, {}, {} to registry'.format(vip_address,
                                                          vip_identity,
                                                          agentid))
        return node[vip_identity]


def volttron_central_agent(config_path, **kwargs):
    config = utils.load_config(config_path)

    vip_identity = config.get('vip_identity', 'volttron.central')

    agent_id = config.get('agentid', 'Volttron Central')
    server_conf = config.get('server', {})
    user_map = config.get('users', None)

    if user_map is None:
        raise ValueError('users not specified within the config file.')


    hander_config = [
        (r'/jsonrpc', ManagerRequestHandler),
        (r'/jsonrpc/', ManagerRequestHandler),
        (r'/websocket', StatusHandler),
        (r'/websocket/', StatusHandler),
        (r"/(.*)", tornado.web.StaticFileHandler,
         {"path": WEB_ROOT, "default_filename": "index.html"})
    ]

    def startWebServer(manager):
        '''Starts the webserver to allow http/RpcParser calls.

        This is where the tornado IOLoop instance is officially started.  It
        does block here so one should call this within a thread or process if
        one doesn't want it to block.

        One can stop the server by calling stopWebServer or by issuing an
        IOLoop.stop() call.
        '''
        session_handler = SessionHandler(Authenticate(user_map))
        webserver = ManagerWebApplication(session_handler, manager,
                                          hander_config, debug=True)
        webserver.listen(server_conf.get('port', 8080),
                         server_conf.get('host', ''))
        tornado.ioloop.IOLoop.instance().start()

    def stopWebServer():
        '''Stops the webserver by calling IOLoop.stop
        '''
        tornado.ioloop.IOLoop.stop()

    class VolttronCentralAgent(Agent):
        """Agent for querying WeatherUndergrounds API"""

        def __init__(self, **kwargs):
            super(VolttronCentralAgent, self).__init__(identity=vip_identity, **kwargs)
            _log.debug("Registering (vip_address, vip_identity) ({}, {})"
                       .format(self.core.address, self.core.identity))
            # a list of peers that have checked in with this agent.
            self.registry = PlatformRegistry()
            self.valid_data = False
            self._vip_channels = {}
            print('vc my identity {} address: {}'.format(self.core.identity,
                                                      self.core.address))

#         #@periodic(period=10)
#         def _update_agent_list(self):
#             jobs = {}
#             print "updating agent list"
#             for p in self.registry.get_platforms():
#                 jobs[p['uuid']] = gevent.spawn(self.list_agents, uuid=p['uuid'])
#             gevent.joinall(jobs.values(), timeout=20)
#             return [self.registry.update_agent_list(j, jobs[j]) for j in jobs]

        def list_agents(self, uuid):
            platform = self.registry.get_platform(uuid)
            results = []
            if platform:
                agent = self._get_rpc_agent(platform['vip_address'])

                results = agent.vip.rpc.call(platform['vip_identity'],
                                         'list_agents').get(timeout=10)

            return results

        @RPC.export
        def register_platform(self, peer_identity, name, peer_address):
            '''Agents will call this to register with the platform.

            This method is successful unless an error is raised.
            '''
            platform = self.registry.register(peer_address, peer_identity,
                                              name)
        def _handle_register_platform(self, address, identity=None):
            agent = self._get_rpc_agent(address)

            if not identity:
                identity = 'platform.agent'

            result = agent.vip.rpc.call(identity, "manage",
                                        address=self.core.address,
                                        identity=self.core.identity)
            if result.get(timeout=10):
                return self.registry.register(address, identity, 'platform.agent')

            return False



        def _get_rpc_agent(self, address):
            if address == self.core.address:
                agent = self
            elif address not in self._vip_channels:
                agent = Agent(address=address)
                gevent.spawn(agent.core.run).join(0)
                self._vip_channels[address] = agent

            else:
                agent = self._vip_channels[address]
            return agent

        @Core.receiver('onsetup')
        def setup(self, sender, **kwargs):
            print "Setting up"
            self.async_caller = AsyncCall()

        @Core.receiver('onstart')
        def start(self, sender, **kwargs):
            '''This event is triggered when the platform is ready for the agent
            '''
            # Start tornado in its own thread
            threading.Thread(target=startWebServer, args=(self,)).start()

        @Core.receiver('onfinish')
        def finish(self, sender, **kwargs):
            stopWebServer()

        def _handle_list_platforms(self):
            return [{'uuid': x['uuid'],
                         'name': x['agentid']}
                        for x in self.registry.get_platforms()]

        def route_request(self, id, method, params):
            '''Route request to either a registered platform or handle here.'''
            print('inside route_request {}, {}, {}'.format(id, method, params))
            if method == 'list_platforms':
                return self._handle_list_platforms()
            elif method == 'register_platform':
                print('registering_platform: {}'.format(params))
                return self._handle_register_platform(**params)


            fields = method.split('.')

            if len(fields) < 3:
                return RpcResponse(id=id, code=METHOD_NOT_FOUND)


            platform_uuid = fields[2]

            platform = self.registry.get_platform(platform_uuid)


            if not platform:
                return RpcResponse(id=id, code=METHOD_NOT_FOUND,
                                   message="Unknown platform {}".format(platform_uuid))

#             if fields[3] == 'list_agents':
#                 return platform['agent_list']

            # The method to route to the platform.
            platform_method = '.'.join(fields[3:])


            agent = self._get_rpc_agent(platform['vip_address'])

            _log.debug("calling identity {} with parameters {} {} {}"
                       .format(platform['vip_identity'],
                               id,
                               platform_method, params))
            result = agent.vip.rpc.call(platform['vip_identity'],
                                            "route_request",
                                            id, platform_method, params).get(timeout=10)


            return result

    VolttronCentralAgent.__name__ = 'VolttronCentralAgent'
    return VolttronCentralAgent(**kwargs)


def main(argv=sys.argv):
    '''Main method called by the eggsecutable.'''
    utils.default_main(volttron_central_agent,
                       description='Volttron central agent',
                       no_pub_sub_socket=True,
                       argv=argv)

if __name__ == '__main__':
    # Entry point for script
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
