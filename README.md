# SatNOGS Rotator Un-Winder Utility

This utility can be used to move a SatNOGS rotator station to an 'absolute' position between passes. This position could either be a 'home' location, or the start of the next pass. This helps 'unwind' a rotator prior to a pass occuring.

## Motivation
I operate SatNOGS station [#232](https://network.satnogs.org/stations/232/). It uses a RF HamDesign SPX-02 rotator, with a SPID Rot2Prog controller, and my setup is configured to provide 640 degrees of travel (-180 through to +460 degrees, where <0 degrees and > 360 degrees is an 'overwind' region).

While hamlib's rot2prog driver will quite happily report the 'absolute' position of the rotator (i.e. if it's in an 'overwind' region it will report <0 or >360 degrees), you cannot *set* an absolute position. Instead, hamlib will direct the rotator to take the shortest path to the provided position.

Unfortunately, this behaviour can lead to the rotator ending up in a 'wound-up' state where on the next pass, the movement of the rotator ends up moving into the overwind region and hitting a limit, and the rotator has to do a 360 degree spin to 'unwind' continue to track the satellite. On my rotator, it can take almost 2 minutes to perform this action, and results in [big signal gaps](https://network.satnogs.org/observations/316507/). Wouldn't it be good if we do this long 'unwind' movement *before* the pass?

## Solution

This problem has been discussed in a satnogs-client [issue](https://gitlab.com/librespacefoundation/satnogs/satnogs-client/issues/275), and I've suggested a fix in the LibreSpace [forum](https://community.libre.space/t/rotator-control-parking/2511/2?u=vk5qi). As a means of testing out a possible solution, I've created the `unwind.py` script in this directory. It's not an ideal solution, but it's a starting point.

In short, since we can read the absolute rotator position from the Rot2Prog, we can move to a desired absolute position by moving in a sequence of small steps. I'm using steps of 90 degrees. This can be used to move back to a 'home' location, or even better - move to the start of the next observation!

SatNOGS provides the handy `SATNOGS_POST_OBSERVATION_SCRIPT` option, which can be used to run a shell script after an observation has finished (duh). We run a script there which will move the rotator to the start of the next observation ahead of time, or alternatively move to a home location if there are no observations in the near (1 day) future.

## Usage

The following dependencies are required (and probably already available on a SatNOGS station):
 * python-requests
 * python-dateutil

The `unwind.py` utility can be run in a few ways.

To move to home location, run it with:
```
$ python unwind.py --home_azimuth=0.0 --home_elevation=0.0
```

By default we assume the movement will take less than 180 seconds. If your rotator takes longer than this to move (?!), then use the `--homing_timeout` parameter to set a different timeout.


To move to the starting point of the next observation for your SatNOGS station, add on the --station_id=X argument, i.e.:
```
$ python unwind.py --home_azimuth=0.0 --home_elevation=0.0 --station_id=232
```
If there is no upcoming observation, the rotator will be moved to the home location. If the observation is closer in time than the movement timeout, then the script will bomb out and not attempt to move. If your station is on network-dev, then add `--network_dev`.

By default, we assume that there is a rotctld instance running on localhost:4533. If it's running elsewhere, then the `--rotctld_host` and `--rotctld_port` options can change this. 

To run this after an observation, create a shell script in your home directory (or elsewhere) containing the above command, set it to executable (`chmod +x yourscript.sh`) and use `satnogs-setup` to define the post-observation script. Note that you might need to use an absolute path to the `unwind.py` utility. As an example, the script could be as simple as:
```
#!/usr/bin/env bash

python /home/pi/satnogs-unwinder/unwind.py --home_azimuth=0.0 --home_elevation=0.0 --station_id=232

```

Run `python unwind.py --help` to see information on all the command-line options.

## Warnings
This script is a fairly quick hack, and will bomb out if there are any errors.

It will *only* work if the rotator (via rotctld) reports *absolute* postions. Check this by manually moving your rotator into an overwind region, and request a position report by running:
```
$ nc localhost 4533
p                                         <i.e. you type in `p` and press enter here, and you will see:>
-90.000000                                <Azimuth>
0.000000                                  <Elevation>
```
If you can get a value below 0 degrees, or above 360 degrees, then this script should work. Otherwise it may not.

There are still situations it may make sense to start a pass in an overwind region, and then progress into the 'normal' region during a pass. I hope to add better support for these kinds of passes in the future.

If you add observations in between the current and next observation, this script won't be called, and as such you won't get the benefit of it. No worse than the usual behaviour though.

You may also encounter very bad behaviour if there is only a very short time between passes and your rotator takes too long to move. The `movement_timeout` argument, and the checking for close observations does help with this, but there may still be edge cases. Having two programs attempting to control one rotator is bad and may cause you to have a bad observation, or a bad day. 

As per the GPL:
```
    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
```

