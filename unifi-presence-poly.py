#!/usr/bin/env python
try:
    import polyinterface
except ImportError:
    import pgc_interface as polyinterface
import sys
import time
import struct
import array
import fcntl
from requests import Session
import json
import re
from typing import Pattern, Dict, Union
import urllib3
urllib3.disable_warnings()

LOGGER = polyinterface.LOGGER

class Controller(polyinterface.Controller):

    def __init__(self, polyglot):
        super(Controller, self).__init__(polyglot)
        self.name = 'UniFi Presence Controller'
        self.poly.onConfig(self.process_config)
        self.firstRun = True

    def start(self):
        # This grabs the server.json data and checks profile_version is up to date
        serverdata = self.poly.get_server_data()
        LOGGER.info('UniFi Presence Controller '.format(serverdata['version']))
        self.heartbeat(0)
        self.check_params()
        self.discover()
        self.setDriver('ST',1)

    def shortPoll(self):
        #LOGGER.debug('Controller.shortPoll')
        for node in self.nodes:
           self.nodes[node].update()
        if self.firstRun:
           self.query()
           self.firstRun = False
           
    def longPoll(self):
        #LOGGER.debug('Controller.longPoll')
        self.heartbeat()

    def query(self,command=None):
        #LOGGER.debug('Controller.query')
        #self.check_params()
        for node in self.nodes:
            self.nodes[node].reportDrivers()

    def discover(self, *args, **kwargs):
        #LOGGER.debug('Controller.discover')
        for key,val in self.polyConfig['customParams'].items():
            if (key.find(':') != -1):
                LOGGER.debug(key + " => " + val)
                nodeaddr = key.replace(':','').lower()
                self.addNode(UniFiNode(self, self.address, nodeaddr, key, val))

    def update(self):
        #LOGGER.info('UniFi Presence Controller update')
        pass

    def delete(self):
        LOGGER.info('UniFi Presence Controller deleted')

    def stop(self):
        LOGGER.debug('UniFi Presence Controller stopped.')

    def process_config(self, config):
        #LOGGER.info("process_config: Enter config={}".format(config));
        #LOGGER.info("process_config: Exit");
        pass

    def heartbeat(self,init=False):
        LOGGER.debug('heartbeat: init={}'.format(init))
        if init is not False:
            self.hb = init
        LOGGER.debug('heartbeat: hb={}'.format(self.hb))
        if self.hb == 0:
            self.reportCmd("DON",2)
            self.hb = 1
        else:
            self.reportCmd("DOF",2)
            self.hb = 0

    def check_params(self):
        self.removeNoticesAll()

        if 'uc_user' in self.polyConfig['customParams']:
            self.uc_user = self.polyConfig['customParams']['uc_user']
            global uc_user
            uc_user = self.polyConfig['customParams']['uc_user']
        else:
            LOGGER.error('check_params: "uc_user" not defined in customParams')
            self.addNotice('Please set proper "uc_user" key and value in the configuration page, then restart this nodeserver')
            st = False

        if 'uc_password' in self.polyConfig['customParams']:
            self.uc_password = self.polyConfig['customParams']['uc_password']
            global uc_password
            uc_password = self.polyConfig['customParams']['uc_password']
        else:
            LOGGER.error('check_params: "uc_password" not defined in customParams')
            self.addNotice('Please set proper "uc_password" key and value in the configuration page, then restart this nodeserver')
            st = False

        if 'uc_ip' in self.polyConfig['customParams']:
            self.uc_ip = self.polyConfig['customParams']['uc_ip']
            global uc_ip
            uc_ip = self.polyConfig['customParams']['uc_ip']
        else:
            LOGGER.error('check_params: "uc_ip" not defined in customParams')
            self.addNotice('Please set proper "uc_ip" key and value in the configuration page, then restart this nodeserver')
            st = False

        if 'uc_port' in self.polyConfig['customParams']:
            self.uc_port = self.polyConfig['customParams']['uc_port']
            global uc_port
            uc_port = self.polyConfig['customParams']['uc_port']
        else:
            LOGGER.error('check_params: "uc_port" not defined in customParams')
            self.addNotice('Please set proper "uc_port" key and value in the configuration page, then restart this nodeserver')
            st = False

    def remove_notice_test(self,command):
        LOGGER.info('remove_notice_test: notices={}'.format(self.poly.config['notices']))
        # Remove all existing notices
        self.removeNotice('test')

    def remove_notices_all(self,command):
        LOGGER.info('remove_notices_all: notices={}'.format(self.poly.config['notices']))
        # Remove all existing notices
        self.removeNoticesAll()

    def update_profile(self,command):
        #LOGGER.info('update_profile:')
        st = self.poly.installprofile()
        return st

    id = 'controller'
    commands = {
        'DISCOVER': discover,
        'UPDATE_PROFILE': update_profile,
        'REMOVE_NOTICES_ALL': remove_notices_all,
    }
    drivers = [{'driver': 'ST', 'value': 1, 'uom': 2}]
    
