# vdemu

## Description

vdemu is a simple Vehicle Diagnostics data EMUlator responding OBD queries.
Now only J1979-2 (on CAN) is supported. DoIP and J1979(legacy OBD) are
future works.

vdemu consists of 2 components below:

1. responder.py, diagnostics responder (currently on CAN)
2. obdonuds.py, OBD access client


## Usage

'responder.py' takes a configuration file which enables to define
a vehicle consists of multiple ECUs.

### responder.py - server

```
$ python3 responder.py -h
usage: responder.py [-h] [--poll_timeout POLL_TIMEOUT] [-i INTERFACE]
                    [-b BROADCAST] [-m MODE] [-d] [--verbose]
                    [--ecus [ECUS ...]]

responer.py

options:
  -h, --help            show this help message and exit
  --poll_timeout POLL_TIMEOUT
  -i INTERFACE, --interface INTERFACE
  -b BROADCAST, --broadcast BROADCAST
  -m MODE, --mode MODE
  -d, --debug
  --verbose
  --ecus [ECUS ...]
```

### obdonuds.py - client

```
$ python3 obdonuds.py -h
usage: obdonuds.py [-h] [--poll_timeout POLL_TIMEOUT] [-i INTERFACE]
                   [-b BROADCAST] [-m MODE] [--scan] [-d]
                   [--ecus [ECUS ...]]

obdonuds.py

options:
  -h, --help            show this help message and exit
  --poll_timeout POLL_TIMEOUT
  -i INTERFACE, --interface INTERFACE
  -b BROADCAST, --broadcast BROADCAST
  -m MODE, --mode MODE
  --scan
  -d, --debug
  --ecus [ECUS ...]
```

## License
Apache License, Version 2.0

## Author
Masanori Itoh <masanori.itoh@gmail.com>

## TODO
* Update this README.md
* Support more SIDs, DIDs, DTCs and OBD/UDS features
* Support J1979 (Legacy OBD) (DTC handling improvement)
* Support DoIP

## References

* https://python-can.readthedocs.io/en/stable/message.html
* https://can-isotp.readthedocs.io/en/v2.0.7/index.html
* https://uds.readthedocs.io/en/stable/
* https://python-obd.readthedocs.io/en/latest/
* https://github.com/juergenH87/python-can-j1939
