import utime
import sms
import app_fota
from misc import Power
import usr.logging as I_LOG

MODULE_FILES = {
    1: 'BMS_data.py',
    2: 'Data_Extract.py',
    3: 'flags.py',
    4: 'GPS.py',
    5: 'hardware.py',
    6: 'iot_sm.py',
    7: 'main.py',
    8: 'network.py',
    9: 'Network_upload.py',
    10: 'ota_upgrade.py',
    11: 'SD_CARD.py',
    12: 'SIM.py'
}

def sms_callback(args):
    """Callback function that triggers on receiving an SMS."""
    I_LOG.info("[OTA_UPGRADE]", "SMS callback triggered with args: {}".format(args))
    ind_flag = args[1]
    if ind_flag >= 0:  # New message indicator flags
        I_LOG.info("[OTA_UPGRADE]", "New SMS received, checking for upgrade/reset commands")
        ota_upgrade_check()

sms.setCallback(sms_callback)

def ota_upgrade_check():
    """Check for an upgrade or reset command in SMS and perform the action."""
    I_LOG.info("[OTA_UPGRADE]", "Checking for OTA upgrade or reset...")
    
    if sms.getMsgNums() > 0:
        msg_content = sms.searchTextMsg(0)[1]
        phone_number = sms.searchTextMsg(0)[0]
        module_to_upgrade = None
        invalid_command = False

        if msg_content.strip().upper() == 'AT+RESET':
            I_LOG.info("[OTA_UPGRADE]", "Received reset command")
            sms.deleteMsg(1, 4)
            message = 'AT+RESET || DONE'
            txtmsg = sms.sendTextMsg(phone_number, message, 'GSM')
            if txtmsg == 1:
                I_LOG.info("[OTA_UPGRADE]", "Sent acknowledgment message for reset command")
            else:
                I_LOG.error("[OTA_UPGRADE]", "Failed to send acknowledgment message for reset command")
            utime.sleep(2)
            Power.powerRestart()  # Reset the device

        elif msg_content.strip().upper().startswith('AT+UPGRADE='):
            # Extract the module to upgrade from the command
            module = msg_content.split('=')[1].strip().upper()
            if module == 'ALL':
                I_LOG.info("[OTA_UPGRADE]", "Received upgrade command for all modules.")
                module_to_upgrade = 'ALL'
            elif module.isdigit() and int(module) in MODULE_FILES:
                module_to_upgrade = int(module)
                I_LOG.info("[OTA_UPGRADE]", "Received upgrade command for module {} ({})".format(module_to_upgrade, MODULE_FILES[module_to_upgrade]))
            else:
                I_LOG.error("[OTA_UPGRADE]", "Invalid module in upgrade command: {}".format(module))
                invalid_command = True
        else:
            I_LOG.error("[OTA_UPGRADE]", "Incorrect command received")
            invalid_command = True

        sms.deleteMsg(1, 4)  # Ensure the correct parameters for deleting the SMS
        if invalid_command:
            message = 'AT+UPGRADE=INVALID COMMAND -- {}'.format(msg_content.split('=')[1].strip())
            txtmsg = sms.sendTextMsg(phone_number, message, 'GSM')
            if txtmsg == 1:
                I_LOG.info("[OTA_UPGRADE]", "Sent acknowledgment message to source number")
            else:
                I_LOG.error("[OTA_UPGRADE]", "Failed to send acknowledgment message to source number")

        if module_to_upgrade:
            if module_to_upgrade == 'ALL':
                I_LOG.info("[OTA_UPGRADE]", "Initiating OTA upgrade for all modules...")
            else:
                I_LOG.info("[OTA_UPGRADE]", "Initiating OTA upgrade for module {} ({})...".format(module_to_upgrade, MODULE_FILES[module_to_upgrade]))

            result = run_fota(module_to_upgrade)
            if result is True:
                if module_to_upgrade == 'ALL':
                    message = 'AT+UPGRADE={} || DONE'.format(module_to_upgrade)
                else:
                    message = 'AT+UPGRADE={} ({}) || DONE'.format(module_to_upgrade, MODULE_FILES[module_to_upgrade])
                txtmsg = sms.sendTextMsg(phone_number, message, 'GSM')
                if txtmsg == 1:
                    I_LOG.info("[OTA_UPGRADE]", "Sent acknowledgment message to source number")
                else:
                    I_LOG.error("[OTA_UPGRADE]", "Failed to send acknowledgment message to source number")
                Power.powerRestart()
            else:
                if module_to_upgrade == 'ALL':
                    message = 'AT+UPGRADE={} || FAILED'.format(module_to_upgrade)
                else:
                    message = 'AT+UPGRADE={} ({}) || FAILED'.format(module_to_upgrade, MODULE_FILES[module_to_upgrade])
                txtmsg = sms.sendTextMsg(phone_number, message, 'GSM')
                if txtmsg == 1:
                    I_LOG.info("[OTA_UPGRADE]", "Sent acknowledgment message to source number")
                else:
                    I_LOG.error("[OTA_UPGRADE]", "Failed to send acknowledgment message to source number")
                I_LOG.error("[OTA_UPGRADE]", "Upgrade failed: {}".format(result))

def run_fota(module=None):
    """Run the OTA update process for specified module."""
    fota = app_fota.new() 

    if module == 'ALL':
        download_list = [{'url': 'http://iotfota.s3.ap-south-1.amazonaws.com/{}.py'.format(MODULE_FILES[module]), 'file_name': '/usr/'+filename} for module, filename in MODULE_FILES.items()]
        upgrade = fota.bulk_download(download_list)
        fota.set_update_flag()
        I_LOG.info("[OTA_UPGRADE]", "Upgrading all modules")
        utime.sleep(2)
        return upgrade is None
        
    elif isinstance(module, int) and module in MODULE_FILES:
        module_index = module
        url = "http://iotfota.s3.ap-south-1.amazonaws.com/{}".format(MODULE_FILES[module_index])
        file_name = '/usr/' + MODULE_FILES[module_index]
        upgrade = fota.download(url, file_name)
        fota.set_update_flag()
        I_LOG.info("[OTA_UPGRADE]", "Upgrading module: {}".format(MODULE_FILES[module_index]))
        utime.sleep(2)
        return upgrade == 0
    else:
        I_LOG.error("[OTA_UPGRADE]", "Invalid module name: {}".format(module))
        I_LOG.error("[OTA_UPGRADE]", "Failed to update")
        return False
