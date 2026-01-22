#!/usr/bin/env python3
"""
Migration Chain Test Script
Tests the full migration chain on a clean test database
"""
import os
import sys
import time
import subprocess
from pathlib import Path

# Set the test database URL and environment
TEST_DB_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/cleaning_test"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["APP_ENV"] = "dev"

# Color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def print_header(text):
    """Print a formatted header"""
    print(f"\n{BLUE}{'=' * 80}{RESET}")
    print(f"{BLUE}{text.center(80)}{RESET}")
    print(f"{BLUE}{'=' * 80}{RESET}\n")

def print_success(text):
    """Print success message"""
    print(f"{GREEN}✓ {text}{RESET}")

def print_error(text):
    """Print error message"""
    print(f"{RED}✗ {text}{RESET}")

def print_warning(text):
    """Print warning message"""
    print(f"{YELLOW}⚠ {text}{RESET}")

def print_info(text):
    """Print info message"""
    print(f"{BLUE}ℹ {text}{RESET}")

def run_command(cmd, description, capture_output=True):
    """Run a shell command and return the result"""
    print_info(f"{description}...")
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=capture_output,
            text=True,
            env=os.environ.copy()
        )
        elapsed = time.time() - start_time

        if result.returncode == 0:
            print_success(f"{description} completed in {elapsed:.2f}s")
            return True, result.stdout, result.stderr, elapsed
        else:
            print_error(f"{description} failed in {elapsed:.2f}s")
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
            return False, result.stdout, result.stderr, elapsed
    except Exception as e:
        elapsed = time.time() - start_time
        print_error(f"{description} failed with exception: {e}")
        return False, "", str(e), elapsed

def get_table_count():
    """Get the number of tables in the database"""
    cmd = f"""PGPASSWORD=postgres psql -h localhost -U postgres -d cleaning_test -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" """
    success, stdout, stderr, _ = run_command(cmd, "Counting tables", capture_output=True)
    if success:
        return int(stdout.strip())
    return -1

def get_migration_count():
    """Get the number of migration files"""
    versions_dir = Path(__file__).parent / "alembic" / "versions_clean"
    if versions_dir.exists():
        return len(list(versions_dir.glob("*.py")))
    return 0

def get_table_list():
    """Get list of all tables in the database"""
    cmd = f"""PGPASSWORD=postgres psql -h localhost -U postgres -d cleaning_test -t -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;" """
    success, stdout, stderr, _ = run_command(cmd, "Getting table list", capture_output=True)
    if success:
        tables = [t.strip() for t in stdout.strip().split('\n') if t.strip()]
        return tables
    return []

def check_alembic_version():
    """Check if alembic_version table exists and has data"""
    cmd = f"""PGPASSWORD=postgres psql -h localhost -U postgres -d cleaning_test -t -c "SELECT version_num FROM alembic_version;" """
    success, stdout, stderr, _ = run_command(cmd, "Checking Alembic version", capture_output=True)
    if success and stdout.strip():
        return stdout.strip()
    return None

