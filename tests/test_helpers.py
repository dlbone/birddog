import os
import json
import sqlite3
import datetime as dt
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.utils.helpers import _open_files_from_proc, get_language, prune_stream_backlog
from scripts.utils import helpers
from scripts import bird_collage
from tests.helpers import Settings

try:
    from scripts.utils import reporting
except ModuleNotFoundError:
    reporting = None

try:
    from scripts.utils import analysis
except ModuleNotFoundError:
    analysis = None


class TestStreamBacklogPruning(unittest.TestCase):

    def test_prunes_only_stale_stream_files(self):
        with tempfile.TemporaryDirectory() as root:
            stream = os.path.join(root, 'StreamData')
            saved = os.path.join(root, 'saved', 'bird')
            os.makedirs(stream)
            os.makedirs(saved)
            now = 100000

            old_stream = os.path.join(stream, 'old.wav')
            keep_stream = os.path.join(stream, 'keep.wav')
            saved_file = os.path.join(saved, 'saved.wav')
            for path in (old_stream, keep_stream, saved_file):
                with open(path, 'wb') as handle:
                    handle.write(b'wav')
            os.utime(old_stream, (now - 4000, now - 4000))
            os.utime(keep_stream, (now - 60, now - 60))
            os.utime(saved_file, (now - 4000, now - 4000))

            conf = Settings({
                'RECS_DIR': root,
                'RECORDING_LENGTH': '15',
                'STREAM_BACKLOG_MAX_FILES': '20',
                'STREAM_BACKLOG_MAX_AGE_SECONDS': '1800',
            })
            result = prune_stream_backlog([old_stream, keep_stream, saved_file], conf, now=now)

            self.assertNotIn(old_stream, result)
            self.assertIn(keep_stream, result)
            self.assertIn(saved_file, result)
            self.assertFalse(os.path.exists(old_stream))
            self.assertTrue(os.path.exists(saved_file))

    def test_can_disable_stream_pruning(self):
        with tempfile.TemporaryDirectory() as root:
            stream = os.path.join(root, 'StreamData')
            os.makedirs(stream)
            old_stream = os.path.join(stream, 'old.wav')
            with open(old_stream, 'wb') as handle:
                handle.write(b'wav')
            conf = Settings({
                'RECS_DIR': root,
                'RECORDING_LENGTH': '15',
                'STREAM_BACKLOG_MAX_FILES': '0',
                'STREAM_BACKLOG_MAX_AGE_SECONDS': '0',
            })

            result = prune_stream_backlog([old_stream], conf, now=100000)

            self.assertEqual([old_stream], result)
            self.assertTrue(os.path.exists(old_stream))

    def test_proc_open_file_scan_finds_stream_fd_without_lsof(self):
        with tempfile.TemporaryDirectory() as root:
            stream = os.path.join(root, 'StreamData')
            outside = os.path.join(root, 'Other')
            proc_fd = os.path.join(root, 'proc', '123', 'fd')
            os.makedirs(stream)
            os.makedirs(outside)
            os.makedirs(proc_fd)

            open_stream = os.path.join(stream, 'current.wav')
            open_other = os.path.join(outside, 'other.wav')
            for path in (open_stream, open_other):
                with open(path, 'wb') as handle:
                    handle.write(b'wav')
            os.symlink(open_stream, os.path.join(proc_fd, '3'))
            os.symlink(open_other, os.path.join(proc_fd, '4'))

            result = _open_files_from_proc(stream, proc_dir=os.path.join(root, 'proc'))

            self.assertIn(open_stream, result)
            self.assertNotIn(open_other, result)


