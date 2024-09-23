'''
*  **********************************************
*
*   Project Name    :   IoT Model
*   Company Name    :   Emo Energy
*   File Name       :   gps.py
*   Description     :   Extracts the useful data from the GPS
*   Author          :   Abhijit Narayan S
*   Created on      :   01-04-2024   
*      
*   © All rights reserved @EMO.Energy [www.emoenergy.in]
*   
*   *********************************************
'''
from machine import UART, RTC
import usr.flags as flags
import utime
import ql_fs
import usr.logging as I_LOG

rtc = RTC()
uart_port = 1  
uart_baudrate = 9600 

last_latitude = None
last_longitude = None
uart1 = flags.GPS_UART

# Initialize logging


def callback(para):
    if para[0] == 0:
        uartReadgp(para[2])

def uartReadgp():
    try:
        msg = uart1.readline()
        utf8_msg = msg.decode()
        I_LOG.info("[GPS_UART]", "Received GPS message: {}".format(utf8_msg.strip()))
        return utf8_msg
    except Exception as e:
        I_LOG.error("[GPS_UART]", "Failed to read GPS message: {}".format(e))
        return None

def get_gps_data():
    try:
        gps_data = uartReadgp()
        #gps_data ="$GPRMC,203522.00,A,5109.0262308,N,11401.8407342,W,0.004,133.4,130522,0.0,E,D*2B"
        if gps_data:
            I_LOG.info("[GPS_UART]", "GPS Data received: {}".format(gps_data.strip()))
            print("GPS Data received ")
            print(gps_data)
        else:
            I_LOG.warning("[GPS_UART]", "GPS Data not received")
            print("GPS Data not received")
            gps_data = ""
    except Exception as e:
        I_LOG.error("[GPS_UART]", "Error while getting GPS data: {}".format(e))
        gps_data = ""
    return gps_data

def extract_lat_lon(gps_data):
    global last_latitude, last_longitude
    try:
        lines = gps_data.split('\n')
        for line in lines:
            if line.startswith('$GPRMC') and line.endswith('\r') and line.count('$GPRMC') == 1:
                data = line.split(',')
                if len(data) >= 10:
                    lat = data[3] + ' ' + data[4]
                    lon = data[5] + ' ' + data[6]
                    if 'V' in data:
                        I_LOG.warning("[GPS_UART]", "Invalid GPS data (status is 'V')")
                        print("Invalid GPS data (status is 'V')")
                        return 'invalid', 'invalid'

                    if lat != last_latitude or lon != last_longitude:
                        last_latitude = lat
                        last_longitude = lon
                        return lat, lon

                    if '$' in lat or '$' in lon:
                        return last_latitude, last_longitude
                    else:
                        return last_latitude, last_longitude
        I_LOG.warning("[GPS_UART]", "No valid GPS data found")
        return last_latitude, last_longitude
    except Exception as e:
        I_LOG.error("[GPS_UART]", "Error while extracting latitude and longitude: {}".format(e))
        return last_latitude, last_longitude
