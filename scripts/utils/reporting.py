import glob
import json
import logging
import os
import sqlite3
import subprocess
import tempfile
import io
from time import sleep

from .helpers import get_settings, get_font, DB_PATH
from .classes import Detection, ParseFileName

log = logging.getLogger(__name__)
DB_INSERT_SQL = "INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
APPRISE_CONFIG = os.path.expanduser('~/BirdNET-Pi/apprise.txt')
_LAST_JSON_BY_STREAM = {}
_JSON_CLEANUP_COUNTER = {}
_JSON_FULL_SCAN_INTERVAL = 240


def extract(in_file, out_file, start, stop):
    result = subprocess.run(['sox', '-V1', f'{in_file}', f'{out_file}', 'trim', f'={start}', f'={stop}'],
                            check=True, capture_output=True)
    ret = result.stdout.decode('utf-8')
    err = result.stderr.decode('utf-8')
    if err:
        raise RuntimeError(f'{ret}:\n {err}')
    return ret


def extract_safe(in_file, out_file, start, stop):
    conf = get_settings()
    # This section sets the SPACER that will be used to pad the audio clip with
    # context. If EXTRACTION_LENGTH is 10, for instance, 3 seconds are removed
    # from that value and divided by 2, so that the 3 seconds of the call are
    # within 3.5 seconds of audio context before and after.
    try:
        ex_len = conf.getint('EXTRACTION_LENGTH')
    except ValueError:
        ex_len = 6
    spacer = (ex_len - 3) / 2
    safe_start = max(0, start - spacer)
    safe_stop = min(conf.getint('RECORDING_LENGTH'), stop + spacer)

    extract(in_file, out_file, safe_start, safe_stop)


def spectrogram(in_file, title, comment, raw=0):
    from PIL import Image, ImageDraw, ImageFont

    fd, tmp_file = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    args = ['sox', '-V1', f'{in_file}', '-n', 'remix', '1', 'rate', '24k', 'spectrogram',
            '-t', '', '-c', '', '-o', tmp_file]
    args += ['-r'] if int(raw) else []

    result = subprocess.run(args, check=True, capture_output=True)
    ret = result.stdout.decode('utf-8')
    err = result.stderr.decode('utf-8')
    if err:
        raise RuntimeError(f'{ret}:\n {err}')
    img = Image.open(tmp_file)
    height = img.size[1]
    width = img.size[0]
    draw = ImageDraw.Draw(img)
    title_font = ImageFont.truetype(get_font()['path'], 13)
    _, _, w, _ = draw.textbbox((0, 0), title, font=title_font)
    draw.text(((width-w)/2, 6), title, fill="white", font=title_font)

    comment_font = ImageFont.truetype(get_font()['path'], 11)
    _, _, _, h = draw.textbbox((0, 0), comment, font=comment_font)
    draw.text((1, height - (h + 1)), comment, fill="white", font=comment_font)
    img.save(f'{in_file}.png')
    os.remove(tmp_file)


def extract_detection(file: ParseFileName, detection: Detection, conf=None):
    conf = get_settings() if conf is None else conf
    new_file_name = f'{detection.common_name_safe}-{detection.confidence_pct}-{detection.date}-birdnet-{file.RTSP_id}{detection.time}.{conf["AUDIOFMT"]}'
    new_dir = os.path.join(conf['EXTRACTED'], 'By_Date', f'{detection.date}', f'{detection.common_name_safe}')
    new_file = os.path.join(new_dir, new_file_name)
    if os.path.isfile(new_file):
        log.warning('Extraction exists. Moving on: %s', new_file)
    else:
        os.makedirs(new_dir, exist_ok=True)
        extract_safe(file.file_name, new_file, detection.start, detection.stop)
        spectrogram(new_file, detection.common_name, new_file.replace(os.path.expanduser('~/'), ''), conf['RAW_SPECTROGRAM'])
    return new_file


