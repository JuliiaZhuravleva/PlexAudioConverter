"""
Download Monitor Module for PlexAudioConverter

Monitors file download completion status, particularly for torrent files.
Supports multiple detection methods to ensure accurate status tracking.
"""

import os
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
from .video_integrity_checker import is_video_file_complete

logger = logging.getLogger(__name__)


class DownloadStatus(Enum):
    """File download status enumeration"""
    UNKNOWN = "unknown"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class FileDownloadInfo:
    """Information about a file's download status"""
    file_path: Path
    status: DownloadStatus = DownloadStatus.UNKNOWN
    size: int = 0
    last_modified: datetime = field(default_factory=datetime.now)
    last_size_change: datetime = field(default_factory=datetime.now)
    stable_duration: float = 0.0  # seconds since last change
    detection_method: str = ""
    is_torrent_file: bool = False
    
    def __post_init__(self):
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)


class DownloadMonitor:
    """
    Monitors file download completion using multiple detection methods:
    1. Temporary file extensions (.!ut, .!qb, .part, .tmp, etc.)
    2. File size stability monitoring
    3. File lock/handle detection
    4. File modification time tracking
    """
    
    # Common incomplete file extensions used by torrent clients
    INCOMPLETE_EXTENSIONS = {
        '.!ut',      # uTorrent
        '.!qb',      # qBittorrent  
        '.part',     # Generic partial download
        '.tmp',      # Temporary files
        '.crdownload', # Chrome downloads
        '.partial',  # Firefox/other browsers
        '.download', # Generic download
        '.incomplete', # Generic incomplete
        '.temp',     # Temporary
    }
    
    # Minimum time (seconds) file must be stable to consider complete
    STABILITY_THRESHOLD = 60.0  # Increased from 30 to 60 seconds for better detection
    
    def __init__(self, stability_threshold: float = None):
        self.stability_threshold = stability_threshold or self.STABILITY_THRESHOLD
        self.monitored_files: Dict[str, FileDownloadInfo] = {}
        self.callbacks: List[Callable[[FileDownloadInfo], None]] = []
        self._monitoring = False
        self._monitor_thread = None
        self._lock = threading.Lock()
        
    def add_callback(self, callback: Callable[[FileDownloadInfo], None]):
        """Add callback function to be called when file status changes"""
        self.callbacks.append(callback)
        
    def remove_callback(self, callback: Callable[[FileDownloadInfo], None]):
        """Remove callback function"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
            
    def _notify_callbacks(self, file_info: FileDownloadInfo):
        """Notify all registered callbacks of status change"""
        for callback in self.callbacks:
            try:
                callback(file_info)
            except Exception as e:
                logger.error(f"Error in download monitor callback: {e}")
                
    def add_file(self, file_path: str | Path, is_torrent_file: bool = True) -> FileDownloadInfo:
        """Add file to monitoring list"""
        file_path = Path(file_path)
        key = str(file_path.absolute())
        
        with self._lock:
            if key not in self.monitored_files:
                file_info = FileDownloadInfo(
                    file_path=file_path,
                    is_torrent_file=is_torrent_file
                )
                self.monitored_files[key] = file_info
                logger.info(f"Added file to download monitoring: {file_path}")
            else:
                file_info = self.monitored_files[key]
                
        # Initial status check
        self._check_file_status(file_info)
        return file_info
        
    def remove_file(self, file_path: str | Path):
        """Remove file from monitoring list"""
        key = str(Path(file_path).absolute())
        with self._lock:
            if key in self.monitored_files:
                del self.monitored_files[key]
                logger.info(f"Removed file from download monitoring: {file_path}")
                
    def get_file_status(self, file_path: str | Path) -> Optional[FileDownloadInfo]:
        """Get current status of monitored file"""
        key = str(Path(file_path).absolute())
        with self._lock:
            return self.monitored_files.get(key)
            
    def get_all_files(self) -> Dict[str, FileDownloadInfo]:
        """Get all monitored files and their status"""
        with self._lock:
            return self.monitored_files.copy()
            
    def _check_file_status(self, file_info: FileDownloadInfo) -> bool:
        """
        Check file download status using multiple methods
        Returns True if status changed
        """
        old_status = file_info.status
        new_status = self._detect_download_status(file_info)
        
        if new_status != old_status:
            file_info.status = new_status
            logger.info(f"File status changed: {file_info.file_path} -> {new_status.value}")
            self._notify_callbacks(file_info)
            return True
            
        return False
        
    def _detect_download_status(self, file_info: FileDownloadInfo) -> DownloadStatus:
        """Detect download status using multiple methods"""
        file_path = file_info.file_path
        
        # Method 1: Check if file exists
        if not file_path.exists():
            # Check for incomplete versions
            incomplete_path = self._find_incomplete_file(file_path)
            if incomplete_path:
                file_info.detection_method = f"incomplete_extension: {incomplete_path.suffix}"
                self._update_file_stats(file_info, incomplete_path)
                return DownloadStatus.DOWNLOADING
            else:
                file_info.detection_method = "file_not_found"
                return DownloadStatus.UNKNOWN
                
        # Method 2: Check file extension for incomplete markers
        if file_path.suffix.lower() in self.INCOMPLETE_EXTENSIONS:
            file_info.detection_method = f"incomplete_extension: {file_path.suffix}"
            self._update_file_stats(file_info, file_path)
            return DownloadStatus.DOWNLOADING
            
        # Method 3: Check if file is locked/being written to
        if self._is_file_locked(file_path):
            file_info.detection_method = "file_locked"
            self._update_file_stats(file_info, file_path)
            return DownloadStatus.DOWNLOADING
            
        # Method 4: Check for torrent-specific indicators
        torrent_status = self._check_torrent_indicators(file_path)
        if torrent_status != DownloadStatus.UNKNOWN:
            self._update_file_stats(file_info, file_path)
            file_info.detection_method = f"torrent_indicator: {torrent_status.value}"
            return torrent_status
            
        # Method 5: Check file size stability
        self._update_file_stats(file_info, file_path)
        
        if file_info.stable_duration < self.stability_threshold:
            file_info.detection_method = f"size_unstable: {file_info.stable_duration:.1f}s"
            return DownloadStatus.DOWNLOADING
            
        # Method 6: Advanced completion checks
        completion_status = self._check_file_completion(file_info)
        if completion_status != DownloadStatus.UNKNOWN:
            file_info.detection_method = f"completion_check: {completion_status.value}"
            return completion_status
            
        # Method 7: File appears complete (fallback)
        file_info.detection_method = f"stable_fallback: {file_info.stable_duration:.1f}s"
        return DownloadStatus.COMPLETED
        
    def _find_incomplete_file(self, target_path: Path) -> Optional[Path]:
        """Find incomplete version of target file"""
        parent = target_path.parent
        stem = target_path.stem
        
        for ext in self.INCOMPLETE_EXTENSIONS:
            # Check for filename.ext.incomplete_ext
            incomplete_path = parent / f"{target_path.name}{ext}"
            if incomplete_path.exists():
                return incomplete_path
                
            # Check for filename.incomplete_ext (without original extension)
            incomplete_path = parent / f"{stem}{ext}"
            if incomplete_path.exists():
                return incomplete_path
                
        return None
        
    def _is_file_locked(self, file_path: Path) -> bool:
        """Check if file is locked/being written to"""
        try:
            # Try to open file in exclusive mode
            with open(file_path, 'r+b') as f:
                pass
            return False
        except (PermissionError, OSError):
            return True
        except Exception:
            return False
            
    def _update_file_stats(self, file_info: FileDownloadInfo, actual_path: Path):
        """Update file statistics (size, modification time, stability)"""
        try:
            stat = actual_path.stat()
            new_size = stat.st_size
            new_mtime = datetime.fromtimestamp(stat.st_mtime)
            
            # Check if size changed
            if new_size != file_info.size:
                file_info.size = new_size
                file_info.last_size_change = datetime.now()
                file_info.stable_duration = 0.0
            else:
                # Calculate stability duration
                file_info.stable_duration = (datetime.now() - file_info.last_size_change).total_seconds()
                
            file_info.last_modified = new_mtime
            
        except Exception as e:
            logger.warning(f"Could not update file stats for {actual_path}: {e}")
    
    def _check_torrent_indicators(self, file_path: Path) -> DownloadStatus:
        """Check for torrent-specific download indicators"""
        try:
            parent_dir = file_path.parent
            file_stem = file_path.stem
            
            # Check for .torrent files in the same directory
            torrent_files = list(parent_dir.glob("*.torrent"))
            if torrent_files:
                # If there are .torrent files, this might be an active download
                logger.debug(f"Found {len(torrent_files)} torrent files in {parent_dir}")
            
            # Check for common torrent client lock files or temp files
            lock_patterns = [
                f"{file_stem}.lock",
                f"{file_stem}.tmp",
                f"{file_path.name}.lock",
                f"{file_path.name}.tmp",
                ".torrent_lock",
                "resume.dat",  # uTorrent
                "fastresume",  # qBittorrent
            ]
            
            for pattern in lock_patterns:
                if (parent_dir / pattern).exists():
                    logger.debug(f"Found torrent indicator file: {pattern}")
                    return DownloadStatus.DOWNLOADING
            
            # Check for incomplete file patterns in the same directory
            incomplete_patterns = [
                f"{file_stem}.*",
                f"{file_path.name}.*"
            ]
            
            for pattern in incomplete_patterns:
                for incomplete_file in parent_dir.glob(pattern):
                    if incomplete_file.suffix.lower() in self.INCOMPLETE_EXTENSIONS:
                        logger.debug(f"Found related incomplete file: {incomplete_file.name}")
                        return DownloadStatus.DOWNLOADING
            
            return DownloadStatus.UNKNOWN
            
        except Exception as e:
            logger.debug(f"Error checking torrent indicators for {file_path}: {e}")
            return DownloadStatus.UNKNOWN
    
    def _check_file_completion(self, file_info: FileDownloadInfo) -> DownloadStatus:
        """Advanced checks for file completion"""
        try:
            file_path = file_info.file_path
            
            # Check 1: File size reasonableness (should be > 10MB for video files)
            if file_info.current_size < 10 * 1024 * 1024:  # 10MB
                logger.debug(f"File size too small: {file_info.current_size} bytes")
                return DownloadStatus.DOWNLOADING
                
            # Check 2: Recent modification time (modified within last 2 minutes = likely downloading)
            if file_info.last_modified:
                time_since_modified = time.time() - file_info.last_modified
                if time_since_modified < 120:  # 2 minutes
                    logger.debug(f"File recently modified: {time_since_modified:.1f}s ago")
                    return DownloadStatus.DOWNLOADING
                    
            # Check 3: Video file integrity check using FFmpeg
            if file_path.suffix.lower() in ['.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.m4v', '.webm']:
                try:
                    is_complete, reason = is_video_file_complete(file_path)
                    if not is_complete:
                        logger.debug(f"Video integrity check failed: {reason}")
                        return DownloadStatus.DOWNLOADING
                    else:
                        logger.debug(f"Video integrity check passed: {reason}")
                        return DownloadStatus.COMPLETED
                        
                except Exception as e:
                    logger.debug(f"Video integrity check error: {e}")
                    # Fallback to basic header check if FFmpeg fails
                    return self._check_video_header(file_path)
            
            return DownloadStatus.UNKNOWN
            
        except Exception as e:
            logger.debug(f"Error in completion check for {file_info.file_path}: {e}")
            return DownloadStatus.UNKNOWN
    
    def _check_video_header(self, file_path: Path) -> DownloadStatus:
        """Basic video file header validation"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(1024)  # Read first 1KB
                if len(header) < 100:  # Too small header
                    logger.debug("File header too small")
                    return DownloadStatus.DOWNLOADING
                
                # Check for common video file signatures
                video_signatures = [
                    b'\x1a\x45\xdf\xa3',  # Matroska/MKV
                    b'ftyp',              # MP4
                    b'RIFF',              # AVI
                ]
                
                has_valid_signature = any(sig in header for sig in video_signatures)
                if not has_valid_signature:
                    logger.debug("No valid video signature found")
                    return DownloadStatus.DOWNLOADING
                    
        except Exception as e:
            logger.debug(f"Could not verify file header: {e}")
            # If we can't read the file, it might still be downloading
            return DownloadStatus.DOWNLOADING
            
        return DownloadStatus.UNKNOWN
            
    def start_monitoring(self, check_interval: float = 5.0):
        """Start background monitoring thread"""
        if self._monitoring:
            return
            
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(check_interval,),
            daemon=True
        )
        self._monitor_thread.start()
        logger.info("Download monitoring started")
        
    def stop_monitoring(self):
        """Stop background monitoring thread"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        logger.info("Download monitoring stopped")
        
    def _monitor_loop(self, check_interval: float):
        """Main monitoring loop"""
        while self._monitoring:
            try:
                with self._lock:
                    files_to_check = list(self.monitored_files.values())
                    
                for file_info in files_to_check:
                    self._check_file_status(file_info)
                    
                time.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"Error in download monitor loop: {e}")
                time.sleep(check_interval)
                
    def get_downloading_files(self) -> List[FileDownloadInfo]:
        """Get list of files currently downloading"""
        with self._lock:
            return [
                info for info in self.monitored_files.values()
                if info.status == DownloadStatus.DOWNLOADING
            ]
            
    def get_completed_files(self) -> List[FileDownloadInfo]:
        """Get list of completed files"""
        with self._lock:
            return [
                info for info in self.monitored_files.values()
                if info.status == DownloadStatus.COMPLETED
            ]
            
    def cleanup_completed_files(self, max_age_hours: int = 24):
        """Remove completed files from monitoring after specified time"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._lock:
            to_remove = []
            for key, file_info in self.monitored_files.items():
                if (file_info.status == DownloadStatus.COMPLETED and 
                    file_info.last_modified < cutoff_time):
                    to_remove.append(key)
                    
            for key in to_remove:
                del self.monitored_files[key]
                logger.info(f"Cleaned up completed file from monitoring: {key}")


# Convenience functions for easy integration
_global_monitor = None

def get_global_monitor() -> DownloadMonitor:
    """Get or create global download monitor instance"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = DownloadMonitor()
    return _global_monitor

def monitor_file(file_path: str | Path, is_torrent_file: bool = True) -> FileDownloadInfo:
    """Add file to global monitor"""
    return get_global_monitor().add_file(file_path, is_torrent_file)

def get_file_download_status(file_path: str | Path) -> Optional[FileDownloadInfo]:
    """Get download status of file from global monitor"""
    return get_global_monitor().get_file_status(file_path)

def is_file_downloading(file_path: str | Path) -> bool:
    """Check if file is currently downloading"""
    info = get_file_download_status(file_path)
    return info is not None and info.status == DownloadStatus.DOWNLOADING

def is_file_download_complete(file_path: str | Path) -> bool:
    """Check if file download is complete"""
    info = get_file_download_status(file_path)
    return info is not None and info.status == DownloadStatus.COMPLETED
