#!/usr/bin/env python
#
#   SatNOGS Rotator Homing
#
#   Move a SPID Rotator (or any other rotator that will report *absolute* positions, i.e. -180 through 540 degrees)
#   to an *absolute* position, in small steps.
#
#   The position an be set as either a 'home' position, but you can also provide a SatNOGS station ID,
#   in which case the rotator will be moved to the start position of the next observation.
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import argparse
import datetime
import logging
import time
import requests
import socket
import sys

from dateutil.parser import parse
from dateutil.tz import *

#logging.basicConfig(level=logging.DEBUG)

class ROTCTLD(object):
    """ rotctld (hamlib) communication class """
    # Note: This is a massive hack. 

    def __init__(self, 
        hostname="127.0.0.1", 
        port=4533, 
        timeout=5,
        poll_rate=5,
        movement_threshold=5.0,
        movement_timeout=120.0):

        """ Initiate the ROTCTLD Connection """
        self.hostname = hostname
        self.port = port
        self.poll_rate = poll_rate
        self.movement_threshold = movement_threshold
        self.movement_timeout = movement_timeout

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)

        self.connect()


    def connect(self):
        """ Connect to rotctld instance """
        self.sock.connect((self.hostname,self.port))
        model = self.get_model()
        if model == None:
            # Timeout!
            self.close()
            raise Exception("Timeout!")
        else:
            return model


    def close(self):
        self.sock.close()


    def send_command(self, command):
        """ Send a command to the connected rotctld instance,
            and return the return value.
        """
        _command = command + '\n'
        self.sock.sendall(_command.encode('ascii'))
        try:
            return self.sock.recv(1024).decode('ascii')
        except:
            return None


    def get_model(self):
        """ Get the rotator model from rotctld """
        model = self.send_command('_')
        return model


    def set_azel(self,azimuth,elevation, blocking=False, timeout=120):
        """ Command rotator to a particular azimuth/elevation """
        # Sanity check inputs.
        if elevation > 90.0:
            elevation = 90.0
        elif elevation < 0.0:
            elevation = 0.0

        if azimuth > 360.0:
            azimuth = azimuth % 360.0


        command = "P %3.1f %2.1f" % (azimuth,elevation)
        response = self.send_command(command)

        # If we don't get RPRT 0 in the response, this indicates
        # an error commanding the rotator.
        if "RPRT 0" not in response:
            return False
        else:
            # If we *do* get RPRT 0, then we have successfully commanded the rotator.
            if not blocking:
                # If we're not in blocking more, return immediately.
                return True

        # Otherwise, we're going to wait for the rotator to reach its intended position.
        _start_time = time.time()
        logging.debug("Target position: %.1f, %.1f" % (azimuth, elevation))

        # Keep checking the rotator position until we have hit our timeout.
        while (time.time() - _start_time) < self.movement_timeout:
            time.sleep(self.poll_rate)
            (_az, _el) = self.get_azel()

            # Immediately raise an exception if we can't get a position.
            if _az is None:
                raise Exception("No communication with rotator.")

            logging.debug("Current position: %.1f, %.1f" % (_az, _el))

            # Otherwise, compare with the target position.
            if (abs(azimuth - _az%360.0) < self.movement_threshold) and (abs(elevation - _el) < self.movement_threshold) :
                # We are there! (or close enough that we can break out of this loop)
                return True
            else:
                continue

        # We have hit the timeout.
        raise Exception("Movement Timeout!")



    def get_azel(self):
        """ Poll rotctld for azimuth and elevation """
        # Send poll command and read in response.
        response = self.send_command('p')

        # Attempt to split response by \n (az and el are on separate lines)
        try:
            response_split = response.split('\n')
            _current_azimuth = float(response_split[0])
            _current_elevation = float(response_split[1])
            return (_current_azimuth, _current_elevation)
        except:
            logging.error("Could not parse position: %s" % response)
            return (None,None)



    def halt(self):
        """ Immediately halt rotator movement, if it support it """
        self.send_command('S')



