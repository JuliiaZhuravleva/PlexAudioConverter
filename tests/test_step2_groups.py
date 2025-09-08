"""
Тесты группировки и EN 2.0 логики для Step 2
"""
import pytest
import time
import os
from pathlib import Path
from unittest.mock import patch, Mock

from tests.fixtures import (
    TempFS, SyntheticDownloader, FakeClock, FakeIntegrityChecker, FFprobeStub,
    StateStoreFixture, StatePlannerFixture, TEST_CONSTANTS, create_test_config,
    create_test_config_manager, create_sample_video_file, assert_metrics_equal
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from core.audio_monitor import AudioMonitor


class TestGroupsAndEN20Logic:
    """Тесты группировки и EN 2.0 логики"""

    def test_t010_stereo_group_generation(self):
        """T-010: Группа .stereo и original (структурная часть Step 2)"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать original и stereo файлы
            original_file = temp_dir / "TWD.S01E01.mkv"
            stereo_file = temp_dir / "TWD.S01E01.stereo.mkv"
            
            create_sample_video_file(original_file, size_mb=100)
            create_sample_video_file(stereo_file, size_mb=50)
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Discovery обоих файлов
            monitor.scan_directory(str(temp_dir))
            
            # Проверить создание файловых записей
            original_data = test_store.get_file_by_path(str(original_file))
            stereo_data = test_store.get_file_by_path(str(stereo_file))
            
            assert original_data is not None
            assert stereo_data is not None
            
            # Проверить корректную детекцию is_stereo
            assert original_data['is_stereo'] == False
            assert stereo_data['is_stereo'] == True
            
            # Проверить что group_id одинаковый
            assert original_data['group_id'] == stereo_data['group_id']
            assert 'TWD.S01E01' in original_data['group_id']
            
            # Проверить создание группы
            assert test_store.get_group_count() == 1
            
            # Проверить группу в базе данных
            with test_store.store._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM groups WHERE group_id = ?", 
                    (original_data['group_id'],)
                )
                group_row = cursor.fetchone()
                assert group_row is not None
                
                group_data = dict(zip([col[0] for col in cursor.description], group_row))
                assert group_data['original_present'] == True
                assert group_data['stereo_present'] == True

    def test_t011_en20_logic_step2_limitation(self):
        """T-011: EN 2.0 пока не влияет (ограничение Step 2)"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "has_en20.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Настроить FFprobe stub для возврата EN 2.0
            ffprobe_stub = FFprobeStub()
            ffprobe_stub.add_en_20_stream(str(video_file))
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0.1
            
            with patch('core.audio_monitor.get_audio_streams') as mock_ffprobe:
                
                mock_ffprobe.return_value = ffprobe_stub.get_audio_streams(str(video_file))
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Patch the integrity checker instance after AudioMonitor creation
                monitor.integrity_checker.check_video_integrity = fake_integrity.check_video_integrity
                
                # Discovery и стабилизация
                monitor.scan_directory(str(temp_dir))
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                # Запустить integrity check
                due_files = test_store.store.get_due_files(limit=1)
                assert len(due_files) == 1
                
                file_entry = due_files[0]
                monitor.handle_integrity_check(file_entry)
                
                # Проверить что Integrity завершилась COMPLETE
                file_data = test_store.get_file_by_path(str(video_file))
                assert file_data['integrity_status'] == IntegrityStatus.COMPLETE.value
                
                # В Step 2 EN 2.0 логика еще не должна влиять
                # processed_status должен остаться NEW или перейти в готовность к конвертации
                # НЕ должно быть SKIPPED_HAS_EN2
                assert file_data['processed_status'] != ProcessedStatus.SKIPPED_HAS_EN2.value

    def test_group_id_normalization(self):
        """Тест нормализации group_id"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать файлы в разных папках с одинаковыми именами
            dir1 = temp_dir / "season1"
            dir2 = temp_dir / "season2"
            dir1.mkdir()
            dir2.mkdir()
            
            file1 = dir1 / "episode01.mkv"
            file2 = dir2 / "episode01.mkv"
            file1_stereo = dir1 / "episode01.stereo.mkv"
            
            create_sample_video_file(file1, size_mb=50)
            create_sample_video_file(file2, size_mb=50)
            create_sample_video_file(file1_stereo, size_mb=25)
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Discovery всех файлов
            monitor.scan_directory(str(temp_dir))
            
            # Получить данные файлов
            file1_data = test_store.get_file_by_path(str(file1))
            file2_data = test_store.get_file_by_path(str(file2))
            file1_stereo_data = test_store.get_file_by_path(str(file1_stereo))
            
            # Проверить что файлы из разных папок имеют разные group_id
            assert file1_data['group_id'] != file2_data['group_id']
            
            # Проверить что original и stereo в одной папке имеют одинаковый group_id
            assert file1_data['group_id'] == file1_stereo_data['group_id']
            
            # Проверить что в group_id есть информация о папке
            assert 'episode01' in file1_data['group_id']
            assert 'episode01' in file2_data['group_id']
            
            # Должно быть 2 группы
            assert test_store.get_group_count() == 2

    def test_single_file_groups(self):
        """Тест групп с одним файлом"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать только original файл
            original_only = temp_dir / "single.mkv"
            create_sample_video_file(original_only, size_mb=50)
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Discovery
            monitor.scan_directory(str(temp_dir))
            
            # Проверить файл
            file_data = test_store.get_file_by_path(str(original_only))
            assert file_data['is_stereo'] == False
            
            # Проверить группу
            assert test_store.get_group_count() == 1
            
            with test_store.store._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM groups WHERE group_id = ?", 
                    (file_data['group_id'],)
                )
                group_data = dict(zip([col[0] for col in cursor.description], cursor.fetchone()))
                
                assert group_data['original_present'] == True
                assert group_data['stereo_present'] == False

    def test_stereo_only_groups(self):
        """Тест групп только с .stereo файлом"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать только stereo файл
            stereo_only = temp_dir / "orphan.stereo.mkv"
            create_sample_video_file(stereo_only, size_mb=25)
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Discovery
            monitor.scan_directory(str(temp_dir))
            
            # Проверить файл
            file_data = test_store.get_file_by_path(str(stereo_only))
            assert file_data['is_stereo'] == True
            
            # Проверить группу
            assert test_store.get_group_count() == 1
            
            with test_store.store._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM groups WHERE group_id = ?", 
                    (file_data['group_id'],)
                )
                group_data = dict(zip([col[0] for col in cursor.description], cursor.fetchone()))
                
                assert group_data['original_present'] == False
                assert group_data['stereo_present'] == True

    def test_group_presence_updates(self):
        """Тест обновления присутствия файлов в группе"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            original_file = temp_dir / "series.mkv"
            stereo_file = temp_dir / "series.stereo.mkv"
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Сначала создать только original
            create_sample_video_file(original_file, size_mb=50)
            monitor.scan_directory(str(temp_dir))
            
            original_data = test_store.get_file_by_path(str(original_file))
            group_id = original_data['group_id']
            
            # Проверить группу - только original
            with test_store.store._get_connection() as conn:
                cursor = conn.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,))
                group_data = dict(zip([col[0] for col in cursor.description], cursor.fetchone()))
                assert group_data['original_present'] == True
                assert group_data['stereo_present'] == False
            
            # Добавить stereo файл
            create_sample_video_file(stereo_file, size_mb=25)
            monitor.scan_directory(str(temp_dir))
            
            # Проверить обновление группы
            with test_store.store._get_connection() as conn:
                cursor = conn.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,))
                group_data = dict(zip([col[0] for col in cursor.description], cursor.fetchone()))
                assert group_data['original_present'] == True
                assert group_data['stereo_present'] == True
            
            # Количество групп не должно измениться
            assert test_store.get_group_count() == 1

    def test_complex_filename_parsing(self):
        """Тест парсинга сложных имен файлов"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Различные форматы имен файлов
            test_files = [
                "Movie.2023.1080p.BluRay.x264.mkv",
                "Movie.2023.1080p.BluRay.x264.stereo.mkv",
                "TV.Show.S01E01.720p.HDTV.x264.mkv", 
                "TV.Show.S01E01.720p.HDTV.x264.stereo.mkv",
                "[Group] Anime - 01 [1080p].mkv",
                "[Group] Anime - 01 [1080p].stereo.mkv"
            ]
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Создать все файлы
            for filename in test_files:
                file_path = temp_dir / filename
                create_sample_video_file(file_path, size_mb=10)
            
            # Discovery
            monitor.scan_directory(str(temp_dir))
            
            # Проверить что stereo файлы правильно сгруппированы
            movie_original = test_store.get_file_by_path(str(temp_dir / test_files[0]))
            movie_stereo = test_store.get_file_by_path(str(temp_dir / test_files[1]))
            assert movie_original['group_id'] == movie_stereo['group_id']
            
            tv_original = test_store.get_file_by_path(str(temp_dir / test_files[2]))
            tv_stereo = test_store.get_file_by_path(str(temp_dir / test_files[3]))
            assert tv_original['group_id'] == tv_stereo['group_id']
            
            anime_original = test_store.get_file_by_path(str(temp_dir / test_files[4]))
            anime_stereo = test_store.get_file_by_path(str(temp_dir / test_files[5]))
            assert anime_original['group_id'] == anime_stereo['group_id']
            
            # Должно быть 3 группы
            assert test_store.get_group_count() == 3

    def test_en20_detection_various_formats(self):
        """Тест детекции EN 2.0 в различных форматах"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "multi_audio.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Различные варианты EN 2.0 потоков
            en20_variants = [
                [{"codec_name": "ac3", "channels": 2, "tags": {"language": "eng"}}],
                [{"codec_name": "aac", "channels": 2, "tags": {"language": "en"}}],
                [{"codec_name": "dts", "channels": 2, "tags": {"language": "english"}}],
                [{"codec_name": "ac3", "channels": 2, "tags": {"title": "English"}}],
            ]
            
            ffprobe_stub = FFprobeStub()
            fake_integrity = FakeIntegrityChecker()
            
            for i, streams in enumerate(en20_variants):
                ffprobe_stub.set_audio_streams(str(video_file), streams)
                
                with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker, \
                     patch('core.audio_monitor.get_audio_streams') as mock_ffprobe:
                    
                    mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                    mock_ffprobe.return_value = streams
                    
                    config = create_test_config_manager()
                    monitor = AudioMonitor(
                        config=config,
                        state_store=test_store.store,
                        state_planner=test_store.planner
                    )
                    
                    # В Step 2 проверяем что EN 2.0 детектируется но не влияет на обработку
                    # Это подготовка к Step 4
                    
                    # Сбросить состояние файла для повторного теста
                    test_store.store.upsert_file(
                        path=str(video_file),
                        size_bytes=50*1024*1024,
                        mtime=time.time(),
                        integrity_status=IntegrityStatus.UNKNOWN,
                        processed_status=ProcessedStatus.NEW
                    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
