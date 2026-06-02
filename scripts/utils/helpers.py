import glob
import json
import os
import re
import subprocess
import time
from collections import OrderedDict
from configparser import ConfigParser
from itertools import chain

_settings = None
_language_cache = {}

BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(BASE_PATH, 'scripts/birds.db')
MODEL_PATH = os.path.join(BASE_PATH, 'model')
FONT_DIR = os.path.join(BASE_PATH, 'homepage/static')
ANALYZING_NOW = os.path.expanduser('~/BirdSongs/StreamData/analyzing_now.txt')


def _int_setting(conf, key, default):
    if key in os.environ:
        raw = os.environ[key]
    elif key in conf:
        raw = conf[key]
    else:
        raw = default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def get_font():
    conf = get_settings()
    if conf['DATABASE_LANG'] == 'ar':
        ret = {'font.family': 'Noto Sans Arabic', 'path': os.path.join(FONT_DIR, 'NotoSansArabic-Regular.ttf')}
    elif conf['DATABASE_LANG'] in ['ja', 'zh_CN', 'zh_TW']:
        ret = {'font.family': 'Noto Sans JP', 'path': os.path.join(FONT_DIR, 'NotoSansJP-Regular.ttf')}
    elif conf['DATABASE_LANG'] == 'ko':
        ret = {'font.family': 'Noto Sans KR', 'path': os.path.join(FONT_DIR, 'NotoSansKR-Regular.ttf')}
    elif conf['DATABASE_LANG'] == 'th':
        ret = {'font.family': 'Noto Sans Thai', 'path': os.path.join(FONT_DIR, 'NotoSansThai-Regular.ttf')}
    else:
        ret = {'font.family': 'Roboto Flex', 'path': os.path.join(FONT_DIR, 'RobotoFlex-Regular.ttf')}
    return ret


class PHPConfigParser(ConfigParser):
    def get(self, section, option, *, raw=False, vars=None, fallback=None):
        value = super().get(section, option, raw=raw, vars=vars, fallback=fallback)
        if raw or not isinstance(value, str):
            return value
        return value.strip('"')


def _load_settings(settings_path='/etc/birdnet/birdnet.conf', force_reload=False):
    global _settings
    if _settings is None or force_reload:
        with open(settings_path) as f:
            parser = PHPConfigParser(interpolation=None)
            # preserve case
            parser.optionxform = lambda option: option
            lines = chain(("[top]",), f)
            parser.read_file(lines)
            _settings = parser['top']
    return _settings


def get_settings(settings_path='/etc/birdnet/birdnet.conf', force_reload=False):
    settings = _load_settings(settings_path, force_reload)
    return settings


def _open_files_from_lsof(dir_name):
    result = subprocess.run(['lsof', '-w', '-Fn', '+D', f'{dir_name}'], check=False, capture_output=True)
    ret = result.stdout.decode('utf-8')
    err = result.stderr.decode('utf-8')
    if err:
        raise RuntimeError(f'{ret}:\n {err}')
    names = [line.lstrip('n') for line in ret.splitlines() if line.startswith('n')]
    return names


def _path_forms(path):
    if path.endswith(' (deleted)'):
        path = path[:-10]
    if not os.path.isabs(path):
        return []
    return [os.path.abspath(path), os.path.realpath(path)]


def _open_files_from_proc(dir_name, proc_dir='/proc'):
    # Scanning /proc fd links is much cheaper than lsof +D on large StreamData dirs.
    uid = os.getuid()
    roots = set(_path_forms(os.path.abspath(dir_name)))
    if not roots:
        return []
    prefixes = tuple(root.rstrip(os.sep) + os.sep for root in roots)
    try:
        pids = os.listdir(proc_dir)
    except OSError as exc:
        raise RuntimeError(f'cannot inspect {proc_dir}: {exc}')

    open_files = set()
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            if os.stat(os.path.join(proc_dir, pid)).st_uid != uid:
                continue
        except OSError:
            continue
        fd_dir = os.path.join(proc_dir, pid, 'fd')
        try:
            fds = os.listdir(fd_dir)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for fd in fds:
            fd_path = os.path.join(fd_dir, fd)
            try:
                forms = _path_forms(os.readlink(fd_path))
            except (FileNotFoundError, OSError, PermissionError):
                continue
            if any(form in roots or form.startswith(prefixes) for form in forms):
                open_files.update(forms)
    return list(open_files)


