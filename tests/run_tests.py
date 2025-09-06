#!/usr/bin/env python3
"""
Comprehensive test runner for PlexAudioConverter state management system
Implements the strong test system from state_management_test_plan_step_2_and_beyond_v_1.md
"""
import os
import sys
import argparse
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import subprocess
import tempfile

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pytest
    import coverage
    COVERAGE_AVAILABLE = True
except ImportError:
    COVERAGE_AVAILABLE = False
    print("Warning: coverage package not available. Install with: pip install coverage")


class TestRunner:
    """Comprehensive test runner with CI integration"""
    
    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.tests_dir = self.project_root / "tests"
        self.results_dir = self.project_root / "test_results"
        self.coverage_dir = self.results_dir / "coverage"
        
        # Ensure results directories exist
        self.results_dir.mkdir(exist_ok=True)
        self.coverage_dir.mkdir(exist_ok=True)
    
    def run_step2_core_tests(self, verbose: bool = False) -> Tuple[bool, Dict]:
        """Run Step 2 core tests (T-001 to T-012)"""
        print("🧪 Running Step 2 Core Tests (T-001 to T-012)...")
        
        test_files = [
            "test_step2_core.py",
            "test_step2_stability.py", 
            "test_step2_pending.py",
            "test_step2_file_ops.py",
            "test_step2_groups.py"
        ]
        
        args = [
            "-v" if verbose else "-q",
            "--tb=short",
            "--strict-markers",
            "--strict-config",
            f"--junitxml={self.results_dir}/step2_core_junit.xml",
            f"--json-report",
            f"--json-report-file={self.results_dir}/step2_core_report.json"
        ]
        
        if COVERAGE_AVAILABLE:
            args.extend([
                "--cov=state_management",
                "--cov=core",
                f"--cov-report=html:{self.coverage_dir}/step2_core",
                f"--cov-report=json:{self.results_dir}/step2_core_coverage.json"
            ])
        
        for test_file in test_files:
            args.append(str(self.tests_dir / test_file))
        
        success = pytest.main(args) == 0
        
        # Load and return results
        results = self._load_test_results("step2_core_report.json")
        return success, results
    
    def run_platform_edge_cases(self, verbose: bool = False) -> Tuple[bool, Dict]:
        """Run platform edge case tests (T-501 to T-504)"""
        print("🌍 Running Platform Edge Case Tests (T-501 to T-504)...")
        
        args = [
            "-v" if verbose else "-q",
            "--tb=short",
            f"--junitxml={self.results_dir}/platform_junit.xml",
            f"--json-report",
            f"--json-report-file={self.results_dir}/platform_report.json",
            str(self.tests_dir / "test_platform_edge_cases.py")
        ]
        
        if COVERAGE_AVAILABLE:
            args.extend([
                "--cov=state_management",
                f"--cov-report=html:{self.coverage_dir}/platform",
                f"--cov-report=json:{self.results_dir}/platform_coverage.json"
            ])
        
        success = pytest.main(args) == 0
        results = self._load_test_results("platform_report.json")
        return success, results
    
    def run_reliability_tests(self, verbose: bool = False) -> Tuple[bool, Dict]:
        """Run reliability and GC tests (T-401 to T-403)"""
        print("🔧 Running Reliability Tests (T-401 to T-403)...")
        
        args = [
            "-v" if verbose else "-q",
            "--tb=short",
            f"--junitxml={self.results_dir}/reliability_junit.xml", 
            f"--json-report",
            f"--json-report-file={self.results_dir}/reliability_report.json",
            str(self.tests_dir / "test_reliability.py")
        ]
        
        if COVERAGE_AVAILABLE:
            args.extend([
                "--cov=state_management",
                f"--cov-report=html:{self.coverage_dir}/reliability",
                f"--cov-report=json:{self.results_dir}/reliability_coverage.json"
            ])
        
        success = pytest.main(args) == 0
        results = self._load_test_results("reliability_report.json")
        return success, results
    
    def run_future_step_tests(self, verbose: bool = False) -> Tuple[bool, Dict]:
        """Run future step tests (marked as skip/xfail)"""
        print("🔮 Running Future Step Tests (Step 3-5, should be skipped)...")
        
        args = [
            "-v" if verbose else "-q",
            "--tb=short",
            "-rs",  # Show skipped test reasons
            f"--junitxml={self.results_dir}/future_junit.xml",
            f"--json-report",
            f"--json-report-file={self.results_dir}/future_report.json",
            str(self.tests_dir / "test_step3_backoff.py")
        ]
        
        success = pytest.main(args) == 0
        results = self._load_test_results("future_report.json")
        return success, results
    
    def run_performance_tests(self, verbose: bool = False) -> Tuple[bool, Dict]:
        """Run performance and stress tests"""
        print("⚡ Running Performance Tests...")
        
        # Set performance test markers
        args = [
            "-v" if verbose else "-q",
            "--tb=short",
            "-m", "not slow",  # Skip slow tests by default
            f"--junitxml={self.results_dir}/performance_junit.xml",
            f"--json-report", 
            f"--json-report-file={self.results_dir}/performance_report.json",
            "--benchmark-only",  # Run only benchmark tests if available
            "--timeout=30"  # 30 second timeout per test
        ]
        
        # Look for performance test files
        performance_files = list(self.tests_dir.glob("**/test_*performance*.py"))
        if not performance_files:
            print("No performance test files found")
            return True, {"tests": 0, "passed": 0}
        
        args.extend(str(f) for f in performance_files)
        
        success = pytest.main(args) == 0
        results = self._load_test_results("performance_report.json")
        return success, results
    
    def run_integration_tests(self, verbose: bool = False) -> Tuple[bool, Dict]:
        """Run integration tests"""
        print("🔗 Running Integration Tests...")
        
        integration_files = [
            self.tests_dir / "test_basic.py",
            self.project_root / "test_step2_integration.py"
        ]
        
        # Add state_management integration tests
        state_mgmt_tests = self.project_root / "state_management" / "tests"
        if state_mgmt_tests.exists():
            integration_files.extend(state_mgmt_tests.glob("test_integration*.py"))
        
        existing_files = [f for f in integration_files if f.exists()]
        
        if not existing_files:
            print("No integration test files found")
            return True, {"tests": 0, "passed": 0}
        
        args = [
            "-v" if verbose else "-q",
            "--tb=short",
            f"--junitxml={self.results_dir}/integration_junit.xml",
            f"--json-report",
            f"--json-report-file={self.results_dir}/integration_report.json"
        ]
        
        if COVERAGE_AVAILABLE:
            args.extend([
                "--cov=state_management",
                "--cov=core",
                f"--cov-report=html:{self.coverage_dir}/integration",
                f"--cov-report=json:{self.results_dir}/integration_coverage.json"
            ])
        
        args.extend(str(f) for f in existing_files)
        
        success = pytest.main(args) == 0
        results = self._load_test_results("integration_report.json")
        return success, results
    
    def run_all_tests(self, verbose: bool = False, include_slow: bool = False) -> Dict[str, Tuple[bool, Dict]]:
        """Run all test suites"""
        print("🚀 Running All Test Suites...")
        print("=" * 60)
        
        results = {}
        
        # Run test suites in order of importance
        test_suites = [
            ("Step2 Core", self.run_step2_core_tests),
            ("Platform Edge Cases", self.run_platform_edge_cases),
            ("Reliability", self.run_reliability_tests),
            ("Integration", self.run_integration_tests),
            ("Future Steps", self.run_future_step_tests),
        ]
        
        if include_slow:
            test_suites.append(("Performance", self.run_performance_tests))
        
        for suite_name, runner_func in test_suites:
            print(f"\n{suite_name}:")
            print("-" * 40)
            
            start_time = time.time()
            try:
                success, suite_results = runner_func(verbose)
                duration = time.time() - start_time
                
                results[suite_name] = (success, suite_results)
                
                # Print summary
                status = "✅ PASSED" if success else "❌ FAILED"
                test_count = suite_results.get("tests", 0)
                passed_count = suite_results.get("passed", 0)
                
                print(f"{status} - {passed_count}/{test_count} tests passed ({duration:.1f}s)")
                
            except Exception as e:
                results[suite_name] = (False, {"error": str(e)})
                print(f"❌ ERROR - {e}")
        
        return results
    
    def generate_summary_report(self, all_results: Dict[str, Tuple[bool, Dict]]) -> Dict:
        """Generate comprehensive summary report"""
        summary = {
            "timestamp": time.time(),
            "platform": sys.platform,
            "python_version": sys.version,
            "total_suites": len(all_results),
            "passed_suites": sum(1 for success, _ in all_results.values() if success),
            "total_tests": 0,
            "passed_tests": 0,
            "failed_tests": 0,
            "skipped_tests": 0,
            "suite_results": {}
        }
        
        for suite_name, (success, results) in all_results.items():
            suite_summary = {
                "success": success,
                "tests": results.get("tests", 0),
                "passed": results.get("passed", 0),
                "failed": results.get("failed", 0),
                "skipped": results.get("skipped", 0),
                "duration": results.get("duration", 0),
                "error": results.get("error")
            }
            
            summary["suite_results"][suite_name] = suite_summary
            summary["total_tests"] += suite_summary["tests"]
            summary["passed_tests"] += suite_summary["passed"]
            summary["failed_tests"] += suite_summary["failed"]
            summary["skipped_tests"] += suite_summary["skipped"]
        
        # Save summary report
        summary_file = self.results_dir / "test_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        return summary
    
    def print_final_summary(self, summary: Dict):
        """Print final test summary"""
        print("\n" + "=" * 60)
        print("📊 FINAL TEST SUMMARY")
        print("=" * 60)
        
        print(f"Platform: {summary['platform']}")
        print(f"Total Suites: {summary['total_suites']}")
        print(f"Passed Suites: {summary['passed_suites']}/{summary['total_suites']}")
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {summary['passed_tests']}")
        print(f"Failed: {summary['failed_tests']}")
        print(f"Skipped: {summary['skipped_tests']}")
        
        print(f"\nResults saved to: {self.results_dir}")
        
        if COVERAGE_AVAILABLE:
            print(f"Coverage reports: {self.coverage_dir}")
        
        # Overall status
        overall_success = (summary['failed_tests'] == 0 and 
                          summary['passed_suites'] == summary['total_suites'])
        
        if overall_success:
            print("\n🎉 ALL TESTS PASSED!")
            return True
        else:
            print("\n💥 SOME TESTS FAILED!")
            return False
    
    def _load_test_results(self, report_file: str) -> Dict:
        """Load test results from JSON report"""
        report_path = self.results_dir / report_file
        
        if not report_path.exists():
            return {"tests": 0, "passed": 0, "failed": 0, "skipped": 0}
        
        try:
            with open(report_path, 'r') as f:
                data = json.load(f)
            
            summary = data.get("summary", {})
            return {
                "tests": summary.get("total", 0),
                "passed": summary.get("passed", 0),
                "failed": summary.get("failed", 0),
                "skipped": summary.get("skipped", 0),
                "duration": summary.get("duration", 0)
            }
        except (json.JSONDecodeError, KeyError):
            return {"tests": 0, "passed": 0, "failed": 0, "skipped": 0}