def main():
    """Main test function"""
    print_header("ALEMBIC MIGRATION CHAIN TEST")

    # Test report data
    report = {
        'migration_count': 0,
        'upgrade_time': 0,
        'downgrade_time': 0,
        'reupgrade_time': 0,
        'errors': [],
        'warnings': [],
        'tables_created': 0,
        'final_version': None
    }

    # Get migration count
    migration_count = get_migration_count()
    report['migration_count'] = migration_count
    print_info(f"Found {migration_count} migration files")

    # Phase 1: Initial database state
    print_header("PHASE 1: VERIFY CLEAN DATABASE")
    initial_tables = get_table_count()
    print_info(f"Initial table count: {initial_tables}")

    if initial_tables > 0:
        print_warning(f"Database is not empty! Found {initial_tables} tables")
        print_info("Dropping all tables to start fresh...")
        tables = get_table_list()
        for table in tables:
            run_command(
                f"""PGPASSWORD=postgres psql -h localhost -U postgres -d cleaning_test -c "DROP TABLE IF EXISTS {table} CASCADE;" """,
                f"Dropping table {table}",
                capture_output=True
            )

        # Verify clean state
        final_count = get_table_count()
        if final_count == 0:
            print_success("Database cleaned successfully")
        else:
            print_error(f"Failed to clean database, {final_count} tables remain")
            report['errors'].append("Failed to clean database before testing")

    # Phase 2: Upgrade to head
    print_header("PHASE 2: RUN 'alembic upgrade head'")
    success, stdout, stderr, elapsed = run_command(
        "cd /home/user/CleanWithSnapshot/backend && alembic upgrade head",
        "Running alembic upgrade head",
        capture_output=True
    )
    report['upgrade_time'] = elapsed

    if not success:
        print_error("Migration upgrade failed!")
        report['errors'].append("Initial upgrade to head failed")
        print(stdout)
        print(stderr)
        return report

    # Print migration output
    print("\nMigration output:")
    for line in stdout.split('\n'):
        if line.strip():
            print(f"  {line}")

    # Phase 3: Verify schema after upgrade
    print_header("PHASE 3: VERIFY SCHEMA AFTER UPGRADE")
    tables_after_upgrade = get_table_count()
    report['tables_created'] = tables_after_upgrade
    print_info(f"Tables created: {tables_after_upgrade}")

    if tables_after_upgrade == 0:
        print_error("No tables created after upgrade!")
        report['errors'].append("No tables created after upgrade")
    else:
        print_success(f"Successfully created {tables_after_upgrade} tables")

        # List all tables
        tables = get_table_list()
        print_info(f"Tables in database:")
        for table in tables:
            print(f"  - {table}")

    # Check Alembic version
    version = check_alembic_version()
    if version:
        print_success(f"Alembic version table exists with version: {version}")
        report['final_version'] = version
    else:
        print_warning("Could not read Alembic version")
        report['warnings'].append("Could not verify Alembic version after upgrade")

    # Phase 4: Downgrade to base
    print_header("PHASE 4: RUN 'alembic downgrade base'")
    success, stdout, stderr, elapsed = run_command(
        "cd /home/user/CleanWithSnapshot/backend && alembic downgrade base",
        "Running alembic downgrade base",
        capture_output=True
    )
    report['downgrade_time'] = elapsed

    if not success:
        print_error("Migration downgrade failed!")
        report['errors'].append("Downgrade to base failed")
        print(stdout)
        print(stderr)
        # Don't return here, continue with report
    else:
        # Print downgrade output
        print("\nDowngrade output:")
        for line in stdout.split('\n'):
            if line.strip():
                print(f"  {line}")

    # Phase 5: Verify empty database
    print_header("PHASE 5: VERIFY DATABASE IS EMPTY AFTER DOWNGRADE")
    tables_after_downgrade = get_table_count()
    print_info(f"Tables remaining: {tables_after_downgrade}")

    if tables_after_downgrade == 0:
        print_success("Database successfully emptied")
    else:
        print_warning(f"Database not empty: {tables_after_downgrade} tables remain")
        report['warnings'].append(f"{tables_after_downgrade} tables remain after downgrade")

        # List remaining tables
        remaining_tables = get_table_list()
        print_info("Remaining tables:")
        for table in remaining_tables:
            print(f"  - {table}")

    # Phase 6: Re-upgrade to head
    print_header("PHASE 6: RUN 'alembic upgrade head' AGAIN")
    success, stdout, stderr, elapsed = run_command(
        "cd /home/user/CleanWithSnapshot/backend && alembic upgrade head",
        "Running alembic upgrade head (second time)",
        capture_output=True
    )
    report['reupgrade_time'] = elapsed

    if not success:
        print_error("Second migration upgrade failed!")
        report['errors'].append("Second upgrade to head failed")
        print(stdout)
        print(stderr)
    else:
        print_success("Successfully re-applied all migrations")

        # Print re-upgrade output
        print("\nRe-upgrade output:")
        for line in stdout.split('\n'):
            if line.strip():
                print(f"  {line}")

        # Verify final state
        final_tables = get_table_count()
        if final_tables == tables_after_upgrade:
            print_success(f"Table count matches: {final_tables}")
        else:
            print_warning(f"Table count mismatch: {tables_after_upgrade} vs {final_tables}")
            report['warnings'].append(f"Table count mismatch after re-upgrade")

    # Phase 7: Generate report
    print_header("TEST REPORT")

    print(f"\n{BLUE}Migration Statistics:{RESET}")
    print(f"  Total migrations: {report['migration_count']}")
    print(f"  Tables created: {report['tables_created']}")
    print(f"  Final version: {report['final_version']}")

    print(f"\n{BLUE}Performance:{RESET}")
    print(f"  Upgrade time: {report['upgrade_time']:.2f}s")
    print(f"  Downgrade time: {report['downgrade_time']:.2f}s")
    print(f"  Re-upgrade time: {report['reupgrade_time']:.2f}s")
    print(f"  Total time: {report['upgrade_time'] + report['downgrade_time'] + report['reupgrade_time']:.2f}s")

    if report['warnings']:
        print(f"\n{YELLOW}Warnings ({len(report['warnings'])}){RESET}:")
        for warning in report['warnings']:
            print(f"  ⚠ {warning}")

    if report['errors']:
        print(f"\n{RED}Errors ({len(report['errors'])}){RESET}:")
        for error in report['errors']:
            print(f"  ✗ {error}")
        print_header("MIGRATION CHAIN TEST: FAILED")
        return 1
    else:
        print_header("MIGRATION CHAIN TEST: PASSED")
        return 0

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print_error("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
