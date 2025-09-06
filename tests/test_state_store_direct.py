"""
Direct State Store Tests - Testing state store functionality directly
These tests verify the core state management storage operations
"""
import pytest
import time
from pathlib import Path

from tests.fixtures import (
    TempFS, FakeClock, StateStoreFixture, create_sample_video_file
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from state_management.models import create_file_entry_from_path


class TestStateStoreDirect:
    """Direct tests of StateStore functionality"""

    def test_t001_file_registration_and_due_scheduling(self):
        """T-001: File registration creates records and schedules correctly"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Create a stable file
            video_file = temp_dir / "movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Create and add file entry to store
            entry = create_file_entry_from_path(str(video_file))
            stored_entry = test_store.store.upsert_file(entry)
            
            # Verify file was created in database
            test_store.assert_file_exists(
                str(video_file),
                integrity_status=IntegrityStatus.UNKNOWN,
                processed_status=ProcessedStatus.NEW
            )
            
            # Verify file has group_id
            file_data = test_store.get_file_by_path(str(video_file))
            assert file_data['group_id'] is not None
            assert 'movie' in file_data['group_id']
            
            # Verify file is due for processing
            due_files = test_store.store.get_due_files(limit=10)
            assert len(due_files) >= 1
            due_paths = [f.path for f in due_files]
            assert str(video_file) in due_paths

    def test_t004_pending_status_prevents_duplicate_processing(self):
        """T-004: PENDING status prevents duplicate picks during processing"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "processing_movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Create and add file entry to store
            entry = create_file_entry_from_path(str(video_file))
            stored_entry = test_store.store.upsert_file(entry)
            
            # First pick should succeed
            due_files_1 = test_store.store.get_due_files(limit=1)
            assert len(due_files_1) == 1
            assert due_files_1[0].path == str(video_file)
            
            # Mark as PENDING (simulating processing started)
            file_entry = test_store.store.get_file(str(video_file))
            file_entry.integrity_status = IntegrityStatus.PENDING
            test_store.store.upsert_file(file_entry)
            
            # Second pick should not return this file
            due_files_2 = test_store.store.get_due_files(limit=10)
            pending_paths = [f.path for f in due_files_2 if f.path == str(video_file)]
            assert len(pending_paths) == 0

    def test_t005_due_limit_batching(self):
        """T-005: DUE_LIMIT controls batch size for processing"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Create 5 files
            video_files = []
            
            for i in range(5):
                video_file = temp_dir / f"movie_{i}.mkv"
                create_sample_video_file(video_file, size_mb=10 + i)
                video_files.append(video_file)
                
                # Create and add each file to store
                entry = create_file_entry_from_path(str(video_file))
                test_store.store.upsert_file(entry)
            
            # All files should be due
            all_due = test_store.store.get_due_files(limit=100)
            assert len(all_due) == 5
            
            # First batch: should get 3 files (using TEST_CONSTANTS DUE_LIMIT)
            batch_1 = test_store.store.get_due_files(limit=3)
            assert len(batch_1) == 3
            
            # Mark first batch as PENDING with future next_check_at
            import time
            future_time = int(time.time()) + 3600  # 1 hour in future
            for file_entry in batch_1:
                file_entry.integrity_status = IntegrityStatus.PENDING
                file_entry.next_check_at = future_time
                test_store.store.upsert_file(file_entry)
            
            # Second batch: should get remaining 2 files
            batch_2 = test_store.store.get_due_files(limit=3)
            assert len(batch_2) == 2
            
            # Mark second batch as PENDING too
            for file_entry in batch_2:
                file_entry.integrity_status = IntegrityStatus.PENDING
                file_entry.next_check_at = future_time
                test_store.store.upsert_file(file_entry)
            
            # Third batch: should be empty (all files are now PENDING)
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
            
            # Create and add original file first
            original_entry = create_file_entry_from_path(str(original_file))
            stored_original = test_store.store.upsert_file(original_entry)
            
            # Update group presence after original file (NONE -> WAITING_PAIR)
            test_store.store.update_group_presence(stored_original.group_id)
            
            # Add stereo file
            stereo_entry = create_file_entry_from_path(str(stereo_file))
            stored_stereo = test_store.store.upsert_file(stereo_entry)
            
            # Update group presence after stereo file (WAITING_PAIR -> PAIRED)
            test_store.store.update_group_presence(stored_original.group_id)
            
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
        """Test that file registration is idempotent (upsert behavior)"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            file_stat = video_file.stat()
            
            # Add file multiple times with same parameters
            entry1 = create_file_entry_from_path(str(video_file))
            stored_entry1 = test_store.store.upsert_file(entry1)
            
            # For subsequent upserts, get the existing file first to preserve ID
            existing_entry = test_store.store.get_file(str(video_file))
            stored_entry2 = test_store.store.upsert_file(existing_entry)
            
            existing_entry_again = test_store.store.get_file(str(video_file))
            stored_entry3 = test_store.store.upsert_file(existing_entry_again)
            
            # Should still have only one file
            assert test_store.get_file_count() == 1
            
            # Should have same IDs (upsert behavior)
            assert stored_entry1.id == stored_entry2.id == stored_entry3.id
            
            # group_id should be stable
            assert stored_entry1.group_id == stored_entry2.group_id == stored_entry3.group_id

    def test_integrity_status_transitions(self):
        """Test integrity status transitions work correctly"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "integrity_test.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Create and add file
            entry = create_file_entry_from_path(str(video_file))
            stored_entry = test_store.store.upsert_file(entry)
            
            # Should start as UNKNOWN
            file_data = test_store.get_file_by_path(str(video_file))
            assert IntegrityStatus(file_data['integrity_status']) == IntegrityStatus.UNKNOWN
            
            # Transition to PENDING
            file_entry = test_store.store.get_file(str(video_file))
            file_entry.integrity_status = IntegrityStatus.PENDING
            test_store.store.upsert_file(file_entry)
            updated_data = test_store.get_file_by_path(str(video_file))
            assert IntegrityStatus(updated_data['integrity_status']) == IntegrityStatus.PENDING
            
            # Transition to COMPLETE
            file_entry = test_store.store.get_file(str(video_file))
            file_entry.integrity_status = IntegrityStatus.COMPLETE
            test_store.store.upsert_file(file_entry)
            final_data = test_store.get_file_by_path(str(video_file))
            assert IntegrityStatus(final_data['integrity_status']) == IntegrityStatus.COMPLETE

    def test_processed_status_transitions(self):
        """Test processed status transitions work correctly"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "processed_test.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Create and add file
            entry = create_file_entry_from_path(str(video_file))
            stored_entry = test_store.store.upsert_file(entry)
            
            # Should start as NEW
            file_data = test_store.get_file_by_path(str(video_file))
            assert ProcessedStatus(file_data['processed_status']) == ProcessedStatus.NEW
            
            # Transition to CONVERTED
            file_entry = test_store.store.get_file(str(video_file))
            file_entry.processed_status = ProcessedStatus.CONVERTED
            test_store.store.upsert_file(file_entry)
            updated_data = test_store.get_file_by_path(str(video_file))
            assert ProcessedStatus(updated_data['processed_status']) == ProcessedStatus.CONVERTED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])