class LoggedInException(Exception):
    def __init__(self, *args, **kwargs):
        super(LoggedInException, self).__init__(*args, **kwargs)

class Unifi_API(object):
    _login_data = {}
    _current_status_code = None

    def __init__(self, username: str="ubnt", password: str="ubnt", site: str="default", baseurl: str="https://unifi:8443"):
        self._login_data['username'] = username
        self._login_data['password'] = password
        self._site = site
        self._verify_ssl = False
        self._baseurl = baseurl
        self._session = Session()

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, *args):
        self.logout()

    def login(self):
        self._current_status_code = self._session.post("{}/api/login".format(self._baseurl), data=json.dumps(self._login_data), verify=self._verify_ssl).status_code
        if self._current_status_code == 400:
            raise LoggedInException("Failed to log in to api with provided credentials")

    def logout(self):
        self._session.get("{}/logout".format(self._baseurl))
        self._session.close()

    def list_clients(self, filters: Dict[str, Union[str, Pattern]]=None, order_by: str=None) -> list:
        r = self._session.get("{}/api/s/{}/stat/sta".format(self._baseurl, self._site, verify=self._verify_ssl), data="json={}")
        self._current_status_code = r.status_code
        if self._current_status_code == 401:
            raise LoggedInException("Invalid login, or login has expired")
        data = r.json()['data']
        if filters:
            for term, value in filters.items():
                value_re = value if isinstance(value, Pattern) else re.compile(value)
                data = [x for x in data if term in x.keys() and re.fullmatch(value_re, x[term])]
        return data

class UniFiNode(polyinterface.Node):

    def __init__(self, controller, primary, address, macaddr, name):
        super(UniFiNode, self).__init__(controller, primary, address, name)
        self.macaddr = macaddr

    def start(self):
        self.setOn('DON')

    def update(self):
        api = Unifi_API(username=uc_user, password=uc_password, baseurl="https://" + uc_ip + ":" + uc_port)
        api.login()
        device_list = (api.list_clients(filters={'mac': self.macaddr}))
        api.logout()
        hostname = ''
        for dict in device_list:
            if dict['mac'] == self.macaddr:
                hostname = dict['hostname']
                #LOGGER.debug('hostname = ' + hostname)
            if 'ap_mac' in dict:
                #LOGGER.debug(self.name + ' is on network')
                self.setOnNetwork('')
            else:
                #LOGGER.debug(self.name + ' is off network')
                self.setOffNetwork('')

    def setOnNetwork(self, command):
        self.setDriver('ST', 1)

    def setOffNetwork(self, command):
        self.setDriver('ST', 0)

    def setOn(self, command):
        self.setDriver('ST', 1)

    def setOff(self, command):
        self.setDriver('ST', 0)

    def query(self,command=None):
        self.reportDrivers()

    hint = [1,2,3,4]
    drivers = [{'driver': 'ST', 'value': 0, 'uom': 2}]
    id = 'unifi_node'
    commands = {
                    'DON': setOn, 'DOF': setOff
                }

if __name__ == "__main__":
    try:
        polyglot = polyinterface.Interface('UniFi Presence Controller')
        polyglot.start()
        control = Controller(polyglot)
        control.runForever()
    except (KeyboardInterrupt, SystemExit):
        LOGGER.warning("Received interrupt or exit...")
        polyglot.stop()
    except Exception as err:
        LOGGER.error('Excption: {0}'.format(err), exc_info=True)
    sys.exit(0)