class TestCachedStaticLookups(unittest.TestCase):

    @unittest.skipIf(analysis is None, "librosa dependency unavailable")
    def test_custom_species_list_reloads_when_file_changes(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'include_species_list.txt')
            analysis.CUSTOM_SPECIES_LIST_CACHE.clear()
            with open(path, 'w') as handle:
                handle.write('Buteo lineatus_Red-shouldered Hawk\n')

            first = analysis.loadCustomSpeciesList(path)
            with open(path, 'w') as handle:
                handle.write('Myiarchus crinitus_Great Crested Flycatcher\n')
            os.utime(path, None)
            second = analysis.loadCustomSpeciesList(path)

            self.assertEqual(['Buteo lineatus'], first)
            self.assertEqual(['Myiarchus crinitus'], second)

    def test_language_cache_preserves_copy_default(self):
        with tempfile.TemporaryDirectory() as root:
            model_path = os.path.join(root, 'model')
            os.makedirs(os.path.join(model_path, 'l18n'))
            labels_path = os.path.join(model_path, 'l18n', 'labels_en.json')
            with open(labels_path, 'w') as handle:
                handle.write('{"Buteo lineatus": "Red-shouldered Hawk"}')
            helpers._language_cache.clear()

            with patch.object(helpers, 'MODEL_PATH', model_path):
                first = get_language('en')
                first['Buteo lineatus'] = 'changed'
                second = get_language('en')
                shared = get_language('en', copy=False)
                shared_again = get_language('en', copy=False)

            self.assertEqual('Red-shouldered Hawk', second['Buteo lineatus'])
            self.assertIs(shared, shared_again)


class TestCollageMetadataState(unittest.TestCase):

    def test_metadata_lookup_uses_cached_description(self):
        with tempfile.TemporaryDirectory() as root:
            meta = {
                'Buteo lineatus': {
                    'description': 'A small hawk.',
                    'date_created': dt.date.today().isoformat(),
                }
            }
            meta_path = os.path.join(root, 'meta.json')
            with open(meta_path, 'w', encoding='utf-8') as handle:
                json.dump(meta, handle)

            with patch.object(bird_collage, 'META_PATH', meta_path):
                self.assertFalse(bird_collage.metadata_lookup_pending({'sci_name': 'Buteo lineatus'}))

    def test_new_bird_badge_state_expires_after_24_hours(self):
        now = dt.datetime(2026, 6, 3, 10, 0, 0)

        self.assertTrue(bird_collage.is_new_bird('2026-06-02 10:00:00', now=now))
        self.assertTrue(bird_collage.is_new_bird('2026-06-03 09:59:59', now=now))
        self.assertFalse(bird_collage.is_new_bird('2026-06-02 09:59:59', now=now))
        self.assertFalse(bird_collage.is_new_bird('manual seed', now=now))


