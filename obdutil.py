#!/usr/bin/env python3
#
# obdonuds.py: A simple OBD client tool
#
# License:
#   Apache License, Version 2.0
# History:
#   * 2026/08/18 v0.2 rename from obdonuds.py and blush up
# Author:
#   Masanori Itoh <masanori.itoh@gmail.com>
# TODO:
#   * Support DoIP
import sys
import time
import argparse
import logging
import threading

import can
import isotp

class OBDUtil():

    scan_timeout = 2.0
    busy_poll_timeout = 0.1
    detected_ecus = {}

    verbose = False
    mode = 'J1979'

    def __init__(self):
        self.logger = logging.getLogger()
        pass

    # utility routines
    def dump_msg(self, rx_payload):
        msg = ' '.join('%02X' % rx_payload[idx]for idx in range(0, len(rx_payload)))
        return msg

    def get_did(self, rx_payload):
        return '%04X' %(int.from_bytes(rx_payload[1:3], 'big'))

    def get_isotp_socket(self, interface=None, txid=None, rxid=None):
        socket = isotp.socket()
        tx_id = txid
        if not rxid:
            rx_id = txid + 0x8
        else:
            rx_id = rxid
        socket.bind(interface, isotp.Address(rxid=rx_id, txid=tx_id))
        return socket

    # OBD routines
    def scan_obd_protocol(self, interface=None):
        self.logger.debug('scan_obd_protocol() called. %s' % (interface))
        bus = can.interface.Bus(interface='socketcan',
                            channel=interface, bitrate=500000)
        bus.set_filters([{'can_id': 0x7E8, 'can_mask': 0x7F8,
                          'extended': False}])
        req_data = []
        if self.mode == 'J1979-2':
            # J1979-2 (OBD on UDS) can be checked
            # if SID=0x22, DID=0xF810 (Protocol Identification) supported
            # Use single frame of ISO-TP
            req_data = [0x03, 0x22, 0xF8, 0x10,
                        0x00, 0x00, 0x00, 0x00]
        elif self.mode == 'J1979':
            # J1979  Mode 0x01 PID=00 with zero pading
            req_data = [0x02, 0x01,
                        0x00, 0x00, 0x00, 0x00, 0x00, 0x00]

        msg = can.Message(
            arbitration_id=0x7DF,
            data=req_data,
            is_extended_id=False
        )

        captured_responses = []
        try:
            # Send a single CAN message to '0x7DF'
            bus.send(msg)

            start_time = time.time()
            while (time.time() - start_time) < self.scan_timeout:
                # busy poll using timeout default is 0.1s
                rx_msg = bus.recv(timeout=self.busy_poll_timeout)
                if rx_msg is not None:
                    captured_responses.append(rx_msg)
            if self.verbose:
                print(f'DEBUG: Received {len(captured_responses)} messages')

            j1979_2_detected = False
            self.detected_ecus = []

            for rx in captured_responses:
                data_str = ' '.join(f'{b:02X}' for b in rx.data)
                if self.verbose:
                    print(f'  [Receive] ID: 0x{rx.arbitration_id:03X} | Data: {data_str}')
                # Record CAN ID of responded ECUs (dedupe)
                if rx.arbitration_id not in self.detected_ecus:
                    self.detected_ecus.append(rx.arbitration_id)

                # Check positive responses (top 0x04 means data length(4bytes),
                # 0x22 means successful response, 0xF810 is DID)
                if len(rx.data) >= 5 and rx.data[1] == 0x62 and rx.data[2] == 0xF8 and rx.data[3] == 0x10:
                    j1979_2_detected = True
                    version = rx.data[4]
                    if self.verbose:
                        print(f'Detected a positive response of J1979-2 (OBD on UDS) (Version: 0x{version:02X})')

            if self.verbose:
                print(f'Response ID of detected ECU: {[f'0x{ecu:03X}' for ecu in sorted(self.detected_ecus)]}')

        except can.CanError as cane:
            print(f'ERROR: CAN Communication Errror: {cane}')
        except Exception as e:
            print(f'ERROR: Exception: {e}')

        finally:
            bus.shutdown()
            return captured_responses

    def send_tester_present(self, socket):
        rx_payload = None
        try:
            # send Tester Present with response request
            socket.send(bytes([0x3E, 0x00]))
            rx_payload = socket.recv()
            if self.verbose:
                print(self.dump_msg(rx_payload), '/', 'Tester Present Positive Response')
        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
        return rx_payload

    def send_get_vin(self, socket, parse=False):
        rx_payload = None
        # get VIN / 03 22 F8 02
        data = [0x22, 0xF8, 0x02]  # or 0xF190
        if self.mode == 'J1979':
            data = [0x09, 0x02]
        try:
            socket.send(bytes(data))
            rx_payload = socket.recv()
            if self.verbose:
                print(self.dump_msg(rx_payload), '/', rx_payload[3:].decode('utf-8'))
        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
                print(type(rx_payload), rx_payload)
            return None

        if parse:
            if self.mode == 'J1979-2':
                return rx_payload[3:].decode('utf-8')
            else:
                return rx_payload[2:].decode('utf-8')
        else:
            return rx_payload

    def send_get_ecu_name(self, socket, parse=False):
        rx_payload = None
        # get ECU_NAME / 03 22 F8 0A
        data = [0x22, 0xF8, 0x0A]
        if self.mode == 'J1979':
            data = [0x09, 0x0A]
        try:
            socket.send(bytes(data))
            rx_payload = socket.recv()
            if self.verbose:
                if self.mode == 'J1979-2':
                    print(self.dump_msg(rx_payload), '/', rx_payload[3:].decode('utf-8'))
                else:
                    print(self.dump_msg(rx_payload), '/', rx_payload[2:].decode('utf-8'))

        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
            return None

        if parse:
            if self.mode == 'J1979-2':
                return rx_payload[3:].decode('utf-8')
            else:
                return rx_payload[2:].decode('utf-8')
        else:
            return rx_payload

    def send_get_sw_version(self, socket, parse=False):
        rx_payload = None
        data = [0x22, 0xF1, 0x89]
        if self.mode == 'J1979':
            data = [0x09, 0x04]
        try:
            socket.send(bytes(data))
            rx_payload = socket.recv()
            if self.verbose:
                if self.mode == 'J1979-2':
                    print(self.dump_msg(rx_payload), '/', rx_payload[3:].decode('utf-8'))
                else:
                    print(self.dump_msg(rx_payload), '/', rx_payload[2:].decode('utf-8'))
        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
                print(type(rx_payload), rx_payload)
            return None

        if parse:
            if self.mode == 'J1979-2':
                return rx_payload[3:].decode('utf-8')
            else:
                return rx_payload[2:].decode('utf-8')
        else:
            return rx_payload

    def send_get_rpm(self, socket):
        rx_payload = None
        try:
            # get RPM  F40C
            if self.mode == 'J1979-2':
                socket.send(bytes([0x22, 0xF4, 0x0C]))
            else:
                socket.send(bytes([0x01, 0x0C]))
            rx_payload = socket.recv()
            if self.verbose:
                if self.mode == 'J1979-2':
                    print(self.dump_msg(rx_payload), '/', (rx_payload[3] * 256 + rx_payload[4])/4)
                else:
                    print(self.dump_msg(rx_payload), '/', (rx_payload[2] * 256 + rx_payload[3])/4)

        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
            return None

        return rx_payload

    def send_get_speed(self, socket):
        rx_payload = None
        try:
            # get SPEED  F40D
            if self.mode == 'J1979-2':
                socket.send(bytes([0x22, 0xF4, 0x0D]))
            else:
                socket.send(bytes([0x01, 0x0D]))

            rx_payload = socket.recv()
            if self.verbose:
                if self.mode == 'J1979-2':
                    print(self.dump_msg(rx_payload), '/', rx_payload[3])
                else:
                    print(self.dump_msg(rx_payload), '/', rx_payload[2])

        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
            return None

        return rx_payload

    def send_get_throttle(self, socket):
        rx_payload = None
        try:
            # get THROTTLE_POS  F411
            if self.mode == 'J1979-2':
                socket.send(bytes([0x22, 0xF4, 0x11]))
            else:
                socket.send(bytes([0x01, 0x11]))

            rx_payload = socket.recv()
            if self.verbose:
                print(self.dump_msg(rx_payload), '/', rx_payload[3] * 100 / 255)
        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
            return None

        return rx_payload

    def send_get_ambient_temp(self, socket):
        rx_payload = None
        try:
            # get AMBIENT_TEMP  F446
            if self.mode == 'J1979-2':
                socket.send(bytes([0x22, 0xF4, 0x46]))
            else:
                socket.send(bytes([0x01, 0x46]))

            rx_payload = socket.recv()
            if self.verbose:
                if self.mode == 'J1979-2':
                    print(self.dump_msg(rx_payload), '/', rx_payload[3])
                else:
                    print(self.dump_msg(rx_payload), '/', rx_payload[2])
        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
            return None

        return rx_payload

    def send_get_all_dtcs(self, socket, parse=False):
        rx_payload = None
        try:
            if self.mode == 'J1979-2':
                # 7E0  8  03 19 02 0F 00 00 00 00 (SID: 19, SF: 02, mask: 0F)
                #   02: reportDTCByStatusMask
                socket.send(bytes([0x19, 0x02, 0xFF]))
                rx_payload = socket.recv()
            else:
                # Need to use 3 Modes (0x03, 0x07, 0x0A)
                rx3 = None
                # UDS Confirmed DTC equivalent
                socket.send(bytes([0x03,
                                   0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
                rx3 = socket.recv()
                return rx3

                # TODO: process response
                # UDS Pending DTC equivalent
                #rx7 = None
                #socket.send(bytes([0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
                #rx7 = socket.recv()
                # TODO: process response

                # UDS Permanent DTC equivalent
                #rxa = None
                #socket.send(bytes([0x0A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
                #rxa = socket.recv()
                # TODO: process response

            if self.verbose:
                if self.mode == 'J1979-2':
                    print(self.dump_msg(rx_payload), '/', '%d DTCs' % (len(rx_payload[3:]) / 3))

            if parse:
                count = int(len(rx_payload[3:]) / 3)
                dtcs = list()
                offset = 3
                for i in range(0, count):
                    dtcs.append(int.from_bytes(rx_payload[offset+i*3:offset+(i*3)+3], 'big'))
                return dtcs

        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
                print(type(rx_payload), rx_payload)
            return None

        return rx_payload

    def send_get_dtc_count(self, socket):
        rx_payload = None
        try:
            if self.mode == 'J1979-2':
                socket.send(bytes([0x19, 0x01, 0xFF]))
                rx_payload = socket.recv()
            else:
                # mode: 01 pid: 01 returns number of confirmed dtcs and MIL
                #socket.send(bytes([0x01, 0x01]))
                #
                # J1979 - get confirmed/pending/permanent DTCs:
                # Mode 0x03/0x07/0x0A
                socket.send(bytes([0x03]))
                rx_3 = socket.recv()
                if self.verbose:
                    print('0x03: ', len(rx_3[1:])/2)
                #socket.send(bytes([0x07]))
                rx_7 = bytes([]) #socket.recv()
                if self.verbose:
                    print('0x07: ', len(rx_7[1:])/2)
                #socket.send(bytes([0x0A]))
                rx_a = bytes([])#socket.recv()
                if self.verbose:
                    print('0x0a: ', len(rx_a[1:])/2)
                num_dtcs = int((len(rx_3[1:]) + len(rx_7[1:])+ len(rx_a[1:]))/2)
                # TODO: Fix this quick hack below.
                return bytes([0x03, 0x00, num_dtcs])
            # NOTE: rx_payload[4:6] means byte 4 and 5.
            if self.verbose:
                if self.mode == 'J1979-2':
                    print(self.dump_msg(rx_payload), '/', '%d DTCs' % (int.from_bytes(rx_payload[4:6], byteorder='big')))
        except TimeoutError:
            if self.verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
            return None

        return rx_payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='obdutil.py')
    parser.add_argument('--poll_timeout', type=float, default=0.1)
    parser.add_argument('-i', '--interface', default='vcan0')
    parser.add_argument('-b', '--broadcast', default=0x7DF)
    parser.add_argument('-m', '--mode', default='J1979-2')
    parser.add_argument('--scan', action='store_true')
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ecus', nargs='*', type=lambda x: int(x, 16), default=[0x7E0, 0x7E1, 0x7E2])
    args = parser.parse_args()

    obdutil = OBDUtil()
    obdutil.verbose = args.verbose

    if not args.mode in ['J1979-2', 'J1979']:
        print(f'Invalide mode: {args.mode}')
        sys.exit()
    else:
        obdutil.mode = args.mode
        print(f'Running mode: {args.mode}')

    if args.scan:
        import sys
        print('Checking...: %03X' % (0x7DF))
        captured_responses = obdutil.scan_obd_protocol(args.interface)
        for resp in captured_responses:
            print('Detected: CANID: %03X' % (resp.arbitration_id - 0x8))
        print('')

    socket = isotp.socket()
    tx_id = 0x7E0
    rx_id = tx_id + 0x8
    socket.bind(args.interface, isotp.Address(rxid=rx_id, txid=tx_id))
    #
    socket.settimeout(10.0)
    #
    print('Checking...: %03X' % (tx_id))
    # 0x02, 0x7E, 0x00
    if args.mode == 'J1979-2':
        tester_present = obdutil.send_tester_present(socket)
        print('TESTER_PRESENT:', obdutil.dump_msg(tester_present))

    # 0x22, 0xF8, 0x02
    vin = obdutil.send_get_vin(socket, parse=True)
    print('VIN:', vin)

    ecu_name = obdutil.send_get_ecu_name(socket, parse=True)
    print('ECU_NAME:', ecu_name)
    sw_version = obdutil.send_get_sw_version(socket, parse=True)
    print('SW_VERSION:', sw_version)
    rpm = obdutil.send_get_rpm(socket)
    print('RPM(dump):', obdutil.dump_msg(rpm))
    if rpm[0] != 0x7F:
        idx = 3  if args.mode == 'J1979-2' else 2
        print('RPM:', (rpm[idx] * 256 + rpm[idx+1])/4)
    speed = obdutil.send_get_speed(socket)
    print('SPEED(dump):', obdutil.dump_msg(speed))
    if speed[0] != 0x7F:
        idx = 3  if args.mode == 'J1979-2' else 2
        print('SPEED:', speed[idx])
    throttle = obdutil.send_get_throttle(socket)
    print('THROTTLE_POS(dump):', obdutil.dump_msg(throttle))
    if rpm[0] != 0x7F:
        idx = 3  if args.mode == 'J1979-2' else 2
        print('THROTTLE_POS:', throttle[idx] * 100 / 255)
    ambient_temp = obdutil.send_get_ambient_temp(socket)
    print('AMBIENT_TEMP(dump):', obdutil.dump_msg(ambient_temp))
    if ambient_temp[0] != 0x7F:
        idx = 3 if args.mode == 'J1979-2' else 2
        print('AMBIENT_TEMP:', ambient_temp[idx] - 40)
    dtc_count = obdutil.send_get_dtc_count(socket)
    print('DTC count(all)(dump):', obdutil.dump_msg(dtc_count))
    if dtc_count[0] != 0x7F:
        if args.mode == 'J1979':
            print('DTC count(all):', dtc_count[2] & 0x7f)
        else:
            print('DTC count(all):', dtc_count[5] & 0x7f)
    all_dtcs = obdutil.send_get_all_dtcs(socket)
    print('ALL DTCs(dump):', obdutil.dump_msg(all_dtcs))
    print('')

    for canid in args.ecus[1:]:
        print('Checking...: %03X' % (canid))
        s = obdutil.get_isotp_socket(interface=args.interface,
                                     txid=canid, rxid=canid + 0x8)
        ecu_name = obdutil.send_get_ecu_name(s, parse=True)
        print('ECU_NAME:', ecu_name)
        sw_version = obdutil.send_get_sw_version(s, parse=True)
        print('SW_VERSION:', sw_version)
        dtc_count = obdutil.send_get_dtc_count(s)
        print('DTC count(all)(dump):', obdutil.dump_msg(dtc_count))
        if dtc_count[0] != 0x7F:
            if args.mode == 'J1979':
                print('DTC count(all):', dtc_count[2] & 0x7f)
            else:
                print('DTC count(all):', dtc_count[5] & 0x7f)
        all_dtcs = obdutil.send_get_all_dtcs(s)
        print('ALL DTCs(dump):', obdutil.dump_msg(all_dtcs))
        print('')
        s.close()

    socket.close()
