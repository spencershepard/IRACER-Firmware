#!/usr/bin/python

import smbus
import socket
import select
import os
import pigpio
import time
import thread
import subprocess
import pickle

pi = pigpio.pi()

bus = smbus.SMBus(1)
bus.write_byte_data(0x44, 0x01, 0x15)
time.sleep(1.5)

global send_string
send_string = ""

global color_triggers
global ratio_tolerance
global sum_tolerance
ratio_tolerance = 0.03  # 0.04-0.13
sum_tolerance = 300  # 100-510


def translate(value, leftMin, leftMax, rightMin, rightMax):
    leftSpan = leftMax - leftMin
    rightSpan = rightMax - rightMin
    valueScaled = float(value - leftMin) / float(leftSpan)
    value = rightMin + (valueScaled * rightSpan)
    if value < rightMin:
        value = rightMin
    if value > rightMax:
        value = rightMax
    return value


current_reading = []


def loadSettings():
    global color_triggers
    global ratio_tolerance
    global sum_tolerance
    f = open('iracer.dat', 'rb')
    settings = pickle.load(f)
    color_triggers = settings[0]
    f.close()
    print('Loaded configuration file.')


def saveSettings():
    global color_triggers
    settings = [color_triggers]
    f = open('iracer.dat', 'wb')  # save to disk
    pickle.dump(settings, f)
    f.close()


try:
    loadSettings()
except (OSError, IOError) as e:
    lap = [0.615, 0.169, 0.216, 1030.0, "LAP\n"]
    gate = [0.2107, 0.274, 0.518, 575.0, "GATE\n"]
    boost = [0.317, 0.374, 0.308, 648.0, "BOOST\n"]
    powerup = [0.671, 0.190, 0.137, 1244.0, "POWERUP\n"]
    slow = [0.999, 0.999, 0.999, 1244.0, "SLOW\n"]
    coin = [0.999, 0.999, 0.999, 1244.0, "COIN\n"]
    octagon = [0.999, 0.999, 0.999, 1244.0, "OCTAGON\n"]
    color_triggers = [lap, gate, boost, powerup, slow, coin, octagon]
    print('Configuration file not found.')


def calibrate(target):
    print('Calibrating target ' + target)
    global color_triggers
    global current_reading
    time.sleep(0.2)
    target_int = int(target)
    print(color_triggers[target_int][0])
    print(current_reading[0])
    color_triggers[target_int][0] = current_reading[0]
    color_triggers[target_int][1] = current_reading[1]
    color_triggers[target_int][2] = current_reading[2]
    color_triggers[target_int][3] = current_reading[3]
    printable = "Calibration data: %f  %f  %f %d" % (current_reading[0],
                                                     current_reading[1], current_reading[2], current_reading[3])
    print(printable)
    saveSettings()


def restoreCalDefaults():
    # print('Restoring calibration defaults')
    # global color_triggers
    # color_triggers = [lap_default, gate_default, boost_default, powerup_default]
    print('Not enabled.')


def colorMatch(red, green, blue, color_sum):
    global ratio_tolerance
    global sum_tolerance
    global color_triggers
    global send_string
    for trigger in color_triggers:
        if abs(red - trigger[0]) < ratio_tolerance and abs(green - trigger[1]) < ratio_tolerance and abs(blue - trigger[2]) < ratio_tolerance and abs(color_sum - trigger[3]) < sum_tolerance:
            if trigger[4] not in send_string:
                print(trigger[4])
                send_string = "%s%s" % (send_string, trigger[4])


def readColor():
    global current_reading

    previous_data = []
    use_sensor_calibration = False
    while True:
        data = bus.read_i2c_block_data(0x44, 0x09, 6)
        if previous_data != data:
            previous_data = data
            green = data[1] * 256 + data[0]
            red = data[3] * 256 + data[2]
            blue = data[5] * 256 + data[4]
            if use_sensor_calibration == True:
                red = translate(red, 5, 210, 0, 255)
                green = translate(green, 3, 160, 0, 255)
                blue = translate(blue, 5, 209, 0, 255)

            color_sum = float(red + green + blue)
            if color_sum > 1:
                red_ratio = red / color_sum
                green_ratio = green / color_sum
                blue_ratio = blue / color_sum
                colorMatch(red_ratio, green_ratio, blue_ratio, color_sum)
                current_reading = [red_ratio, green_ratio, blue_ratio, color_sum]
                # ratio = "%f  %f  %f" % (red_ratio, green_ratio, blue_ratio)
                # print ratio


try:
    print("Starting color sensor thread")
    thread.start_new_thread(readColor, ())
except:
    print("Error: unable to start thread")

time.sleep(1)
reversing = 0


