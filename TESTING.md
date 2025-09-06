# PlexAudioConverter Strong Test System

This document describes the comprehensive test system implemented for PlexAudioConverter's state management layer, based on the test plan in `state_management_test_plan_step_2_and_beyond_v_1.md`.

## 🎯 Overview

The strong test system validates that the state management layer:
- Treats **integrity** as the only gate before heavy work
- Triggers integrity **only** after file size stability for N seconds  
- Schedules work via **`next_check_at`** (no polling loops)
- Accurately tracks **grouped files** and **processed states**
- Remains resource-light in background operation

## 🏗️ Test Architecture

### Test Categories

1. **Step 2 Core Tests (T-001 to T-012)** - Current implementation requirements
2. **Platform Edge Cases (T-501 to T-504)** - Cross-platform compatibility
3. **Reliability Tests (T-401 to T-403)** - GC, migration, dangling cleanup
4. **Integration Tests** - End-to-end workflow validation
5. **Future Step Tests (T-101+, T-201+, T-301+)** - Marked as skip/xfail

### Key Test Components

- **TempFS** - Isolated temporary filesystem per test
- **SyntheticDownloader** - Simulates file downloads with controllable timing
- **FakeClock** - Deterministic time control for stability testing
- **FakeIntegrityChecker** - Configurable integrity check results
- **FFprobeStub** - Controlled audio stream metadata
- **StateStoreFixture** - Database with test helpers and assertions

## 🚀 Running Tests

### Quick Development Tests
```bash
# Run essential tests quickly during development
python quick_test.py
```

### Comprehensive Test Runner
```bash
# Install test dependencies first
pip install -r tests/requirements.txt

# Run all test suites
python tests/run_tests.py --all --verbose

# Run specific test categories
python tests/run_tests.py --step2           # Core Step 2 tests
python tests/run_tests.py --platform        # Platform edge cases
python tests/run_tests.py --reliability     # Reliability tests
python tests/run_tests.py --integration     # Integration tests

# CI mode (strict, includes slow tests)
python tests/run_tests.py --ci
```

### Direct pytest Usage
```bash
# Run with pytest directly
pytest tests/ -v
pytest tests/test_step2_core.py::TestDiscoveryAndPlanning::test_t001_discovery_creates_records_no_spinning -v

# With coverage
pytest tests/ --cov=state_management --cov=core --cov-report=html
```

## 📊 Test Coverage

### Coverage Requirements
- **Minimum**: 85% line and branch coverage
- **Target**: 90%+ for critical state management components
- **Exclusions**: Debug code, platform-specific code, abstract methods

### Coverage Reports
```bash
# Generate coverage report
coverage run -m pytest tests/
coverage report --show-missing
coverage html  # HTML report in test_results/coverage/html/
```

### Coverage Configuration
- **File**: `.coveragerc`
- **Data**: `test_results/coverage/.coverage`
- **Reports**: `test_results/coverage/`

## 🧪 Test Implementation Details

### Step 2 Core Tests (T-001 to T-012)

| Test | Description | Status |
|------|-------------|--------|
| T-001 | Discovery creates entries, no spinning | ✅ Implemented |
| T-002 | Size gate blocks integrity for growing files | ✅ Implemented |
| T-003 | Stability triggers integrity after N seconds | ✅ Implemented |
| T-004 | PENDING prevents duplicate picks | ✅ Implemented |
| T-005 | Multiple files respect DUE_LIMIT | ✅ Implemented |
| T-006 | Jittery writes don't trigger integrity | ✅ Implemented |
| T-007 | Restart recovery | ✅ Implemented |
| T-008 | Rename before stabilization | ✅ Implemented |
| T-009 | Deletion during waiting | ✅ Implemented |
| T-010 | Group entries for stereo + original | ✅ Implemented |
| T-011 | EN 2.0 doesn't alter behavior (Step 2) | ✅ Implemented |
| T-012 | Idle performance | ✅ Implemented |

### Platform Edge Cases (T-501 to T-504)

| Test | Description | Status |
|------|-------------|--------|
| T-501 | Unicode/long paths (Windows/NTFS) | ✅ Implemented |
| T-502 | Case sensitivity | ✅ Implemented |
| T-503 | Hard links (Unix) | ✅ Implemented |
| T-504 | System time shift | ✅ Implemented |

### Future Step Tests (Skip/XFail)

| Test | Description | Status |
|------|-------------|--------|
| T-101 | Backoff after INCOMPLETE | ⏳ Skip (Step 3) |
| T-102 | Backoff reset on size change | ⏳ Skip (Step 3) |
| T-201 | Skip if EN 2.0 present | ⏳ Skip (Step 4) |
| T-202 | No EN 2.0 → Ready for conversion | ⏳ Skip (Step 4) |
| T-301 | Pair required when delete_original=false | ⏳ Skip (Step 5) |
| T-302 | Single copy sufficient when delete_original=true | ⏳ Skip (Step 5) |

## 🔧 Test Configuration

### pytest Configuration (`pytest.ini`)
- Test discovery patterns
- Timeout settings (5 minutes max per test)  
- Marker definitions
- Warning filters
- Output formatting