def get_open_files_in_dir(dir_name):
    try:
        return _open_files_from_proc(dir_name)
    except RuntimeError:
        return _open_files_from_lsof(dir_name)


def get_wav_files():
    conf = get_settings()
    files = (glob.glob(os.path.join(conf['RECS_DIR'], '*/*/*.wav')) +
             glob.glob(os.path.join(conf['RECS_DIR'], 'StreamData/*.wav')))
    files.sort()
    rec_dir = os.path.join(conf['RECS_DIR'], 'StreamData')
    open_recs = set(get_open_files_in_dir(rec_dir))
    files = [file for file in files if file not in open_recs]
    return prune_stream_backlog(files, conf)


def prune_stream_backlog(files, conf, now=None):
    rec_dir = os.path.join(conf['RECS_DIR'], 'StreamData')
    now = time.time() if now is None else now
    try:
        recording_length = max(1, _int_setting(conf, 'RECORDING_LENGTH', 15))
    except TypeError:
        recording_length = 15
    default_max_files = max(20, min(240, int(1800 / recording_length)))
    max_files = _int_setting(conf, 'STREAM_BACKLOG_MAX_FILES', default_max_files)
    max_age = _int_setting(conf, 'STREAM_BACKLOG_MAX_AGE_SECONDS', 1800)
    if max_files <= 0 and max_age <= 0:
        return files

    stream_files = []
    other_files = []
    for file in files:
        if os.path.dirname(file) == rec_dir:
            stream_files.append(file)
        else:
            other_files.append(file)
    if not stream_files:
        return files

    def file_mtime(path):
        try:
            return os.path.getmtime(path)
        except FileNotFoundError:
            return 0

    newest_first = sorted(stream_files, key=file_mtime, reverse=True)
    keep = set()
    for index, file in enumerate(newest_first):
        if max_files > 0 and index >= max_files:
            continue
        if max_age > 0 and now - file_mtime(file) > max_age:
            continue
        keep.add(file)

    for file in stream_files:
        if file in keep:
            continue
        try:
            os.remove(file)
        except FileNotFoundError:
            pass

    return sorted(other_files + [file for file in stream_files if file in keep])


def get_language(language=None, copy=True):
    if language is None:
        language = get_settings()['DATABASE_LANG']
    file_name = os.path.join(MODEL_PATH, f'l18n/labels_{language}.json')
    try:
        stat = os.stat(file_name)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        stamp = None
    cached = _language_cache.get(language)
    if cached is None or cached[0] != stamp:
        with open(file_name) as f:
            labels = json.loads(f.read())
        cached = (stamp, labels)
        _language_cache[language] = cached
    return dict(cached[1]) if copy else cached[1]


def save_language(labels, language):
    file_name = os.path.join(MODEL_PATH, f'l18n/labels_{language}.json')
    with open(file_name, 'w') as f:
        f.write(json.dumps(OrderedDict(sorted(labels.items())), indent=2, ensure_ascii=False))
    _language_cache.pop(language, None)


def get_model_labels(model=None):
    if model is None:
        model = get_settings()['MODEL']
    file_name = os.path.join(MODEL_PATH, f'{model}_Labels.txt')
    with open(file_name) as f:
        labels = [line.strip() for line in f.readlines()]
    if labels and labels[0].count('_') == 1:
        labels = [re.sub(r'_.+$', '', label) for label in labels]
    return labels


def set_label_file():
    lang = get_language()
    labels = [f'{label}_{lang[label]}\n' for label in get_model_labels()]
    file_name = os.path.join(MODEL_PATH, 'labels.txt')
    if os.path.islink(file_name):
        os.remove(file_name)
    with open(file_name, 'w') as f:
        f.writelines(labels)