class TestReportingBatchDbWrites(unittest.TestCase):

    @unittest.skipIf(reporting is None, "BirdNET reporting dependencies unavailable")

    def detection(self, time, sci_name, common_name, confidence, file_name):
        return SimpleNamespace(
            date='2026-06-02',
            time=time,
            scientific_name=sci_name,
            common_name=common_name,
            confidence=confidence,
            week=23,
            file_name_extr=file_name,
        )

    def test_writes_multiple_detections_in_one_call(self):
        with tempfile.TemporaryDirectory() as root:
            db_path = os.path.join(root, 'birds.db')
            con = sqlite3.connect(db_path)
            con.execute("""
                CREATE TABLE detections (
                  Date DATE,
                  Time TIME,
                  Sci_Name VARCHAR(100) NOT NULL,
                  Com_Name VARCHAR(100) NOT NULL,
                  Confidence FLOAT,
                  Lat FLOAT,
                  Lon FLOAT,
                  Cutoff FLOAT,
                  Week INT,
                  Sens FLOAT,
                  Overlap FLOAT,
                  File_Name VARCHAR(100) NOT NULL
                )
            """)
            con.commit()
            con.close()

            settings = Settings.with_defaults()
            settings.update({
                'LATITUDE': '36.0',
                'LONGITUDE': '-79.0',
                'CONFIDENCE': '0.7',
                'SENSITIVITY': '1.25',
                'OVERLAP': '0.0',
            })
            detections = [
                self.detection('16:01:01', 'Buteo lineatus', 'Red-shouldered Hawk', 0.91, '/tmp/hawk-91.mp3'),
                self.detection('16:01:04', 'Myiarchus crinitus', 'Great Crested Flycatcher', 0.78, '/tmp/flycatcher-78.mp3'),
            ]

            with patch.object(reporting, 'DB_PATH', db_path), \
                 patch.object(reporting, 'get_settings', return_value=settings):
                reporting.write_detections_to_db(SimpleNamespace(), detections)

            con = sqlite3.connect(db_path)
            rows = con.execute('SELECT Sci_Name, File_Name FROM detections ORDER BY Time').fetchall()
            con.close()

            self.assertEqual([
                ('Buteo lineatus', 'hawk-91.mp3'),
                ('Myiarchus crinitus', 'flycatcher-78.mp3'),
            ], rows)

    def test_appends_multiple_birddb_rows_in_one_call(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, 'BirdNET-Pi'))
            settings = Settings.with_defaults()
            settings.update({
                'LATITUDE': '36.0',
                'LONGITUDE': '-79.0',
                'CONFIDENCE': '0.7',
                'SENSITIVITY': '1.25',
                'OVERLAP': '0.0',
            })
            detections = [
                self.detection('16:01:01', 'Buteo lineatus', 'Red-shouldered Hawk', 0.91, '/tmp/hawk-91.mp3'),
                self.detection('16:01:04', 'Myiarchus crinitus', 'Great Crested Flycatcher', 0.78, '/tmp/flycatcher-78.mp3'),
            ]

            with patch.dict(os.environ, {'HOME': root}), \
                 patch.object(reporting, 'get_settings', return_value=settings):
                reporting.write_detections_to_file(SimpleNamespace(), detections)

            with open(os.path.join(root, 'BirdNET-Pi', 'BirdDB.txt')) as handle:
                lines = handle.readlines()

            self.assertEqual(2, len(lines))
            self.assertIn('Buteo lineatus;Red-shouldered Hawk;0.91', lines[0])
            self.assertIn('Myiarchus crinitus;Great Crested Flycatcher;0.78', lines[1])


class TestReportingJsonStatus(unittest.TestCase):

    def setUp(self):
        if reporting is None:
            self.skipTest("BirdNET reporting dependencies unavailable")
        reporting._LAST_JSON_BY_STREAM.clear()
        reporting._JSON_CLEANUP_COUNTER.clear()

    def test_status_json_cleanup_uses_cached_previous_file(self):
        with tempfile.TemporaryDirectory() as root:
            settings = Settings.with_defaults()
            settings['RECORDING_LENGTH'] = '15'
            first = SimpleNamespace(
                file_name=os.path.join(root, '2026-06-02-birdnet-10:00:00.wav'),
                RTSP_id=None,
                iso8601='2026-06-02T10:00:00',
            )
            second = SimpleNamespace(
                file_name=os.path.join(root, '2026-06-02-birdnet-10:00:15.wav'),
                RTSP_id=None,
                iso8601='2026-06-02T10:00:15',
            )

            with patch.object(reporting, 'get_settings', return_value=settings):
                reporting.update_json_file(first, [])
                self.assertTrue(os.path.exists(first.file_name + '.json'))
                reporting.update_json_file(second, [])

            self.assertFalse(os.path.exists(first.file_name + '.json'))
            self.assertTrue(os.path.exists(second.file_name + '.json'))

    def test_status_json_first_write_removes_stale_files(self):
        with tempfile.TemporaryDirectory() as root:
            stale = os.path.join(root, 'old.wav.json')
            with open(stale, 'w') as handle:
                handle.write('{}')
            settings = Settings.with_defaults()
            settings['RECORDING_LENGTH'] = '15'
            current = SimpleNamespace(
                file_name=os.path.join(root, '2026-06-02-birdnet-10:00:00.wav'),
                RTSP_id=None,
                iso8601='2026-06-02T10:00:00',
            )

            with patch.object(reporting, 'get_settings', return_value=settings):
                reporting.update_json_file(current, [])

            self.assertFalse(os.path.exists(stale))
            self.assertTrue(os.path.exists(current.file_name + '.json'))