def get_next_rise_azimuth(station_id=1, dev=False):
    ''' Query the SatNOGS network for upcoming scheduled observations for a station,
        and return the rise azimuth of the next pass.

        Args:
            station_id (int): Station ID of the station
            dev (bool): Use network-dev instead of network.

        Returns:
            float / None: None if there are no upcoming observations, otherwise the rise azimuth of the next observation.
            float / None: None if there are no upcoming observations, otherwise, the number of seconds until the next observation.
    '''

    _dev = "-dev" if dev else ""
    _request_url = "https://network%s.satnogs.org/api/observations/?ground_station=%d&status=future" % (_dev, station_id)

    _more_data = True
    _obs = []
    while _more_data:
        try:
            _r = requests.get(_request_url)
            _obs_temp = _r.json()
        except Exception as e:
            logging.error("Error getting next observation info - %s" % str(e))
            return (None, None)

        # The network API returns a list of observation objects.
        if type(_obs_temp) is not list:
            logging.error("SatNOGS API did not return expected list.")
            return (None, None)

        # Check that there are actually some observations to look at.
        if len(_obs_temp) == 0:
            logging.info("No scheduled observations found.")
            return (None, None)

        # Extend obs list
        _obs.extend(_obs_temp)
        logging.debug("Appended %d observations to list." % (len(_obs_temp)))

        # Check if there is another page of data, if there is run another request.
        if 'next' in _r.links:
            _request_url = _r.links['next']['url']
        else:
            _more_data = False
    

    # Observations are not always provided in time-sorted order, so we need to search for the earliest one.
    # If we don't find one that's sooner than one day ahead, just go to the home position.
    _next_obs_time = datetime.datetime.now(tzutc()) + datetime.timedelta(1)
    _earliest_obs_time = datetime.datetime.now(tzutc()) + datetime.timedelta(0,60)
    _rise_az = None
    _obs_info = None

    for _o in _obs:
        _start = parse(_o['start'])

        if (_start < _next_obs_time) and (_start > _earliest_obs_time):
            _next_obs_time = _start
            _rise_az = _o['rise_azimuth']
            _obs_info = _o

    _time_to_obs = (_next_obs_time - datetime.datetime.now(tzutc())).total_seconds()

    if _obs_info is not None:
        logging.info("Next observation (#%d) rises at %.1f degrees, in %.1f minutes." % (_obs_info['id'], _rise_az, _time_to_obs/60.0))
        return (_rise_az, _time_to_obs)
    else:
        logging.info("No scheduled observations found.")
        return (None, None)



if __name__ == "__main__":

    # Read in command line arguments.
    parser = argparse.ArgumentParser()
    parser.add_argument('--station_id', type=int, default=-1, help="SatNOGS Station ID")
    parser.add_argument('--network_dev', action='store_true', default=False, help="Use SatNOGS Network-Dev instead of Network.")
    parser.add_argument('--home_azimuth', type=float, default=0.0, help="Home Azimuth. Default=0.0")
    parser.add_argument('--home_elevation', type=float, default=0.0, help="Home Elevation, Default=0.0")
    parser.add_argument('--homing_timeout', type=float, default=180.0, help='Overall homing timeout. Default = 180 seconds.')
    parser.add_argument('--azimuth_step', type=float, default=90.0, help="Move in X degree steps. Default = 90 degrees")
    parser.add_argument('--movement_threshold', type=float, default=10.0, help="Movement threshold. Default = 10 degrees")
    parser.add_argument('--rotctld_host', type=str, default="127.0.0.1", help="rotctld hostname. Default=127.0.0.1")
    parser.add_argument('--rotctld_port', type=int, default=4533, help="rotctld port. Default=4533")
    parser.add_argument('--log', type=str, default='/tmp/rotator.log', help="Log file. Default=/tmp/rotator.log")
    args = parser.parse_args()

    logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s', filename=args.log, level=logging.DEBUG)
    stdout_format = logging.Formatter('%(asctime)s %(levelname)s:%(message)s')
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(stdout_format)
    logging.getLogger().addHandler(stdout_handler)

    _home_az = args.home_azimuth
    _home_el = args.home_elevation

    # Attempt to get the next observation rise azimuth.
    if args.station_id != -1:
        (_rise_az, _time_to_obs) = get_next_rise_azimuth(args.station_id, args.network_dev)

        if _rise_az is not None:
            if _time_to_obs < args.homing_timeout:
                logging.critical("Next observation is only %s seconds away! Not enough time to move..." % _time_to_obs)
                sys.exit(0)

            _home_az = _rise_az

        else:
            logging.info("No observations scheduled, using home position.")


    # Attempt to connect to ROTCTLD
    _rot = ROTCTLD(
        hostname = args.rotctld_host,
        port = args.rotctld_port,
        poll_rate = 3.0,
        movement_threshold = args.movement_threshold
        )

    _start_time = time.time()

    logging.info("Attempting to move to target position: %.1f, %.1f" % (_home_az, _home_el))

    # Keep trying to move until we hit the timeout.
    while (time.time() - _start_time) < args.homing_timeout:
        # First up, get the current rotator position
        (_az, _el) = _rot.get_azel()

        # Check the position is valid.
        if _az is None:
            logging.error("Could not communicate with rotator.")
            break

        if (abs(_home_az - _az) < args.movement_threshold) and (abs(_home_el - _el) < args.movement_threshold):
            logging.info("Finished moving to target position.")
            # One more time, with feeling...
            _rot.set_azel(_home_az, _home_el, blocking=False)
            break

        if _az < _home_az:
            # Move clockwise
            _new_az = _az + args.azimuth_step
            # We're close enough that we don't need to move in steps any more, just go straight there.
            if _new_az > _home_az:
                _new_az = _home_az

        elif _az > _home_az:
            # Move anticlockwise.
            _new_az = _az - args.azimuth_step

            if _new_az < _home_az:
                _new_az = _home_az

        # Now modulo the new target azimuth so that we can send it to the rotator.
        _new_az = _new_az % 360.0

        # Command the rotator!
        try:
            _success = _rot.set_azel(_new_az, _home_el, blocking=True)
        except Exception as e:
             logging.error("Error - %s" % str(e))
             break

        # Check the command was successful.
        if _success:
            logging.info("Movement successful!")
        else:
            logging.error("Failed to move rotator. Breaking")
            break


    # Finished!
    _rot.close()
    logging.info("Elapsed time: %d seconds" % (time.time() - _start_time))











