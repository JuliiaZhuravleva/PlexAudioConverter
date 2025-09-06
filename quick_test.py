#!/usr/bin/env python3
"""
Quick test runner for local development
Runs essential tests quickly for development workflow
"""
import sys
import subprocess
from pathlib import Path

def run_command(cmd, description):
    """Run command and return success status"""
    print(f"\n[Running] {description}...")
    print("-" * 50)
    
    try:
        result = subprocess.run(cmd, shell=True, check=True, text=True, 
                              capture_output=True)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        print(f"[PASSED] {description} - PASSED")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[FAILED] {description} - FAILED")
        print(f"Exit code: {e.returncode}")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        return False

def main():
    """Run quick essential tests"""
    print("PlexAudioConverter Quick Test Runner")
    print("=" * 50)
    
    # Change to project directory
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))
    
    tests_passed = 0
    total_tests = 0
    
    # Essential test suites for local development
    test_suites = [
        # Basic functionality check
        ("python -m pytest tests/test_basic.py -v --tb=short", 
         "Basic functionality tests"),
        
        # Core Step 2 tests (subset)
        ("python -m pytest tests/test_step2_core.py::TestDiscoveryAndPlanning::test_t001_discovery_creates_records_no_spinning -v --tb=short",
         "T-001: Discovery creates records"),
        
        ("python -m pytest tests/test_step2_stability.py::TestStabilityGate::test_t002_size_gate_growing_file_no_integrity -v --tb=short",
         "T-002: Size gate blocks integrity"),
        
        ("python -m pytest tests/test_step2_groups.py::TestGroupProcessing::test_t010_stereo_group_generation -v --tb=short",
         "T-010: Group generation"),
        
        # Platform edge cases (quick subset)
        ("python -m pytest tests/test_platform_edge_cases.py::TestPlatformEdgeCases::test_path_normalization_edge_cases -v --tb=short",
         "Path normalization"),
        
        # Integration test (if exists)
        ("python -m pytest test_step2_integration.py -v --tb=short -x",
         "Integration test (if present)"),
    ]
    
    for cmd, description in test_suites:
        total_tests += 1
        if run_command(cmd, description):
            tests_passed += 1
        else:
            print(f"[WARNING]  Continuing with remaining tests...")
    
    # Summary
    print("\n" + "=" * 50)
    print("[SUMMARY] QUICK TEST SUMMARY")
    print("=" * 50)
    print(f"Tests Passed: {tests_passed}/{total_tests}")
    
    if tests_passed == total_tests:
        print("[SUCCESS] ALL QUICK TESTS PASSED!")
        print("Ready to run full test suite with: python tests/run_tests.py --all")
        return 0
    else:
        print("[FAILURE] SOME TESTS FAILED!")
        print("Fix issues before running full test suite")
        return 1

if __name__ == "__main__":
    sys.exit(main())