#!/usr/bin/env python3
"""
Platform Utilities for State Management

Provides cross-platform utilities for handling filesystem differences,
particularly case sensitivity detection and path normalization.
"""

import os
import sys
import tempfile
from pathlib import Path
from functools import lru_cache
from typing import Union
import logging

logger = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def filesystem_is_case_sensitive(path: Union[str, Path]) -> bool:
    """
    Detect if the filesystem at the given path is case-sensitive.
    
    This function creates temporary files to test case sensitivity behavior.
    Results are cached per filesystem root to avoid repeated tests.
    
    Args:
        path: Path to test for case sensitivity (file or directory)
    
    Returns:
        True if filesystem is case-sensitive, False otherwise
        
    Note:
        - On Unix systems, typically returns True (ext4, XFS, etc.)
        - On Windows NTFS, typically returns False
        - On macOS HFS+/APFS, typically returns False (case-preserving but insensitive)
        - Network filesystems may vary
    """
    try:
        path_obj = Path(path)
        
        # Find the root directory to test (use parent if path is a file)
        if path_obj.is_file():
            test_dir = path_obj.parent
        elif path_obj.is_dir():
            test_dir = path_obj
        else:
            # Path doesn't exist, use parent or fallback to current dir
            test_dir = path_obj.parent if path_obj.parent.exists() else Path.cwd()
        
        # Ensure we have a valid directory
        if not test_dir.exists() or not test_dir.is_dir():
            logger.warning(f"Cannot test case sensitivity for invalid path: {test_dir}")
            # Default assumption based on platform
            return sys.platform != 'win32' and sys.platform != 'darwin'
        
        # Create a temporary test file with mixed case
        with tempfile.TemporaryDirectory(dir=test_dir) as temp_dir:
            temp_path = Path(temp_dir)
            
            # Test file names with different cases
            upper_name = "CaseSensitivityTest.tmp"
            lower_name = "casesensitivitytest.tmp"
            
            upper_file = temp_path / upper_name
            lower_file = temp_path / lower_name
            
            # Create the first file
            upper_file.write_text("test_upper")
            
            # Try to create the second file with different case
            try:
                lower_file.write_text("test_lower")
                
                # If both files exist as separate entities, filesystem is case-sensitive
                if upper_file.exists() and lower_file.exists():
                    # Double-check they're actually different files
                    upper_content = upper_file.read_text()
                    lower_content = lower_file.read_text()
                    
                    is_case_sensitive = upper_content != lower_content
                    logger.debug(f"Filesystem case sensitivity test for {test_dir}: {is_case_sensitive}")
                    return is_case_sensitive
                else:
                    # One file overwrote the other - case-insensitive
                    logger.debug(f"Filesystem case sensitivity test for {test_dir}: False (overwrite)")
                    return False
                    
            except FileExistsError:
                # OS prevented creating the second file - case-insensitive
                logger.debug(f"Filesystem case sensitivity test for {test_dir}: False (FileExistsError)")
                return False
                
    except (OSError, PermissionError) as e:
        logger.warning(f"Cannot test case sensitivity for {path}: {e}")
        # Fallback to platform-based guess
        return sys.platform not in ('win32', 'darwin')
    
    # Default fallback
    return sys.platform not in ('win32', 'darwin')


def normalize_path_for_storage(path: Union[str, Path], base_path: Union[str, Path] = None) -> str:
    """
    Normalize a path for consistent storage and comparison.
    
    On case-sensitive filesystems, preserves the original case.
    On case-insensitive filesystems, normalizes using os.path.normcase.
    
    Args:
        path: Path to normalize
        base_path: Base path to use for case sensitivity detection (defaults to path)
        
    Returns:
        Normalized path string suitable for database storage
    """
    path_obj = Path(path)
    
    # Always resolve to get absolute path and resolve symlinks
    resolved_path = path_obj.resolve()
    
    # Determine which filesystem to test
    test_path = base_path if base_path is not None else resolved_path
    
    # Check if filesystem is case-sensitive
    if filesystem_is_case_sensitive(test_path):
        # Case-sensitive: preserve exact case
        return str(resolved_path)
    else:
        # Case-insensitive: normalize case for consistent storage
        return os.path.normcase(str(resolved_path))


def normalize_path_for_comparison(path: Union[str, Path], base_path: Union[str, Path] = None) -> str:
    """
    Normalize a path for comparison with stored paths.
    
    This should match the normalization used in normalize_path_for_storage.
    
    Args:
        path: Path to normalize for comparison
        base_path: Base path to use for case sensitivity detection (defaults to path)
        
    Returns:
        Normalized path string suitable for comparison
    """
    return normalize_path_for_storage(path, base_path)


def paths_are_equivalent(path1: Union[str, Path], path2: Union[str, Path]) -> bool:
    """
    Check if two paths refer to the same file, accounting for case sensitivity.
    
    Args:
        path1: First path to compare
        path2: Second path to compare
        
    Returns:
        True if paths are equivalent on the current filesystem
    """
    try:
        norm1 = normalize_path_for_comparison(path1)
        norm2 = normalize_path_for_comparison(path2)
        return norm1 == norm2
    except (OSError, ValueError):
        # Fallback to string comparison if normalization fails
        return str(path1) == str(path2)


def get_canonical_path(path: Union[str, Path]) -> str:
    """
    Get the canonical representation of a path.
    
    This function returns the "first seen" case on case-insensitive filesystems,
    but always returns the exact case on case-sensitive filesystems.
    
    Args:
        path: Path to get canonical form for
        
    Returns:
        Canonical path representation
    """
    # For now, this is the same as normalize_path_for_storage
    # In the future, we could implement "first seen" case preservation
    return normalize_path_for_storage(path)


# Platform-specific constants
IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_UNIX = not IS_WINDOWS and not IS_MACOS

# Common case-insensitive platforms
CASE_INSENSITIVE_PLATFORMS = {'win32', 'darwin'}
DEFAULT_CASE_SENSITIVE = sys.platform not in CASE_INSENSITIVE_PLATFORMS