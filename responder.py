#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
#   * Support J1979 (Legacy OBD)
import time
import argparse

import threading
import can
import isotp
#import obd
import yaml
import pprint

args = None

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

def serve_functional():
    if args.debug:
        print('DEBUG: serve_functional(): started.')

    bus = can.interface.Bus(interface='socketcan',
                            channel=args.interface,
                            bitrate=500000)

    bus.set_filters([{"can_id": 0x7DF,
                      "can_mask": 0x7F8,
                      "extended": False}])

    poll_timeout = args.poll_timeout
    if args.debug:
        print('DEBUG: serve_functional(): set recv timeout to %d' % (poll_timeout))
    count = 0
    rx_msg = None
    try:
        while True:
            rx_msg = bus.recv(timeout=poll_timeout)
            count += 1
            # adaptive busy poll
            if rx_msg and poll_timeout == args.poll_timeout:
                poll_timeout = 0.1
                if args.debug:
                    print('DEBUG: poll_timeout: %d count: %d' %( poll_timeout, count))
                    print('DEBUG: set recv timeout to %f' % (poll_timeout))
            if poll_timeout < args.poll_timeout and count >= 100:
                count = 0
                poll_timeout = args.poll_timeout
                if args.debug:
                    print('DEBUG: poll_timeout: %d count: %d' % (poll_timeout, count))
                    print('DEBUG: set recv timeout to %f' % (poll_timeout))

            if rx_msg is not None:
                if args.debug:
                    print(dump_message(rx_msg))
                #
                # SID=0x22, DID=0xF810 - Protocol Identification
                if rx_msg.data[1] == 0x22 and rx_msg.data[2] == 0xF8 and rx_msg.data[3] == 0x10:
                #if rx_msg.data[1] == 0x22 and rx_msg.data[2:3] == 0xF810:
                    print('Received SID=0x22, DID=0xF810 (Protocol Identification)')
                    res_data = [0x03,            # ISOTP Sigle Frame, length=2
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

                else:
                    print('Not SID=0x22/DID=0xF810 of J1979-2 to: %X', 0x7DF)

    except can.CanError as e:
        print(f"CAN Exception: {e}")
    finally:
        bus.shutdown()


def serve_ecu(interface, rx_id):
    if args.debug:
        print('DEBUG: serve_ecu(): %s: can_id: %X' % (interface, rx_id), vehicle_data['vehicle']['ecus'][rx_id]['ecu_name'])

    socket = isotp.socket()
    socket.bind(interface, isotp.Address(rxid=rx_id, txid=rx_id + 0x8))

    socket.settimeout(10.0)
    try:
        while True:
            try:
                rx_payload = socket.recv()
                msg = ' '.join('%02X' % rx_payload[idx]for idx in range(0, len(rx_payload)))

                print('%7s %3X [%d] %s (isotp)' % (interface, rx_id, len(msg), msg))
                # SID  0x22 (Read DID by Identifier)
                if rx_payload[0] == 0x22:
                    did = int('0x' + get_did(rx_payload), 16)
                    #print('DEBUG: did: %04X' % (did))
                    if did == 0xF802 or did == 0xF190:
                        # 0xF801 is WWH-OBD(ISO 27145), F190 UDS(ISO 14229)
                        print('request to get VIN (DID: %04X)' % (did))
                        #
                        vin = vehicle_data['vehicle']['vin']
                        data = bytes([0x22 + 0x40, rx_payload[1], rx_payload[2]])+ vin.encode('utf-8')
                        socket.send(data)

                    # Hardware Humber   F187
                    # Software Number   F188
                    # SW_VERSON F189
                    elif did == 0xF189:
                        print('request to get SW VERSION (DID: F189)')
                        #
                        sw_version = vehicle_data['vehicle']['ecus'][rx_id]['data'][0x22][0xF189]
                        #print(sw_version)
                        data = bytes([0x62, 0xF1, 0x89]) + sw_version.encode('utf-8')
                        socket.send(data)

                    # ECU Serial        F18C
                    # Engine code       F19E
                    # ENGINE LOAD       F404
                    elif did == 0xF404:
                        print('request to get ENGINE LOAD (DID: F404)')
                        load = 45
                        load = int(load * 255 / 100) # 0 - 100%
                        data = bytes([0x22 + 0x40, 0xF8, 0x11, load])
                        socket.send(data)

                    # RPM      F40C
                    elif did == 0xF40C:
                        print('request to get RPM (DID: F40C)')
                        rpm = 2345
                        high, low = divmod(4 * rpm, 256)
                        data = bytes([0x22 + 0x40, 0xF8, 0x0C, high, low])
                        socket.send(data)

                    # SPEED    F40D
                    elif did == 0xF40D:
                        print('request to get SPEED (DID: F40D)')
                        speed = 75
                        data = bytes([0x22 + 0x40, 0xF8, 0x0D, speed])
                        socket.send(data)

                    # THROTTLE F411
                    elif did == 0xF411:
                        print('request to get THROTTLE (DID: F411)')
                        throttle = int(64 * 255 / 100) # 0 - 100%
                        data = bytes([0x22 + 0x40, 0xF8, 0x11, throttle,
                                      0xAA, 0xAA, 0xAA])
                        socket.send(data)

                    # AMBIENT_TEMP F446
                    elif did == 0xF446:
                        print('request to get AMBIENT_TEMP (DID: F446)')
                        atemp = 32
                        data = bytes([0x22 + 0x40, 0xF8, 0x46, atemp,
                                      0xAA, 0xAA, 0xAA])
                        socket.send(data)

                    # ECU_NAME F80A
                    elif did == 0xF80A:
                        print('request to get ECU_NAME (DID: F80A)')
                        #
                        ecu_name = vehicle_data['vehicle']['ecus'][rx_id]['ecu_name']
                        #print(ecu_name)
                        data = bytes([0x62, 0xF8, 0x0A]) + ecu_name.encode('utf-8')
                        socket.send(data)

                    else:
                        print('DID: %s not supported(yet)' % (did))
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
                    if args.debug:
                        print('DEGUG: reportDTCByStatusMask received. SF: 0x%02X' % (rx_payload[1]))
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
                        print('Subfunction: %02X not supported(yet)' % (rx_payload[1]))
                        data = bytes([0x7F, rx_payload[1], 0x7E])
                        socket.send(data)

                # SID 0x3E (Tester Present)
                elif rx_payload[0] == 0x3E:
                    # No SuppressPosRspMsgIndicationBit
                    if rx_payload[1] == 0x00:
                        if args.debug:
                            print('Request Tester present with ACK. (SID: 0x3E)')
                        data = bytes([0x3E + 0x40, 0x00])
                        socket.send(data)

                # non-supported SID
                else:
                    print('SID: %02X not supported(yet)' % (rx_payload[0]))
                    data = bytes([0x7F, rx_payload[0], 0x11])
                    socket.send(data)

            except TimeoutError:
                if args.debug and args.verbose:
                    print(time.time(), 'timeout: %s %3X' % (interface, rx_id))
                continue
    except Exception as e:
        print('Exeption: ', e)
    finally:
        print('DEBUG: closing isotp socket')
        socket.close()



vehicle_data = None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="responer.py")
    parser.add_argument("--poll_timeout", type=float, default=10.0)
    parser.add_argument("-i", "--interface", default='vcan0')
    parser.add_argument("-b", "--broadcast", default=0x7DF)
    parser.add_argument("-m", "--mode", default='J1979-2')
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ecus", nargs='*', type=lambda x: int(x, 16), default=[0x7E0, 0x7E1, 0x7E2])
    args = parser.parse_args()

    with open('vehicle.yaml', 'rt') as fp:
        vehicle_data = yaml.load(fp, Loader=yaml.SafeLoader)
    if not vehicle_data:
        sys.exit()
    # DEBUG
    if args.debug and args.verbose:
        pprint.pprint(vehicle_data)

    th_functional = threading.Thread(target=serve_functional, args=())
    th_functional.start()

    th_unicasts = list()
    for ecu in args.ecus:
        th_unicast = threading.Thread(target=serve_ecu,
                                      args=(args.interface, ecu, ))
        th_unicast.start()

    th_functional.join()
    for th in th_unicasts:
        th.join()
