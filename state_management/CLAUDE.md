# State Management System - CLAUDE.md

This file provides detailed guidance for working with the state management system in PlexAudioConverter. This package implements a sophisticated file processing state machine with SQLite persistence, metrics collection, and deterministic processing.

## Package Overview

The state management system provides deterministic video file processing with comprehensive state tracking, error handling, and performance monitoring. It replaces ad-hoc file processing with a robust, transactional approach suitable for large media libraries.

## Architecture Components

### Core Modules

- **`manager.py`** - Main StateManager API providing unified access to all system components
- **`machine.py`** - AudioStateMachine implementing finite state machine logic with transition handlers
- **`store.py`** - StateStore providing SQLite-based persistent storage with indexing and transactions
- **`planner.py`** - StatePlanner handling scheduling and batched operations based on `next_check_at` timestamps
- **`models.py`** - Data models (FileEntry, GroupEntry) with business logic and validation
- **`config.py`** - StateConfig and StateConfigManager for centralized configuration management
- **`metrics.py`** - StateMetrics providing comprehensive telemetry and performance monitoring
- **`enums.py`** - State enumerations (IntegrityStatus, ProcessedStatus) with transition validation
- **`integrity_adapter.py`** - Integration adapter for video integrity checking with FFmpeg

### State Enumerations

#### IntegrityStatus
- `UNKNOWN` - File not yet checked for completeness
- `PENDING` - Integrity check scheduled or in progress
- `COMPLETE` - File integrity verified, safe to process
- `INCOMPLETE` - Integrity check failed, file not ready
- `ERROR` - Error during integrity validation

#### ProcessedStatus
- `NEW` - New file discovered, no processing attempted
- `SKIPPED_HAS_EN2` - File has English 2.0 audio track, skipping conversion
- `CONVERTED` - Successfully converted to stereo
- `CONVERT_FAILED` - Conversion process failed
- `GROUP_PENDING_PAIR` - Waiting for paired file in processing group
- `GROUP_PROCESSED` - Group processing completed
- `IGNORED` - File excluded by filtering rules
- `DUPLICATE` - Duplicate file with same group_id

## Configuration

### Basic Configuration
```python
from state_management.config import StateConfig

config = StateConfig(
    storage_url="production.db",        # SQLite database path
    stable_wait_sec=60,                # File stability wait time
    backoff_step_sec=30,               # Error backoff step
    backoff_max_sec=600,               # Maximum backoff time
    batch_size=100,                    # Processing batch size
    loop_interval_sec=10,              # Main loop interval
    integrity_quick_mode=False,        # Full integrity checks
    keep_processed_days=60,            # Retention period
    max_state_entries=10000            # Memory limits
)
```

### Environment-Specific Configs
```python
from state_management.config import get_development_config, get_production_config

# Development with debug logging and smaller batches
dev_config = get_development_config()

# Production with optimized performance settings
prod_config = get_production_config()
```

### Configuration File (JSON)
```json
{
  "storage_url": "state.db",
  "stable_wait_sec": 30,
  "backoff_step_sec": 30,
  "batch_size": 50,
  "integrity_quick_mode": true,
  "enable_metrics": true,
  "log_level": "INFO"
}
```

## Core Usage Patterns

### Basic StateManager Operations
```python
import asyncio
from state_management import create_state_manager

async def basic_processing():
    # Create manager with default config
    manager = create_state_manager(environment='production')
    
    # Scan directory for new files
    scan_result = await manager.discover_directory("/path/to/videos")
    print(f"Discovered {scan_result['files_added']} new files")
    
    # Process pending files
    processed = await manager.process_pending()
    print(f"Processed {len(processed)} files")
    
    # Get system status
    status = manager.get_system_status()
    print(f"Total files tracked: {status['total_files']}")
    
    await manager.close()

asyncio.run(basic_processing())
```

### Continuous Monitoring
```python
import asyncio
from state_management import create_state_manager

async def continuous_monitor():
    manager = create_state_manager()
    
    try:
        # This runs indefinitely
        await manager.start_monitoring()
    except KeyboardInterrupt:
        print("Stopping monitoring...")
    finally:
        await manager.close()

asyncio.run(continuous_monitor())
```

### Configuration Management
```python
from state_management.config import StateConfigManager

# Load configuration from file
config_mgr = StateConfigManager("custom_config.json")
config = config_mgr.load_config()

# Update specific settings
config_mgr.update_config({
    "batch_size": 200,
    "integrity_quick_mode": False
})

# Save changes
config_mgr.save_config()
```

## Command Line Interface

### Basic Operations
```bash
# Scan directory for new files
python -m state_management.manager --scan "/path/to/videos"

# Start continuous monitoring (runs indefinitely)
python -m state_management.manager --monitor

# Get detailed system status
python -m state_management.manager --status

# Run maintenance operations (cleanup, optimization)
python -m state_management.manager --maintenance
```

