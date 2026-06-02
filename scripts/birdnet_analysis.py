import logging
import os
import os.path
import signal
import sqlite3
import sys
import threading
from queue import Queue, Full
from subprocess import CalledProcessError

import inotify.adapters
from inotify.constants import IN_CLOSE_WRITE

from utils.analysis import load_global_model, run_analysis
from utils.helpers import get_settings, get_wav_files, ANALYZING_NOW, DB_PATH, _int_setting
from utils.classes import ParseFileName
from utils.reporting import extract_detection, summary, write_detections_to_file, write_detections_to_db, apprise, bird_weather, heartbeat, \
    update_json_file

shutdown = False

log = logging.getLogger(__name__)


def sig_handler(sig_num, curr_stack_frame):
    global shutdown
    log.info('Caught shutdown signal %d', sig_num)
    shutdown = True


def handle_reporting_side_effects(queue):
    while True:
        msg = queue.get()
        if msg is None:
            queue.task_done()
            break

        try:
            file, detections, conf = msg
            run_reporting_side_effects(file, detections, conf)
            try:
                os.remove(file.file_name)
            except FileNotFoundError:
                pass
            except BaseException as cleanup_error:
                log.warning("Failed to delete analyzed file %s: %s", file.file_name, cleanup_error)
        except BaseException as e:
            log.warning('Side-effect worker warning: %s', e)
        queue.task_done()


def run_reporting_side_effects(file, detections, conf):
    if detections is not None and conf is not None:
        if detections:
            apprise(file, detections, conf=conf)
            # Keep bird_weather on the dedicated side-effect worker to avoid I/O/requests
            # on the hot-path analysis/reporting loop.
            if conf.get('BIRDWEATHER_ID', ''):
                bird_weather(file, detections, conf=conf)
        heartbeat(conf=conf)
    elif conf:
        heartbeat(conf=conf)
    return


def main():
    load_global_model()
    conf = get_settings()
    i = inotify.adapters.Inotify()
    i.add_watch(os.path.join(conf['RECS_DIR'], 'StreamData'), mask=IN_CLOSE_WRITE)

    backlog = get_wav_files()
    report_queue = Queue(maxsize=_int_setting(conf, 'REPORT_QUEUE_MAX', 128))
    side_queue = Queue(maxsize=_int_setting(conf, 'REPORT_SIDE_QUEUE_MAX', 128))
    side_thread = threading.Thread(target=handle_reporting_side_effects, args=(side_queue,), daemon=True)
    thread = threading.Thread(target=handle_reporting_queue, args=(report_queue, side_queue))
    side_thread.start()
    thread.start()

    log.info('backlog is %d', len(backlog))
    backlog_set = set(backlog)
    for file_name in backlog:
        process_file(file_name, report_queue)
        if shutdown:
            break
    log.info('backlog done')

    empty_count = 0
    for event in i.event_gen():
        if shutdown:
            break

        if event is None:
            if empty_count > (conf.getint('RECORDING_LENGTH') * 2 + 30):
                log.error('no more notifications: restarting...')
                break
            empty_count += 1
            continue

        (_, type_names, path, file_name) = event
        if not file_name.endswith('.wav'):
            continue
        log.debug("PATH=[%s] FILENAME=[%s] EVENT_TYPES=%s", path, file_name, type_names)

        file_path = os.path.join(path, file_name)
        if file_path in backlog_set:
            # Skip events for files that were already queued from startup backlog.
            backlog_set.discard(file_path)
            continue

        process_file(file_path, report_queue)
        empty_count = 0

    # we're all done
    report_queue.put(None)
    thread.join()
    report_queue.join()
    side_queue.put(None)
    side_queue.join()
    side_thread.join(timeout=1)


def process_file(file_name, report_queue):
    try:
        if os.path.getsize(file_name) == 0:
            os.remove(file_name)
            return
        log.info('Analyzing %s', file_name)
        with open(ANALYZING_NOW, 'w') as analyzing:
            analyzing.write(file_name)
        file = ParseFileName(file_name)
        detections = run_analysis(file)
        report_queue.put((file, detections))
    except BaseException as e:
        stderr = e.stderr.decode('utf-8') if isinstance(e, CalledProcessError) else ""
        log.exception(f'Unexpected error: {stderr}', exc_info=e)
        try:
            os.remove(file_name)
        except FileNotFoundError:
            pass
        except BaseException as cleanup_error:
            log.warning("Failed to delete errored file %s: %s", file_name, cleanup_error)


def handle_reporting_queue(queue, side_queue):
    db_conn = sqlite3.connect(DB_PATH, timeout=30)
    db_conn.execute("PRAGMA journal_mode=WAL")
    db_conn.execute("PRAGMA synchronous=NORMAL")
    db_conn.execute("PRAGMA busy_timeout=2000")
    db_cursor = db_conn.cursor()
    conf = get_settings()
    while True:
        msg = queue.get()
        # check for signal that we are done
        if msg is None:
            break

        file, detections = msg
        file_removed = False
        side_queued = False
        try:
            update_json_file(file, detections, conf=conf)
            extracted_detections = []
            for detection in detections:
                detection.file_name_extr = extract_detection(file, detection, conf=conf)
                log.info('%s;%s', summary(file, detection, conf=conf), os.path.basename(detection.file_name_extr))
                extracted_detections.append(detection)
            write_detections_to_file(file, extracted_detections, conf=conf)
            write_detections_to_db(file, extracted_detections, connection=db_conn, cursor=db_cursor, conf=conf)
        except BaseException as e:
            stderr = e.stderr.decode('utf-8') if isinstance(e, CalledProcessError) else ""
            log.exception(f'Unexpected error: {stderr}', exc_info=e)
        finally:
            try:
                side_queue.put_nowait((file, detections, conf))
                side_queued = True
            except Full:
                try:
                    run_reporting_side_effects(file, detections, conf)
                    file_removed = True
                except BaseException as side_error:
                    log.warning("Side-effect fallback failed: %s", side_error)

                if file_removed:
                    pass
                else:
                    try:
                        os.remove(file.file_name)
                    except FileNotFoundError:
                        pass
                    except BaseException as cleanup_error:
                        log.warning("Failed to delete analyzed file %s: %s", file.file_name, cleanup_error)

            if not side_queued and not file_removed:
                try:
                    os.remove(file.file_name)
                except FileNotFoundError:
                    pass
                except BaseException as cleanup_error:
                    log.warning("Failed to delete analyzed file %s: %s", file.file_name, cleanup_error)

        queue.task_done()

    # mark the 'None' signal as processed
    db_conn.close()
    queue.task_done()
    log.info('handle_reporting_queue done')


def setup_logging():
    logger = logging.getLogger()
    formatter = logging.Formatter("[%(name)s][%(levelname)s] %(message)s")
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    global log
    log = logging.getLogger('birdnet_analysis')


if __name__ == '__main__':
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    setup_logging()

    main()
