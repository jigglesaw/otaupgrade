

import usr.flags as flags
from machine import RTC
import utime
import uos
from uos import VfsSd
import usr.flags as flags
import ql_fs
import sim, modem
from usr.GPS import extract_lat_lon, get_gps_data
from usr.Data_Extract import global_datetime_list
import usr.logging as I_LOG

rtc = RTC()

MAX_QUEUE_SIZE = 10
data_queue_real = []
data_queue_save = []
upload_in_progress = False
data_queue_sd = []
max_queue_size = 10 

def initialize_sd_card():
    try:
        udev = VfsSd("sd_fs")
        uos.mount(udev, "/sd")
        udev.set_det(udev.GPIO30, 0)
        flags.SD_Card_working_status_flag = True
        I_LOG.info("[SD_CARD]", "SD Card Mounted Successfully....!")
        return True
    except Exception as e:
        flags.SD_Card_working_status_flag = False
        I_LOG.error("[SD_CARD]", "Failed to mount SD card", exc_info=True)
        return False

# Check SD Card Status
def check_sd_card():
    if flags.SD_Card_working_status_flag:
        I_LOG.info("[SD_CARD]", "SD Card is mounted.")
        return True
    else:
        I_LOG.error("[SD_CARD]", "SD Card is not mounted.")
        return False

def save_to_sd_card(filename, batch_data):
    try:
        I_LOG.info("[SD_CARD]", "Saving BMS data to SD card: {}".format(filename))
        with open(filename, "a+") as f:
            gps_data = get_gps_data()
            for data in batch_data:
                latitude, longitude = extract_lat_lon(gps_data)
                if global_datetime_list:
                    timestamp = global_datetime_list.pop(0)  # Get the oldest datetime from the list
                else:
                    timestamp = "0000-00-00 00:00:00"  # Default value if list is empty

                # Split timestamp into date and time parts
                date_part, time_part = timestamp.split()
                year, month, day = map(int, date_part.split('-'))
                hour, minute, second = map(int, time_part.split(':'))

                # Format timestamp as required "yyyy,mm,dd,00,hh,mm,ss"
                for_timestamp = "{:04d},{:02d},{:02d},00,{:02d},{:02d},{:02d}".format(year, month, day, hour, minute, second)
                data_to_write = data
                # Remove "AT+" prefix only if it's at the beginning
                if data_to_write.startswith("AT+,"):
                    end_index = data_to_write.find(",\r\n")
                    final_data = data_to_write[len("AT+,"):end_index]
                else:
                    final_data = data_to_write

                f.write("{},{},{},{}\r\n".format(for_timestamp, final_data, latitude, longitude))
                strin = "{},{},{},{}\r\n".format(for_timestamp, final_data, latitude, longitude)
                I_LOG.info("[SD_CARD]", strin)
        
        I_LOG.info("[SD_CARD]", "BMS data saved to SD card: {}".format(filename))
    except Exception as e:
        I_LOG.error("[SD_CARD]", "Error saving BMS data to SD card: {}".format(e))

def sd_extract(sd_data):
    if len(sd_data) > 5:
        data_parts = [value for value in sd_data.split(',') if value]
        result = {
            "IMEI": None,
            "IMSI": None,
            "ICCID": None,
            "Network_operator": '1',  # Assuming this is a constant value
            "Time": None,
            "Date": None,
            "DeviceID": None,
            "Data": {
                "packVoltage": None,
                "packCurrent": None,
                "SOC": None,
                "CellData": None,
                "TemperatureData": None,
                "Faults": None,
                "Latitude": None,
                "Longitude": None,
                "Data_Type": "B",  # Set to "B" for backup data type
            },
        }

        try:
            result["DeviceID"] = data_parts[7]
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract DeviceID: {}".format(e))

        try:
            result["Data"]["packVoltage"] = int(data_parts[26]) / 100.0
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract packVoltage: {}".format(e))

        try:
            result["Data"]["packCurrent"] = int(data_parts[27]) / 100.0
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract packCurrent: {}".format(e))

        try:
            result["Data"]["SOC"] = int(data_parts[28] if int(data_parts[28] < 120) else None)
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract SOC: {}".format(e))

        try:
            result["Data"]["CellData"] = [int(value) / 1000.0 for value in data_parts[8:22] ]
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract CellData: {}".format(e))

        try:
            result["Data"]["TemperatureData"] = [int(value) for value in data_parts[22:26] if int(value) < 100]
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract TemperatureData: {}".format(e))

        try:
            result["Data"]["Faults"] = ([int(value) for value in data_parts[29:35] if int(value) < 256])
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract Faults: {}".format(e))

        try:
            result["Data"]["Latitude"] = str(data_parts[-2])
            result["Data"]["Longitude"] = str(data_parts[-1])
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract GPS data: {}".format(e))

        try:
            year = int(data_parts[0])
            month = int(data_parts[1])
            day = int(data_parts[2])
            hour = int(data_parts[4])
            minute = int(data_parts[5])
            second = int(data_parts[6])
            date_string = "{:04d}-{:02d}-{:02d}".format(year, month, day)
            time_string = "{}:{}:{}".format(hour, minute, second)
            result["Time"] = time_string
            result["Date"] = date_string
        except (IndexError, ValueError) as e:
            I_LOG.error("[SD_CARD]", "Failed to extract date/time: {}".format(e))

        try:
            result["IMSI"] = flags.SIM_IMSI
        except Exception as e:
            I_LOG.error("[SD_CARD]", "Failed to extract IMSI: {}".format(e))

        try:
            result["ICCID"] = flags.SIM_ICCID
        except Exception as e:
            I_LOG.error("[SD_CARD]", "Failed to extract ICCID: {}".format(e))

        try:
            result["IMEI"] = flags.DEV_IMEI
        except Exception as e:
            I_LOG.error("[SD_CARD]", "Failed to extract IMEI: {}".format(e))

        return result
    return None

def read_sd_card_data():
    try:
        with open('sd/bms_data.txt', 'r+') as file:
            lines = file.read().split('\n')
    except OSError as e:
        I_LOG.error("[SD_CARD]", "Error reading SD card file: {}".format(e))
        return None

    if not lines:
        I_LOG.info("[SD_CARD]", "SD card empty")
        return None

    I_LOG.info("[SD_CARD]", "Read SD card data")

    for line in lines:
        extracted_data = sd_extract(line)
        if extracted_data:
            data_queue_sd.append(extracted_data)
        if len(data_queue_sd) >= max_queue_size:
            break

    with open('sd/bms_data.txt', 'w+') as file:
        for line in lines[max_queue_size:]:
            file.write(line + '\n')

    return data_queue_sd
