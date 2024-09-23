import utime
import _thread
from machine import RTC, Timer
import sms
import app_fota
import uos
import usr.flags as flags
from misc import Power
from usr.BMS_data import get_bms_data
from usr.GPS import get_gps_data
from usr.Data_Extract import extract_data
from usr.Network_upload import SimpleSSLClient
from usr.SD_CARD import save_to_sd_card, initialize_sd_card, sd_extract
from usr.ota_upgrade import sms_callback
import usr.logging as I_LOG
import sim
import modem
from machine import UART
from usr.hardware import hardware_check, config_init, update_bms_uart

MAX_QUEUE_SIZE = 10
data_queue_real = []
data_queue_save = []
data_lock = _thread.allocate_lock()
upload_in_progress = False
data_queue_sd = []
sd_max_queue_size = 5
start_line = 0 
rtc = RTC()

# State Definitions
STATE_IDLE = 0
STATE_START = 1
STATE_HARDWARE_CHECK = 2
STATE_SYSTEM_CONFIG = 3
STATE_DATA_ACQUISITION = 4
STATE_BATCH_PROCESSING = 5
STATE_SD_CARD_BACKUP = 6
STATE_SD_CARD_PROCESSING =7
STATE_OTA_CHECK = 8
STATE_RETRY = 9


current_state = STATE_IDLE

def set_state(state):
    global current_state
    current_state = state

def start():
    print('')
    I_LOG.info("[START]", "Entering Start State")
    I_LOG.info("[START]", "Module Powered-ON [CODE : {}] ".format(Power.powerOnReason()))
    I_LOG.info("[START]", "Configuring Device Parameters......!")
    flags.DEV_IMEI = modem.getDevImei()
    print(flags.DEV_IMEI)
    if(flags.DEV_IMEI != -1):
        I_LOG.info("[START]", "Fetched DEV IMEI")
        return 1
    else:
        I_LOG.info("[START]", "Dev IMEI Error")
        return -1

def data_fetch():
    try:
        I_LOG.info("[DATA_FETCH]", "Fetching BMS and GPS data")
        bms_id, bms_data = get_bms_data()
        gps_data = get_gps_data()
        return bms_id, bms_data, gps_data
    except Exception as e:
        I_LOG.error("[DATA_FETCH]", "Error fetching data: {}".format(e))
        return None, None, None

def process_acquired_data(bms_id, bms_data, gps_data):
    try:
        I_LOG.info("[DATA_EXTRACT]", "Processing acquired data")
        extracted_data = extract_data(bms_id, bms_data, gps_data)
        return extracted_data
    except Exception as e:
        I_LOG.error("[DATA_EXTRACT]", "Failed to process acquired data: {}".format(e))
        return None

def append_data_to_queue(extracted_data, bms_data):
    with data_lock:
        data_queue_real.append(extracted_data)
        data_queue_save.append(bms_data)
    I_LOG.info("[DATA_EXTRACT]", "Data appended to queue. Queue size: {}".format(len(data_queue_real)))

def prepare_data_for_upload():
    global upload_in_progress
    data_to_upload = []
    data_to_save = []
    data_to_upload_sd = []
    global start_line
     # Initialize the starting line for SD card reading

    with data_lock:
        # Process only when real-time data queue reaches the maximum size
        if len(data_queue_real) >= MAX_QUEUE_SIZE and not upload_in_progress:
            upload_in_progress = True
            data_to_upload = data_queue_real[:]
            data_to_save = data_queue_save[:]
            del data_queue_real[:]
            del data_queue_save[:]
            I_LOG.info("[DATA_EXTRACT]", "Prepared real-time data for upload.")

            try:
                lines = read_sd_card_data(sd_max_queue_size, start_line)  # Read the next set of lines
                if lines:
                    data_queue_sd = extract_sd_card_data(lines)
                    data_to_upload_sd.extend(data_queue_sd[:])
                    del data_queue_sd[:]
                    I_LOG.info("[SD_CARD]", "SD card data appended to real-time data.")
                    start_line += sd_max_queue_size  # Move to the next set of lines
                else:
                    I_LOG.info("[SD_CARD]", "No more data to read from SD card.")
                      # Exit the loop if no more lines are available
            except Exception as e:
                I_LOG.error("[SD_CARD]", "Error reading from SD card: {}".format(e))
                  # Exit the loop on error

    # Combine real-time data with SD card data, if available
    combined_data_to_upload = data_to_upload + data_to_upload_sd
    return combined_data_to_upload, data_to_save



