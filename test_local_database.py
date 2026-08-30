"""Unit tests for local_database job appearance count and status behavior."""

import json
import sqlite3
from pathlib import Path
import pytest

from job_hunter_lib import local_database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "test_jobs.db"
    monkeypatch.setattr(local_database, "DATABASE_PATH", test_db_path)
    return test_db_path


def test_first_scan_sets_appearance_count_one_and_status_new(temp_db):
    jobs = [
        {"title": "Software Engineer", "company": "Acme Corp", "url": "https://example.com/job1", "job_id": "job1"}
    ]
    saved = local_database.save_search_results(jobs)
    assert len(saved) == 1
    assert saved[0]["appearance_count"] == 1
    assert saved[0]["status"] == "new"

    all_jobs = local_database.get_all_jobs()
    assert len(all_jobs) == 1
    assert all_jobs[0]["appearance_count"] == 1
    assert all_jobs[0]["status"] == "new"


def test_subsequent_scans_increment_appearance_count(temp_db):
    job = {"title": "Software Engineer", "company": "Acme Corp", "url": "https://example.com/job1", "job_id": "job1"}
    
    # 1st scan -> appearance_count = 1
    first_run = local_database.save_search_results([job])
    assert first_run[0]["appearance_count"] == 1
    assert first_run[0]["status"] == "new"

    # 2nd scan -> appearance_count = 2, status becomes "old"
    second_run = local_database.save_search_results([job])
    assert second_run[0]["appearance_count"] == 2
    assert second_run[0]["status"] == "old"

    # 3rd scan -> appearance_count = 3, status remains "old"
    third_run = local_database.save_search_results([job])
    assert third_run[0]["appearance_count"] == 3
    assert third_run[0]["status"] == "old"

    # 4th scan -> appearance_count = 4, status remains "old"
    fourth_run = local_database.save_search_results([job])
    assert fourth_run[0]["appearance_count"] == 4
    assert fourth_run[0]["status"] == "old"


def test_user_chosen_status_persists_across_scans(temp_db):
    job = {"title": "Backend Dev", "company": "Beta Inc", "url": "https://example.com/job2", "job_id": "job2"}
    local_database.save_search_results([job])

    # User marks status as applied
    local_database.update_job_status("job2", "applied")
    all_jobs = local_database.get_all_jobs()
    assert all_jobs[0]["status"] == "applied"

    # Next scans increment count but preserve 'applied'
    second_run = local_database.save_search_results([job])
    assert second_run[0]["appearance_count"] == 2
    assert second_run[0]["status"] == "applied"


def test_incremental_batch_saving_does_not_double_count(temp_db):
    job1 = {"title": "Dev1", "company": "Gamma", "url": "https://example.com/j1", "job_id": "j1"}
    job2 = {"title": "Dev2", "company": "Delta", "url": "https://example.com/j2", "job_id": "j2"}
    
    seen_ids = set()
    # Batch 1 in same run
    local_database.save_search_results([job1], run_seen_ids=seen_ids)
    # Batch 2 in same run (includes duplicate of job1)
    local_database.save_search_results([job1, job2], run_seen_ids=seen_ids)

    all_jobs = {j["job_id"]: j for j in local_database.get_all_jobs()}
    assert all_jobs["j1"]["appearance_count"] == 1
    assert all_jobs["j2"]["appearance_count"] == 1