def write_to_db(file: ParseFileName, detection: Detection, connection=None, conf=None):
    write_detections_to_db(file, [detection], connection=connection, conf=conf)


def write_detections_to_db(file: ParseFileName, detections: [Detection], connection=None, cursor=None, conf=None):
    if not detections:
        return
    conf = get_settings() if conf is None else conf
    rows = [
        (detection.date, detection.time, detection.scientific_name, detection.common_name, detection.confidence,
         conf['LATITUDE'], conf['LONGITUDE'], conf['CONFIDENCE'], str(detection.week), conf['SENSITIVITY'],
         conf['OVERLAP'], os.path.basename(detection.file_name_extr))
        for detection in detections
    ]

    local_connection = connection is None
    local_cursor = cursor is None
    con = connection if connection is not None else sqlite3.connect(DB_PATH)
    db_cursor = cursor if cursor is not None else con.cursor()
    try:
        for attempt_number in range(3):
            try:
                db_cursor.executemany(DB_INSERT_SQL, rows)
                con.commit()
                break
            except BaseException as e:
                if not local_connection:
                    raise
                log.warning("Database busy: %s", e)
                sleep(2)
    finally:
        if local_cursor:
            db_cursor.close()
        if local_connection:
            con.close()


def summary(file: ParseFileName, detection: Detection, conf=None):
    conf = get_settings() if conf is None else conf
    # Date;Time;Sci_Name;Com_Name;Confidence;Lat;Lon;Cutoff;Week;Sens;Overlap
    # 2023-03-03;12:48:01;Phleocryptes melanops;Wren-like Rushbird;0.76950216;-1;-1;0.7;9;1.25;0.0
    s = (f'{detection.date};{detection.time};{detection.scientific_name};{detection.common_name};'
         f'{detection.confidence};'
         f'{conf["LATITUDE"]};{conf["LONGITUDE"]};{conf["CONFIDENCE"]};{detection.week};{conf["SENSITIVITY"]};'
         f'{conf["OVERLAP"]}')
    return s


def write_to_file(file: ParseFileName, detection: Detection, conf=None):
    write_detections_to_file(file, [detection], conf=conf)


def write_detections_to_file(file: ParseFileName, detections: [Detection], conf=None):
    if not detections:
        return
    conf = get_settings() if conf is None else conf
    with open(os.path.expanduser('~/BirdNET-Pi/BirdDB.txt'), 'a') as rfile:
        rfile.writelines(f'{summary(file, detection)}\n' for detection in detections)


def update_json_file(file: ParseFileName, detections: [Detection], conf=None):
    json_file = f'{file.file_name}.json'
    conf = get_settings() if conf is None else conf
    cleanup_prior_json_files(file, json_file)
    write_to_json_file(file, detections, json_file, conf=conf)


def cleanup_prior_json_files(file: ParseFileName, current_json):
    stream_key = (os.path.dirname(file.file_name), file.RTSP_id or '')
    cleanup_count = _JSON_CLEANUP_COUNTER.get(stream_key, 0) + 1
    _JSON_CLEANUP_COUNTER[stream_key] = cleanup_count
    previous_json = _LAST_JSON_BY_STREAM.get(stream_key)
    _LAST_JSON_BY_STREAM[stream_key] = current_json

    if previous_json and previous_json != current_json and cleanup_count % _JSON_FULL_SCAN_INTERVAL != 0:
        try:
            os.remove(previous_json)
        except FileNotFoundError:
            pass
        return

    if file.RTSP_id is None:
        mask = f'{os.path.dirname(file.file_name)}/*.json'
    else:
        mask = f'{os.path.dirname(file.file_name)}/*{file.RTSP_id}*.json'
    for f in glob.glob(mask):
        if f == current_json:
            continue
        log.debug(f'deleting {f}')
        os.remove(f)


