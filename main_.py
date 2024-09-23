import utime
import _thread
from machine import Timer, WDT
from usr.hardware import hardware_check
import usr.iot_sm as state
from misc import Power
import sms
import net
from usr.ota_upgrade import sms_callback
import usr.logging as I_LOG
from usr.network import checkNet  # Import the checkNet module for network status checking

MAX_RETRIES = 5
retry_count = 0
timer1 = Timer(Timer.Timer1)
network_timer = Timer(Timer.Timer2)  # Timer for network status check
failed_state = None
sd_card_backup_start_time = None

# Watchdog Timer Initialization
wdt = WDT(20)  # Enables the watchdog and sets the timeout period to 20 seconds

def feed_watchdog(t):
    """Feed the watchdog to prevent system reset."""
    wdt.feed()

def module_reset():
    I_LOG.info("[MODULE_RESET]", "Maximum retries reached, resetting module")
    Power.powerRestart()

def reset_retry_count():
    global retry_count
    retry_count = 0

def increment_retry_count():
    global retry_count
    retry_count += 1
    if retry_count >= MAX_RETRIES:
        module_reset()

def check_network_and_reset(t):
    global sd_card_backup_start_time, last_sms_time
    stage, state = checkNet.waitNetworkReady()
    range_value = net.csqQueryPoll()  # Getting the network range

    current_time = utime.time()

    if stage == 3 and state == 1:
        I_LOG.info("[NETWORK_CHECK]", "Network connection successful during SD card backup.")
        try:
            sms.sendTextMsg('7356820493', 'Network connection restored. Range: {}'.format(range_value), 'GSM')
            I_LOG.info("[SMS]", "Sent SMS: Network connection restored.")
        except Exception as e:
            I_LOG.error("[SMS]", "Failed to send SMS: {}".format(e))
        sd_card_backup_start_time = None  # Reset the start time as the connection is back
        last_sms_time = None  # Reset the last SMS time
    else:
        I_LOG.warning("[NETWORK_CHECK]", "Network connection failed during SD card backup. stage={}, state={}".format(stage, state))
        if sd_card_backup_start_time is None:
            sd_card_backup_start_time = current_time
            last_sms_time = current_time  # Initialize the last SMS time
        elif current_time - sd_card_backup_start_time >= 3600:  # 1 hour = 3600 seconds
            I_LOG.error("[NETWORK_CHECK]", "No network connection for 1 hour, resetting module.")
            module_reset()
        elif current_time - last_sms_time >= 1800:  # 30 minutes = 1800 seconds
            downtime_minutes = (current_time - sd_card_backup_start_time) // 60
            message = "Network down for {} minutes. Range: {}".format(downtime_minutes, range_value)
            try:
                sms.sendTextMsg('7356820493', message, 'GSM')
                I_LOG.info("[SMS]", "Sent SMS: {}".format(message))
                last_sms_time = current_time  # Update the last SMS time
            except Exception as e:
                I_LOG.error("[SMS]", "Failed to send SMS: {}".format(e))