### Advanced Operations
```bash
# Reset database (WARNING: destroys all state)
python -m state_management.manager --reset

# Custom configuration file
python -m state_management.manager --config custom.json --scan "/videos"

# Debug mode with verbose logging
python -m state_management.manager --debug --monitor

# Process specific batch size
python -m state_management.manager --batch-size 25 --monitor
```

### Configuration via Environment Variables
```bash
# Override database location
export STATE_DB_URL="production.db"
python -m state_management.manager --monitor

# Enable debug logging
export STATE_LOG_LEVEL="DEBUG"
python -m state_management.manager --status
```

## Metrics and Monitoring

### Metrics Collection
```python
from state_management.metrics import get_metrics

# Get global metrics instance
metrics = get_metrics()

# Manual metric recording
metrics.increment_counter("files_processed", tags={"status": "success"})
metrics.record_timing("scan_duration", 1.23)
metrics.record_gauge("queue_size", 42)

# Get metrics summary
summary = metrics.get_summary(since_hours=1.0)
print(f"Files discovered: {summary['counters']['files_discovered']}")
print(f"Average scan time: {summary['timings']['scan_duration']['avg']:.2f}s")
```

### Performance Monitoring
```python
# System status includes performance metrics
status = manager.get_system_status()
print(f"Database size: {status['database_size_mb']:.1f} MB")
print(f"Total processing time: {status['total_processing_time_sec']:.1f}s")
print(f"Files per second: {status['processing_rate_fps']:.2f}")
```

### Health Checks
```python
# Check system health
health = manager.get_health_status()
if health['status'] == 'healthy':
    print("✅ System running normally")
else:
    print(f"⚠️ Issues detected: {health['issues']}")
```

## Testing

### Running Tests
```bash
cd state_management

# Run all tests with verbose output
python -m pytest tests/ -v

# Run specific test modules
python -m pytest tests/test_manager.py -v
python -m pytest tests/test_store.py -v
python -m pytest tests/test_integration.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html
```

### Test Categories

#### Unit Tests
- **`test_enums.py`** - State transition validation
- **`test_models.py`** - Data model validation and business logic
- **`test_store.py`** - Database operations and transactions
- **`test_config.py`** - Configuration loading and validation

#### Integration Tests  
- **`test_manager.py`** - Complete StateManager workflows
- **`test_integration.py`** - End-to-end file processing scenarios
- **`test_performance.py`** - Performance and scalability testing

### Test Utilities
```python
from state_management.tests.utils import create_test_manager, create_temp_videos

async def test_custom_scenario():
    # Create isolated test manager
    manager = await create_test_manager()
    
    # Create test video files
    video_files = create_temp_videos(count=5, directory="/tmp/test_videos")
    
    # Test processing
    result = await manager.discover_directory("/tmp/test_videos")
    assert result['files_added'] == 5
    
    await manager.close()
```

## Development Workflows

### Adding New State Transitions
1. Update enums in `enums.py` with new states
2. Add transition validation logic
3. Implement handlers in `machine.py`
4. Update models in `models.py` if needed
5. Add comprehensive tests

### Performance Optimization
1. Monitor metrics via `get_metrics().get_summary()`
2. Analyze database query performance in `store.py`
3. Adjust batch sizes in configuration
4. Use profiling tools for bottleneck identification

### Error Handling Best Practices
- All operations use structured error handling with backoff
- Failed operations are retried with exponential backoff
- Critical errors are logged with full context
- Recovery mechanisms handle database corruption scenarios

## Integration Points

### FFmpeg Integration
```python
from state_management.integrity_adapter import IntegrityAdapter

# Check video file integrity
adapter = IntegrityAdapter(config)
is_complete = await adapter.check_integrity("/path/to/video.mp4")
```

### Legacy System Migration
```python
# Migrate from old .json state files
await manager.migrate_legacy_state_files("/path/to/videos")

# Import existing processing results
await manager.import_legacy_results(legacy_data)
```

## Important Notes

### Database Management
- SQLite database includes automatic schema migrations
- Regular maintenance removes old entries based on `keep_processed_days`
- Database vacuum operations optimize storage periodically
- Backup procedures should include state database

### Performance Considerations
- Indexed queries on `next_check_at` for efficient scheduling
- Batched processing reduces database transaction overhead  
- Connection pooling optimizes SQLite access patterns
- Memory usage monitored and limited by `max_state_entries`

### Error Recovery
- Transactional operations ensure consistency during failures
- Exponential backoff prevents resource exhaustion
- State machine validates all transitions to prevent corruption
- Comprehensive logging enables debugging and recovery

### Concurrency Safety
- Async/await patterns throughout for non-blocking operations
- SQLite with WAL mode supports concurrent readers
- State transitions are atomic and consistent
- Resource cleanup handled via context managers

This state management system provides enterprise-grade reliability for media processing workflows while maintaining simplicity for common operations.