def upload_data(client, combined_data_to_upload):
    try:
        I_LOG.info("[NETWORK_UPLOAD]", "Uploading combined real-time and SD card data (if available) to network")
        response = client.send_data_over_ssl(combined_data_to_upload)
        return response
    except Exception as e:
        I_LOG.error("[NETWORK_UPLOAD]", "Failed to upload combined data to network: {}".format(e))
        return False

def save_data_to_sd_card(data_to_save):
    try:
        I_LOG.info("[SD_CARD]", "Saving data to SD card")
        save_to_sd_card('sd/bms_data.txt', data_to_save)
    except Exception as e:
        I_LOG.error("[SD_CARD]", "Failed to save data to SD card: {}".format(e))

def reset_upload_in_progress():
    global upload_in_progress
    upload_in_progress = False
    I_LOG.info("[NETWORK_UPLOAD]", "Upload in progress reset")

def sd_card_data_task():
    I_LOG.info("[SD_CARD]", "SD card data task triggered")
    max_queue_size = sd_max_queue_size
    start_line = 0

    while True:
        lines = read_sd_card_data(max_queue_size, start_line)
        
        if not lines:
            I_LOG.info("[SD_CARD]", "End of file reached. Deleting SD card file.")
            delete_sd_card_file()
            break
        
        data_queue_sd = extract_sd_card_data(lines)
        if data_queue_sd:
            I_LOG.info("[SD_CARD]", "Sending batch data from SD card to server")
            client = SimpleSSLClient()
            upload_response = upload_data(client, data_queue_sd)
            if upload_response:
                I_LOG.info("[SD_CARD]", "Data upload to network completed successfully.")
                start_line += max_queue_size
            else:
                I_LOG.warning("[SD_CARD]", "Failed to upload batch data to the network.")
                break
            data_queue_sd.clear()
        else:
            I_LOG.info("[SD_CARD]", "No data extracted from SD card.")
            break

def extract_sd_card_data(lines):
    I_LOG.info("[SD_CARD]", "Extracting data from SD card")
    for line in lines:
        extracted_data = sd_extract(line)
        if extracted_data:
            data_queue_sd.append(extracted_data)
        if len(data_queue_sd) >= MAX_QUEUE_SIZE:
            break
    return data_queue_sd

def read_sd_card_data(max_lines, start_line):
    try:
        I_LOG.info("[SD_CARD]", "Reading {} lines from SD card starting at line {}".format(max_lines, start_line))
        lines = []
        with open('sd/bms_data.txt', 'r') as file:
            for _ in range(start_line):
                file.readline()  # Skip lines up to the start_line
            while len(lines) < max_lines:
                line = file.readline().strip()
                if not line:
                    break
                if len(line.split(',')) == 34 or len(line.split(',')) == 37 :  # Validate line contains 34 elements after splitting by commas
                    lines.append(line)
                else:
                    I_LOG.warning("[SD_CARD]", "Skipped invalid line: {}".format(line))
    except OSError as e:
        I_LOG.error("[SD_CARD]", "Error reading SD card file: {}".format(e))
        return None

    if not lines:
        I_LOG.info("[SD_CARD]", "No more valid lines to read from SD card")
        return []

    return lines


def delete_sd_card_file():
    I_LOG.info("[SD_CARD]", "Deleting SD card file")
    try:
        uos.remove('sd/bms_data.txt')
    except OSError as e:
        I_LOG.error("[SD_CARD]", "Error deleting SD card file: {}".format(e))

def check_for_ota_upgrade():
    try:
        I_LOG.info("[FOTA]", "Setting up SMS Callback for OTA and other functions")
        sms.setCallback(sms_callback)
    except Exception as e:
        I_LOG.error("[FOTA]", "Failed to check for OTA upgrade: {}".format(e))