def state_machine():
    global failed_state
    current_state = state.STATE_START   

    while True:
        if current_state == state.STATE_START:
            print("[STATE_MACHINE]", "Entering START state")
            state.start()
            state.check_for_ota_upgrade() #setting up sms callback
            current_state = state.STATE_HARDWARE_CHECK
            utime.sleep(1)
        
        elif current_state == state.STATE_HARDWARE_CHECK:
            I_LOG.info("[STATE_MACHINE]", "Entering HARDWARE_CHECK state")
            try:
                hardware_check()
                current_state = state.STATE_SYSTEM_CONFIG
            except Exception as e:
                I_LOG.error("[HARDWARE_CHECK]", "Error in hardware check: {}".format(e))
                failed_state = current_state  
                current_state = state.STATE_RETRY  

        elif current_state == state.STATE_SYSTEM_CONFIG:
            I_LOG.info("[STATE_MACHINE]", "Entering SYSTEM CONFIG state")
            try:
                state.config_init()
                current_state = state.STATE_DATA_ACQUISITION
            except Exception as e:
                I_LOG.error("[SYSTEM_CONFIG]", "Error in system config: {}".format(e))
                failed_state = current_state  
                current_state = state.STATE_RETRY  

        elif current_state == state.STATE_DATA_ACQUISITION:
            I_LOG.info("[STATE_MACHINE]", "Entering DATA_ACQUISITION state")
            try:
                bms_id, bms_data, gps_data = state.data_fetch()

                if bms_data.startswith("AT+UART=1"):
                    state.update_bms_uart(9600)
                    I_LOG.info("[BMS_UART]", "BMS_UART updated to 9600.....Restarting")
                    Power.powerRestart()
                elif bms_data.startswith("AT+UART=2"):
                    state.update_bms_uart(57600)
                    I_LOG.info("[BMS_UART]", "BMS_UART updated to 57600.....Restarting")
                    Power.powerRestart()
                elif bms_data.startswith("AT+UART=3"):
                    state.update_bms_uart(115200)
                    I_LOG.info("[BMS_UART]", "BMS_UART updated to 115200.....Restarting")
                    Power.powerRestart()
                elif bms_data.startswith("AT+RESET"):
                    I_LOG.info("[MODULE_RESET]", "AT+RESET received, resetting module")
                    Power.powerRestart()
                elif bms_id and bms_data and bms_data.startswith("AT+"):
                    extracted_data = state.process_acquired_data(bms_id, bms_data, gps_data)
                    
                    if extracted_data:
                        state.append_data_to_queue(extracted_data, bms_data)
                        
                    current_state = state.STATE_BATCH_PROCESSING
                else:
                    I_LOG.warning("[DATA_ACQUISITION]", "Invalid BMS data, retrying...")
                    current_state = state.STATE_DATA_ACQUISITION
            except Exception as e:
                I_LOG.error("[DATA_ACQUISITION]", "Error in data acquisition: {}".format(e))
                failed_state = current_state  
                current_state = state.STATE_RETRY  

        elif current_state == state.STATE_BATCH_PROCESSING:
            I_LOG.info("[STATE_MACHINE]", "Entering BATCH_PROCESSING state")
            try:
                data_to_upload, data_to_save = state.prepare_data_for_upload()
                if data_to_upload:
                    client = state.SimpleSSLClient()
                    upload_response = state.upload_data(client, data_to_upload)
                    if upload_response:
                        I_LOG.info("[NETWORK_UPLOAD]", "Data upload to network completed successfully.")
                        reset_retry_count()
                    else:
                        I_LOG.error("[NETWORK_UPLOAD]", "Network upload failed, backing up to SD card.")
                        current_state = state.STATE_SD_CARD_BACKUP  # Transition to SD card backup state
                    state.reset_upload_in_progress()
                    data_to_upload.clear()
                else:
                    I_LOG.info("[BATCH_PROCESSING]", "Queue has not been filled.")
                current_state = state.STATE_DATA_ACQUISITION
            except Exception as e:
                I_LOG.error("[BATCH_PROCESSING]", "Error in batch processing: {}".format(e))
                failed_state = current_state  
                current_state = state.STATE_RETRY  

        elif current_state == state.STATE_SD_CARD_BACKUP:
            I_LOG.info("[STATE_MACHINE]", "Entering SD_CARD_BACKUP state")
            try:
                sd_card_backup_start_time = utime.time()
                state.save_data_to_sd_card(data_to_save)
                I_LOG.info("[SD_CARD_BACKUP]", "Data backup to SD card completed.")
                
                network_timer.start(period=1800000, mode=network_timer.PERIODIC, callback=check_network_and_reset)
                
                
                current_state = state.STATE_DATA_ACQUISITION  # Return to data acquisition
            except Exception as e:
                I_LOG.error("[SD_CARD_BACKUP]", "Error in SD card backup: {}".format(e))
                failed_state = current_state  
                current_state = state.STATE_RETRY 

        elif current_state == state.STATE_OTA_CHECK:
            I_LOG.info("[STATE_MACHINE]", "Entering OTA_CHECK state")
            try:
                state.check_for_ota_upgrade()
                current_state = state.STATE_DATA_ACQUISITION
            except Exception as e:
                I_LOG.error("[OTA_CHECK]", "Error in OTA check: {}".format(e))
                failed_state = current_state  
                current_state = state.STATE_RETRY  

        elif current_state == state.STATE_RETRY:
            I_LOG.info("[STATE_MACHINE]", "Entering RETRY state")
            increment_retry_count()
            current_state = failed_state  
            utime.sleep(2)  # Small delay before retry

        elif current_state == state.STATE_IDLE:
            I_LOG.info("[STATE_MACHINE]", "Entering IDLE state")
            utime.sleep(5)
            current_state = state.STATE_DATA_ACQUISITION

        else:
            I_LOG.error("[STATE_MACHINE]", "Invalid state")
            current_state = state.STATE_IDLE

def main():
    print("[Main] Starting state machine")
    print("OTAUPGRADEDONEEEEEEEEEEEEEEEEEEE")
    _thread.start_new_thread(state_machine, ())  
    _thread.start_new_thread(state.data_fetch, ())  
    
    # Watchdog feeding timer
    print("[Main] Setting up watchdog feeding timer")
    timer1.start(period=15000, mode=timer1.PERIODIC, callback=feed_watchdog)
    
    while True:
        utime.sleep(1)

if __name__ == "__main__":
    main()


#https://github.com/jigglesaw/otaupgrade/blob/38cb45e0e7b0836d28864a8935fd4d062e6f660c/Device_config.json