def main():
    """Main test runner entry point"""
    parser = argparse.ArgumentParser(
        description="PlexAudioConverter Strong Test System Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py --step2              # Run only Step 2 core tests
  python run_tests.py --platform           # Run only platform edge cases
  python run_tests.py --all --verbose      # Run all tests with verbose output
  python run_tests.py --ci                 # CI mode (all tests, strict)
  python run_tests.py --performance        # Run performance tests
        """
    )
    
    # Test selection
    parser.add_argument("--step2", action="store_true", help="Run Step 2 core tests only")
    parser.add_argument("--platform", action="store_true", help="Run platform edge case tests")
    parser.add_argument("--reliability", action="store_true", help="Run reliability tests")
    parser.add_argument("--integration", action="store_true", help="Run integration tests")
    parser.add_argument("--performance", action="store_true", help="Run performance tests")
    parser.add_argument("--future", action="store_true", help="Run future step tests (skipped)")
    parser.add_argument("--all", action="store_true", help="Run all test suites")
    
    # Options
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--ci", action="store_true", help="CI mode (strict, all tests)")
    parser.add_argument("--include-slow", action="store_true", help="Include slow performance tests")
    
    args = parser.parse_args()
    
    # Default to all tests if no specific suite selected
    if not any([args.step2, args.platform, args.reliability, args.integration, 
                args.performance, args.future, args.all]):
        args.all = True
    
    runner = TestRunner()
    
    try:
        if args.ci:
            # CI mode - run all tests strictly
            print("🤖 Running in CI mode...")
            all_results = runner.run_all_tests(verbose=True, include_slow=True)
        elif args.all:
            all_results = runner.run_all_tests(verbose=args.verbose, include_slow=args.include_slow)
        else:
            # Run specific test suites
            all_results = {}
            
            if args.step2:
                success, results = runner.run_step2_core_tests(args.verbose)
                all_results["Step2 Core"] = (success, results)
            
            if args.platform:
                success, results = runner.run_platform_edge_cases(args.verbose)
                all_results["Platform Edge Cases"] = (success, results)
            
            if args.reliability:
                success, results = runner.run_reliability_tests(args.verbose)
                all_results["Reliability"] = (success, results)
            
            if args.integration:
                success, results = runner.run_integration_tests(args.verbose)
                all_results["Integration"] = (success, results)
            
            if args.performance:
                success, results = runner.run_performance_tests(args.verbose)
                all_results["Performance"] = (success, results)
            
            if args.future:
                success, results = runner.run_future_step_tests(args.verbose)
                all_results["Future Steps"] = (success, results)
        
        # Generate and print summary
        summary = runner.generate_summary_report(all_results)
        overall_success = runner.print_final_summary(summary)
        
        # Exit with appropriate code
        sys.exit(0 if overall_success else 1)
        
    except KeyboardInterrupt:
        print("\n⚠️  Test run interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 Test runner error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()