def write_to_json_file(file: ParseFileName, detections: [Detection], json_file=None, conf=None):
    conf = get_settings() if conf is None else conf
    if json_file is None:
        json_file = f'{file.file_name}.json'
    log.debug(f'WRITING RESULTS TO {json_file}')
    dets = {'file_name': os.path.basename(json_file), 'timestamp': file.iso8601, 'delay': conf['RECORDING_LENGTH'],
            'detections': [{"start": det.start, "common_name": det.common_name, "confidence": det.confidence} for det in
                           detections]}
    with open(json_file, 'w') as rfile:
        rfile.write(json.dumps(dets))
    log.debug(f'DONE! WROTE {len(detections)} RESULTS.')


def apprise(file: ParseFileName, detections: [Detection], conf=None):
    if not detections:
        return
    if not (os.path.exists(APPRISE_CONFIG) and os.path.getsize(APPRISE_CONFIG) > 0):
        return
    from .notifications import sendAppriseNotifications

    species_apprised_this_run = []
    conf = get_settings() if conf is None else conf

    for detection in detections:
        # Apprise of detection if not already alerted this run.
        if detection.species not in species_apprised_this_run:
            try:
                sendAppriseNotifications(detection.scientific_name, detection.common_name, str(detection.confidence), str(detection.confidence_pct),
                                         os.path.basename(detection.file_name_extr), detection.date, detection.time, str(detection.week),
                                         conf['LATITUDE'], conf['LONGITUDE'], conf['CONFIDENCE'], conf['SENSITIVITY'], conf['OVERLAP'])

            except BaseException as e:
                log.exception('Error during Apprise:', exc_info=e)

            species_apprised_this_run.append(detection.species)


def bird_weather(file: ParseFileName, detections: [Detection], conf=None):
    conf = get_settings() if conf is None else conf
    if conf['BIRDWEATHER_ID'] == "":
        return
    if detections:
        import requests
        import soundfile

        try:
            data, samplerate = soundfile.read(file.file_name)
            buf = io.BytesIO()
            soundfile.write(buf, data, samplerate, format='FLAC')
            flac_data = buf.getvalue()
        except Exception as e:
            log.error("Error during FLAC conversion: %s", e)
            return

        # POST soundscape to server
        soundscape_url = (f'https://app.birdweather.com/api/v1/stations/'
                          f'{conf["BIRDWEATHER_ID"]}/soundscapes?timestamp={file.iso8601}')

        try:
            response = requests.post(url=soundscape_url, data=flac_data, timeout=30,
                                     headers={'Content-Type': 'audio/flac'})
            log.info("Soundscape POST Response Status - %d", response.status_code)
            sdata = response.json()
        except BaseException as e:
            log.error("Cannot POST soundscape: %s", e)
            return
        if not sdata.get('success'):
            log.error(sdata.get('message'))
            return
        soundscape_id = sdata['soundscape']['id']

        for detection in detections:
            # POST detection to server
            detection_url = f'https://app.birdweather.com/api/v1/stations/{conf["BIRDWEATHER_ID"]}/detections'

            data = {'timestamp': detection.iso8601, 'lat': conf['LATITUDE'], 'lon': conf['LONGITUDE'],
                    'soundscapeId': soundscape_id,
                    'soundscapeStartTime': detection.start, 'soundscapeEndTime': detection.stop,
                    'commonName': detection.common_name, 'scientificName': detection.scientific_name,
                    'algorithm': '2p4' if conf['MODEL'] == 'BirdNET_GLOBAL_6K_V2.4_Model_FP16' else 'alpha',
                    'confidence': detection.confidence}

            log.debug(data)
            try:
                response = requests.post(detection_url, json=data, timeout=20)
                log.info("Detection POST Response Status - %d", response.status_code)
            except BaseException as e:
                log.error("Cannot POST detection: %s", e)


def heartbeat(conf=None):
    conf = get_settings() if conf is None else conf
    if conf['HEARTBEAT_URL']:
        import requests

        try:
            result = requests.get(url=conf['HEARTBEAT_URL'], timeout=10)
            log.info('Heartbeat: %s', result.text)
        except BaseException as e:
            log.error('Error during heartbeat: %s', e)
