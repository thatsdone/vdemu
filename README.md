# vdemu

## Description

vdemu is a simple Vehicle Diagnostics data EMUlator responding OBD queries.
Now J1979-2 (UDSonCAN) and J1979 (Classic OBD) are supported.
DoIP is a future work.

vdemu consists of 2 components below:

1. responder.py, diagnostics responder (currently on CAN)
2. obdutil.py, OBD access client

Supported platforms:
* Linux
  * vdemu uses Linux SocketCAN including ISOTP,
    both CAN_ISOTP enabled / disabled kernels are supported.
  * Use `--userland_isotp` for CAN_ISOTP disabled kernel.
* Windows (WSL2 environment)
  * The same with native Linux except that default WSL2 kernel does not configure VCAN.
* Windows (Non-WSL2 environment) without any CAN devices/drivers
  * Use `--can_interface udp_multicast` and `--userland_isotp`

## Usage

### responder.py - server

'responder.py' takes a configuration file optionally enablling
to define a vehicle consists of multiple ECUs.
Default filename is 'vehicle.yaml'. No need to care about `databse:` section for now.
The below options can be configured by the configuration file.

```
$ python responder.py -h
usage: responder.py [-h] [-c CONFIG] [--poll_timeout POLL_TIMEOUT]
                    [-I CAN_INTERFACE] [-C CAN_CHANNEL] [--userland_isotp]
                    [-b BROADCAST] [-m MODE] [-d] [--verbose] [--ecus [ECUS ...]]

responer.py

options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
  --poll_timeout POLL_TIMEOUT
  -I CAN_INTERFACE, --can_interface CAN_INTERFACE
  -C CAN_CHANNEL, --can_channel CAN_CHANNEL
  --userland_isotp
  -b BROADCAST, --broadcast BROADCAST
  -m MODE, --mode MODE
  -d, --debug
  --verbose
  --ecus [ECUS ...]
```

### obdutil.py - client

```
$ python obdutil.py -h
usage: obdutil.py [-h] [--poll_timeout POLL_TIMEOUT] [-I CAN_INTERFACE]
                  [-C CAN_CHANNEL] [-b BROADCAST] [-m MODE] [--scan] [-d] [-u]
                  [--verbose] [--ecus [ECUS ...]]

obdutil.py

options:
  -h, --help            show this help message and exit
  --poll_timeout POLL_TIMEOUT
  -I CAN_INTERFACE, --can_interface CAN_INTERFACE
  -C CAN_CHANNEL, --can_channel CAN_CHANNEL
  -b BROADCAST, --broadcast BROADCAST
  -m MODE, --mode MODE
  --scan
  -d, --debug
  -u, --userland_isotp
  --verbose
  --ecus [ECUS ...]
```

## License
Apache License, Version 2.0

## Author
Masanori Itoh <masanori.itoh@gmail.com>

## TODO
* Support more SIDs, DIDs, DTCs and OBD/UDS features
* Support DoIP

## References

* https://python-can.readthedocs.io/en/stable/message.html
* https://can-isotp.readthedocs.io/en/v2.0.7/index.html
* https://uds.readthedocs.io/en/stable/
* https://python-obd.readthedocs.io/en/latest/
* https://github.com/juergenH87/python-can-j1939