def motor_output(value):
    global reversing
    value = int(value)
    if (not reversing and value < 0):
        reversing = True
        reverse()
    if (reversing and value > 0):
        reversing = False
        forward()
    motor_output = ((float(abs(value)) / 1000.0) * 255)
    motor_output = int(motor_output)
    # print(str(motor_output))
    pi.set_PWM_dutycycle(18, motor_output)


def forward():
    pi.write(17, 0)
    pi.write(27, 1)


def reverse():
    pi.write(17, 1)
    pi.write(27, 0)


reverse()
time.sleep(0.5)
forward()


def move_servo(value):
    pi.set_servo_pulsewidth(16, int(value))


def systemCommand(value):
    global ratio_tolerance
    global sum_tolerance
    if (value[0] == 'S'):
        print('Shutting down')
        os.system('sudo shutdown -h now')
    if (value[0] == 'R'):
        print('Rebooting')
        os.system('sudo reboot')
    if (value[0] == 'B'):
        brightness_value = value[2:4]  # only 10-99 values safe!
        os.system('v4l2-ctl --set-ctrl=brightness=' + brightness_value)  # execute bash command
        print('Brightness set to:' + brightness_value)
    if (value[0] == 'V'):
        bitrate = value[2:] 
        os.system('v4l2-ctl --set-ctrl=video_bitrate=' + bitrate)  # execute bash command
        print('Bitrate set to:' + bitrate)
    if (value[0] == 'W'):
        get_wifi_quality()
    if (value[0:3] == 'CAL'):
        if value[4] == 'D':
            restoreCalDefaults()
        else:
            calibration_target = value[4]  # only 0-9 values safe!
            calibrate(calibration_target)


def get_wifi_quality():
    global send_string
    cmd = subprocess.Popen('iwconfig ' 'wlan0', shell=True, stdout=subprocess.PIPE)
    for response in cmd.stdout:
        if 'Link Quality' in response and 'Link Quality' not in send_string:
            response = response.lstrip(' ')
            response = response.rstrip()
            send_string = "%s%s\n" % (send_string, response)


keys = [["S=", move_servo], ["M=", motor_output], ["U=", systemCommand]]


class SocketServer:
    """ Simple socket server that listens to one single client. """

    def __init__(self, host='0.0.0.0', port=5001):
        """ Initialize the server with a host and port to listen to. """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.host = host
        self.port = port
        self.sock.bind((host, port))
        self.sock.listen(1)

    def close(self):
        """ Close the server socket. """
        print(
            'Closing server socket (host {}, port {})'.format(
                self.host, self.port))
        if self.sock:
            self.sock.close()
            self.sock = None

    def run_server(self):
        """ Accept and handle an incoming connection. """
        print(
            'Starting socket server (host {}, port {})'.format(
                self.host, self.port))
        pi.write(20, 1)  # turn LEDs on
        client_sock, client_addr = self.sock.accept()

        print('Client {} connected'.format(client_addr))

        stop = False
        while not stop:
            if client_sock:
                # Check if the client is still connected and if data is
                # available:
                try:
                    rdy_read, rdy_write, sock_err = select.select(
                        [client_sock, ], [], [])
                except select.error:
                    print(
                        'Select() failed on socket with {}'.format(client_addr))
                    return 1

                if len(rdy_read) > 0:
                    try:
                        read_data = client_sock.recv(255)
                    except BaseException:
                        print("Unable to read data")
                    # Check if socket has been closed
                    if len(read_data) == 0:
                        print('{} closed the socket.'.format(client_addr))
                        stop = True
                    else:
                        # print('>>> Received: {}'.format(read_data.rstrip()))
                        incstring = read_data.rstrip()
                        for key in keys:  # look for our keys in the incoming string, and send to our functions
                            if incstring.find(key[0]) >= 0:
                                key_pos_start = incstring.find(key[0])
                                key_pos_end = key_pos_start + len(key[0])
                                value = incstring[key_pos_end:incstring.find('&', key_pos_end)]
                                key[1](value)  # send to our function

                        if read_data.rstrip() == 'quit':
                            stop = True
                        else:
                            global send_string
                            if send_string != "":
                                try:
                                    client_sock.send(send_string)
                                    send_string = ""  # clear buffer
                                    # client_sock.send(read_data)
                                except:
                                    print("sending error")
            else:
                print("No client is connected, SocketServer can't receive data")
                stop = True

        # Close socket
        print('Closing connection with {}'.format(client_addr))
        client_sock.close()
        return 0


def main():
    while True:
        server = SocketServer()
        server.run_server()
        print('Exiting')
        server.sock.close()


if __name__ == "__main__":
    main()