### Coverage Configuration (`.coveragerc`)
- Source inclusion/exclusion patterns
- Branch coverage enabled
- Fail threshold: 85%
- HTML/XML/JSON report formats

### Test Requirements (`tests/requirements.txt`)
- Core testing: pytest, pytest-asyncio, pytest-timeout
- Coverage: coverage, pytest-cov
- Reporting: pytest-html, pytest-json-report
- Utilities: pytest-mock, pytest-xdist, pytest-benchmark

## 🏃‍♂️ Continuous Integration

### GitHub Actions (`.github/workflows/tests.yml`)
- **Matrix testing**: Ubuntu/Windows × Python 3.8-3.12
- **System dependencies**: FFmpeg installation
- **Test execution**: All test suites with proper separation
- **Coverage reporting**: Codecov integration
- **Artifact upload**: Test results and coverage reports
- **Summary generation**: Test results matrix

### CI Requirements
- All Step 2 core tests must pass on Linux and Windows
- No performance regressions in idle scenarios
- Coverage threshold maintained
- Future step tests properly marked as skip/xfail

## 🐛 Test Development Guidelines

### Writing New Tests

1. **Use fixtures from `conftest.py`**:
   ```python
   def test_example(temp_fs, state_store, fake_integrity_checker):
       # Test implementation
   ```

2. **Follow naming conventions**:
   - Test files: `test_*.py`
   - Test classes: `Test*`
   - Test methods: `test_*` or `test_tXXX_*` for plan tests

3. **Use appropriate markers**:
   ```python
   @pytest.mark.step2
   def test_core_functionality():
       pass
   
   @pytest.mark.platform
   def test_unicode_handling():
       pass
   
   @pytest.mark.slow
   def test_large_dataset():
       pass
   ```

### Test Utilities

- **`assert_helpers`** fixture for common assertions
- **`performance_monitor`** fixture for timing tests
- **Parametrized fixtures** for cross-cutting variations
- **Mock configurations** for different test scenarios

### Debugging Tests

```bash
# Run single test with debugging
pytest tests/test_step2_core.py::test_t001_discovery_creates_records_no_spinning -vvv -s --tb=long

# Run with pdb on failure  
pytest tests/ --pdb

# Run with specific markers
pytest -m "step2 and not slow" -v
```

## 📈 Performance Testing

### Performance Requirements
- Idle cycles: < 0.1 seconds for empty due queue
- Discovery: < 1 second per 100 files
- Integrity checks: Bounded by `integrity_timeout_sec`
- Database operations: Indexed queries, transaction batching

### Benchmarking
```bash
# Run performance tests
python tests/run_tests.py --performance --include-slow

# With benchmarking
pytest tests/ --benchmark-only --benchmark-sort=mean
```

## 🔍 Test Monitoring

### Metrics Collection
- `files_discovered`: Number of files found during discovery
- `due_picked`: Number of due files selected for processing  
- `integrity_started`/`integrity_finished`: Integrity check counters
- `cycles_run`: Planner execution cycles

### Test Artifacts
- **JSON reports**: Machine-readable test results
- **JUnit XML**: CI integration format
- **HTML reports**: Human-readable test results
- **Coverage reports**: HTML, XML, JSON formats
- **Performance benchmarks**: Timing and resource usage

## 🚨 Troubleshooting

### Common Issues

1. **Test timeout**: Increase timeout in `pytest.ini` or use `@pytest.mark.timeout`
2. **Platform-specific failures**: Check platform markers and skip conditions
3. **Coverage too low**: Add tests for uncovered code paths
4. **Flaky tests**: Use `pytest-rerunfailures` or `pytest-repeat`
5. **Resource cleanup**: Ensure fixtures properly cleanup temp files/connections

### Debug Commands
```bash
# List all available tests
pytest --collect-only

# Run tests matching pattern
pytest -k "test_t001 or test_stability" -v

# Show test durations
pytest tests/ --durations=10

# Detailed failure info
pytest tests/ --tb=long --showlocals
```

## 📋 Acceptance Criteria (Step 2)

✅ **All Core Step 2 tests (T-001 to T-012) are green on CI for Linux and Windows**

✅ **No measurable CPU spin in idle scenarios; due scheduling is the only wake-up trigger**

✅ **State is fully recoverable between restarts; no duplicate entries**

### Verification Commands
```bash
# Verify acceptance criteria
python tests/run_tests.py --step2 --ci
python tests/run_tests.py --platform --ci  
python tests/run_tests.py --reliability --ci

# Full verification
python tests/run_tests.py --all --ci
```

## 🔄 Future Steps

### Step 3 Implementation
- Enable backoff tests (T-101, T-102)
- Implement exponential backoff logic
- Add retry policies

### Step 4 Implementation  
- Enable EN 2.0 tests (T-201, T-202)
- Implement audio track analysis
- Add skip policies

### Step 5 Implementation
- Enable group finalization tests (T-301, T-302)  
- Implement delete_original logic
- Add group completion rules

---

**Policy**: If any critical test fails, we are explicitly allowed to change the code and/or adjust interfaces to make the system correct, simple, and reliable. Tests are the specification of expected behavior.