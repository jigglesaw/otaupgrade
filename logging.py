import uos
import utime

SD_LOG_PATH = 'sd/log_files'
LOG_FILE_NAME = 'log_file.txt'
LOG_FILE_PATH = '{}/{}'.format(SD_LOG_PATH, LOG_FILE_NAME)

def initialize_logging():
    try:
        if not uos.path.exists(SD_LOG_PATH):
            uos.makedirs(SD_LOG_PATH)
        if not uos.path.exists(LOG_FILE_PATH):
            with open(LOG_FILE_PATH, 'w') as log_file:
                log_file.write('')
        save_to_sd("---------------START---------------")
    except Exception as e:
        print("[ERROR] Logging Initialization Failed:", e)

def save_to_sd(data):
    try:
        with open(LOG_FILE_PATH, 'a') as log_file:
            log_file.write('{}\n'.format(data))
    except Exception as e:
        print("[ERROR] Failed to save log:", e)

def log(level, tag, val):
    local_time = utime.localtime()
    log_message = '[{d:02d}-{mo:02d}-{y:04d} {h:02d}:{m:02d}:{s:02d}]: {level}: {tag}: {val}'.format(
        y=local_time[0], mo=local_time[1], d=local_time[2],
        h=local_time[3], m=local_time[4], s=local_time[5],
        level=level, tag=tag, val=val
    )
    print(log_message)
    
    if level in ["WARN", "ERROR"]:
        save_to_sd(log_message)

def info(tag, val):
    log("INFO", tag, val)

def error(tag, val):
    log("ERROR", tag, val)

def warning(tag, val):
    log("WARN", tag, val)


