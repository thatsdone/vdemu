#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
#   * Support J1979 (Legacy OBD)
import time
import argparse
import logging
import threading

import can
import isotp
#import obd

global verbose
verbose = False


class OBDUtil():

    scan_timeout = 2.0
    busy_poll_timeout = 0.1
    detected_ecus = {}
    #logger = None

    def __init__(self):
        self.logger = logging.getLogger()#__name__) #'OBDUtil')
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
    #
    #
    #
    def scan_obd_protocol(self, interface=None):
        self.logger.debug('scan_obd_protocol() called. %s' % (interface))
        bus = can.interface.Bus(interface='socketcan',
                            channel=interface, bitrate=500000)
        bus.set_filters([{"can_id": 0x7E8, "can_mask": 0x7F8,
                          "extended": False}])
        # J1979-2 (OBD on UDS) can be checked
        # if SID=0x22, DID=0xF810 (Protocol Identification) supported
        # Use single frame of ISO-TP
        req_data = [0x03, 0x22, 0xF8, 0x10] #, 0x00, 0x00, 0x00, 0x00]
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

            #print(f'DEBUG: Received {len(captured_responses)} messages')

            j1979_2_detected = False
            self.detected_ecus = []

            for rx in captured_responses:
                data_str = ' '.join(f'{b:02X}' for b in rx.data)
                #print(f"  [Receive] ID: 0x{rx.arbitration_id:03X} | Data: {data_str}")
                # Record CAN ID of responded ECUs (dedupe)
                if rx.arbitration_id not in self.detected_ecus:
                    self.detected_ecus.append(rx.arbitration_id)

                # Check positive responses (top 0x04 means data length(4bytes),
                # 0x22 means successful response, 0xF810 is DID)
                if len(rx.data) >= 5 and rx.data[1] == 0x62 and rx.data[2] == 0xF8 and rx.data[3] == 0x10:
                    j1979_2_detected = True
                    version = rx.data[4]
                    #print(f"Detected a positive response of J1979-2 (OBD on UDS) (Version: 0x{version:02X})")

            # 6. Show Summary
            #print(f"Response ID of detected ECU: {[f'0x{ecu:03X}' for ecu in sorted(detected_ecus)]}")

        except can.CanError as cane:
            print(f"ERROR: CAN Communication Errror: {cane}")
        except Exception as e:
            print(f"ERROR: Exception: {e}")

        finally:
            bus.shutdown()
            return captured_responses

    def send_tester_present(self, socket):
        rx_payload = None
        try:
            # send Tester Present with response request
            socket.send(bytes([0x3E, 0x00]))
            rx_payload = socket.recv()
            #print(self.dump_msg(rx_payload), '/', 'Tester Present Positive Response')
        except TimeoutError:
            #if verbose:
            print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
        return rx_payload

    def send_get_vin(self, socket, parse=False):
        rx_payload = None
        try:
            # get VIN / 03 22 F8 02
            socket.send(bytes([0x22, 0xF8, 0x02]))
            rx_payload = socket.recv()
            #print(self.dump_msg(rx_payload), '/', rx_payload[3:].decode('utf-8'))
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
                print(type(rx_payload), rx_payload)

        #return rx_payload[3:].decode('utf-8')
        if parse:
            return rx_payload[3:].decode('utf-8')
        else:
            return rx_payload

    def send_get_ecu_name(self, socket, parse=False):
        rx_payload = None
        try:
            # get VIN / 03 22 F8 0A
            socket.send(bytes([0x22, 0xF8, 0x0A]))
            rx_payload = socket.recv()
            if verbose:
                print(self.dump_msg(rx_payload), '/', rx_payload[3:].decode('utf-8'))
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
        #print(type(rx_payload), rx_payload)
        if parse:
            return rx_payload[3:].decode('utf-8')
        else:
            return rx_payload
            

    def send_get_sw_version(self, socket, parse=False):
        rx_payload = None
        try:
            socket.send(bytes([0x22, 0xF1, 0x89]))
            rx_payload = socket.recv()
            if verbose:
                print(self.dump_msg(rx_payload), '/', rx_payload[3:].decode('utf-8'))
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
                print(type(rx_payload), rx_payload)
        if parse:
            return rx_payload[3:].decode('utf-8')
        else:
            return rx_payload

    def send_get_rpm(self, socket):
        rx_payload = None
        try:
            # get RPM  F40C
            socket.send(bytes([0x22, 0xF4, 0x0C]))
            rx_payload = socket.recv()
            if verbose:
                print(self.dump_msg(rx_payload), '/', (rx_payload[3] * 256 + rx_payload[4])/4)
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
        return rx_payload #(rx_payload[3] * 256 + rx_payload[4])/4

    def send_get_speed(self, socket):
        rx_payload = None
        try:
            # get SPEED  F40D
            socket.send(bytes([0x22, 0xF4, 0x0D]))
            rx_payload = socket.recv()
            if verbose:
                print(self.dump_msg(rx_payload), '/', rx_payload[3])
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
        #print(type(rx_payload), rx_payload)
        return rx_payload

    def send_get_throttle(self, socket):
        rx_payload = None
        try:
            # get THROTTLE_POS  F411
            socket.send(bytes([0x22, 0xF4, 0x11]))
            rx_payload = socket.recv()
            if verbose:
                print(self.dump_msg(rx_payload), '/', rx_payload[3] * 100 / 255)
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
        #print(type(rx_payload), rx_payload)
        return rx_payload

    def send_get_ambient_temp(self, socket):
        rx_payload = None
        try:
            # get AMBIENT_TEMP  F446
            socket.send(bytes([0x22, 0xF4, 0x46]))
            rx_payload = socket.recv()
            if verbose:
                print(self.dump_msg(rx_payload), '/', rx_payload[3])
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
                print(type(rx_payload), rx_payload)
        return rx_payload

    def send_get_all_dtcs(self, socket, parse=False):
        rx_payload = None
        try:
            # 7E0  8  03 19 02 0F 00 00 00 00 (SID: 19, SF: 02, mask: 0F)
            #   02: reportDTCByStatusMask
            socket.send(bytes([0x19, 0x02, 0x0F]))
            rx_payload = socket.recv()
            #print(self.dump_msg(rx_payload), '/', '%d DTCs' % (len(rx_payload[3:]) / 3))
            count = int(len(rx_payload[3:]) / 3)
            dtcs = list()
            offset = 3
            for i in range(0, count):
                dtcs.append(int.from_bytes(rx_payload[offset+i*3:offset+(i*3)+3], 'big'))
            if parse:
                return dtcs
            else:
                return rx_payload
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
        #print(type(rx_payload), rx_payload)
        return rx_payload

    def send_get_dtc_count(self, socket):
        rx_payload = None
        try:
            socket.send(bytes([0x19, 0x01, 0x0F]))
            rx_payload = socket.recv()
            # NOTE: rx_payload[4:6] means byte 4 and 5.
            if verbose:
                print(self.dump_msg(rx_payload), '/', '%d DTCs' % (int.from_bytes(rx_payload[4:6], byteorder='big')))
        except TimeoutError:
            if verbose:
                print(time.time(), 'timeout: %s %3X' % (args.interface, rx_id))
        return rx_payload #int.from_bytes(rx_payload[4:6], byteorder='big')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="obdutil.py")
    parser.add_argument("--poll_timeout", type=float, default=0.1)
    parser.add_argument("-i", "--interface", default='vcan0')
    parser.add_argument("-b", "--broadcast", default=0x7DF)
    parser.add_argument("-m", "--mode", default='J1979-2')
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ecus", nargs='*', type=lambda x: int(x, 16), default=[0x7E0, 0x7E1, 0x7E2])
    args = parser.parse_args()

    verbose = args.verbose

    obdutil = OBDUtil()

    if args.scan:
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
    tester_present = obdutil.send_tester_present(socket)
    print('TESTER_PRESENT:', obdutil.dump_msg(tester_present))
    #
    # 0x22, 0xF8, 0x02
    vin = obdutil.send_get_vin(socket, parse=True)
    print('VIN:', vin)

    ecu_name = obdutil.send_get_ecu_name(socket, parse=True)
    print('ECU_NAME:', ecu_name)
    sw_version = obdutil.send_get_sw_version(socket, parse=True)
    print('SW_VERSION:', sw_version)#[3:].decode('utf-8'))
    rpm = obdutil.send_get_rpm(socket)
    print('RPM:', (rpm[3] * 256 + rpm[4])/4)
    speed = obdutil.send_get_speed(socket)
    print('SPEED:', speed[3])# * 100 / 255) #speed)
    throttle = obdutil.send_get_throttle(socket)
    print('THROTTLE_POS:', throttle[3] * 100 / 255)
    ambient_temp = obdutil.send_get_ambient_temp(socket)
    print('AMBIENT_TEMP:', ambient_temp[3])
    dtc_count = obdutil.send_get_dtc_count(socket)
    print('DTC count:', int.from_bytes(dtc_count[4:6], byteorder='big'))
    obdutil.send_get_dtc_count(socket)
    all_dtcs = obdutil.send_get_all_dtcs(socket)
    print('ALL DTCs:', obdutil.dump_msg(all_dtcs))
    print('')

    for canid in args.ecus[1:]:
        print('Checking...: %03X' % (canid))
        s = obdutil.get_isotp_socket(interface=args.interface,
                                     txid=canid, rxid=canid + 0x8)
        ecu_name = obdutil.send_get_ecu_name(s, parse=True)
        print('ECU_NAME:', ecu_name)
        sw_version = obdutil.send_get_sw_version(s, parse=True)
        print('SW_VERSION:', sw_version)#[3:].decode('utf-8')) #sw_version)
        dtc_count = obdutil.send_get_dtc_count(s)
        print('DTC count:', int.from_bytes(dtc_count[4:6], byteorder='big'))
        all_dtcs = obdutil.send_get_all_dtcs(s)
        print('ALL DTCs:', obdutil.dump_msg(all_dtcs))
        print('')
        s.close()

    socket.close()
