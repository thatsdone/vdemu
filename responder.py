#!/usr/bin/env python3
#
# responder.py: A simple OBD responder running on Linux SocketCAN/ISOTP.
#
# License:
#   Apache License, Version 2.0
# History:
#   * 2026/08/06 v0.1 Initial version
# Author:
#   Masanori Itoh <masanori.itoh@gmail.com>
# TODO:
#   * Support DoIP
import sys
import time
import argparse

import threading
import can
import isotp
import yaml
import pprint
import logging

args = None
global logger
logger = None

import obdutil

default_pidlist = [0x01, 0x0C, 0x0D, 0x11, 0x46]

def pid_bitmap(pid):
    base_value = ((pid // 0x20) + 1) * 0x20
    return (0x1 << (0x20 - (pid % 0x20)))


# pid: 0x00, 0x20, 0x40,
# supported_pids: 0x1C, 0x1D, 0x46 etc.
def build_bitmap(base_pid=0x00, supported_pids=[]):
    bitmap = 0x00000000

    if len(supported_pids) <= 0:
        supported_pids = default_pidlist

    has_next = False
    for p in supported_pids:
        if p >= base_pid and p < base_pid + 0x20:
            bitmap |= pid_bitmap(p)
        elif p > base_pid + 0x20:
            has_next = True
            bitmap |= 0x1

    return bitmap

def get_did(rx_payload):
    return '%04X' %(int.from_bytes(rx_payload[1:3], 'big'))

def dump_message(rx_msg):

    msg = '%7s %3X [%d] %s' % (
        rx_msg.channel,
        rx_msg.arbitration_id,
        rx_msg.dlc,
        ' '.join('%02X' % rx_msg.data[idx]for idx in range(0, rx_msg.dlc))
    )
    return msg

def check_mode(isotp_payload):
    # J1979 Mode 0x01 ~ 0x0A
    if isotp_payload[0] >= 0x01 and isotp_payload[0] <= 0x0A:
        # J1979 request
        #logger.debug(f'J1979 request in {args.mode} mode')
        # J1979 req in J1979   -> GO
        # J1979 req in J1979-2 -> GO
        return 0

    elif isotp_payload[0] in [0x19, 0x22, 0x3E]:
        # J1979-2 request
        #   0x19 # Read DTC Read DTC Information
        #   0x22 # Read DID by Identifier
        #   0x3E # Tester present
        #logger.debug(f'J1979-2 request in {args.mode} mode')
        # J1979-2 req in J1979   -> Fail
        # J1979   req in J1979-2 -> GO
        if args.mode == 'J1979':
            return -1
        else:
            return 0
        return
    else:
        logger.error(f'Non supported Mode/SID): {isotp_payload[0]:02X}')
        return -1


def serve_functional(interface, channel):
    logger.debug('started.')

    bus = None
    # For Windows
    if interface == 'udp_multicast':
        bus = can.interface.Bus(interface=interface)

    else:
        bus = can.interface.Bus(interface=interface,
                                channel=channel,
                                bitrate=500000)

    bus.set_filters([{'can_id': 0x7DF,
                      'can_mask': 0x7F8,
                      'extended': False}])

    poll_timeout = args.poll_timeout
    logger.debug('set recv timeout to %d' % (poll_timeout))
    count = 0
    rx_msg = None
    try:
        while True:
            rx_msg = bus.recv(timeout=poll_timeout)
            if not rx_msg:
                # mostly timeout case.
                continue

            else:
                check_mode(rx_msg.data[1:])
            count += 1

            # adaptive busy poll
            if rx_msg and poll_timeout == args.poll_timeout:
                poll_timeout = 0.1
                logger.debug('poll_timeout: %d count: %d' %( poll_timeout, count))
                logger.debug('set recv timeout to %f' % (poll_timeout))
            if poll_timeout < args.poll_timeout and count >= 100:
                count = 0
                poll_timeout = args.poll_timeout
                logger.debug('poll_timeout: %d count: %d' % (poll_timeout, count))
                logger.debug('set recv timeout to %f' % (poll_timeout))

            if rx_msg is not None:
                logger.debug(dump_message(rx_msg))
                #
                # SID=0x22, DID=0xF810 - Protocol Identification
                if rx_msg.data[1] == 0x22 and rx_msg.data[2] == 0xF8 and rx_msg.data[3] == 0x10:
                    logger.info('Received SID=0x22, DID=0xF810 (Protocol Identification)')
                    if args.mode == 'J1979':
                        logger.info('In J1979 mode, 0x22 is ignored')
                        continue

                    res_data = [0x03,            # ISOTP Sigle Frame, length=3
                                0x22 + 0x40,     # SID=0x22 + 0x40
                                0xF8, 0x10,      # DID=0xF810
                                0x01,            # supports OBDonUDS
                                0x00, 0x00, 0x00 # padding
                                ]
                    # send resp
                    # error case NRCs
                    #   Conditions not correct  03 7f 22 31
                    #   request of range        03 0f 22 22
                    for rx_id in args.ecus:
                        msg = can.Message(
                            # Engine ECU req/res CAN ID           : 7E0/7E8
                            # Transmission ECU req/res CAN ID     : 7E1/7E9
                            # Hybrid/BEV Powrtrain req/res CAN ID : 7E2/7EA
                            arbitration_id=rx_id + 0x8,
                            data=res_data,
                            is_extended_id=False
                        )
                        bus.send(msg)

                # J1979 (Legacy OBD)
                # length=0x02, mode=0x01 PID=0x00
                #elif rx_msg.data[0] == 0x02 and rx_msg.data[1] == 0x01 and rx_msg.data[2] == 0x00:
                # note: DTCs. mode= 03, 07, 0A
                # note: rx_msg.data[0] is ISOTP control byte
                elif rx_msg.data[1] == 0x01 and (
                        rx_msg.data[2] in [0x00, 0x20, 0x40]):
                        # Theoretically PID can be 0x00, 0x20, 0x40,...,0xE0
                    logger.info('Received J1979 Mode=0x01, PID=0x00 (Supported PID List)')
                    if args.mode == 'J1979-2':
                        logger.info('Got J1979 Mode:0x01 PID:0x00 in J1979-2 mode')

                    # send resposes
                    for rx_id in args.ecus:
                        #
                        plist = vehicle_data['vehicle']['ecus'][rx_id]['data'].get(0x01)
                        bitmap = build_bitmap(rx_msg.data[2], supported_pids=plist)
                        bitmap = bytearray(bytes(bitmap.to_bytes(4, 'big')))
                        res_data = [
                            0x08,                   # ISOTP Sigle Frame, length=8
                            rx_msg.data[1] + 0x40,  # Mode=0x01 + 0x40
                            rx_msg.data[2]          # Response PID
                        ]
                        res_data += bitmap
                        res_data += [0xAA]
                        #
                        msg = can.Message(
                            arbitration_id=rx_id + 0x8,
                            data=res_data,
                            is_extended_id=False
                        )
                        bus.send(msg)
                else:
                    logger.info('Not SID=0x22/DID=0xF810(J1979-2) nor Mode=0x01/PID=0x00(J1979) to: %X',
                                0x7DF)

    except can.CanError as e:
        logger.error(f'CAN Exception: {e}')
    finally:
        bus.shutdown()


def serve_ecu(interface, channel, rx_id):
    logger.debug('%s: can_id: %X %s' % (interface, rx_id, vehicle_data['vehicle']['ecus'][rx_id]['ecu_name']))

    socket = None
    bus = None
    outil = obdutil.OBDUtil()
    outil.userland_isotp = args.userland_isotp
    socket = outil.get_isotp_socket(interface=interface,
                                    channel=channel,
                                    txid=rx_id + 0x8, rxid=rx_id)
    if interface == 'socketcan':
        socket.settimeout(10.0)

    elif interface == 'udp_multicast':
        channel = None # dummy for logging
        # TODO: set timeout

    try:
        while True:
            try:
                rx_payload = outil.recv(socket, timeout=10.0)
                if not rx_payload:
                    continue

                msg = ' '.join('%02X' % rx_payload[idx] for idx in range(0, len(rx_payload)))
                logger.info('isotp: %-7s %3X [%d] %s' % (channel, rx_id, len(rx_payload), msg))

                # check J1979/J1979-2 consistency
                action = check_mode(rx_payload)
                if action != 0:
                    # make it fail.
                    data = bytes([0x7F, rx_payload[0], 0x11])
                    socket.send(data)
                    continue

                # J1979-2 commands
                # SID  0x22 (Read DID by Identifier)
                if rx_payload[0] == 0x22:
                    if args.mode == 'J1979':
                        logger.debug('Request J1979-2 SID 0x22 in J1979 mode. Responding with NRC 0x11')
                        data = bytes([0x7F, rx_payload[0], 0x11])
                        socket.send(data)
                        continue

                    did = int('0x' + get_did(rx_payload), 16)

                    if did == 0xF802 or did == 0xF190:
                        # 0xF801 is WWH-OBD(ISO 27145), F190 UDS(ISO 14229)
                        logger.info('request to get VIN (DID: %04X)' % (did))
                        #
                        vin = vehicle_data['vehicle']['vin']
                        data = bytes([0x22 + 0x40, rx_payload[1], rx_payload[2]])+ vin.encode('utf-8')
                        socket.send(data)

                    # Hardware Humber   F187
                    # Software Number   F188
                    # SW_VERSON F189
                    elif did == 0xF189:
                        logger.info('request to get SW VERSION (DID: F189)')
                        #
                        sw_version = vehicle_data['vehicle']['ecus'][rx_id]['data'][0x22][0xF189]
                        #print(sw_version)
                        data = bytes([0x62, 0xF1, 0x89]) + sw_version.encode('utf-8')
                        socket.send(data)

                    # ECU Serial        F18C
                    # Engine code       F19E
                    # ENGINE LOAD       F404
                    elif did == 0xF404:
                        logger.info('request to get ENGINE LOAD (DID: F404)')
                        load = 45
                        load = int(load * 255 / 100) # 0 - 100%
                        data = bytes([0x22 + 0x40, 0xF8, 0x11, load])
                        socket.send(data)

                    # RPM      F40C
                    elif did == 0xF40C:
                        logger.info('request to get RPM (DID: F40C)')
                        rpm = 2345
                        high, low = divmod(4 * rpm, 256)
                        data = bytes([0x22 + 0x40, 0xF8, 0x0C, high, low])
                        socket.send(data)

                    # SPEED    F40D
                    elif did == 0xF40D:
                        logger.info('request to get SPEED (DID: F40D)')
                        speed = 75
                        data = bytes([0x22 + 0x40, 0xF8, 0x0D, speed])
                        socket.send(data)

                    # THROTTLE F411
                    elif did == 0xF411:
                        logger.info('request to get THROTTLE (DID: F411)')
                        throttle = int(64 * 255 / 100) # 0 - 100%
                        data = bytes([0x22 + 0x40, 0xF8, 0x11, throttle,
                                      0xAA, 0xAA, 0xAA])
                        socket.send(data)

                    # AMBIENT_TEMP F446
                    elif did == 0xF446:
                        logger.info('request to get AMBIENT_TEMP (DID: F446)')
                        atemp = 32 + 40 # (32 degree in celsius, 40 is offset)
                        data = bytes([0x22 + 0x40, 0xF8, 0x46, atemp,
                                      0xAA, 0xAA, 0xAA])
                        socket.send(data)

                    # ECU_NAME F80A
                    elif did == 0xF80A:
                        logger.info('request to get ECU_NAME (DID: F80A)')
                        #
                        ecu_name = vehicle_data['vehicle']['ecus'][rx_id]['ecu_name']
                        #print(ecu_name)
                        data = bytes([0x62, 0xF8, 0x0A]) + ecu_name.encode('utf-8')
                        socket.send(data)

                    else:
                        logger.warning('DID: %s not supported(yet)' % (did))
                        data = bytes([0x7F, 0x22, 0x31,
                                      0xAA, 0xAA, 0xAA, 0xAA])
                        socket.send(data)
                        # 0x12 - Sub-functionNotSupported
                        # 0x31 - RequestOutOfRange
                        # 0x13 - IncorrectMessageLengthOrInvalidFormat
                        # 0x22 - ConditionsNotCorrect
                        # 0x33 - SecurityAccessDenied

                # SID 0x19 - ReadDTCInformation
                elif rx_payload[0] == 0x19:
                    logger.debug('reportDTCByStatusMask received. SF: 0x%02X' % (rx_payload[1]))
                    # SubFunction 0x01 - ReportNumberOfDTCByStatusMask
                    if rx_payload[1] == 0x01:
                        num_dtcs = 0
                        if 0x19 in vehicle_data['vehicle']['ecus'][rx_id]['data'].keys():
                            num_dtcs = len(vehicle_data['vehicle']['ecus'][rx_id]['data'][0x19])
                        sam = 0x0F # TODO: better to set ECU specific SAM
                        data = bytes([0x19 + 0x40, 0x02, sam, 0x00]) + num_dtcs.to_bytes(2, byteorder='big')
                        socket.send(data)

                    # SubFunction 0x02 - ReportDTCByStatusMask
                    elif rx_payload[1] == 0x02:
                        # TODO: see status mask
                        dtc_list = []
                        if 0x19 in vehicle_data['vehicle']['ecus'][rx_id]['data'].keys():
                            for dtc in vehicle_data['vehicle']['ecus'][rx_id]['data'][0x19]:
                                dtc1 = dtc>>16 & 0xff
                                dtc2 = dtc>>8 & 0xff
                                dtc3 = dtc>>0 & 0xff
                                dtc_list += [dtc1, dtc2, dtc3]
                        data = bytes([0x19 + 0x40, 0x02, 0x0F]) + bytes(dtc_list)
                        socket.send(data)

                    else:
                        logger.warning('Subfunction: %02X not supported(yet)' % (rx_payload[1]))
                        data = bytes([0x7F, rx_payload[1], 0x7E])
                        socket.send(data)

                # SID 0x3E (Tester Present)
                elif rx_payload[0] == 0x3E:
                    if args.mode == 'J1979':
                        logger.debug('Request Tester present in J1979 mode. Responding with NRC 0x11')
                        data = bytes([0x7F, 0x3E, 0x11])
                        socket.send(data)
                        continue

                    # No SuppressPosRspMsgIndicationBit
                    if rx_payload[1] == 0x00:
                        logger.debug('Request Tester present with ACK. (SID: 0x3E)')
                        data = bytes([0x3E + 0x40, 0x00])
                        socket.send(data)


                # J1979 - VIN: Mode 09, PID 02
                elif  rx_payload[0] == 0x09 and rx_payload[1] == 0x02:
                    pid = 0x02
                    logger.info(f'request to get VIN (pid: {pid:02X})')

                    vin = vehicle_data['vehicle']['vin']
                    data = bytes([0x09 + 0x40, rx_payload[1]])+ vin.encode('utf-8')
                    socket.send(data)

                # J1979 - CALID(~SW VER): Mode 09, PID 04
                elif rx_payload[0] == 0x09 and rx_payload[1] == 0x04:
                    sw_version = vehicle_data['vehicle']['ecus'][rx_id]['data'][0x22][0xF189]
                    data = bytes([0x09 + 0x40, rx_payload[1]]) + sw_version.encode('utf-8')
                    socket.send(data)

                # J1979 - ECU_NAME: Mode 09, PID 0A
                elif rx_payload[0] == 0x09 and rx_payload[1] == 0x0A:
                    ecu_name = vehicle_data['vehicle']['ecus'][rx_id]['ecu_name']
                    data = bytes([0x0A + 0x40, rx_payload[1]]) + ecu_name.encode('utf-8')
                    socket.send(data)

                # J1979 - RPM: Mode 01, PID 0C
                elif rx_payload[0] == 0x01 and rx_payload[1] == 0x0C:
                    rpm = 2345
                    high, low = divmod(4 * rpm, 256)
                    data = bytes([0x01 + 0x40, 0x0C, high, low])
                    socket.send(data)

                # J1979 - SPEED: Mode 01, PID 0D
                elif rx_payload[0] == 0x01 and rx_payload[1] == 0x0D:
                    speed = 75
                    data = bytes([0x01 + 0x40, 0x0D, speed])
                    socket.send(data)

                # J1979 - THROTTLE_POS: Mode 01, PID 11
                elif rx_payload[0] == 0x01 and rx_payload[1] == 0x11:
                    throttle = int(64 * 255 / 100) # 0 - 100%
                    data = bytes([0x01 + 0x40, 0x11, throttle,
                                  0xAA, 0xAA, 0xAA, 0xAA])
                    socket.send(data)
                # J1979 - AMBIENT_TEMP: Mode 01, PID 46
                elif rx_payload[0] == 0x01 and rx_payload[1] == 0x46:
                    atemp = 32 + 40 # (32 degree in celsius, 40 is offset)
                    data = bytes([0x01 + 0x40, 0x46, atemp,
                                  0xAA, 0xAA, 0xAA, 0xAA])
                    socket.send(data)

                # J1979 - DTC Count # Mode 01 PID 0x01
                #   J1979-2 SID 0x22 SF 0x01 equivalent
                elif rx_payload[0] == 0x01 and rx_payload[1] == 0x01:
                    num_dtcs = 0
                    if 0x19 in vehicle_data['vehicle']['ecus'][rx_id]['data'].keys():
                        num_dtcs = len(vehicle_data['vehicle']['ecus'][rx_id]['data'][0x19])
                    data = bytes([0x01 + 0x40, 0x01,
                                  0x80 + num_dtcs,
                                  0x00, 0x00, 0x00, 0x00])
                    socket.send(data)

                # J1979 - get confirmed/pending/permanent DTCs:
                # Mode 0x03/0x07/0x0A
                elif rx_payload[0] == 0x03 or rx_payload[0] == 0x07 or rx_payload[0] == 0x0A:
                    # TODO: see status mask
                    dtc_list = []
                    if 0x19 in vehicle_data['vehicle']['ecus'][rx_id]['data'].keys():
                        for dtc in vehicle_data['vehicle']['ecus'][rx_id]['data'][0x19]:
                            # check mode (0x03/0x07/0x0A) and mask
                            dtc1 = dtc>>16 & 0xff
                            dtc2 = dtc>>8 & 0xff
                            #dtc3 = dtc>>0 & 0xff
                            dtc_list += [dtc1, dtc2]#, dtc3]
                    data = bytes([rx_payload[0] + 0x40]) + bytes(dtc_list)
                    socket.send(data)

                # Supported PIDs (0x00, 0x20, 0x40,...0xE0)
                elif rx_payload[0] == 0x01 and (rx_payload[1] == 0x00 or
                                                rx_payload[1] == 0x20 or
                                                rx_payload[1] == 0x40):
                    plist = vehicle_data['vehicle']['ecus'][rx_id]['data'].get(0x01)
                    bitmap = build_bitmap(rx_payload[1], supported_pids=plist)
                    bitmap = bytearray(bytes(bitmap.to_bytes(4, 'big')))
                    res_data = [
                        0x01 + 0x40,            # Mode=0x01 + 0x40
                        rx_payload[1]           # Response PID
                    ]
                    res_data += bitmap          # PID bitmap
                    res_data += [0xAA]          # padding

                    socket.send(bytes(res_data))

                # non-supported SID(J1979-2) / Mode(J1979)
                else:
                    logger.warning('SID/Mode: %02X not supported(yet)' % (rx_payload[0]))
                    data = bytes([0x7F, rx_payload[0], 0x11])
                    socket.send(data)

            except TimeoutError:
                if args.debug and args.verbose:
                    logger.debug('timeout: %s %3X' % (interface, rx_id))
                continue
    except Exception as e:
        logger.error(f'Exeption: {e}')
    finally:
        logger.debug('closing isotp socket')
        if args.can_interface == 'socketcan':
            socket.close()
        else:
            socket.shutdown()



vehicle_data = None

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='responer.py')
    parser.add_argument('-c', '--config',default='vehicle.yaml')
    parser.add_argument('--poll_timeout', type=float, default=10.0)
    parser.add_argument('-I', '--can_interface', default='socketcan')
    parser.add_argument('-C', '--can_channel', default='vcan0')
    parser.add_argument('--userland_isotp', action='store_true')
    parser.add_argument('-b', '--broadcast', default=0x7DF)
    parser.add_argument('-m', '--mode', default='J1979-2')
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ecus', nargs='*', type=lambda x: int(x, 16), default=[0x7E0, 0x7E1, 0x7E2])
    args = parser.parse_args()

    # logging
    logger = logging.getLogger('vdemu')
    log_level = 'DEBUG' if args.debug else 'INFO'
    logger.setLevel(log_level)
    logger.propagate = False
    formatter = logging.Formatter(
        fmt = '%(asctime)s.%(msecs)03d %(levelname)s: %(funcName)s: %(message)s',
        datefmt='%Y/%m/%d %H:%M:%S')
    streamHandler = logging.StreamHandler(sys.stdout)
    streamHandler.setFormatter(formatter)
    logger.addHandler(streamHandler)

    if not args.mode in ['J1979-2', 'J1979']:
        logger.error(f'Invalide mode: {args.mode}')
        sys.exit()
    else:
        logger.info(f'Running mode: {args.mode}')

    with open(args.config , 'rt') as fp:
        vehicle_data = yaml.load(fp, Loader=yaml.SafeLoader)
        logger.debug(f'Loaded {args.config}, {len(vehicle_data['vehicle']['ecus'].keys())} ECUs defined.')
        logger.debug(f'Serving {len(args.ecus)} ECUs')
    if not vehicle_data:
        sys.exit()

    if args.debug and args.verbose:
        logger.debug(pprint.pformat(vehicle_data))

    th_functional = threading.Thread(target=serve_functional,
                                     args=(args.can_interface, args.can_channel,))
    th_functional.start()

    th_unicasts = list()
    for ecu in args.ecus:
        th_unicast = threading.Thread(target=serve_ecu,
                                      args=(args.can_interface, args.can_channel, ecu, ))
        th_unicast.start()

    th_functional.join()
    for th in th_unicasts:
        th.join()