class TestCollageIndexQueries(unittest.TestCase):

    def test_species_recordings_are_limited_to_latest_six(self):
        with tempfile.TemporaryDirectory() as root:
            db_path = os.path.join(root, 'birds.db')
            con = sqlite3.connect(db_path)
            con.row_factory = sqlite3.Row
            con.execute("""
                CREATE TABLE detections (
                  Date DATE,
                  Time TIME,
                  Sci_Name VARCHAR(100) NOT NULL,
                  Com_Name VARCHAR(100) NOT NULL,
                  Confidence FLOAT,
                  Lat FLOAT,
                  Lon FLOAT,
                  Cutoff FLOAT,
                  Week INT,
                  Sens FLOAT,
                  Overlap FLOAT,
                  File_Name VARCHAR(100) NOT NULL
                )
            """)
            bird_collage.ensure_detection_indexes(con)
            for i in range(10):
                con.execute(
                    "INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        '2026-06-02',
                        f'12:00:{i:02d}',
                        'Buteo lineatus',
                        'Red-shouldered Hawk',
                        0.8,
                        36.0,
                        -79.0,
                        0.7,
                        23,
                        1.25,
                        0.0,
                        f'hawk-{i}.mp3',
                    ),
                )
            con.commit()

            species = bird_collage.get_species(1000000, 1, conn=con, labels={
                'Buteo lineatus': 'Red-shouldered Hawk',
            })
            con.close()

            recordings = species[0]['recordings']
            self.assertEqual(6, len(recordings))
            self.assertEqual(['hawk-9.mp3', 'hawk-8.mp3', 'hawk-7.mp3', 'hawk-6.mp3', 'hawk-5.mp3', 'hawk-4.mp3'], [
                rec['file_name'] for rec in recordings
            ])

    def test_species_limit_zero_returns_all_species(self):
        with tempfile.TemporaryDirectory() as root:
            db_path = os.path.join(root, 'birds.db')
            con = sqlite3.connect(db_path)
            con.row_factory = sqlite3.Row
            con.execute("""
                CREATE TABLE detections (
                  Date DATE,
                  Time TIME,
                  Sci_Name VARCHAR(100) NOT NULL,
                  Com_Name VARCHAR(100) NOT NULL,
                  Confidence FLOAT,
                  Lat FLOAT,
                  Lon FLOAT,
                  Cutoff FLOAT,
                  Week INT,
                  Sens FLOAT,
                  Overlap FLOAT,
                  File_Name VARCHAR(100) NOT NULL
                )
            """)
            bird_collage.ensure_detection_indexes(con)
            detections = [
                ('2026-06-02', '12:00:00', 'Buteo lineatus', 'Red-shouldered Hawk', 'hawk.mp3'),
                ('2026-06-02', '12:01:00', 'Cardinalis cardinalis', 'Northern Cardinal', 'cardinal.mp3'),
                ('2026-06-02', '12:02:00', 'Sialia sialis', 'Eastern Bluebird', 'bluebird.mp3'),
            ]
            for date, time, sci_name, com_name, file_name in detections:
                con.execute(
                    "INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        date,
                        time,
                        sci_name,
                        com_name,
                        0.8,
                        36.0,
                        -79.0,
                        0.7,
                        23,
                        1.25,
                        0.0,
                        file_name,
                    ),
                )
            con.commit()

            species = bird_collage.get_species(1000000, 0, conn=con, labels={})
            con.close()

            self.assertEqual(3, len(species))
            self.assertEqual([
                'Eastern Bluebird',
                'Northern Cardinal',
                'Red-shouldered Hawk',
            ], [bird['com_name'] for bird in species])


if __name__ == '__main__':
    unittest.main()
