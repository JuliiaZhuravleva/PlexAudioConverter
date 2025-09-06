"""
Direct State Management Tests - Testing state management components directly
These tests focus on the core state management functionality without AudioMonitor dependencies
"""
import pytest
import asyncio
import time
from pathlib import Path
from unittest.mock import patch, Mock

from tests.fixtures import (
    TempFS, FakeClock, FakeIntegrityChecker, StateStoreFixture,
    create_test_config, create_sample_video_file
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from state_management.manager import create_state_manager
from state_management.models import FileEntry


class TestDirectStateManagement:
    """Direct tests of state management components"""

    @pytest.mark.asyncio
    async def test_t001_direct_file_discovery_and_due_scheduling(self):
        """T-001: Direct file discovery creates records and schedules correctly"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Create a stable file
            video_file = temp_dir / "movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Create state manager with test store
            manager = create_state_manager()
            manager.store = test_store.store  # Use test store
            
            try:
                # Discover files in directory
                result = await manager.discover_directory(str(temp_dir))
                
                # Verify file was discovered
                assert result['files_added'] >= 1
                
                # Verify file exists in database  
                file_info = manager.get_file_info(str(video_file))
                assert file_info is not None
                assert file_info['integrity_status'] == IntegrityStatus.UNKNOWN.value
                assert file_info['processed_status'] == ProcessedStatus.NEW.value
                
                # Verify file is tracked in database
                test_store.assert_file_exists(
                    str(video_file),
                    integrity_status=IntegrityStatus.UNKNOWN,
                    processed_status=ProcessedStatus.NEW
                )
                
            finally:
                await manager.shutdown()

    def test_t002_size_stability_gate(self):
        """T-002: Size gate blocks integrity until file is stable"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "growing_movie.mkv"
            
            # Create initial small file
            create_sample_video_file(video_file, size_mb=10)
            
            config = create_test_config(stable_wait_sec=5)
            manager = StateManager(config, test_store.store)
            
            # Register the file
            file_entry = manager.register_file(str(video_file))
            
            # Simulate file growth by updating mtime and size
            time.sleep(0.1)
            with open(video_file, 'ab') as f:
                f.write(b'more_data' * 1000)  # Add more data
            
            # Update the file in state store (simulate detection of size change)
            current_stat = video_file.stat()
            test_store.store.update_file_size(str(video_file), current_stat.st_size, current_stat.st_mtime)
            
            # File should not be stable yet
            file_data = test_store.get_file_by_path(str(video_file))
            assert file_data['stable_since'] is None
            
            # Advance time but not enough for stability
            clock.advance(3)  # Only 3 seconds, need 5
            
            # File should still not be stable
            test_store.store.check_stability_and_schedule(str(video_file))
            updated_data = test_store.get_file_by_path(str(video_file))
            assert updated_data['stable_since'] is None

    def test_t003_stability_triggers_integrity_scheduling(self):
        """T-003: Stability triggers integrity check scheduling after N seconds"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "stable_movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            config = create_test_config(stable_wait_sec=5)
            manager = StateManager(config, test_store.store)
            
            # Register the file
            file_entry = manager.register_file(str(video_file))
            
            # Advance time to make file stable
            clock.advance(6)  # More than stable_wait_sec
            
            # Trigger stability check
            test_store.store.check_stability_and_schedule(str(video_file))
            
            # File should now be marked as stable and due for integrity check
            updated_data = test_store.get_file_by_path(str(video_file))
            assert updated_data['stable_since'] is not None
            
            # Should be in due list
            due_files = test_store.store.get_due_files(limit=10)
            assert len(due_files) == 1
            assert due_files[0].path == str(video_file)

    def test_t004_pending_status_prevents_duplicate_processing(self):
        """T-004: PENDING status prevents duplicate picks during processing"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "processing_movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            config = create_test_config(stable_wait_sec=1)
            manager = StateManager(config, test_store.store)
            
            # Register and make file due
            file_entry = manager.register_file(str(video_file))
            clock.advance(2)
            test_store.store.check_stability_and_schedule(str(video_file))
            
            # First pick should succeed
            due_files_1 = test_store.store.get_due_files(limit=1)
            assert len(due_files_1) == 1
            
            # Mark as PENDING (simulating processing started)
            test_store.store.set_integrity_status(str(video_file), IntegrityStatus.PENDING)
            
            # Second pick should not return this file
            due_files_2 = test_store.store.get_due_files(limit=10)
            assert len(due_files_2) == 0

    def test_t005_due_limit_batching(self):
        """T-005: DUE_LIMIT controls batch size for processing"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Create 5 files
            video_files = []
            config = create_test_config(stable_wait_sec=0, batch_size=3)  # DUE_LIMIT = 3
            manager = StateManager(config, test_store.store)
            
            for i in range(5):
                video_file = temp_dir / f"movie_{i}.mkv"
                create_sample_video_file(video_file, size_mb=10 + i)
                video_files.append(video_file)
                
                # Register each file
                manager.register_file(str(video_file))
            
            # All files should be due (stable_wait_sec=0)
            all_due = test_store.store.get_due_files(limit=100)
            assert len(all_due) == 5
            
            # First batch: should get 3 files (DUE_LIMIT)
            batch_1 = test_store.store.get_due_files(limit=3)
            assert len(batch_1) == 3
            
            # Mark first batch as PENDING
            for file_entry in batch_1:
                test_store.store.set_integrity_status(file_entry.path, IntegrityStatus.PENDING)
            
            # Second batch: should get remaining 2 files
            batch_2 = test_store.store.get_due_files(limit=3)
            assert len(batch_2) == 2
            
            # Third batch: should be empty
            batch_3 = test_store.store.get_due_files(limit=3)
            assert len(batch_3) == 0

    def test_t010_group_generation_for_stereo_pairs(self):
        """T-010: Group entries for .stereo + original files"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Create original and stereo files
            original_file = temp_dir / "TWD.S01E01.mkv" 
            stereo_file = temp_dir / "TWD.S01E01.stereo.mkv"
            
            create_sample_video_file(original_file, size_mb=100)
            create_sample_video_file(stereo_file, size_mb=50)
            
            config = create_test_config()
            manager = StateManager(config, test_store.store)
            
            # Register both files
            original_entry = manager.register_file(str(original_file))
            stereo_entry = manager.register_file(str(stereo_file))
            
            # Both should exist in database
            assert test_store.get_file_count() == 2
            
            # Check is_stereo detection
            original_data = test_store.get_file_by_path(str(original_file))
            stereo_data = test_store.get_file_by_path(str(stereo_file))
            
            assert original_data['is_stereo'] == False
            assert stereo_data['is_stereo'] == True
            
            # Should have same group_id
            assert original_data['group_id'] == stereo_data['group_id']
            
            # Should have one group
            assert test_store.get_group_count() == 1

    def test_t012_idle_performance_no_spinning(self):
        """T-012: Idle performance - no CPU spinning when no work"""
        with StateStoreFixture() as test_store:
            config = create_test_config()
            
            # Ensure no due files
            test_store.assert_no_due_files()
            
            # Multiple idle checks should be fast
            start_time = time.time()
            for _ in range(10):
                due_files = test_store.store.get_due_files(limit=10)
                assert len(due_files) == 0
                time.sleep(0.001)  # Tiny sleep to simulate real loop
            
            elapsed = time.time() - start_time
            
            # Should complete very quickly (< 0.1 seconds for 10 iterations)
            assert elapsed < 0.1, f"Idle operations took {elapsed}s, expected < 0.1s"

    def test_file_registration_idempotent(self):
        """Test that file registration is idempotent"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            config = create_test_config()
            manager = StateManager(config, test_store.store)
            
            # Register file multiple times
            entry1 = manager.register_file(str(video_file))
            entry2 = manager.register_file(str(video_file))
            entry3 = manager.register_file(str(video_file))
            
            # Should still have only one file
            assert test_store.get_file_count() == 1
            
            # Should have same IDs
            assert entry1.id == entry2.id == entry3.id
            
            # group_id should be stable
            assert entry1.group_id == entry2.group_id == entry3.group_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])